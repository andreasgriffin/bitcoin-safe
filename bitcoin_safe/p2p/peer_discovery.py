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
import socket
from ipaddress import ip_address
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread

from .p2p_client import Peer

logger = logging.getLogger(__name__)


DEFAULT_REQUIRED_SERVICE_FLAGS = (1 << 0) | (1 << 3)
CBF_REQUIRED_SERVICE_FLAGS = DEFAULT_REQUIRED_SERVICE_FLAGS | (1 << 6)

# Mapping of networks to their DNS seeds and default port
DNS_SEEDS: dict[bdk.Network, dict[str, Any]] = {
    bdk.Network.BITCOIN: {
        "hosts": [
            "seed.bitcoin.sipa.be",  # Pieter Wuille
            "dnsseed.bluematt.me",  # Matt Corallo
            "dnsseed.bitcoin.dashjr-list-of-p2p-nodes.us",  # Luke Dashjr
            "seed.bitcoin.jonasschnelli.ch",  # Jonas Schnelli
            "seed.btc.petertodd.net",  # Peter Todd
            "seed.bitcoin.sprovoost.nl",  # Sjors Provoost
            "dnsseed.emzy.de",  # Stephan Oeste
            "seed.bitcoin.wiz.biz",  # Jason Maurice
            "seed.mainnet.achownodes.xyz",  # Ava Chow, only supports x1, x5, x9, x49, x809,
            # x849, xd, x400, x404, x408, x448, xc08, xc48, x40c
            "127.0.0.1",  # Local fallback
        ],
        "port": 8333,
    },
    bdk.Network.TESTNET: {
        "hosts": [
            "testnet-seed.bitcoin.jonasschnelli.ch",  # Jonas Schnelli
            "seed.tbtc.petertodd.net",  # Peter Todd
            "seed.testnet.bitcoin.sprovoost.nl",  # Sjors Provoost
            "testnet-seed.bluematt.me",  # Matt Corallo
            "seed.testnet.achownodes.xyz",  # Ava Chow, only supports x1, x5, x9, x49, x809,
            # x849, xd, x400, x404, x408, x448, xc08, xc48, x40c
            "127.0.0.1",  # Local fallback
        ],
        "port": 18333,
    },
    bdk.Network.SIGNET: {
        "hosts": [
            "seed.signet.bitcoin.sprovoost.nl",  # Sjors Provoost
            "seed.signet.achownodes.xyz",
            "v7ajjeirttkbnt32wpy3c6w3emwnfr3fkla7hpxcfokr3ysd3kqtzmqd.onion:38333",
            "127.0.0.1",  # Local fallback
        ],
        "port": 38333,
    },
    bdk.Network.REGTEST: {
        # Regtest only ever uses localhost
        "hosts": ["127.0.0.1"],
        "port": 18444,
    },
    bdk.Network.TESTNET4: {
        "hosts": [
            "seed.testnet4.bitcoin.sprovoost.nl",  # Sjors Provoost
            "seed.testnet4.wiz.biz",  # Jason Maurice
            "127.0.0.1",  # Local fallback
        ],
        "port": 48333,  # Testnet-4’s default port
    },
}


class PeerDiscovery:
    def __init__(self, network: bdk.Network, loop_in_thread: LoopInThread | None) -> None:
        """Initialize instance.

        Parameters
        ----------
        network : bdk.Network
            Network to discover peers for.
        loop_in_thread : LoopInThread | None
            Optional event loop to reuse instead of creating a new one. Sharing an existing
            loop avoids spawning extra threads and file descriptors (socketpairs on macOS),
            which can exhaust the default file descriptor limit when opening multiple
            wallets.
        """

        self.network = network
        self._loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None

    def _seed_with_service_bits(self, host: str, required_services: int | None) -> str:
        """Seed with service bits."""
        if required_services is None:
            return host

        if host in {"localhost"}:
            return host

        try:
            ip_address(host)
            return host
        except ValueError:
            pass

        if host.endswith(".onion") or host.endswith(".i2p"):
            return host

        service_hex = format(required_services, "x")
        service_host = f"x{service_hex}.{host}"
        return service_host

    async def _resolve_dns_seed(
        self,
        candidate_seed: str,
        seed_port: int,
    ) -> list[Peer]:
        """Resolve dns seed."""
        loop = asyncio.get_running_loop()

        try:
            addrinfos = await loop.run_in_executor(
                None, socket.getaddrinfo, candidate_seed, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
        except Exception:
            return []

        if not addrinfos:
            return []

        random.shuffle(addrinfos)
        peers: list[Peer] = []
        for ai in addrinfos:
            sockaddr = ai[4]
            ip = sockaddr[0]
            port = sockaddr[1] or seed_port
            peers.append(Peer(ip, port))  # type: ignore[arg-type]

        return peers

    async def get_bitcoin_peers(
        self,
        lower_bound: int | None,
        required_services: int | None,
        timeout: int = 5,
    ):
        dns_seeds = DNS_SEEDS[self.network]["hosts"].copy()
        random.shuffle(dns_seeds)

        effective_required_services = (
            DEFAULT_REQUIRED_SERVICE_FLAGS if required_services is None else required_services
        )

        partial_results: list[list[Peer]] = []

        async def resolve(seed_host: str) -> list[Peer]:
            seed_info = Peer.parse(seed_host, self.network)
            candidate_seed = self._seed_with_service_bits(
                seed_info.host,
                effective_required_services if effective_required_services else None,
            )
            peers = await self._resolve_dns_seed(candidate_seed, seed_info.port)
            partial_results.append(peers)
            return peers

        def enough(results):
            if lower_bound is None:
                return False
            unique = {peer for batch in results for peer in batch}
            return len(unique) >= lower_bound

        try:
            batches = await asyncio.wait_for(
                self._loop_in_thread.gather(
                    [resolve(seed) for seed in dns_seeds],
                    early_finish_criteria_function=enough,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Peer discovery timed out after {timeout} seconds")
            return {peer for batch in partial_results for peer in batch}

        return {peer for batch in batches for peer in batch}

    async def get_bitcoin_peer(
        self, required_services: int | None = DEFAULT_REQUIRED_SERVICE_FLAGS
    ) -> None | Peer:
        """Get bitcoin peer."""

        # the limit may not be 1 , otherwise 127.0.0.1 will always be returned
        peers = await self.get_bitcoin_peers(
            lower_bound=10,
            required_services=required_services,
        )
        if not peers:
            return None
        peer_list = list(peers)
        random.shuffle(peer_list)
        return peer_list[0]

    def stop(self) -> None:
        """Stop the internally managed loop, if we created it."""

        if self._owns_loop_in_thread:
            self._loop_in_thread.stop()
