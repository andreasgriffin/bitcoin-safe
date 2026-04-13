#
# Bitcoin Safe
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
import logging
import random
import socket
from contextlib import suppress
from ipaddress import ip_address
from threading import RLock
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread

from .p2p_client import Peer

logger = logging.getLogger(__name__)


# Bitcoin P2P service flags (nServices field in version message)

# Reference:
# https://github.com/bitcoin/bitcoin/blob/master/src/protocol.h

# --------------------------------------------------------------------
# Core blockchain serving capabilities
# --------------------------------------------------------------------

# (1 << 0)
# NODE_NETWORK
# The node can serve the complete blockchain (not pruned).
# Required for historical block serving.
NODE_NETWORK = 1 << 0

# (1 << 1)
# NODE_GETUTXO (deprecated / unused in practice)
# Supports the BIP64 getutxo protocol (never widely deployed).
NODE_GETUTXO = 1 << 1

# (1 << 2)
# NODE_BLOOM (deprecated)
# Supports BIP37 bloom filtering (used by old SPV wallets).
# Disabled by default in modern Bitcoin Core.
NODE_BLOOM = 1 << 2

# (1 << 3)
# NODE_WITNESS
# Supports SegWit (BIP141) and serves witness data.
# Mandatory for modern nodes.
NODE_WITNESS = 1 << 3

# (1 << 4)
# NODE_XTHIN (obsolete, Bitcoin XT extension)
# Not part of Bitcoin Core consensus network.
NODE_XTHIN = 1 << 4

# (1 << 5)
# NODE_NETWORK_LIMITED
# Can serve the last 288 blocks (~2 days) but is pruned.
# Introduced in BIP159.
NODE_NETWORK_LIMITED = 1 << 5

# (1 << 6)
# NODE_COMPACT_FILTERS
# Supports BIP157/158 compact block filters (Neutrino).
# Required for client-side block filtering.
NODE_COMPACT_FILTERS = 1 << 6

# (1 << 7)
# NODE_DOUBLE_SPEND_PROOFS (not active in Bitcoin Core)
# Proposal for double-spend proofs (never standardized).
NODE_DOUBLE_SPEND_PROOFS = 1 << 7

# (1 << 8)
# NODE_UTXO_SNAPSHOT
# Supports assumeutxo / UTXO snapshot service.
NODE_UTXO_SNAPSHOT = 1 << 8

# --------------------------------------------------------------------
# Common combinations
# --------------------------------------------------------------------

# Typical modern full node:
FULL_NODE_SERVICE_FLAGS = NODE_NETWORK | NODE_WITNESS

# Modern pruned node:
PRUNED_NODE_SERVICE_FLAGS = NODE_NETWORK_LIMITED | NODE_WITNESS

# Neutrino-compatible full node:
CBF_FULL_NODE_SERVICE_FLAGS = NODE_NETWORK | NODE_WITNESS | NODE_COMPACT_FILTERS

# Neutrino-compatible pruned node (rare but valid):
CBF_PRUNED_NODE_SERVICE_FLAGS = NODE_NETWORK_LIMITED | NODE_WITNESS | NODE_COMPACT_FILTERS

# Flag for default node (segwit required to recieve full segwit transactions)
DEFAULT_REQUIRED_SERVICE_FLAGS = NODE_NETWORK | NODE_WITNESS

# Compact Block filter node
CBF_REQUIRED_SERVICE_FLAGS = DEFAULT_REQUIRED_SERVICE_FLAGS | NODE_COMPACT_FILTERS


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
        self._state_lock = RLock()
        self._total_discovered_peers: set[Peer] = set()

    @property
    def total_discovered_peers(self) -> set[Peer]:
        with self._state_lock:
            return set(self._total_discovered_peers)

    def _add_discovered_peers(self, peers: set[Peer]) -> None:
        with self._state_lock:
            self._total_discovered_peers.update(peers)

    @staticmethod
    def _requires_reachability_probe(seed_host: str) -> bool:
        """Return True when seed entries should be verified by connecting."""
        return seed_host in {"127.0.0.1", "::1", "localhost"}

    async def _is_peer_reachable(self, peer: Peer, timeout: float = 0.35) -> bool:
        """Check whether a TCP peer can be reached."""
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(peer.host, peer.port), timeout=timeout)
        except Exception:
            return False

        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
        return True

    async def _resolve_seed_to_peers(self, seed_host: str, required_services: int | None) -> list[Peer]:
        """Resolve a single seed and optionally probe reachability."""
        seed_info = Peer.parse(seed_host, self.network)
        candidate_seed = self._seed_with_service_bits(
            seed_info.host,
            required_services if required_services else None,
        )
        peers = await self._resolve_dns_seed(candidate_seed, seed_info.port)
        if self._requires_reachability_probe(seed_info.host):
            return [peer for peer in peers if await self._is_peer_reachable(peer)]
        else:
            return peers

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
        timeout: float = 5,
    ):
        dns_seeds = DNS_SEEDS[self.network]["hosts"].copy()
        random.shuffle(dns_seeds)

        effective_required_services = (
            DEFAULT_REQUIRED_SERVICE_FLAGS if required_services is None else required_services
        )

        def return_results(results: list[list[Peer]]):
            peers = {peer for batch in results for peer in batch}
            self._add_discovered_peers(peers)
            return peers

        partial_results: list[list[Peer]] = []

        async def resolve(seed_host: str) -> list[Peer]:
            peers = await self._resolve_seed_to_peers(seed_host, effective_required_services)
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
            return return_results(partial_results)

        return return_results(batches)

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
