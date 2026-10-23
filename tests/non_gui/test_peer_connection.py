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

import bdkpython as bdk

from bitcoin_safe.gui.qt.network_settings import main as network_settings_main
from bitcoin_safe.network_config import NetworkConfig, Peer, Peers, PeerSelectionMode
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.p2p.p2p_client import (
    P2PClient,
    PeerConnectionResult,
    PeerConnectionTestResult,
    validate_peer_connections,
)
from bitcoin_safe.pythonbdk_types import BlockchainType


class _Reader:
    async def readexactly(self, size: int) -> bytes:
        return bytes(size)


class _Writer:
    def __init__(self) -> None:
        self.closed = False

    def write(self, data: bytes) -> None:
        pass

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_peer_connections_tests_all_peers_and_applies_threshold(monkeypatch) -> None:
    peers = Peers([Peer("127.0.0.1", 18444), Peer("127.0.0.1", 18445), Peer("127.0.0.1", 18446)])
    attempted: list[tuple[Peer, ProxyInfo | None]] = []

    async def fake_connect(cls, peer, proxy_info, timeout):
        attempted.append((peer, proxy_info))
        if peer.port == 18446:
            raise ConnectionError("refused")
        return _Reader(), _Writer()

    monkeypatch.setattr(P2PClient, "_connect", classmethod(fake_connect))

    async def fake_is_peer_on_network(**kwargs):
        del kwargs
        return True

    monkeypatch.setattr("bitcoin_safe.p2p.p2p_client.is_peer_on_network", fake_is_peer_on_network)

    result = validate_peer_connections(
        peers, network=bdk.Network.REGTEST, proxy_info=None, required_connections=2
    )

    assert result.success
    assert result.successful_connections == 2
    assert [peer for peer, _ in attempted] == list(peers)
    assert "127.0.0.1:18446: Failed: refused" in result.format_details()


def test_peer_connections_passes_proxy_and_fails_below_threshold(monkeypatch) -> None:
    peer = Peer("example.com", 8333)
    proxy_info = ProxyInfo(host="127.0.0.1", port=9050)
    attempted: list[ProxyInfo | None] = []

    async def fake_connect(cls, peer, proxy_info, timeout):
        attempted.append(proxy_info)
        raise TimeoutError("timed out")

    monkeypatch.setattr(P2PClient, "_connect", classmethod(fake_connect))

    async def fake_is_peer_on_network(**kwargs):
        del kwargs
        return True

    monkeypatch.setattr("bitcoin_safe.p2p.p2p_client.is_peer_on_network", fake_is_peer_on_network)

    result = validate_peer_connections(
        [peer], network=bdk.Network.BITCOIN, proxy_info=proxy_info, required_connections=1
    )

    assert not result.success
    assert result.successful_connections == 0
    assert attempted == [proxy_info]


def test_peer_connections_rejects_peer_on_wrong_network(monkeypatch) -> None:
    peer = Peer("127.0.0.1", 18444)

    async def fake_connect(cls, peer, proxy_info, timeout):
        del cls, peer, proxy_info, timeout
        return _Reader(), _Writer()

    async def fake_is_peer_on_network(**kwargs):
        del kwargs
        return False

    monkeypatch.setattr(P2PClient, "_connect", classmethod(fake_connect))
    monkeypatch.setattr("bitcoin_safe.p2p.p2p_client.is_peer_on_network", fake_is_peer_on_network)

    result = validate_peer_connections(
        [peer], network=bdk.Network.REGTEST, proxy_info=None, required_connections=1
    )

    assert not result.success
    assert result.results[0].error == "Peer is not on the REGTEST network"


def test_cbf_connection_test_validates_configured_peers(monkeypatch) -> None:
    config = NetworkConfig(network=bdk.Network.REGTEST)
    config.server_type = BlockchainType.CompactBlockFilter
    config.peer_selection_mode = PeerSelectionMode.only_configured
    config.cbf_connections = 2
    config.configured_peers = Peers([Peer("127.0.0.1", 18444), Peer("127.0.0.1", 18445)])
    expected = PeerConnectionTestResult(
        results=tuple(PeerConnectionResult(peer=peer, connected=True) for peer in config.configured_peers),
        required_connections=2,
    )
    monkeypatch.setattr(network_settings_main, "validate_peer_connections", lambda **kwargs: expected)

    result = network_settings_main.test_connection(config)

    assert result.success
    assert result.peer_results == expected.results
    assert "Connected to 2/2 peers" in result.format_details()


def test_cbf_connection_test_reports_failed_peers(monkeypatch) -> None:
    config = NetworkConfig(network=bdk.Network.REGTEST)
    config.server_type = BlockchainType.CompactBlockFilter
    config.peer_selection_mode = PeerSelectionMode.only_configured
    config.cbf_connections = 2
    config.configured_peers = Peers([Peer("127.0.0.1", 18444), Peer("127.0.0.1", 18445)])
    expected = PeerConnectionTestResult(
        results=(
            PeerConnectionResult(peer=config.configured_peers[0], connected=True),
            PeerConnectionResult(peer=config.configured_peers[1], connected=False, error="refused"),
        ),
        required_connections=2,
    )
    monkeypatch.setattr(network_settings_main, "validate_peer_connections", lambda **kwargs: expected)

    result = network_settings_main.test_connection(config)

    assert not result.success
    details = result.format_details()
    assert "Connected: 127.0.0.1:18444" in details
    assert "Failed: 127.0.0.1:18445 (refused)" in details
