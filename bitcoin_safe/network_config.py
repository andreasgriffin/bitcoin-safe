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


import logging
from dataclasses import dataclass

from packaging import version

logger = logging.getLogger(__name__)

from typing import Any, Dict

import bdkpython as bdk

from bitcoin_safe.pythonbdk_types import BlockchainType, CBFServerType
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init

from .html_utils import link
from .i18n import translate

MIN_RELAY_FEE = 1
FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this


def get_mempool_url(network: bdk.Network) -> Dict[str, str]:
    d = {
        bdk.Network.BITCOIN: {
            "default": "https://mempool.space/",
            "umbrel": "http://umbrel.local:3006",
        },
        bdk.Network.REGTEST: {
            "default": "http://localhost:8080/"
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {"default": "https://mempool.space/testnet/"},
        bdk.Network.SIGNET: {"default": "https://mutinynet.com"},
    }
    return d[network]


@dataclass
class ElectrumConfig:
    url: str
    use_ssl: bool


def get_electrum_configs(network: bdk.Network) -> Dict[str, ElectrumConfig]:
    d = {
        bdk.Network.BITCOIN: {
            # "default": ElectrumConfig("mempool.space:50002", True),
            "default": ElectrumConfig("electrum.blockstream.info:50002", True),
            "blockstream": ElectrumConfig("electrum.blockstream.info:50002", True),
            "umbrel": ElectrumConfig("umbrel.local:50001", False),
            "localhost": ElectrumConfig("127.0.0.1:50001", False),
        },
        bdk.Network.REGTEST: {
            "default": ElectrumConfig("127.0.0.1:50000", False),
            "nigiri": ElectrumConfig("127.0.0.1:50000", False),
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": ElectrumConfig("electrum.blockstream.info:60002", True),
            "blockstream": ElectrumConfig("electrum.blockstream.info:60002", True),
        },
        bdk.Network.SIGNET: {
            "default": ElectrumConfig("mutinynet.com:50001", False),
            "mutinynet": ElectrumConfig("mutinynet.com:50001", False),
            "mempool": ElectrumConfig("mempool.space:60602", True),
        },
    }
    return d[network]


def get_default_electrum_use_ssl(network: bdk.Network) -> bool:
    d = {
        bdk.Network.BITCOIN: False,
        bdk.Network.REGTEST: False,
        bdk.Network.TESTNET: True,
        bdk.Network.SIGNET: False,
    }
    return d[network]


def get_default_port(network: bdk.Network, server_type: BlockchainType) -> int:
    if server_type == BlockchainType.CompactBlockFilter:
        d = {
            bdk.Network.BITCOIN: 8333,
            bdk.Network.REGTEST: 18444,
            bdk.Network.TESTNET: 18333,
            bdk.Network.SIGNET: 38333,
        }
        return d[network]
    elif server_type == BlockchainType.Electrum:
        d = {
            bdk.Network.BITCOIN: 50001,
            bdk.Network.REGTEST: 50000,  # nigiri default
            bdk.Network.TESTNET: 51001,
            bdk.Network.SIGNET: 51001,
        }
        return d[network]
    elif server_type == BlockchainType.Esplora:
        d = {
            bdk.Network.BITCOIN: 60002,
            bdk.Network.REGTEST: 3000,  # nigiri default
            bdk.Network.TESTNET: 51001,
            bdk.Network.SIGNET: 51001,
        }
        return d[network]
    elif server_type == BlockchainType.RPC:
        d = {
            bdk.Network.BITCOIN: 8332,
            bdk.Network.REGTEST: 18443,
            bdk.Network.TESTNET: 18332,
            bdk.Network.SIGNET: 38332,
        }
        return d[network]
    raise ValueError(f"Could not get port for {network, server_type}")


def get_esplora_urls(network: bdk.Network) -> Dict[str, str]:
    d = {
        bdk.Network.BITCOIN: {
            "default": "https://blockstream.info/api/",
            "blockstream": "https://blockstream.info/api/",
        },
        bdk.Network.REGTEST: {
            "default": "http://127.0.0.1:3000",
            "localhost": "http://127.0.0.1:3000",
            "nigiri": "http://127.0.0.1:3000",
        },  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: {
            "default": "https://blockstream.info/testnet//api/",
            "blockstream": "https://blockstream.info/testnet/api/",
        },
        bdk.Network.SIGNET: {
            "default": "http://127.0.0.1:3000",
            "localhost": "http://127.0.0.1:3000",
        },
    }
    return d[network]


def get_description(network: bdk.Network, server_type: BlockchainType) -> str:
    if server_type == BlockchainType.CompactBlockFilter:
        d = {
            bdk.Network.BITCOIN: translate(
                "net_conf", "This is a private and fast way to connect to the bitcoin network."
            ),
            bdk.Network.REGTEST: "",
            bdk.Network.TESTNET: "",
            bdk.Network.SIGNET: "",
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
                    "You can setup {link} with an electrum server on {server} and a block explorer on {explorer}",
                ).format(
                    link=link("https://nigiri.vulpem.com/", "nigiri"),
                    server=link("http://localhost:50000", "localhost:50000"),
                    explorer=link("http://localhost:5000", "localhost:5000"),
                )
            ),
            bdk.Network.TESTNET: (
                translate("net_conf", "A good option is {link} and a block explorer on {explorer}.").format(
                    link=link(get_electrum_configs(bdk.Network.TESTNET)["blockstream"].url),
                    explorer=link("https://blockstream.info/testnet"),
                )
            ),
            bdk.Network.SIGNET: (
                translate(
                    "net_conf",
                    "A good option is {link} and a block explorer on {explorer}. There is a {faucet}.",
                ).format(
                    link=link(get_electrum_configs(bdk.Network.SIGNET)["mutinynet"].url),
                    explorer=link("https://mutinynet.com/"),
                    faucet=link("https://faucet.mutinynet.com", "faucet"),
                )
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
                    "You can setup {setup} with an esplora server on {server} and a block explorer on {explorer}",
                ).format(
                    setup=link("https://nigiri.vulpem.com/", "nigiri"),
                    server=link("http://localhost:3000", "localhost:3000"),
                    explorer=link("http://localhost:5000", "localhost:5000"),
                )
            ),  # nigiri default
            bdk.Network.TESTNET: "",
            bdk.Network.SIGNET: "",
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
            bdk.Network.SIGNET: translate(
                "net_conf",
                'Run your bitcoind with "bitcoind -chain=signet"  This however is a different signet than mutinynet.com.',
            ),
        }
        return d[network]
    raise ValueError(f"Could not get description for {network, server_type}")


class NetworkConfig(BaseSaveableClass):
    VERSION = "0.0.2"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "BlockchainType": BlockchainType,
        "CBFServerType": CBFServerType,
    }

    def __init__(self, network: bdk.Network) -> None:
        self.network = network
        self.server_type: BlockchainType = BlockchainType.Electrum
        self.cbf_server_type: CBFServerType = CBFServerType.Automatic
        self.compactblockfilters_ip: str = "127.0.0.1"
        self.compactblockfilters_port: int = get_default_port(network, BlockchainType.CompactBlockFilter)
        electrum_config = get_electrum_configs(network)["default"]
        self.electrum_url: str = electrum_config.url
        self.electrum_use_ssl: bool = electrum_config.use_ssl
        self.rpc_ip: str = "127.0.0.1"
        self.rpc_port: int = get_default_port(network, BlockchainType.RPC)
        self.rpc_username: str = ""
        self.rpc_password: str = ""

        self.esplora_url: str = get_esplora_urls(network)["default"]

        self.mempool_url: str = get_mempool_url(network)["default"]

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d.update(self.__dict__)

        return d

    @classmethod
    def from_dump(cls, dct, class_kwargs=None) -> "NetworkConfig":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        u = cls(**filtered_for_init(dct, cls))

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(u, k, v)
        return u

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        "this class should be overwritten in child classes"
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            dct["_network"] = dct["network"]
            del dct["network"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.1"):
            dct["network"] = dct["_network"]
            del dct["_network"]

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct


class NetworkConfigs(BaseSaveableClass):
    VERSION = "0.0.0"
    known_classes = {**BaseSaveableClass.known_classes, "NetworkConfig": NetworkConfig}

    def __init__(self, configs: dict[str, NetworkConfig] | None = None) -> None:
        super().__init__()

        self.configs: dict[str, NetworkConfig] = (
            configs if configs else {network.name: NetworkConfig(network=network) for network in bdk.Network}
        )

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def dump(self) -> Dict:
        d = super().dump()
        d["configs"] = {k: v.dump() for k, v in self.configs.items()}
        return d

    @classmethod
    def from_file(cls, filename: str, password: str | None = None) -> "NetworkConfigs":
        return super()._from_file(
            filename=filename,
            password=password,
        )

    @classmethod
    def from_dump(cls, dct, class_kwargs=None) -> "NetworkConfigs":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))
