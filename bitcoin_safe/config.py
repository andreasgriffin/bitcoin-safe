import logging
from collections import deque

from packaging import version

logger = logging.getLogger(__name__)

import os
from typing import Any, Dict, List

import appdirs
import bdkpython as bdk

from .network_config import NetworkConfig, NetworkConfigs
from .storage import BaseSaveableClass
from .util import path_to_rel_home_path, rel_home_path_to_abs_path

MIN_RELAY_FEE = 1
FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this
NO_FEE_WARNING_BELOW = 10  # sat/vB


class UserConfig(BaseSaveableClass):
    known_classes = {**BaseSaveableClass.known_classes, "NetworkConfigs": NetworkConfigs}
    VERSION = "0.1.3"

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
        self.network_configs = NetworkConfigs()
        self.network = bdk.Network
        self.last_wallet_files: Dict[str, List[str]] = {}  # network:[file_path0]
        self.opened_txlike: Dict[str, List[str]] = {}  # network:[serializedtx, serialized psbt]
        self.data_dir = appdirs.user_data_dir(self.app_name)
        self.is_maximized = False
        self.recently_open_wallets: deque = deque(maxlen=5)

    @property
    def network_config(self) -> NetworkConfig:
        return self.network_configs.configs[self.network.name]

    @property
    def wallet_dir(self):
        return os.path.join(self.config_dir, self.network.name)

    def get(self, key, default=None):
        "For legacy reasons"
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def dump(self):
        d = super().dump()
        d.update(self.__dict__.copy())

        d["data_dir"] = path_to_rel_home_path(self.data_dir)

        d["recently_open_wallets"] = list(self.recently_open_wallets)
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs=None) -> "UserConfig":
        super()._from_dump(dct, class_kwargs=class_kwargs)
        dct["recently_open_wallets"] = deque(dct.get("recently_open_wallets", []), maxlen=5)
        dct["data_dir"] = rel_home_path_to_abs_path(dct["data_dir"])

        u = cls()

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(u, k, v)
        return u

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        "this class should be overwritten in child classes"
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.0"):
            network_config: NetworkConfig = dct["network_config"]
            dct["network_configs"] = {network.name: NetworkConfig(network=network) for network in bdk.Network}
            dct["network_configs"][network_config.network.name] = network_config
            dct["network"] = network_config.network
            del dct["network_config"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.1"):
            del dct["enable_opportunistic_merging_fee_rate"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.2"):
            del dct["network_configs"]

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    @classmethod
    def from_file(cls, password=None, file_path=None):
        if file_path is None:
            file_path = cls.config_file
        if os.path.isfile(file_path):
            return super()._from_file(file_path, password=password)
        else:
            return UserConfig()

    def save(self):
        super().save(self.config_file)
