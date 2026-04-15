#
# Bitcoin Safe
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
from bitcoin_safe.p2p.peer_discovery import DNS_SEEDS, PeerDiscovery


def test_loopback_peer_is_excluded_when_unreachable(monkeypatch) -> None:
    seed_config = {"hosts": ["127.0.0.1"], "port": 8333}
    monkeypatch.setitem(DNS_SEEDS, bdk.Network.BITCOIN, seed_config)

    class FakePeerDiscovery(PeerDiscovery):
        async def _resolve_dns_seed(self, candidate_seed: str, seed_port: int) -> list[Peer]:
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
        async def _resolve_dns_seed(self, candidate_seed: str, seed_port: int) -> list[Peer]:
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
