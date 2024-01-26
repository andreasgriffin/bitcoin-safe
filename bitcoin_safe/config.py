import logging

logger = logging.getLogger(__name__)

import os
from typing import Dict, List

import appdirs
import bdkpython as bdk

from .pythonbdk_types import BlockchainType, CBFServerType
from .storage import BaseSaveableClass

MIN_RELAY_FEE = 1
FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this


def get_default_mempool_url(network: bdk.Network) -> str:
    d = {
        bdk.Network.BITCOIN: "https://mempool.space/",
        bdk.Network.REGTEST: "http://localhost:8080/",  # you can use https://github.com/ngutech21/nigiri-mempool/
        bdk.Network.TESTNET: "https://mempool.space/testnet/",
        bdk.Network.SIGNET: "https://mempool.space/signet/",
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


class NetworkConfig(BaseSaveableClass):
    def __init__(self):
        self.network: bdk.Network = bdk.Network.REGTEST
        self.server_type: BlockchainType = BlockchainType.Electrum
        self.cbf_server_type: CBFServerType = CBFServerType.Automatic
        self.compactblockfilters_ip: str = "127.0.0.1"
        self.compactblockfilters_port: int = get_default_port(self.network, BlockchainType.CompactBlockFilter)
        self.electrum_url: str = "127.0.0.1:51001"
        self.rpc_ip: str = "127.0.0.1"
        self.rpc_port: int = get_default_port(self.network, BlockchainType.RPC)
        self.rpc_username: str = ""
        self.rpc_password: str = ""

        self.esplora_url: str = "http://127.0.0.1:3000"

        self.mempool_url: str = get_default_mempool_url(self.network)

    def serialize(self):
        d = super().serialize()
        d.update(self.__dict__)
        return d

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        super().deserialize(dct, class_kwargs=class_kwargs)
        u = cls()

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(u, k, v)
        return u


class UserConfig(BaseSaveableClass):
    global_variables = globals()

    VERSION = "0.1.0"
    app_name = "bitcoin_safe"
    config_dir = appdirs.user_config_dir(app_name)
    config_file = os.path.join(appdirs.user_config_dir(app_name), app_name + ".conf")

    fee_ranges = {
        bdk.Network.BITCOIN: [1, 1000],
        bdk.Network.REGTEST: [0, 1000],
        bdk.Network.SIGNET: [0, 1000],
        bdk.Network.TESTNET: [0, 1000],
    }

    def __init__(self):
        self.network_config = NetworkConfig()
        self.last_wallet_files: Dict[str, List[str]] = {}  # network:[file_path0]
        self.opened_txlike: Dict[str, List[str]] = {}  # network:[serializedtx, serialized psbt]
        self.data_dir = appdirs.user_data_dir(self.app_name)
        self.is_maximized = False
        self.enable_opportunistic_merging_fee_rate = 5

    @property
    def wallet_dir(self):
        return os.path.join(self.config_dir, self.network_config.network.name)

    def get(self, key, default=None):
        "For legacy reasons"
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def serialize(self):
        d = super().serialize()
        d.update(self.__dict__)
        return d

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        super().deserialize(dct, class_kwargs=class_kwargs)
        u = cls()

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(u, k, v)
        return u

    @classmethod
    def load(cls, password=None):
        if os.path.isfile(cls.config_file):
            return super()._load(cls.config_file, password=password)
        else:
            return UserConfig()

    def save(self):
        super().save(self.config_file)
