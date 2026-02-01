#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import asyncio
import logging
import random
import time
from asyncio import Queue, QueueEmpty
from concurrent.futures import Future
from functools import partial
from typing import TypeVar, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.network_config import ConnectionInfo
from bitcoin_safe.network_utils import ProxyInfo

from .p2p_client import Inventory, InventoryType, P2PClient, Peer, Peers
from .peer_discovery import PeerDiscovery
from .tools import address_match, outpoint_match

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=list)


class P2pListener(QObject):
    signal_tx = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))
    signal_block = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_break_current_connection = cast(SignalProtocol[[]], pyqtSignal())
    signal_disconnected_to = cast(SignalProtocol[[Peer]], pyqtSignal(Peer))
    signal_try_connecting_to = cast(SignalProtocol[[ConnectionInfo]], pyqtSignal(ConnectionInfo))
    signal_current_peers_change = cast(SignalProtocol[[list[ConnectionInfo]]], pyqtSignal(list))

    def __init__(
        self,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
        debug=False,
        fetch_txs=True,
        timeout: int = 200,
        discovered_peers: Peers | list[Peer] | None = None,
        autodiscover_additional_peers: bool = True,
        max_parallel_peers: int = 2,
        parent: QObject | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        if max_parallel_peers < 1:
            raise ValueError("max_parallel_peers must be >= 1")

        self.fetch_txs = fetch_txs
        self.network = network
        self.debug = debug
        self.timeout = timeout
        self.max_parallel_peers = max_parallel_peers

        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None
        self.address_filter: set[str] | None = None
        self.outpoint_filter: set[str] | None = None
        self.peer_discovery = PeerDiscovery(network=network, loop_in_thread=self.loop_in_thread)
        self.autodiscover_additional_peers = autodiscover_additional_peers

        self.discovered_peers = discovered_peers if discovered_peers else Peers()

        self.signal_tracker = SignalTracker()
        self.clients: list[P2PClient] = []
        self._connection_tasks: list[Future[None]] = []
        self._active_peers: set[Peer] = set()
        self._current_peers: dict[int, ConnectionInfo | None] = {}
        self._stop_requested = False

        self.signal_tracker.connect(self.signal_disconnected_to, self.on_disconnected_to)
        self.signal_tracker.connect(self.signal_break_current_connection, self._on_break_current_connection)
        self._ensure_clients()

    def _build_client(self, slot_id: int) -> P2PClient:
        """Create and wire a P2PClient for the given slot."""
        client = P2PClient(
            network=self.network,
            debug=self.debug,
            timeout=self.timeout,
            parent=self,
        )
        self.signal_tracker.connect(client.signal_received_peers, self.on_received_peers)
        self.signal_tracker.connect(client.signal_disconnected_to, self.on_disconnected_to)
        self.signal_tracker.connect(client.signal_inv, partial(self.on_inv_from_client, client))
        self.signal_tracker.connect(client.signal_tx, self.on_tx)
        self.signal_tracker.connect(client.signal_try_connecting_to, self.signal_try_connecting_to.emit)
        self.signal_tracker.connect(
            client.signal_current_peer_change, partial(self._on_current_peer_change, slot_id)
        )
        return client

    def _ensure_clients(self) -> None:
        """Create missing client slots without duplicating signal wiring."""
        missing = self.max_parallel_peers - len(self.clients)
        if missing <= 0:
            return
        start_slot = len(self.clients)
        for offset in range(missing):
            slot_id = start_slot + offset
            self.clients.append(self._build_client(slot_id))

    def set_address_filter(self, address_filter: set[str] | None):
        """Set address filter."""
        self.address_filter = address_filter

    def set_outpoint_filter(self, outpoint_filter: set[str] | None):
        """Set outpoint filter."""
        self.outpoint_filter = outpoint_filter

    def _on_current_peer_change(self, slot_id: int, connection_info: ConnectionInfo | None) -> None:
        """Track active peers per slot and emit aggregated changes."""
        self._current_peers[slot_id] = connection_info
        self.signal_current_peers_change.emit(self.active_connections)

    def on_tx(self, tx: bdk.Transaction):
        """On tx."""
        if (self.address_filter is not None) and address_match(
            tx=tx, network=self.network, address_filter=self.address_filter
        ):
            self.signal_tx.emit(tx)
            return
        if (self.outpoint_filter is not None) and outpoint_match(tx=tx, outpoint_filter=self.outpoint_filter):
            self.signal_tx.emit(tx)
            return

    async def random_select_peer(
        self,
        weight_getaddr: float = 0.7,
        weight_dns: float = 0.3,
        exclude_peers: set[Peer] | None = None,
    ) -> Peer | None:
        """Pick a random peer according to two relative weights.

        Parameters
        ----------
        weight_getaddr : float
            Relative chance to pick from `self.discovered_peers`
            (addresses learned via getaddr/addrv2 or provided upfront).
        weight_dns : float
            Relative chance to call `self.peer_discovery.get_bitcoin_peer()`
            (DNS seeds, hard-coded lists, etc.).

        Returns
        -------
        Peer | None
            A `Peer` object, or `None` if neither source has anything.
        """
        exclude_peers = exclude_peers or set()
        if weight_getaddr < 0 or weight_dns < 0:
            raise ValueError("weights must be non-negative")

        if not self.autodiscover_additional_peers:
            weight_dns = 0

        discovered_candidates = [peer for peer in self.discovered_peers if peer not in exclude_peers]

        # Fast paths -------------------------------------------------
        if not discovered_candidates:
            if not self.autodiscover_additional_peers:
                logger.debug("Peer discovery disabled; no discovered peers available")
                return None
            peer = await self.peer_discovery.get_bitcoin_peer()  # may be None
            logger.debug(f"Picked {peer=} from DNS seed")
            return peer
        if weight_dns == 0:
            peer = random.choice(discovered_candidates)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        total = weight_getaddr + weight_dns
        if total == 0:
            raise ValueError("both weights are zero")

        # Weighted choice -------------------------------------------
        pick = random.random() * total
        if pick < weight_getaddr and discovered_candidates:
            peer = random.choice(discovered_candidates)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        peer = await self.peer_discovery.get_bitcoin_peer()  # may be None
        logger.debug(f"Picked {peer=} from DNS seed")
        return peer

    async def _next_peer_candidate(
        self,
        preferred_queue: Queue[Peer],
        exclude_peers: set[Peer],
    ) -> Peer | None:
        """Fetch the next peer from preferred list or discovery."""
        try:
            while True:
                candidate = preferred_queue.get_nowait()
                if candidate not in exclude_peers:
                    return candidate
        except QueueEmpty:
            pass
        return await self.random_select_peer(exclude_peers=exclude_peers)

    async def _maintain_connection(
        self,
        slot_id: int,
        client: P2PClient,
        proxy_info: ProxyInfo | None,
        preferred_queue: Queue[Peer],
    ) -> None:
        """Keep a single slot connected to a peer."""
        retry_delay = 5
        previous_peer: Peer | None = None

        while not self._stop_requested:
            peer = await self._next_peer_candidate(
                preferred_queue=preferred_queue,
                exclude_peers=self._active_peers,
            )
            if peer is None:
                await asyncio.sleep(retry_delay)
                continue

            if peer == previous_peer:
                await asyncio.sleep(retry_delay)

            self._active_peers.add(peer)
            logger.info(f"[slot {slot_id}] Try peer: {peer!r}")
            start_time: float | None = None

            try:
                await client.connect(peer=peer, proxy_info=proxy_info)
                start_time = time.monotonic()

                if not client.is_running():
                    previous_peer = peer
                    continue

                await client.listen_forever()

            except asyncio.CancelledError:
                await client.disconnect()
                raise

            except Exception as exc:
                self.signal_disconnected_to.emit(peer)
                logger.debug(f"[slot {slot_id}] Connection error with {peer}: {exc}")
            finally:
                self._active_peers.discard(peer)
                await client.disconnect()

                if peer and start_time is not None:
                    elapsed = time.monotonic() - start_time
                    logger.info(f"[slot {slot_id}] Disconnected from {peer!r} after {elapsed:.2f} seconds")

                previous_peer = peer

    def start(
        self,
        proxy_info: ProxyInfo | None,
        preferred_peers: list[Peer] | None = None,
    ):
        """Start."""
        self._stop_requested = False
        for task in list(self._connection_tasks):
            task.cancel()
        for client in self.clients:
            self.loop_in_thread.run_background(client.disconnect())
        self._active_peers.clear()
        self._current_peers = {i: None for i in range(len(self.clients))}
        self._connection_tasks.clear()
        self.signal_current_peers_change.emit([])

        self._ensure_clients()

        preferred_queue: Queue[Peer] = Queue()
        if preferred_peers:
            for peer in preferred_peers:
                preferred_queue.put_nowait(peer)
            self.add_peers(Peers(preferred_peers))

        # ensure required clients exist, then (re)start tasks for the first `max_parallel_peers`
        for slot_id, client in enumerate(self.clients[: self.max_parallel_peers]):
            task = self.loop_in_thread.run_background(
                self._maintain_connection(
                    slot_id=slot_id,
                    client=client,
                    proxy_info=proxy_info,
                    preferred_queue=preferred_queue,
                )
            )
            self._connection_tasks.append(task)

    def stop(self):
        """Stop."""
        self.peer_discovery.stop()
        self._stop_requested = True
        for task in list(self._connection_tasks):
            task.cancel()
        self._connection_tasks.clear()
        for client in self.clients:
            self.loop_in_thread.run_background(client.disconnect())
        self._active_peers.clear()
        self._current_peers = {i: None for i in range(len(self.clients))}
        self.signal_current_peers_change.emit([])

    @property
    def active_connections(self) -> list[ConnectionInfo]:
        """List of active connections."""
        return [info for info in self._current_peers.values() if info]

    def do_fetch_txs(self, client: P2PClient, inventory: Inventory):
        """Do fetch txs."""
        tx_inventory = Inventory()
        for item in inventory:
            if item.type in [InventoryType.MSG_TX, InventoryType.MSG_WITNESS_TX]:
                tx_inventory.append(item)
        if tx_inventory:
            self.loop_in_thread.run_background(client.getdata(tx_inventory))

    def handle_block_msg(self, inventory: Inventory):
        """Handle block msg."""
        for item in inventory:
            if item.type in [
                InventoryType.MSG_BLOCK,
                InventoryType.MSG_CMPCT_BLOCK,
                InventoryType.MSG_CMPCT_BLOCK,
            ]:
                block_hash = item.payload
                logger.info(f"Block: {item.type=} {block_hash=}")
                self.signal_block.emit(block_hash)

    def on_inv_from_client(self, client: P2PClient, inventory: Inventory):
        """On inv."""
        if self.fetch_txs:
            self.do_fetch_txs(client=client, inventory=inventory)
        self.handle_block_msg(inventory=inventory)

    def on_disconnected_to(self, peer: Peer):
        "Do not keep peers in the list, which disconnected in the past"
        if not self.autodiscover_additional_peers:
            return
        if peer in self.discovered_peers:
            self.discovered_peers.remove(peer)

    def on_received_peers(self, peers: Peers):
        """On received peers."""
        self.add_peers(peers=peers)

    def add_peers(self, peers: Peers):
        # by restricting the new peers, we restrict how fast the discovered_peers can be eclipsed
        """Add peers."""
        maximum_new_peers = 300
        # restricting the total is necessary to restrict memory
        maximum_total_peers = 1000

        new_peers: list[Peer] = []
        for peer in peers:
            if peer not in self.discovered_peers:
                new_peers.append(peer)

        new_peers = self._shuffle_and_restrict(new_peers, max_len=maximum_new_peers)
        self.discovered_peers = self._shuffle_and_restrict(
            self.discovered_peers + new_peers, max_len=maximum_total_peers
        )
        logger.debug(
            f"Added {len(new_peers)=} peers to discovered_peers and shrunk the size to {len(self.discovered_peers)=}"
        )

    @staticmethod
    def _shuffle_and_restrict(some_list: T, max_len: int) -> T:
        """Shuffle and restrict."""
        random.shuffle(some_list)
        del some_list[max_len:]
        return some_list

    def _on_break_current_connection(self) -> None:
        """Slot invoked when `signal_break_current_connection` fires.

        We can’t `await` inside a Qt slot, so we schedule the coroutine.
        """
        for client in self.clients:
            if client.is_running():
                self.loop_in_thread.run_background(client.disconnect())
