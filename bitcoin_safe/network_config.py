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

import enum
import logging
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import bdkpython as bdk

from bitcoin_safe.mempool_data import MempoolData
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.pythonbdk_types import BlockchainType, IpAddress
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init

from .html_utils import link
from .i18n import translate
from .util import fast_version

logger = logging.getLogger(__name__)

FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this


def clean_electrum_url(url: str, electrum_use_ssl: bool) -> str:
    """Clean electrum url."""
    if electrum_use_ssl and not url.startswith("ssl://"):
        url = "ssl://" + url
    return url


def get_mempool_url(network: bdk.Network) -> dict[str, str]:
    """Get mempool url."""
    d = {
        bdk.Network.BITCOIN: {
            "default": "https://mempool.space/",
            "umbrel": "http://umbrel.local:3006",
            "tor_mempool.space": "http://mempoolhqx4isw62xs7abwphsq7ldayuidyx2v2oethdhhj6mlo2r6ad.onion/",
        },
        bdk.Network.REGTEST: {
            "default": "http://localhost:8080/",
            "nigiri": "http://localhost:5000/",
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": "https://mempool.space/testnet/",
            "mempool.space": "https://mempool.space/testnet/",
            "blockstream": "https://blockstream.info/testnet",
            "tor_mempool.space": "http://mempoolhqx4isw62xs7abwphsq7ldayuidyx2v2oethdhhj6mlo2r6ad.onion/testnet",
        },
        bdk.Network.TESTNET4: {
            "default": "https://mempool.space/testnet4",
            "mempool.space": "https://mempool.space/testnet4",
            "tor_mempool.space": "http://mempoolhqx4isw62xs7abwphsq7ldayuidyx2v2oethdhhj6mlo2r6ad.onion/testnet4",
        },
        bdk.Network.SIGNET: {
            "default": "https://mempool.space/signet",
            "mempool.space": "https://mempool.space/signet",
            "mutinynet": "https://mutinynet.com",
            "tor_mempool.space": "http://mempoolhqx4isw62xs7abwphsq7ldayuidyx2v2oethdhhj6mlo2r6ad.onion/signet",
        },
    }
    return d[network]


@dataclass
class ElectrumConfig:
    url: str
    use_ssl: bool


def get_electrum_configs(network: bdk.Network) -> dict[str, ElectrumConfig]:
    """Get electrum configs."""
    d = {
        bdk.Network.BITCOIN: {
            # "default": ElectrumConfig("mempool.space:50002", True),
            "default": ElectrumConfig("electrum.blockstream.info:50002", True),
            "blockstream": ElectrumConfig("electrum.blockstream.info:50002", True),
            "bullbitcoin-fulcrum": ElectrumConfig("fulcrum.bullbitcoin.com:50002", True),
            "bullbitcoin-wes": ElectrumConfig("wes.bullbitcoin.com:50002", True),
            "umbrel": ElectrumConfig("umbrel.local:50001", False),
            "localhost": ElectrumConfig("127.0.0.1:50001", False),
        },
        bdk.Network.REGTEST: {
            "default": ElectrumConfig("127.0.0.1:50000", False),
            "nigiri": ElectrumConfig("127.0.0.1:50000", False),
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": ElectrumConfig("blockstream.info:993", True),  # testnet3
            "blockstream": ElectrumConfig("blockstream.info:993", True),  # testnet3
            "electrum.blockstream.info": ElectrumConfig("electrum.blockstream.info:60002", True),  # testnet3
        },
        bdk.Network.TESTNET4: {
            "default": ElectrumConfig("blackie.c3-soft.com:57010", True),
            "blackie": ElectrumConfig("blackie.c3-soft.com:57010", True),
            "mempool.space": ElectrumConfig("mempool.space:40002", True),
        },
        bdk.Network.SIGNET: {
            "default": ElectrumConfig("mempool.space:60602", True),
            "mutinynet": ElectrumConfig("mutinynet.com:50001", False),
            "mempool.space": ElectrumConfig("mempool.space:60602", True),
        },
    }
    return d[network]


def get_default_rpc_hosts(network: bdk.Network) -> dict[str, str]:
    """Get default rpc hosts."""
    return {"default": "127.0.0.1", "umbrel": "umbrel.local"}


def get_default_port(network: bdk.Network, server_type: BlockchainType) -> int:
    """Get default port."""
    if server_type == BlockchainType.CompactBlockFilter:
        d = {
            bdk.Network.BITCOIN: 8333,
            bdk.Network.REGTEST: 18444,
            bdk.Network.TESTNET: 18333,
            bdk.Network.TESTNET4: 48333,
            bdk.Network.SIGNET: 38333,
        }
        return d[network]
    elif server_type == BlockchainType.Electrum:
        d = {
            bdk.Network.BITCOIN: 50001,
            bdk.Network.REGTEST: 50000,  # nigiri default
            bdk.Network.TESTNET: 51001,
            bdk.Network.TESTNET4: 51001,
            bdk.Network.SIGNET: 51001,
        }
        return d[network]
    elif server_type == BlockchainType.Esplora:
        d = {
            bdk.Network.BITCOIN: 60002,
            bdk.Network.REGTEST: 3000,  # nigiri default
            bdk.Network.TESTNET: 51001,
            bdk.Network.TESTNET4: 51001,
            bdk.Network.SIGNET: 51001,
        }
        return d[network]
    elif server_type == BlockchainType.RPC:
        d = {
            bdk.Network.BITCOIN: 8332,
            bdk.Network.REGTEST: 18443,
            bdk.Network.TESTNET: 18332,
            bdk.Network.TESTNET4: 18332,
            bdk.Network.SIGNET: 38332,
        }
        return d[network]
    raise ValueError(f"Could not get port for {network, server_type}")


def get_esplora_urls(network: bdk.Network) -> dict[str, str]:
    """Get esplora urls."""
    d = {
        bdk.Network.BITCOIN: {
            "default": "",
            "blockstream": "",
        },
        bdk.Network.REGTEST: {
            "default": "http://127.0.0.1:3000",
            "localhost": "http://127.0.0.1:3000",
            "nigiri": "http://127.0.0.1:3000",
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": "",
        },
        bdk.Network.TESTNET4: {
            "default": "",
        },
        bdk.Network.SIGNET: {
            "default": "https://mutinynet.com/api",
            "mutinynet": "https://mutinynet.com/api",
            "localhost": "http://127.0.0.1:3000",
        },
    }
    return d[network]


def get_default_p2p_node_urls(network: bdk.Network) -> dict[str, str]:
    """Get default p2p node urls."""
    port = get_default_port(network=network, server_type=BlockchainType.CompactBlockFilter)
    d = {
        bdk.Network.BITCOIN: {
            "default": f"127.0.0.1:{port}",
            "umbrel": f"umbrel.local:{port}",
        },
        bdk.Network.REGTEST: {
            "default": f"127.0.0.1:{port}",
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": f"127.0.0.1:{port}",
        },
        bdk.Network.TESTNET4: {
            "default": f"127.0.0.1:{port}",
        },
        bdk.Network.SIGNET: {
            "default": f"127.0.0.1:{port}",
        },
    }
    return d[network]


def get_testnet_faucet(network: bdk.Network) -> str | None:
    """Get testnet faucet."""
    d = {
        bdk.Network.TESTNET: "https://bitcoinfaucet.uo1.net/",
        bdk.Network.TESTNET4: "https://faucet.testnet4.dev/",
        bdk.Network.SIGNET: "https://signet25.bublina.eu.org/",
    }
    return d.get(network)


def get_description(network: bdk.Network, server_type: BlockchainType) -> str:
    """Get description."""
    if server_type == BlockchainType.CompactBlockFilter:
        cbf_default_description = translate(
            "net_conf",
            "Compact Block Filters are a private and fast way to get all blockchain information. "
            "The wallet will connect directly to multiple bitcoin nodes and download "
            "block summaries (Compact Block Filters) from them.<br>"
            "If you specify manual peers in the 'Bitcoin Network monitoring' section below, "
            "Compact Block Filters will connect to them first.",
        )
        d = {
            bdk.Network.BITCOIN: cbf_default_description,
            bdk.Network.REGTEST: cbf_default_description,
            bdk.Network.TESTNET: cbf_default_description,
            bdk.Network.TESTNET4: cbf_default_description,
            bdk.Network.SIGNET: cbf_default_description,
        }

        return d[network]
    elif server_type == BlockchainType.Electrum:
        d = {
            bdk.Network.BITCOIN: (
                translate(
                    "net_conf",
                    "The server can associate your IP address with the wallet addresses.\n"
                    "It is best to use your own server, such as {link}.",
                ).format(link=link("https://umbrel.com/", "umbrel"))
            ),
            bdk.Network.REGTEST: (
                translate(
                    "net_conf",
                    "You can setup {electrum} with an electrum server on {server} "
                    "and a block explorer on {explorer}",
                ).format(
                    electrum=link("https://nigiri.vulpem.com/", "nigiri"),
                    server=link("http://localhost:50000", "localhost:50000"),
                    explorer=link("http://localhost:5000", "localhost:5000"),
                )
            ),
            bdk.Network.TESTNET: (
                translate(
                    "net_conf",
                    "A good option is  {electrum_testnet} and as block explorer {explorer_testnet}",
                ).format(
                    electrum_testnet=link(get_electrum_configs(bdk.Network.TESTNET)["default"].url),
                    explorer_testnet=link(get_mempool_url(bdk.Network.TESTNET)["default"]),
                )
            ),
            bdk.Network.TESTNET4: (
                translate(
                    "net_conf",
                    "A good option is  {electrum_testnet4} and as "
                    "block explorer {explorer_testnet4}. There is a {faucet} for free test coins.",
                ).format(
                    electrum_testnet4=link(get_electrum_configs(bdk.Network.TESTNET4)["mempool.space"].url),
                    explorer_testnet4=link(get_mempool_url(bdk.Network.TESTNET4)["mempool.space"]),
                    faucet=link(get_testnet_faucet(network=network), "faucet"),
                )
            ),
            bdk.Network.SIGNET: translate(
                "net_conf",
                "Signet choose {electrum} and a block explorer on {mempool_url}. "
                "There is a {faucet} for free test coins.",
            ).format(
                electrum=link(get_electrum_configs(bdk.Network.SIGNET)["mempool.space"].url),
                mempool_url=link(get_mempool_url(bdk.Network.SIGNET)["mempool.space"]),
                faucet=link(get_testnet_faucet(network=network), "faucet"),
            ),
        }
        return d[network]
    elif server_type == BlockchainType.Esplora:
        d = {
            bdk.Network.BITCOIN: (
                translate(
                    "net_conf",
                    "The server can associate your IP address with the wallet addresses.\n"
                    "It is best to use your own server, such as {link}.",
                ).format(link=link("https://umbrel.com/", "umbrel"))
            ),
            bdk.Network.REGTEST: (
                translate(
                    "net_conf",
                    "You can setup {setup} with an esplora server on {server} "
                    "and a block explorer on {explorer}",
                ).format(
                    setup=link("https://nigiri.vulpem.com/", "nigiri"),
                    server=link("http://localhost:3000", "localhost:3000"),
                    explorer=link("http://localhost:5000", "localhost:5000"),
                )
            ),  # nigiri default
            bdk.Network.TESTNET: "",
            bdk.Network.TESTNET4: (
                translate(
                    "net_conf",
                    "There is a {faucet} for free test coins.",
                ).format(
                    faucet=link(get_testnet_faucet(network=network), "faucet"),
                )
            ),
            bdk.Network.SIGNET: (
                translate(
                    "net_conf",
                    "A (somtimes working) server is {link} and a block explorer on {explorer}. "
                    "There is a {faucet}.",
                ).format(
                    link=link(get_esplora_urls(bdk.Network.SIGNET)["mutinynet"]),
                    explorer=link("https://mutinynet.com/"),
                    faucet=link(get_testnet_faucet(network=network), "faucet"),
                )
            ),
        }
        return d[network]
    elif server_type == BlockchainType.RPC:
        d = {
            bdk.Network.BITCOIN: (
                translate("net_conf", "You can connect your own Bitcoin node, such as {link}.").format(
                    link=link("https://umbrel.com/", "umbrel")
                )
            ),
            bdk.Network.REGTEST: translate("net_conf", 'Run your bitcoind with "bitcoind -chain=regtest"'),
            bdk.Network.TESTNET: translate("net_conf", 'Run your bitcoind with "bitcoind -chain=test"'),
            bdk.Network.TESTNET4: translate("net_conf", 'Run your bitcoind with "bitcoind -chain=testnet4"'),
            bdk.Network.SIGNET: translate(
                "net_conf",
                'Run your bitcoind with "bitcoind -chain=signet"  '
                "This however is a different signet than mutinynet.com.",
            ),
        }
        return d[network]
    raise ValueError(f"Could not get description for {network, server_type}")


@dataclass(frozen=True)
class Peer:
    host: str
    port: int

    @classmethod
    def parse(cls, url: str, network: bdk.Network) -> Peer:
        """
        Parse any of these forms:
        - IPv4                ("192.168.1.1")
        - IPv4:port           ("192.168.1.1:8080")
        - IPv6 (bracketed or not)
        - [IPv6]:port         ("[2001:db8::1]:8080")
        - onion.onion[:port]  ("abcd1234.onion" or "abcd1234.onion:80")
        - i2p.i2p[:port]      ("xyzabcd.i2p:443")
        Returns (hostname, port) where port is an int or None.
        """
        # If it already has a scheme (e.g. "http://…"), urlparse will parse it normally.
        # Otherwise, prefix "http://" so urlparse treats the entire string as netloc.
        prefix = "" if "://" in url else "http://"
        parsed = urlparse(prefix + url)

        host = parsed.hostname
        port = parsed.port  # int or None

        assert host is not None
        if port is None:
            port = get_default_port(network=network, server_type=BlockchainType.CompactBlockFilter)
        return Peer(host=host, port=port)

    def __str__(self) -> str:
        """Return string representation."""
        host = self.host
        port = self.port
        if ":" in host and not host.startswith("["):  # likely an IPv6 address
            host = f"[{host}]"
        return f"{host}:{port}"

    def to_bdk(self, v2_transport=False) -> bdk.Peer | None:
        """To bdk."""
        try:
            return bdk.Peer(address=IpAddress.from_host(self.host), port=self.port, v2_transport=v2_transport)
        except Exception:
            return None


class Peers(list[Peer]):
    pass


@dataclass
class ConnectionInfo:
    peer: Peer
    proxy_info: ProxyInfo | None


class P2pListenerType(enum.Enum):
    automatic = enum.auto()
    deactive = enum.auto()


class NetworkConfig(BaseSaveableClass):
    VERSION = "0.2.6"
    known_classes = {
        **BaseSaveableClass.known_classes,
        BlockchainType.__name__: BlockchainType,
        bdk.Network.__name__: bdk.Network,
        P2pListenerType.__name__: P2pListenerType,
        MempoolData.__name__: MempoolData,
    }

    def __init__(
        self,
        network: bdk.Network,
        discovered_peers: Peers | list[Peer] | None = None,
        mempool_data: MempoolData | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.network = network
        self.server_type: BlockchainType = BlockchainType.Electrum
        electrum_config = get_electrum_configs(network)["default"]
        self.electrum_url: str = electrum_config.url
        self.electrum_use_ssl: bool = electrum_config.use_ssl
        self.rpc_ip: str = get_default_rpc_hosts(network=network)["default"]
        self.rpc_port: int = get_default_port(network, BlockchainType.RPC)
        self.rpc_username: str = ""
        self.rpc_password: str = ""

        self.esplora_url: str = get_esplora_urls(network)["default"]

        self.mempool_url: str = get_mempool_url(network)["default"]
        self.proxy_url: str | None = None
        self.p2p_listener_type: P2pListenerType = P2pListenerType.automatic
        self.manual_peers: Peers = Peers()
        self.p2p_autodiscover_additional_peers: bool = True
        self.p2p_listener_parallel_connections: int = 2
        self.discovered_peers: Peers | list[Peer] = discovered_peers if discovered_peers else Peers()
        self.mempool_data: MempoolData = mempool_data if mempool_data else MempoolData()

        self.cbf_connections: int = 2

    def description_short(self):
        """Description short."""
        server_name = ""
        if self.server_type == BlockchainType.Electrum:
            server_name = f"{self.electrum_url}"
        elif self.server_type == BlockchainType.Esplora:
            server_name = f"{self.esplora_url}"
        elif self.server_type == BlockchainType.CompactBlockFilter:
            server_name = translate(
                "network_config", "{cbf_connections} bitcoin nodes via {server_type}"
            ).format(server_type=self.server_type.name, cbf_connections=self.cbf_connections)
        elif self.server_type == BlockchainType.RPC:
            server_name = f"{self.server_type.name}"

        if self.proxy_url:
            return translate("network_config", "{server_name} via the proxy {proxy}").format(
                server_name=server_name, proxy=self.proxy_url
            )
        else:
            return translate("network_config", "{server_name}").format(server_name=server_name)

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d.update(self.__dict__)

        # overwrite the dict value
        d["discovered_peers"] = Peers() + [asdict(peer) for peer in self.discovered_peers]
        d["manual_peers"] = Peers() + [asdict(peer) for peer in self.manual_peers]

        return d

    def get_manual_peers(self) -> Peers:
        """Return manually configured peers (copy)."""
        return Peers(self.manual_peers)

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> NetworkConfig:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        u = cls(**filtered_for_init(dct, cls))

        dct["discovered_peers"] = [
            Peer(**filtered_for_init(peer, Peer)) for peer in dct.get("discovered_peers", [])
        ]
        dct["manual_peers"] = [Peer(**filtered_for_init(peer, Peer)) for peer in dct.get("manual_peers", [])]

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(u, k, v)
        return u

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            dct["_network"] = dct["network"]
            del dct["network"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            dct["network"] = dct["_network"]
            del dct["_network"]
        if fast_version(str(dct["VERSION"])) < fast_version("0.1.0"):
            # handle proxy
            if "proxy_url" not in dct:
                dct["proxy_url"] = None

            # handle rpc
            if dct["server_type"] == BlockchainType.RPC:
                # blank out the fields.  let the user choose themself.
                dct["server_type"] = BlockchainType.Electrum
                dct["electrum_url"] = ""
        if fast_version(str(dct["VERSION"])) < fast_version("0.2.2"):
            # existing users might have had set the network settings paranoid
            # and would not like to have P2pListenerType enabled
            # Therefore I deactivate it for migrations
            # New users who are paranoid, can deactivate p2p_listener_type
            # together when they set an electrum server
            dct["p2p_listener_type"] = P2pListenerType.deactive
        if fast_version(str(dct["VERSION"])) < fast_version("0.2.3"):
            dct["mempool_data"] = res if (res := dct.get("mempool_data")) else None
        if fast_version(str(dct["VERSION"])) < fast_version("0.2.6"):
            # migrate deprecated initial peer field into manual peers
            manual_peers: list[dict] = []
            if initial := dct.get("p2p_inital_url"):
                try:
                    manual_peers.append(
                        asdict(Peer.parse(initial, network=dct.get("network", bdk.Network.BITCOIN)))
                    )
                except Exception:
                    logger.warning("Could not migrate p2p_inital_url to manual_peers")
            dct["manual_peers"] = manual_peers
            # drop invalid enum value if present
            if dct.get("p2p_listener_type") not in list(P2pListenerType):
                dct["p2p_listener_type"] = P2pListenerType.automatic
            elif dct.get("p2p_listener_type") is P2pListenerType.automatic:
                # when it was automatic, the inital peer was not considered
                dct["manual_peers"] = []

        return super().from_dump_migration(dct=dct)


class NetworkConfigs(BaseSaveableClass):
    VERSION = "0.1.0"
    known_classes = {**BaseSaveableClass.known_classes, NetworkConfig.__name__: NetworkConfig}

    def __init__(self, configs: dict[str, NetworkConfig] | None = None) -> None:
        """Initialize instance."""
        super().__init__()

        self.configs: dict[str, NetworkConfig] = (
            configs if configs else {network.name: NetworkConfig(network=network) for network in bdk.Network}
        )
        self.enforce_consistency(self.configs)

    @classmethod
    def enforce_consistency(cls, configs: dict[str, NetworkConfig]):
        """Enforce consistency."""
        for network in bdk.Network:
            if network.name not in configs:
                configs[network.name] = NetworkConfig(network=network)
            if configs[network.name].network != network:
                configs[network.name].network = network

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.0"):
            if bdk.Network.TESTNET4.name not in dct["configs"]:
                dct["configs"][bdk.Network.TESTNET4.name] = NetworkConfig(network=bdk.Network.TESTNET4)

        return super().from_dump_migration(dct=dct)

    def dump(self) -> dict:
        """Dump."""
        d = super().dump()
        d["configs"] = {k: v.dump() for k, v in self.configs.items()}
        return d

    @classmethod
    def from_file(cls, filename: str, password: str | None = None) -> NetworkConfigs:
        """From file."""
        return super()._from_file(
            filename=filename,
            password=password,
        )

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> NetworkConfigs:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))
