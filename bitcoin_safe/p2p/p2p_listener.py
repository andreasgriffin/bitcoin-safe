#
# Bitcoin-Safe
# Copyright (C) 2025-2026 Andreas Griffin
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
#

from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import time
from asyncio import Queue, QueueEmpty
from concurrent.futures import Future
from dataclasses import dataclass
from functools import partial
from threading import RLock
from typing import TypeVar, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.execute_config import ENABLE_P2P_LISTENER_DIAGNOSTICS
from bitcoin_safe.network_config import ConnectionInfo
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.tx import short_tx_id

from .p2p_client import Inventory, InventoryType, P2PClient, P2PDiagnosticEvent, Peer, Peers
from .peer_discovery import PeerDiscovery
from .tools import address_match, outpoint_match

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=list)
SHORT_LIVED_CONNECTION_SECONDS = 30.0
STABLE_CONNECTION_SECONDS = 180.0
CONNECT_FAILURE_COOLDOWN_SECONDS = 120.0
SHORT_LIVED_COOLDOWN_SECONDS = 180.0
PROTOCOL_FAILURE_COOLDOWN_SECONDS = 300.0


@dataclass
class PeerQuality:
    score: float = 0.0
    attempts: int = 0
    handshake_successes: int = 0
    completed_sessions: int = 0
    total_uptime_seconds: float = 0.0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_failure_reason: str | None = None


class P2pListener(QObject):
    signal_relevant_tx = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))
    signal_block = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_break_current_connection = cast(SignalProtocol[[]], pyqtSignal())
    signal_disconnected_to = cast(SignalProtocol[[Peer]], pyqtSignal(Peer))
    signal_try_connecting_to = cast(SignalProtocol[[ConnectionInfo]], pyqtSignal(ConnectionInfo))
    signal_current_peers_change = cast(SignalProtocol[[list[ConnectionInfo]]], pyqtSignal(list))
    signal_peer_tx_rate_change = cast(SignalProtocol[[Peer, float]], pyqtSignal(object, float))

    def __init__(
        self,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
        debug=False,
        fetch_txs=True,
        timeout: int = 200,
        discovered_peers: Peers | list[Peer] | None = None,
        autodiscover_additional_peers: bool = True,
        allowed_peers: Peers | list[Peer] | None = None,
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
        self.allowed_peers = set(allowed_peers) if allowed_peers is not None else None

        self._state_lock = RLock()
        initial_peers = Peers(discovered_peers) if discovered_peers else Peers()
        if self.allowed_peers is not None:
            initial_peers = Peers(peer for peer in initial_peers if peer in self.allowed_peers)
        self._discovered_peers = initial_peers

        self.signal_tracker = SignalTracker()
        self.clients: list[P2PClient] = []
        self._connection_tasks: list[Future[None]] = []
        self._active_peers: set[Peer] = set()
        self._current_peers: dict[int, ConnectionInfo | None] = {}
        self._stop_requested = False
        self._proxy_info: ProxyInfo | None = None
        self._tx_times_by_peer: dict[Peer, list[float]] = {}
        self._peer_quality_by_peer: dict[Peer, PeerQuality] = {}

        self.signal_tracker.connect(self.signal_disconnected_to, self.on_disconnected_to)
        self.signal_tracker.connect(self.signal_break_current_connection, self._on_break_current_connection)
        self._ensure_clients()

    @property
    def discovered_peers(self) -> Peers:
        with self._state_lock:
            return Peers(self._discovered_peers)

    def _snapshot_active_peers(self) -> set[Peer]:
        with self._state_lock:
            return set(self._active_peers)

    def _try_reserve_peer(self, peer: Peer) -> bool:
        """Reserve a peer for one connection slot.

        Candidate selection can await DNS discovery, so checking and adding a peer
        must happen atomically after selection as well.  This prevents two slots
        from connecting to the same peer when they select it concurrently.
        """
        with self._state_lock:
            if peer in self._active_peers:
                return False
            self._active_peers.add(peer)
            return True

    def _snapshot_current_connections(self) -> list[ConnectionInfo]:
        with self._state_lock:
            return [info for info in self._current_peers.values() if info]

    def _peer_quality(self, peer: Peer) -> PeerQuality:
        with self._state_lock:
            quality = self._peer_quality_by_peer.get(peer)
            if quality is None:
                quality = PeerQuality()
                self._peer_quality_by_peer[peer] = quality
            return quality

    def _selection_score(self, peer: Peer, now: float) -> float:
        quality = self._peer_quality(peer)
        uptime_bonus = min(quality.total_uptime_seconds / 300.0, 6.0)
        cooldown_penalty = 50.0 if quality.cooldown_until > now else 0.0
        return quality.score + uptime_bonus - cooldown_penalty

    def _is_selectable_peer(self, peer: Peer, now: float) -> bool:
        return self._peer_quality(peer).cooldown_until <= now

    def _record_connect_attempt(self, peer: Peer) -> None:
        quality = self._peer_quality(peer)
        with self._state_lock:
            quality.attempts += 1

    def _reward_peer(self, peer: Peer, reward: float, reset_failures: bool) -> None:
        quality = self._peer_quality(peer)
        with self._state_lock:
            quality.score = min(quality.score + reward, 40.0)
            if reset_failures:
                quality.consecutive_failures = 0
                quality.cooldown_until = 0.0
                quality.last_failure_reason = None

    def _penalize_peer(self, peer: Peer, penalty: float, cooldown_seconds: float, reason: str) -> None:
        quality = self._peer_quality(peer)
        now = time.time()
        with self._state_lock:
            quality.score = max(quality.score - penalty, -40.0)
            quality.consecutive_failures += 1
            quality.last_failure_reason = reason
            multiplier = min(quality.consecutive_failures, 4)
            quality.cooldown_until = max(quality.cooldown_until, now + cooldown_seconds * multiplier)

    @staticmethod
    def _disconnect_category(reason: str | None) -> str:
        reason_lower = (reason or "").lower()
        if "timed out while waiting" in reason_lower:
            return "read_timeout"
        if "timed out while sending" in reason_lower:
            return "send_timeout"
        if "timed out while establishing" in reason_lower:
            return "connect_timeout"
        if (
            "network is unreachable" in reason_lower
            or "no route to host" in reason_lower
            or "connection refused" in reason_lower
            or "connect call failed" in reason_lower
            or "name or service not known" in reason_lower
        ):
            return "connect_error"
        if "peer closed" in reason_lower:
            return "peer_closed"
        if "checksum" in reason_lower:
            return "bad_checksum"
        if "payload" in reason_lower:
            return "oversized_payload"
        if "rate limit" in reason_lower:
            return "rate_limit"
        if "handler error" in reason_lower or "unknown-command" in reason_lower:
            return "protocol_error"
        return "other"

    def _should_keep_discovered_peer(self, peer: Peer) -> bool:
        quality = self._peer_quality(peer)
        with self._state_lock:
            return quality.score > -20.0 or quality.handshake_successes > 0

    @staticmethod
    def _peer_host_sort_key(peer: Peer) -> int:
        try:
            address = ipaddress.ip_address(peer.host)
        except ValueError:
            return 1
        if address.version == 4:
            return 2
        return 0

    def _select_discovered_peer(self, candidates: list[Peer]) -> Peer | None:
        if not candidates:
            return None
        now = time.time()
        selectable = [peer for peer in candidates if self._is_selectable_peer(peer, now)]
        if not selectable:
            return None

        best_score = max(self._selection_score(peer, now) for peer in selectable)
        best_candidates = [peer for peer in selectable if self._selection_score(peer, now) == best_score]
        best_candidates.sort(key=self._peer_host_sort_key, reverse=True)
        return random.choice(best_candidates)

    async def _select_dns_peer(self, exclude_peers: set[Peer]) -> Peer | None:
        for _ in range(5):
            peer = await self.peer_discovery.get_bitcoin_peer(proxy_info=self._proxy_info)
            if peer is None:
                return None
            if self.allowed_peers is not None and peer not in self.allowed_peers:
                continue
            if peer in exclude_peers:
                continue
            if not self._is_selectable_peer(peer, time.time()):
                continue
            return peer
        return None

    def on_client_diagnostic(self, event: P2PDiagnosticEvent) -> None:
        peer = event.peer
        if peer is None:
            return

        if event.event == "connect_attempt":
            self._record_connect_attempt(peer)
            return
        if event.event == "verack_received":
            quality = self._peer_quality(peer)
            with self._state_lock:
                quality.handshake_successes += 1
            self._reward_peer(peer, reward=2.0, reset_failures=True)
            return
        if event.event == "connect_timeout":
            self._penalize_peer(
                peer,
                penalty=5.0,
                cooldown_seconds=CONNECT_FAILURE_COOLDOWN_SECONDS,
                reason=event.detail or "connect_timeout",
            )
            return
        if event.event == "connect_error":
            self._penalize_peer(
                peer,
                penalty=6.0,
                cooldown_seconds=CONNECT_FAILURE_COOLDOWN_SECONDS,
                reason=event.detail or "connect_error",
            )
            return
        if event.event != "disconnected":
            return

        uptime = event.uptime_seconds or 0.0
        quality = self._peer_quality(peer)
        with self._state_lock:
            quality.completed_sessions += 1
            quality.total_uptime_seconds += uptime

        category = self._disconnect_category(event.detail)
        if category == "read_timeout" and uptime >= max(float(self.timeout) - 5.0, 30.0):
            self._reward_peer(peer, reward=2.0, reset_failures=True)
            return
        if uptime >= STABLE_CONNECTION_SECONDS:
            self._reward_peer(peer, reward=6.0, reset_failures=True)
            return
        if category == "peer_closed":
            if uptime < SHORT_LIVED_CONNECTION_SECONDS:
                self._penalize_peer(
                    peer,
                    penalty=4.0,
                    cooldown_seconds=SHORT_LIVED_COOLDOWN_SECONDS,
                    reason=event.detail or "peer_closed",
                )
            else:
                self._reward_peer(peer, reward=1.0, reset_failures=True)
            return
        if category in {"send_timeout", "bad_checksum", "oversized_payload", "rate_limit", "protocol_error"}:
            self._penalize_peer(
                peer,
                penalty=5.0,
                cooldown_seconds=PROTOCOL_FAILURE_COOLDOWN_SECONDS,
                reason=event.detail or category,
            )
            return
        if uptime < SHORT_LIVED_CONNECTION_SECONDS:
            self._penalize_peer(
                peer,
                penalty=3.0,
                cooldown_seconds=SHORT_LIVED_COOLDOWN_SECONDS,
                reason=event.detail or category,
            )
            return
        self._reward_peer(peer, reward=1.0, reset_failures=True)

    def _on_client_diagnostic_signal(self, event: object) -> None:
        if isinstance(event, P2PDiagnosticEvent):
            self.on_client_diagnostic(event)

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
        self.signal_tracker.connect(client.signal_tx_received, partial(self.on_received_tx, slot_id, client))
        self.signal_tracker.connect(client.signal_try_connecting_to, self.signal_try_connecting_to.emit)
        self.signal_tracker.connect(client.signal_diagnostic, self._on_client_diagnostic_signal)
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
        with self._state_lock:
            self._current_peers[slot_id] = connection_info
        self.signal_current_peers_change.emit(self.active_connections)

    def get_current_peers(self):
        return self._snapshot_current_connections()

    @property
    def tx_rates(self) -> dict[Peer, float]:
        """Return rolling received transaction rates per connected peer."""
        now = time.monotonic()
        with self._state_lock:
            return {
                peer: len([timestamp for timestamp in timestamps if timestamp >= now - 60.0]) / 60.0
                for peer, timestamps in self._tx_times_by_peer.items()
            }

    def on_received_tx(self, slot_id: int, client: P2PClient, tx: bdk.Transaction):
        """Track per-peer tx rate and forward wallet-relevant transactions."""
        peer = client.current_peer()
        if peer is None:
            if ENABLE_P2P_LISTENER_DIAGNOSTICS:
                logger.warning("P2P tx received on slot %s without a current peer", slot_id)
            return

        now = time.monotonic()
        with self._state_lock:
            timestamps = self._tx_times_by_peer.setdefault(peer, [])
            timestamps[:] = [timestamp for timestamp in timestamps if timestamp >= now - 60.0]
            timestamps.append(now)
            rate = len(timestamps) / 60.0
        self.signal_peer_tx_rate_change.emit(peer, rate)

        if ENABLE_P2P_LISTENER_DIAGNOSTICS:
            txid = short_tx_id(tx.compute_txid())
            logger.info("P2P tx [slot %s %s] txid=%s rate=%.2f txs/s", slot_id, peer, txid, rate)

        if (self.address_filter is not None) and address_match(
            tx=tx, network=self.network, address_filter=self.address_filter
        ):
            self.signal_relevant_tx.emit(tx)
            return
        if (self.outpoint_filter is not None) and outpoint_match(tx=tx, outpoint_filter=self.outpoint_filter):
            self.signal_relevant_tx.emit(tx)
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

        with self._state_lock:
            discovered_candidates = [peer for peer in self._discovered_peers if peer not in exclude_peers]

        # Fast paths -------------------------------------------------
        if not discovered_candidates:
            if not self.autodiscover_additional_peers:
                logger.debug("Peer discovery disabled; no discovered peers available")
                return None
            peer = await self._select_dns_peer(exclude_peers=exclude_peers)
            logger.debug(f"Picked {peer=} from DNS seed")
            return peer
        if weight_dns == 0:
            peer = self._select_discovered_peer(discovered_candidates)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        total = weight_getaddr + weight_dns
        if total == 0:
            raise ValueError("both weights are zero")

        # Weighted choice -------------------------------------------
        pick = random.random() * total
        if pick < weight_getaddr and discovered_candidates:
            peer = self._select_discovered_peer(discovered_candidates)
            logger.debug(f"Picked {peer=} from discovered_peers")
            return peer

        peer = await self._select_dns_peer(exclude_peers=exclude_peers)
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
                exclude_peers=self._snapshot_active_peers(),
            )
            if peer is None:
                await asyncio.sleep(retry_delay)
                continue

            if peer == previous_peer:
                await asyncio.sleep(retry_delay)

            if not self._try_reserve_peer(peer):
                continue
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
                with self._state_lock:
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
        self._proxy_info = proxy_info
        self._stop_requested = False
        for task in list(self._connection_tasks):
            task.cancel()
        for client in self.clients:
            self.loop_in_thread.run_background(client.disconnect())
        with self._state_lock:
            self._active_peers.clear()
            self._current_peers = {i: None for i in range(len(self.clients))}
            self._tx_times_by_peer.clear()
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
        with self._state_lock:
            self._active_peers.clear()
            self._current_peers = {i: None for i in range(len(self.clients))}
        self.signal_current_peers_change.emit([])

    @property
    def active_connections(self) -> list[ConnectionInfo]:
        """List of active connections."""
        return self._snapshot_current_connections()

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
        with self._state_lock:
            self._tx_times_by_peer.pop(peer, None)

    def on_received_peers(self, peers: Peers):
        """On received peers."""
        self.add_peers(peers=peers)

    def add_peers(self, peers: Peers):
        # by restricting the new peers, we restrict how fast the discovered_peers can be eclipsed
        """Add peers."""
        maximum_new_peers = 300
        # restricting the total is necessary to restrict memory
        maximum_total_peers = 1000

        if self.allowed_peers is not None:
            peers = Peers(peer for peer in peers if peer in self.allowed_peers)

        with self._state_lock:
            new_peers = [peer for peer in peers if peer not in self._discovered_peers]
            new_peers = self._shuffle_and_restrict(new_peers, max_len=maximum_new_peers)
            combined_peers = [
                peer for peer in self._discovered_peers if self._should_keep_discovered_peer(peer)
            ]
            combined_peers.extend(new_peers)
            self._discovered_peers = self._restrict_peers_by_quality(
                combined_peers, max_len=maximum_total_peers
            )
            discovered_count = len(self._discovered_peers)
        logger.debug(
            f"Added {len(new_peers)=} peers to discovered_peers and shrunk the size to {discovered_count=}"
        )

    @staticmethod
    def _shuffle_and_restrict(some_list: T, max_len: int) -> T:
        """Shuffle and restrict."""
        random.shuffle(some_list)
        del some_list[max_len:]
        return some_list

    def _restrict_peers_by_quality(self, peers: list[Peer], max_len: int) -> Peers:
        """Keep the strongest known peers when trimming the discovered pool."""
        unique_peers = list(dict.fromkeys(peers))
        random.shuffle(unique_peers)
        unique_peers.sort(key=lambda peer: self._selection_score(peer, time.time()), reverse=True)
        del unique_peers[max_len:]
        return Peers(unique_peers)

    def _on_break_current_connection(self) -> None:
        """Slot invoked when `signal_break_current_connection` fires.

        We can’t `await` inside a Qt slot, so we schedule the coroutine.
        """
        for client in self.clients:
            if client.is_running():
                self.loop_in_thread.run_background(client.disconnect())
