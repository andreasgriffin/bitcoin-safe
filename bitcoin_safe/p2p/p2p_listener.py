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
from typing import TypeVar, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal

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

    def __init__(
        self,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
        debug=False,
        fetch_txs=True,
        timeout: int = 200,
        discovered_peers: Peers | list[Peer] | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.fetch_txs = fetch_txs
        self.client = P2PClient(network=network, debug=debug, timeout=timeout, parent=self)
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self.address_filter: set[str] | None = None
        self.outpoint_filter: set[str] | None = None
        self.peer_discovery = PeerDiscovery(network=network, loop_in_thread=self.loop_in_thread)

        self.discovered_peers = discovered_peers if discovered_peers else Peers()

        # signals
        self.client.signal_received_peers.connect(self.on_received_peers)
        self.client.signal_disconnected_to.connect(self.on_disconnected_to)
        self.signal_disconnected_to.connect(self.on_disconnected_to)
        self.client.signal_inv.connect(self.on_inv)
        self.client.signal_tx.connect(self.on_tx)
        self.signal_break_current_connection.connect(self._on_break_current_connection)

    def set_address_filter(self, address_filter: set[str] | None):
        """Set address filter."""
        self.address_filter = address_filter

    def set_outpoint_filter(self, outpoint_filter: set[str] | None):
        """Set outpoint filter."""
        self.outpoint_filter = outpoint_filter

    def on_tx(self, tx: bdk.Transaction):
        """On tx."""
        if (self.address_filter is not None) and address_match(
            tx=tx, network=self.client.network, address_filter=self.address_filter
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
    ) -> Peer | None:
        """Pick a random peer according to two relative weights.

        Parameters
        ----------
        weight_getaddr : float
            Relative chance to pick from `self.discovered_peers`
            (addresses learned via getaddr/addrv2).
        weight_dns : float
            Relative chance to call `self.peer_discovery.get_bitcoin_peer()`
            (DNS seeds, hard-coded lists, etc.).

        Returns
        -------
        Peer | None
            A `Peer` object, or `None` if neither source has anything.
        """
        if weight_getaddr < 0 or weight_dns < 0:
            raise ValueError("weights must be non-negative")

        # Fast paths -------------------------------------------------
        if not self.discovered_peers:
            peer = await self.peer_discovery.get_bitcoin_peer()  # may be None
            logger.debug(f"Picked {peer=} from DNS seed")
            return peer
        if weight_dns == 0:
            peer = random.choice(self.discovered_peers)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        total = weight_getaddr + weight_dns
        if total == 0:
            raise ValueError("both weights are zero")

        # Weighted choice -------------------------------------------
        pick = random.random() * total
        if pick < weight_getaddr and self.discovered_peers:
            peer = random.choice(self.discovered_peers)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        peer = await self.peer_discovery.get_bitcoin_peer()  # may be None
        logger.debug(f"Picked {peer=} from DNS seed")
        return peer

    async def _start(
        self,
        proxy_info: ProxyInfo | None,
        initial_peer: Peer | None = None,
    ) -> None:
        """Keep the client *always* connected to **some** Bitcoin peer.

        Parameters
        ----------
        initial_peer : Peer | None
            A preferred first peer to try. If it is ``None`` or the connection
            to it fails, we fall back to peers returned by ``get_bitcoin_peer()``.
        """
        previous_peer: Peer | None = None
        peer = initial_peer
        retry_delay = 5  # seconds to wait when no peer is immediately available

        while True:
            start_time: float | None = None

            # ------------------------------------------------------------------
            # 1. Select the next peer (and avoid repeating the last one immediately)
            # ------------------------------------------------------------------
            if peer is None:
                peer = await self.random_select_peer()
                if peer is None:
                    # no peers at all? wait then retry
                    await asyncio.sleep(retry_delay)
                    continue

            # if it's the same as last time, back off before retrying
            if peer == previous_peer:
                logger.info(f"Peer {peer!r} was just tried—waiting {retry_delay}s before retry")
                await asyncio.sleep(retry_delay)

            logger.info(f"Try peer: {peer!r}")

            try:
                # ------------------------------------------------------------------
                # 2. Try to connect
                # ------------------------------------------------------------------
                await self.client.connect(peer=peer, proxy_info=proxy_info)
                start_time = time.monotonic()

                # Connection attempt failed outright → pick a new peer next loop
                if not self.client.is_running():
                    peer = None
                    continue

                # ------------------------------------------------------------------
                # 3. We are connected – stay connected until something breaks
                # ------------------------------------------------------------------
                await self.client.listen_forever()  # returns on disconnect/error

            except asyncio.CancelledError:
                # Allow external task-cancellation to propagate
                await self.client.disconnect()
                raise

            except Exception as exc:
                # signal disconnection, then retry a fresh peer next time
                if peer:
                    self.signal_disconnected_to.emit(peer)
                logger.debug(f"Connection error with {peer}: {exc}")
            finally:
                # Ensure the socket is fully closed before we loop again
                await self.client.disconnect()

                if peer and start_time is not None:
                    elapsed = time.monotonic() - start_time
                    logger.info(f"Disconnected from {peer!r} after {elapsed:.2f} seconds")

                # remember which peer we just tried, then force a fresh pick
                previous_peer = peer
                peer = None

    def start(
        self,
        proxy_info: ProxyInfo | None,
        initial_peer: Peer | None = None,
    ):
        """Start."""
        self.loop_in_thread.run_background(self._start(initial_peer=initial_peer, proxy_info=proxy_info))

    def stop(self):
        """Stop."""
        self.peer_discovery.stop()
        self.loop_in_thread.stop()

    def do_fetch_txs(self, inventory: Inventory):
        """Do fetch txs."""
        tx_inventory = Inventory()
        for item in inventory:
            if item.type in [InventoryType.MSG_TX, InventoryType.MSG_WITNESS_TX]:
                tx_inventory.append(item)
        self.loop_in_thread.run_background(self.client.getdata(tx_inventory))

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

    def on_inv(self, inventory: Inventory):
        """On inv."""
        if self.fetch_txs:
            self.do_fetch_txs(inventory=inventory)
        self.handle_block_msg(inventory=inventory)

    def on_disconnected_to(self, peer: Peer):
        "Do not keep peers in the list, which disconnected in the past"
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
            f"Added {len(new_peers)=} peers to discovered_peers and "
            f"shrunk the size to {len(self.discovered_peers)=}"
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
        if not self.client.is_running():  # already closed
            return
        self.loop_in_thread.run_background(self.client.disconnect())
