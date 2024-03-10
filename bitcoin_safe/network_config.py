import logging

from packaging import version

logger = logging.getLogger(__name__)

from typing import Any, Dict

import bdkpython as bdk

from bitcoin_safe.pythonbdk_types import BlockchainType, CBFServerType
from bitcoin_safe.storage import BaseSaveableClass

MIN_RELAY_FEE = 1
FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this


def get_default_mempool_url(network: bdk.Network) -> str:
    d = {
        bdk.Network.BITCOIN: "https://mempool.space/",
        bdk.Network.REGTEST: "http://localhost:8080/",  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: "https://mempool.space/testnet/",
        bdk.Network.SIGNET: "https://mutinynet.com",
    }
    return d[network]


def get_default_electrum_url(network: bdk.Network) -> str:
    d = {
        bdk.Network.BITCOIN: "127.0.0.1:50001",
        bdk.Network.REGTEST: "127.0.0.1:50000",  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: "electrum.blockstream.info:60002",
        bdk.Network.SIGNET: "mutinynet.com:50001",
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
    return 0


def get_description(network: bdk.Network, server_type: BlockchainType) -> str:
    if server_type == BlockchainType.CompactBlockFilter:
        d = {
            bdk.Network.BITCOIN: ("This is a private and fast way to connect to the bitcoin network."),
            bdk.Network.REGTEST: "",
            bdk.Network.TESTNET: "",
            bdk.Network.SIGNET: "",
        }
        return d[network]
    elif server_type == BlockchainType.Electrum:
        d = {
            bdk.Network.BITCOIN: (
                "The server can associate your IP address with the wallet addresses.\n"
                'It is best to use your own server, such as <a href="https://umbrel.com/">umbrel</a>.'
            ),
            bdk.Network.REGTEST: (
                'You can setup <a href="https://nigiri.vulpem.com/">nigiri</a> with an electrum server on <a href="http://localhost:50000">localhost:50000</a>'
                ' and a block explorer on <a href="http://localhost:5000">localhost:5000</a>'
            ),
            bdk.Network.TESTNET: (
                f'A good option is <a href="{get_default_electrum_url(bdk.Network.TESTNET)}">{get_default_electrum_url(bdk.Network.TESTNET)}</a>'
                ' and a block explorer on <a href="https://blockstream.info/testnet/">https://blockstream.info/testnet</a>.'
            ),
            bdk.Network.SIGNET: (
                f'A good option is <a href="{get_default_electrum_url(bdk.Network.SIGNET)}">{get_default_electrum_url(bdk.Network.SIGNET)}</a>'
                ' and a block explorer on <a href="https://mutinynet.com/">https://mutinynet.com</a>. There is a <a href="https://faucet.mutinynet.com">faucet</a>.'
            ),
        }
        return d[network]
    elif server_type == BlockchainType.Esplora:
        d = {
            bdk.Network.BITCOIN: (
                "The server can associate your IP address with the wallet addresses.\n"
                'It is best to use your own server, such as <a href="https://umbrel.com/">umbrel</a>.'
            ),
            bdk.Network.REGTEST: (
                'You can setup <a href="https://nigiri.vulpem.com/">nigiri</a> with an esplora server on <a href="http://localhost:3000">localhost:3000</a>'
                ' and a block explorer on <a href="http://localhost:5000">localhost:5000</a>'
            ),  # nigiri default
            bdk.Network.TESTNET: "",
            bdk.Network.SIGNET: "",
        }
        return d[network]
    elif server_type == BlockchainType.RPC:
        d = {
            bdk.Network.BITCOIN: (
                'You can connect your own Bitcoin node, such as <a href="https://umbrel.com/">umbrel</a>.'
            ),
            bdk.Network.REGTEST: ('Run your bitcoind with "bitcoind -chain=regtest"'),
            bdk.Network.TESTNET: ('Run your bitcoind with "bitcoind -chain=test"'),
            bdk.Network.SIGNET: (
                'Run your bitcoind with "bitcoind -chain=signet"  This however is a different signet than mutinynet.com.'
            ),
        }
        return d[network]
    return 0


class NetworkConfig(BaseSaveableClass):
    VERSION = "0.0.2"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "BlockchainType": BlockchainType,
        "CBFServerType": CBFServerType,
    }

    def __init__(self, network: bdk.Network):
        self.network = network
        self.server_type: BlockchainType = BlockchainType.Electrum
        self.cbf_server_type: CBFServerType = CBFServerType.Automatic
        self.compactblockfilters_ip: str = "127.0.0.1"
        self.compactblockfilters_port: int = get_default_port(network, BlockchainType.CompactBlockFilter)
        self.electrum_url: str = get_default_electrum_url(network)
        self.electrum_use_ssl: bool = get_default_electrum_use_ssl(network)
        self.rpc_ip: str = "127.0.0.1"
        self.rpc_port: int = get_default_port(network, BlockchainType.RPC)
        self.rpc_username: str = ""
        self.rpc_password: str = ""

        self.esplora_url: str = "http://127.0.0.1:3000"

        self.mempool_url: str = get_default_mempool_url(network)

    def dump(self):
        d = super().dump()
        d.update(self.__dict__)

        return d

    @classmethod
    def from_dump(cls, dct, class_kwargs=None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        u = NetworkConfig(network=dct["network"])

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

    def __init__(self, configs: dict[str, NetworkConfig] = None) -> None:
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

    def dump(self):
        d = super().dump()
        d["configs"] = {k: v.dump() for k, v in self.configs.items()}
        return d

    @classmethod
    def from_file(cls, filename: str, password: str = None):
        return super()._from_file(
            filename=filename,
            password=password,
        )

    @classmethod
    def from_dump(cls, dct, class_kwargs=None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**dct)
