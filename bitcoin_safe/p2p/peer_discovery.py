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

import logging
import random
import socket
from typing import Set

import bdkpython as bdk

from .p2p_client import Peer

logger = logging.getLogger(__name__)


class PeerDiscovery:
    def __init__(self, network: bdk.Network, timeout: int = 200) -> None:
        self.network = network
        self.timeout = timeout

    def get_bitcoin_peers(self, maximum: int | None = None) -> Set[Peer]:
        """
        Discover peers for various Bitcoin networks using multiple DNS seeds.

        Supports:
        - Mainnet (bdk.Network.BITCOIN)
        - Testnet (bdk.Network.TESTNET)
        - Signet (bdk.Network.SIGNET)
        - Regtest (bdk.Network.REGTEST; no DNS seeds - localhost only)
        - Testnet4
        """
        # Mapping of networks to their DNS seeds and default port
        seeds = {
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
                    "seed.mainnet.achownodes.xyz",  # Ava Chow, only supports x1, x5, x9, x49, x809, x849, xd, x400, x404, x408, x448, xc08, xc48, x40c
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
                    "seed.testnet.achownodes.xyz",  # Ava Chow, only supports x1, x5, x9, x49, x809, x849, xd, x400, x404, x408, x448, xc08, xc48, x40c
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

        # Determine which seeds to use; fallback testnet3 if TESTNET4 not supported
        info = seeds[self.network]

        peers: Set[Peer] = set()
        hosts = info["hosts"].copy()  # type: ignore
        random.shuffle(hosts)
        for host in hosts:
            try:
                addrinfos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
                random.shuffle(addrinfos)
                for ai in addrinfos:
                    ip = ai[4][0]
                    peers.add(Peer(ip, info["port"]))  # type: ignore
                    if maximum is not None and len(peers) >= maximum:
                        logger.debug(f"Contacted DNS {host} seed for bitcoin peers and got {peers=}")
                        return peers
            except:
                continue

        return peers

    def get_bitcoin_peer(self) -> None | Peer:
        peers = self.get_bitcoin_peers(maximum=1)
        if not peers:
            return None
        return list(peers)[0]
