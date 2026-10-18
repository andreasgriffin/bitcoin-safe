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
import time

import bdkpython as bdk

from bitcoin_safe.network_config import ConnectionInfo, Peer
from bitcoin_safe.p2p.p2p_client import InventoryType, P2PClient, P2PDiagnosticEvent, encode_varint
from bitcoin_safe.p2p.p2p_listener import P2pListener

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
