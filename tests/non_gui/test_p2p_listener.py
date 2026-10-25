#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
import threading
import time

import bdkpython as bdk

from bitcoin_safe.network_config import ConnectionInfo, Peer
from bitcoin_safe.p2p.p2p_client import (
    Inventory,
    InventoryItem,
    InventoryType,
    P2PClient,
    P2PDiagnosticEvent,
    encode_varint,
)
from bitcoin_safe.p2p.p2p_listener import P2pListener
from bitcoin_safe.p2p.tools import BoundedTxidSet

VALID_TEST_TX = (
    "0200000000010101d7eb881ab8cac7d6adc6a7f9aa13e694813d95330c7299cee3623e5d14bd590000000000fdffffff"
    "02c5e6c1010000000016001407103a1cccf6a1ea654bee964a4020d20c41fb055c819725010000001600146337ec04"
    "bf42015e5d077b90cae05c06925c491a0247304402206aae2bf32da4c3b71cb95e6633c22f9f5a4a4f459975965c0c39"
    "b0ab439737b702200c4b16d2029383190965b07adeb87e6d634c68c70d2742f25e456874e8dc273a012103930326d6d7"
    "2f8663340ce4341d0d3bdb1a1c0734d46e5df8a3003ab6bb50073b00000000"
)


def _always_running() -> bool:
    return True


def _always_match_outpoint(tx: bdk.Transaction, outpoint_filter: set[str]) -> bool:
    del tx, outpoint_filter
    return True


def test_p2p_listener_shared_state_accessors_return_snapshots() -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    peer = Peer(host="127.0.0.1", port=18444)
    connection = ConnectionInfo(peer=peer, proxy_info=None)
    try:
        listener.add_peers([peer])
        with listener._state_lock:
            listener._current_peers[0] = connection

        discovered_snapshot = listener.discovered_peers
        active_snapshot = listener.active_connections

        discovered_snapshot.clear()
        active_snapshot.clear()

        assert listener.discovered_peers == [peer]
        assert listener.active_connections == [connection]
    finally:
        listener.stop()


def test_p2p_listener_allowed_peers_filter_discovered_peers() -> None:
    allowed_peer = Peer(host="127.0.0.1", port=18444)
    rejected_peer = Peer(host="127.0.0.1", port=18445)
    listener = P2pListener(
        network=bdk.Network.REGTEST,
        loop_in_thread=None,
        autodiscover_additional_peers=False,
        allowed_peers=[allowed_peer],
        discovered_peers=[allowed_peer, rejected_peer],
    )
    try:
        listener.add_peers([rejected_peer])
        listener.on_received_peers([rejected_peer])
        assert listener.discovered_peers == [allowed_peer]
    finally:
        listener.stop()


def test_p2p_listener_reserves_peer_only_once() -> None:
    peer = Peer(host="127.0.0.1", port=18444)
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    try:
        assert listener._try_reserve_peer(peer)
        assert not listener._try_reserve_peer(peer)
    finally:
        listener.stop()


def test_p2p_listener_skips_disallowed_and_cooled_preferred_peers() -> None:
    allowed_peer = Peer(host="127.0.0.1", port=18444)
    rejected_peer = Peer(host="127.0.0.1", port=18445)
    listener = P2pListener(
        network=bdk.Network.REGTEST,
        loop_in_thread=None,
        autodiscover_additional_peers=False,
        allowed_peers=[allowed_peer],
        discovered_peers=[allowed_peer],
    )

    async def select_preferred_peer(peer: Peer) -> Peer | None:
        preferred_queue: asyncio.Queue[Peer] = asyncio.Queue()
        preferred_queue.put_nowait(peer)
        return await listener._next_peer_candidate(preferred_queue, exclude_peers=set())

    try:
        assert asyncio.run(select_preferred_peer(rejected_peer)) == allowed_peer
        listener._penalize_peer(
            allowed_peer,
            penalty=1.0,
            cooldown_seconds=120.0,
            reason="test cooldown",
        )
        assert asyncio.run(select_preferred_peer(allowed_peer)) is None
    finally:
        listener.stop()


def test_p2p_listener_tx_rates_returns_recent_peer_rates() -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    peer = Peer(host="127.0.0.1", port=18444)
    try:
        with listener._state_lock:
            listener._tx_times_by_peer[peer] = [0.0]
        assert peer in listener.tx_rates
        assert listener.tx_rates[peer] >= 0
    finally:
        listener.stop()


def test_p2p_client_advertises_observer_capabilities() -> None:
    client = P2PClient(network=bdk.Network.REGTEST)
    payload = client._version_payload(Peer(host="127.0.0.1", port=18444))
    version = client._decode_version(payload)

    assert version["services"] == 1 << 3
    assert version["user_agent"].startswith("/Satoshi:")
    assert version["user_agent"].endswith("/")
    assert version["start_height"] == 0


def test_p2p_client_ignores_unknown_inventory_types() -> None:
    payload = encode_varint(2) + (99).to_bytes(4, "little") + bytes(32)
    payload += InventoryType.MSG_TX.value.to_bytes(4, "little") + bytes.fromhex("11" * 32)[::-1]

    inventory = P2PClient._parse_inv(payload)

    assert len(inventory) == 1
    assert inventory[0].type is InventoryType.MSG_TX


def test_p2p_client_rejects_truncated_inventory() -> None:
    payload = encode_varint(1) + bytes(35)

    try:
        P2PClient._parse_inv(payload)
    except ValueError as error:
        assert str(error) == "truncated inv payload"
    else:
        raise AssertionError("Expected truncated inventory to be rejected")


def test_p2p_listener_on_received_tx_updates_rate_and_emits_relevant_tx(monkeypatch) -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    peer = Peer(host="127.0.0.1", port=18444)
    client = P2PClient(network=bdk.Network.REGTEST)
    client._current_peer = peer
    tx = bdk.Transaction(bytes.fromhex(VALID_TEST_TX))
    seen_txs: list[bdk.Transaction] = []
    seen_rates: list[tuple[Peer, float]] = []

    def record_rate(seen_peer: Peer, rate: float) -> None:
        seen_rates.append((seen_peer, rate))

    listener.signal_relevant_tx.connect(seen_txs.append)
    listener.signal_peer_tx_rate_change.connect(record_rate)
    listener.set_outpoint_filter({"mock:0"})
    monkeypatch.setattr("bitcoin_safe.p2p.p2p_listener.outpoint_match", _always_match_outpoint)
    try:
        listener.on_received_tx(slot_id=0, client=client, tx=tx)
        assert seen_txs == [tx]
        assert seen_rates and seen_rates[0][0] == peer
        assert peer in listener.tx_rates
    finally:
        listener.stop()


def test_bounded_txid_set_add_if_new_and_eviction() -> None:
    txids = BoundedTxidSet(max_size=2)
    assert txids.add_if_new("a")
    assert txids.add_if_new("b")
    assert not txids.add_if_new("a")  # duplicate, no insert
    assert txids.add_if_new("c")  # evicts oldest inserted "a"

    assert "a" not in txids
    assert "b" in txids
    assert "c" in txids
    assert len(txids) == 2


def test_bounded_txid_set_duplicate_rate_counts_duplicate_hits() -> None:
    txids = BoundedTxidSet(max_size=10)
    assert txids.duplicate_rate == 0.0
    assert txids.add_if_new("a")
    assert not txids.add_if_new("a")
    assert not txids.add_if_new("a")
    assert txids.duplicate_rate == 2 / 60.0


def test_bounded_txid_set_add_if_new_is_thread_safe() -> None:
    txids = BoundedTxidSet(max_size=10_000)
    wins: list[bool] = []
    wins_lock = threading.Lock()

    def worker() -> None:
        local_wins = [txids.add_if_new(f"{i:064x}") for i in range(2_000)]
        with wins_lock:
            wins.append(sum(local_wins))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Each txid must be "new" for exactly one thread.
    assert sum(wins) == 2_000
    assert len(txids) == 2_000


def test_p2p_listener_on_received_tx_ignores_duplicate_from_other_peer(monkeypatch) -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    first_peer = Peer(host="127.0.0.1", port=18444)
    second_peer = Peer(host="127.0.0.2", port=18444)
    first_client = P2PClient(network=bdk.Network.REGTEST)
    first_client._current_peer = first_peer
    second_client = P2PClient(network=bdk.Network.REGTEST)
    second_client._current_peer = second_peer
    tx = bdk.Transaction(bytes.fromhex(VALID_TEST_TX))
    seen_txs: list[bdk.Transaction] = []
    seen_rates: list[tuple[Peer, float]] = []

    listener.signal_relevant_tx.connect(seen_txs.append)
    listener.signal_peer_tx_rate_change.connect(lambda peer, rate: seen_rates.append((peer, rate)))
    listener.set_outpoint_filter({"mock:0"})
    monkeypatch.setattr("bitcoin_safe.p2p.p2p_listener.outpoint_match", _always_match_outpoint)
    try:
        listener.on_received_tx(slot_id=0, client=first_client, tx=tx)
        listener.on_received_tx(slot_id=1, client=second_client, tx=tx)
        assert seen_txs == [tx]
        assert [peer for peer, _ in seen_rates] == [first_peer]
        assert second_peer not in listener.tx_rates
    finally:
        listener.stop()


def test_p2p_listener_logs_deduplicated_tx_rate(monkeypatch) -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    monkeypatch.setattr("bitcoin_safe.p2p.p2p_listener.ENABLE_P2P_LISTENER_DIAGNOSTICS", True)
    logged: list[str] = []
    monkeypatch.setattr(
        "bitcoin_safe.p2p.p2p_listener.logger.info",
        lambda message, *args: logged.append(message % args),
    )
    peer = Peer(host="127.0.0.1", port=18444)
    client = P2PClient(network=bdk.Network.REGTEST)
    client._current_peer = peer
    tx = bdk.Transaction(bytes.fromhex(VALID_TEST_TX))
    try:
        listener.on_received_tx(slot_id=0, client=client, tx=tx)
        listener.on_received_tx(slot_id=0, client=client, tx=tx)
        assert listener._seen_txids.duplicate_rate > 0
        assert any("deduplicated_tx/s=" in line for line in logged)
    finally:
        listener.stop()


def test_p2p_listener_do_fetch_txs_does_not_cache_requested_txids(monkeypatch) -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    txid = "44" * 32
    requested: list[Inventory] = []

    async def record_getdata(inventory: Inventory) -> None:
        requested.append(inventory)

    client = P2PClient(network=bdk.Network.REGTEST)
    monkeypatch.setattr(client, "getdata", record_getdata)
    monkeypatch.setattr(listener.loop_in_thread, "run_background", lambda coro: asyncio.run(coro))
    inventory = Inventory([InventoryItem(type=InventoryType.MSG_WITNESS_TX, payload=txid)])
    try:
        listener.do_fetch_txs(client=client, inventory=inventory)
        assert len(requested) == 1
        # Sending getdata must not mark the txid as seen; only receipt does.
        assert txid not in listener._seen_txids
        listener.do_fetch_txs(client=client, inventory=inventory)
        assert len(requested) == 2
    finally:
        listener.stop()


def test_p2p_listener_do_fetch_txs_skips_already_seen_txids(monkeypatch) -> None:
    listener = P2pListener(
        network=bdk.Network.REGTEST, loop_in_thread=None, autodiscover_additional_peers=False
    )
    tx = bdk.Transaction(bytes.fromhex(VALID_TEST_TX))
    seen_txid = str(tx.compute_txid())
    unseen_txid = "22" * 32
    block_hash = "33" * 32
    requested: list[Inventory] = []

    async def record_getdata(inventory: Inventory) -> None:
        requested.append(inventory)

    client = P2PClient(network=bdk.Network.REGTEST)
    monkeypatch.setattr(client, "getdata", record_getdata)
    monkeypatch.setattr(listener.loop_in_thread, "run_background", lambda coro: asyncio.run(coro))
    listener._seen_txids.add_if_new(seen_txid)
    inventory = Inventory(
        [
            InventoryItem(type=InventoryType.MSG_WITNESS_TX, payload=seen_txid),
            InventoryItem(type=InventoryType.MSG_WITNESS_TX, payload=unseen_txid),
            InventoryItem(type=InventoryType.MSG_BLOCK, payload=block_hash),
        ]
    )
    try:
        listener.do_fetch_txs(client=client, inventory=inventory)
        assert len(requested) == 1
        assert [item.payload for item in requested[0]] == [unseen_txid]
    finally:
        listener.stop()


def test_p2p_listener_prefers_scored_stable_peers() -> None:
    preferred_peer = Peer(host="127.0.0.1", port=18444)
    penalized_peer = Peer(host="127.0.0.1", port=18445)
    listener = P2pListener(
        network=bdk.Network.REGTEST,
        loop_in_thread=None,
        autodiscover_additional_peers=False,
        discovered_peers=[preferred_peer, penalized_peer],
    )
    try:
        listener.on_client_diagnostic(
            P2PDiagnosticEvent(
                event="verack_received",
                peer=preferred_peer,
                timestamp=time.time(),
                handshake_stage="verack_received",
                detail="Handshake complete",
            )
        )
        listener.on_client_diagnostic(
            P2PDiagnosticEvent(
                event="disconnected",
                peer=preferred_peer,
                timestamp=time.time(),
                handshake_stage="verack_received",
                detail="Peer closed the connection during read",
                uptime_seconds=240.0,
            )
        )
        listener.on_client_diagnostic(
            P2PDiagnosticEvent(
                event="connect_error",
                peer=penalized_peer,
                timestamp=time.time(),
                handshake_stage="connecting",
                detail="[Errno 101] Network is unreachable",
            )
        )

        assert listener._select_discovered_peer([preferred_peer, penalized_peer]) == preferred_peer
    finally:
        listener.stop()


def test_p2p_listener_cools_down_short_lived_peer() -> None:
    peer = Peer(host="127.0.0.1", port=18444)
    listener = P2pListener(
        network=bdk.Network.REGTEST,
        loop_in_thread=None,
        autodiscover_additional_peers=False,
        discovered_peers=[peer],
    )
    try:
        listener.on_client_diagnostic(
            P2PDiagnosticEvent(
                event="disconnected",
                peer=peer,
                timestamp=time.time(),
                handshake_stage="verack_received",
                detail="Peer closed the connection during read",
                uptime_seconds=4.0,
            )
        )

        assert not listener._is_selectable_peer(peer, time.time())
    finally:
        listener.stop()


def test_p2p_client_idle_timeout_after_handshake_sends_ping_gracefully() -> None:
    client = P2PClient(network=bdk.Network.REGTEST, timeout=1)
    client._handshake_stage = "verack_received"
    client._connected_at = time.monotonic()

    sent_messages: list[tuple[str, bytes]] = []

    async def fake_send_raw(cmd: str, payload: bytes) -> None:
        sent_messages.append((cmd, payload))

    client._send_raw = fake_send_raw  # type: ignore[method-assign]
    client.is_running = _always_running  # type: ignore[method-assign]

    assert asyncio.run(client._handle_idle_read_timeout(expected_bytes=24, received_bytes=0))
    assert sent_messages
    assert sent_messages[0][0] == "ping"
    assert client._idle_timeout_probes_sent == 1


def test_p2p_client_idle_timeout_before_handshake_disconnects() -> None:
    client = P2PClient(network=bdk.Network.REGTEST, timeout=1)
    client._handshake_stage = "version_sent"
    client._connected_at = time.monotonic()

    sent_messages: list[tuple[str, bytes]] = []

    async def fake_send_raw(cmd: str, payload: bytes) -> None:
        sent_messages.append((cmd, payload))

    client._send_raw = fake_send_raw  # type: ignore[method-assign]
    client.is_running = _always_running  # type: ignore[method-assign]

    assert not asyncio.run(client._handle_idle_read_timeout(expected_bytes=24, received_bytes=0))
    assert not sent_messages
