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
import socket
import struct
from ipaddress import IPv4Network
from types import SimpleNamespace

import bdkpython as bdk

from bitcoin_safe.gui.qt.network_settings.main import merge_configured_peers
from bitcoin_safe.network_config import Peer
from bitcoin_safe.p2p import peer_discovery
from bitcoin_safe.p2p.p2p_client import MAGIC_VALUES, P2PClient, double_sha256
from bitcoin_safe.p2p.peer_discovery import PeerDiscovery


class FakeWriter:
    def close(self) -> None:
        pass

    async def wait_closed(self) -> None:
        pass


class FakeReader:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def readexactly(self, size: int) -> bytes:
        if len(self.data) < size:
            raise ConnectionError("unexpected end of stream")
        data, self.data = self.data[:size], self.data[size:]
        return data


def test_merge_configured_peers_preserves_existing_and_deduplicates() -> None:
    existing = [Peer("192.168.1.2", 18444)]
    discovered = [Peer("192.168.1.2", 18444), Peer("192.168.1.3", 18444)]

    assert merge_configured_peers(existing, discovered) == [
        Peer("192.168.1.2", 18444),
        Peer("192.168.1.3", 18444),
    ]


def test_local_ipv4_networks_filters_interfaces(monkeypatch) -> None:
    monkeypatch.setattr(
        peer_discovery.psutil,
        "net_if_stats",
        lambda: {
            "up": SimpleNamespace(isup=True),
            "down": SimpleNamespace(isup=False),
        },
    )
    monkeypatch.setattr(
        peer_discovery.psutil,
        "net_if_addrs",
        lambda: {
            "up": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.10", netmask="255.255.255.0"),
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.20", netmask="255.255.255.0"),
                SimpleNamespace(family=socket.AF_INET, address="127.0.0.1", netmask="255.0.0.0"),
                SimpleNamespace(family=socket.AF_INET, address="169.254.1.10", netmask="255.255.0.0"),
                SimpleNamespace(family=socket.AF_INET, address="10.0.0.10", netmask="255.255.0.0"),
            ],
            "down": [SimpleNamespace(family=socket.AF_INET, address="172.16.0.10", netmask="255.255.255.0")],
        },
    )

    assert peer_discovery.local_ipv4_networks() == (IPv4Network("192.168.1.0/24"),)


def test_local_os_routes_and_neighbors_are_bounded(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        del kwargs
        if command[-2:] == ["route", "show"]:
            return SimpleNamespace(
                stdout=(
                    "default via 192.168.1.1 dev eth0\n"
                    "192.168.1.0/24 dev eth0 scope link\n"
                    "100.64.12.0/24 dev tailscale0 scope link\n"
                    "10.0.0.0/8 dev eth1 scope link\n"
                )
            )
        return SimpleNamespace(
            stdout=(
                "192.168.1.20 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"
                "100.64.12.5 dev tailscale0 lladdr aa:bb:cc:dd:ee:01 STALE\n"
                "192.168.1.30 dev eth0 FAILED\n"
            )
        )

    monkeypatch.setattr(peer_discovery.subprocess, "run", fake_run)

    assert peer_discovery.local_ipv4_routes() == (
        IPv4Network("100.64.12.0/24"),
        IPv4Network("192.168.1.0/24"),
    )
    assert peer_discovery.local_ipv4_neighbors() == ("100.64.12.5", "192.168.1.20")


def test_discover_local_peers_uses_default_port_and_bounded_probes(monkeypatch) -> None:
    monkeypatch.setattr(
        peer_discovery,
        "local_ipv4_networks",
        lambda: (IPv4Network("192.168.1.0/30"), IPv4Network("192.168.1.0/30")),
    )
    active = 0
    maximum_active = 0

    async def fake_reachable(self, peer: Peer, timeout: float) -> bool:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return peer.host == "192.168.1.1"

    monkeypatch.setattr(PeerDiscovery, "_is_peer_reachable", fake_reachable)

    discovery = PeerDiscovery(network=bdk.Network.REGTEST, loop_in_thread=None)
    try:
        peers = asyncio.run(discovery.discover_local_peers(max_concurrent=1))
    finally:
        discovery.stop()

    assert peers == [Peer("192.168.1.1", 18444)]
    assert maximum_active == 1


def test_local_discovery_accepts_matching_network_handshake(monkeypatch) -> None:
    payload = b"\x70\x11\x01\x00" + b"\x00" * 100
    header = (
        struct.pack(">L", MAGIC_VALUES[bdk.Network.REGTEST])
        + struct.pack("12s", b"version")
        + struct.pack("<L", len(payload))
        + double_sha256(payload)[:4]
    )

    async def fake_connect(peer, proxy_info, timeout):
        assert proxy_info is None
        return FakeReader(header + payload), FakeWriter()

    monkeypatch.setattr(P2PClient, "_connect", fake_connect)
    discovery = PeerDiscovery(network=bdk.Network.REGTEST, loop_in_thread=None)
    try:
        assert asyncio.run(discovery._is_peer_reachable(Peer("192.168.1.2", 18444)))
    finally:
        discovery.stop()


def test_local_discovery_rejects_wrong_network_handshake(monkeypatch) -> None:
    payload = b"version"
    header = (
        struct.pack(">L", MAGIC_VALUES[bdk.Network.BITCOIN])
        + struct.pack("12s", b"version")
        + struct.pack("<L", len(payload))
        + double_sha256(payload)[:4]
    )

    async def fake_connect(peer, proxy_info, timeout):
        return FakeReader(header + payload), FakeWriter()

    monkeypatch.setattr(P2PClient, "_connect", fake_connect)
    discovery = PeerDiscovery(network=bdk.Network.REGTEST, loop_in_thread=None)
    try:
        assert not asyncio.run(discovery._is_peer_reachable(Peer("192.168.1.2", 18444)))
    finally:
        discovery.stop()
