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

import bdkpython as bdk

from bitcoin_safe.network_config import Peer
from bitcoin_safe.network_utils import ProxyInfo, ResolvedEndpoint
from bitcoin_safe.p2p.peer_discovery import DNS_SEEDS, PeerDiscovery


def test_loopback_peer_is_excluded_when_unreachable(monkeypatch) -> None:
    seed_config = {"hosts": ["127.0.0.1"], "port": 8333}
    monkeypatch.setitem(DNS_SEEDS, bdk.Network.BITCOIN, seed_config)

    class FakePeerDiscovery(PeerDiscovery):
        async def _resolve_dns_seed(
            self, candidate_seed: str, seed_port: int, proxy_info: ProxyInfo | None
        ) -> list[Peer]:
            del candidate_seed, proxy_info
            return [Peer(host="127.0.0.1", port=seed_port)]

        async def _is_peer_reachable(self, peer: Peer, timeout: float = 0.35) -> bool:
            return False

    async def run() -> None:
        discovery = FakePeerDiscovery(network=bdk.Network.BITCOIN, loop_in_thread=None)
        try:
            peers = await discovery.get_bitcoin_peers(lower_bound=None, required_services=0, timeout=1)
            assert Peer(host="127.0.0.1", port=8333) not in peers
            assert Peer(host="127.0.0.1", port=8333) not in discovery.total_discovered_peers
        finally:
            discovery.stop()

    asyncio.run(run())


def test_loopback_peer_is_included_when_reachable(monkeypatch) -> None:
    seed_config = {"hosts": ["127.0.0.1"], "port": 8333}
    monkeypatch.setitem(DNS_SEEDS, bdk.Network.BITCOIN, seed_config)

    class FakePeerDiscovery(PeerDiscovery):
        async def _resolve_dns_seed(
            self, candidate_seed: str, seed_port: int, proxy_info: ProxyInfo | None
        ) -> list[Peer]:
            del candidate_seed, proxy_info
            return [Peer(host="127.0.0.1", port=seed_port)]

        async def _is_peer_reachable(self, peer: Peer, timeout: float = 0.35) -> bool:
            return True

    async def run() -> None:
        discovery = FakePeerDiscovery(network=bdk.Network.BITCOIN, loop_in_thread=None)
        try:
            peers = await discovery.get_bitcoin_peers(lower_bound=None, required_services=0, timeout=1)
            assert Peer(host="127.0.0.1", port=8333) in peers
            assert Peer(host="127.0.0.1", port=8333) in discovery.total_discovered_peers
        finally:
            discovery.stop()

    asyncio.run(run())


def test_total_discovered_peers_returns_snapshot() -> None:
    discovery = PeerDiscovery(network=bdk.Network.BITCOIN, loop_in_thread=None)
    peer = Peer(host="8.8.8.8", port=8333)
    try:
        discovery._add_discovered_peers({peer})
        snapshot = discovery.total_discovered_peers
        snapshot.clear()
        assert discovery.total_discovered_peers == {peer}
    finally:
        discovery.stop()


def test_resolve_dns_seed_uses_shared_resolver(monkeypatch) -> None:
    captured: list[tuple[str, ProxyInfo | None]] = []

    async def fake_resolve_host_endpoints_async(
        host: str,
        proxy_info: ProxyInfo | None,
        port: int | None = None,
        timeout="default",
        family=0,
        socktype=0,
    ) -> list[ResolvedEndpoint]:
        del timeout, family, socktype
        captured.append((host, proxy_info))
        assert port == 8333
        return [
            ResolvedEndpoint(host="8.8.8.8", port=8333, family=0),
            ResolvedEndpoint(host="1.1.1.1", port=18333, family=0),
        ]

    monkeypatch.setattr(
        "bitcoin_safe.p2p.peer_discovery.resolve_host_endpoints_async",
        fake_resolve_host_endpoints_async,
    )

    async def run() -> None:
        discovery = PeerDiscovery(network=bdk.Network.BITCOIN, loop_in_thread=None)
        proxy_info = ProxyInfo.parse("socks5h://127.0.0.1:9050")
        try:
            peers = await discovery._resolve_dns_seed("seed.example", 8333, proxy_info=proxy_info)
            assert set(peers) == {Peer(host="8.8.8.8", port=8333), Peer(host="1.1.1.1", port=18333)}
            assert captured == [("seed.example", proxy_info)]
        finally:
            discovery.stop()

    asyncio.run(run())
