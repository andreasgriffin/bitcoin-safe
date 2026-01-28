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

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import appdirs
import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol
from PyQt6.QtCore import QCoreApplication

from bitcoin_safe.gui.qt.unique_deque import UniqueDeque
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.util import current_project_dir

from .execute_config import DEFAULT_LANG_CODE, DEFAULT_MAINNET
from .network_config import (
    NetworkConfig,
    NetworkConfigs,
    get_electrum_configs,
    get_esplora_urls,
)
from .storage import BaseSaveableClass
from .util import fast_version

logger = logging.getLogger(__name__)

FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this
NO_FEE_WARNING_BELOW = 10  # sat/vB


RECENT_WALLET_MAXLEN = 15


class UserConfig(BaseSaveableClass):
    known_classes = {
        **BaseSaveableClass.known_classes,
        NetworkConfigs.__name__: NetworkConfigs,
        BitcoinSymbol.__name__: BitcoinSymbol,
    }
    VERSION = "0.2.8"

    app_name = "bitcoin_safe"
    locales_path = current_project_dir() / "gui" / "locales"
    config_dir = Path(appdirs.user_config_dir(app_name))
    config_file = config_dir / (app_name + ".conf")
    window_properties_config_file = config_dir / (app_name + "_window_properties.conf")

    fee_ranges = {
        bdk.Network.BITCOIN: [0.1, 1000],
        bdk.Network.REGTEST: [0.0, 1000],
        bdk.Network.SIGNET: [0.0, 1000],
        bdk.Network.TESTNET: [0.0, 1000],
        bdk.Network.TESTNET4: [0.0, 1000],
    }

    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__()
        self.network_configs = NetworkConfigs()
        self.network: bdk.Network = bdk.Network.BITCOIN if DEFAULT_MAINNET else bdk.Network.TESTNET4
        self.last_wallet_files: dict[str, list[str]] = {}  # network:[file_path0]
        self.opened_txlike: dict[str, list[str]] = {}  # network:[serializedtx, serialized psbt]
        self.is_maximized = False
        self.recently_open_wallets: dict[bdk.Network, UniqueDeque[str]] = {
            network: UniqueDeque(maxlen=RECENT_WALLET_MAXLEN) for network in bdk.Network
        }
        self.language_code: str = DEFAULT_LANG_CODE
        self.currency: str = "USD"
        self.bitcoin_symbol: BitcoinSymbol = BitcoinSymbol.ISO
        self.rates: dict[str, dict[str, Any]] = {}
        self.last_tab_title: list[str] = []
        self.auto_label_change_addresses: bool = False

    def clean_recently_open_wallet(self):
        """Clean recently open wallet."""
        this_deque = self.recently_open_wallets[self.network]
        # clean deleted paths
        for deque_item in list(this_deque):
            if not Path(deque_item).exists():
                this_deque.remove(deque_item)

    def add_recently_open_wallet(self, file_path: str) -> None:
        """Add recently open wallet."""
        self.clean_recently_open_wallet()
        self.recently_open_wallets[self.network].append(file_path)

    @property
    def network_config(self) -> NetworkConfig:
        """Network config."""
        return self.network_configs.configs[self.network.name]

    @property
    def wallet_dir(self) -> str:
        """Wallet dir."""
        return os.path.join(self.config_dir, self.network.name)

    def get(self, key: str, default=None) -> Any:
        "For legacy reasons"
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d.update(self.__dict__.copy())

        # for better portability between computers we make this relative to the home folder
        d["rates"] = self.rates

        d["recently_open_wallets"] = {
            network.name: list(v) for network, v in self.recently_open_wallets.items()
        }
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> UserConfig:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        dct["recently_open_wallets"] = {
            bdk.Network._member_map_[k]: UniqueDeque(v, maxlen=RECENT_WALLET_MAXLEN)
            for k, v in dct.get(
                "recently_open_wallets",
                {network.name: UniqueDeque(maxlen=RECENT_WALLET_MAXLEN) for network in bdk.Network},
            ).items()
            if k in bdk.Network._member_map_
        }
        # for better portability between computers the saved string is relative to the home folder
        # dct["config_dir"] = rel_home_path_to_abs_path(dct["config_dir"])
        # dct["config_file"] = rel_home_path_to_abs_path(dct["config_file"])

        instance = cls()

        for k, v in dct.items():
            if v is not None:  # only overwrite the default value, if there is a value
                setattr(instance, k, v)

        instance.clean_recently_open_wallet()
        return instance

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.0"):
            network_config_testnet_3: NetworkConfig = dct["network_config"]
            dct["network_configs"] = {network.name: NetworkConfig(network=network) for network in bdk.Network}
            dct["network_configs"][network_config_testnet_3.network.name] = network_config_testnet_3
            dct["network"] = network_config_testnet_3.network
            del dct["network_config"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.1"):
            if "enable_opportunistic_merging_fee_rate" in dct:
                del dct["enable_opportunistic_merging_fee_rate"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.2"):
            if "network_configs" in dct:
                del dct["network_configs"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.3"):
            if "recently_open_wallets" in dct:
                del dct["recently_open_wallets"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.4"):
            if "recently_open_wallets" in dct:
                del dct["recently_open_wallets"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.6"):
            if "config_dir" in dct:
                del dct["config_dir"]
            if "config_file" in dct:
                del dct["config_file"]
        if fast_version(str(dct["VERSION"])) <= fast_version("0.2.0"):
            # handle testnet4
            if "recently_open_wallets" in dct:
                dct["recently_open_wallets"][bdk.Network.TESTNET4.name] = []
            if dct["network"] == bdk.Network.TESTNET:
                network_configs: NetworkConfigs = dct["network_configs"]  # type: ignore
                network_config_testnet_3 = network_configs.configs[bdk.Network.TESTNET.name]
                if (
                    network_config_testnet_3.server_type == BlockchainType.Electrum
                    and network_config_testnet_3.electrum_url
                    in [c.url for c in get_electrum_configs(bdk.Network.TESTNET4).values()]
                ):
                    dct["network"] = bdk.Network.TESTNET4
                    network_config_testnet_4 = network_configs.configs[bdk.Network.TESTNET4.name]
                    network_config_testnet_4.electrum_url = network_config_testnet_3.electrum_url
                    network_config_testnet_4.electrum_use_ssl = network_config_testnet_3.electrum_use_ssl
                    network_config_testnet_4.server_type = network_config_testnet_3.server_type
                    network_config_testnet_4.proxy_url = network_config_testnet_3.proxy_url

                elif (
                    network_config_testnet_3.server_type == BlockchainType.Esplora
                    and network_config_testnet_3.esplora_url
                    in get_esplora_urls(bdk.Network.TESTNET4).values()
                ):
                    dct["network"] = bdk.Network.TESTNET4
                    network_config_testnet_4 = network_configs.configs[bdk.Network.TESTNET4.name]
                    network_config_testnet_4.esplora_url = network_config_testnet_3.esplora_url
                    network_config_testnet_4.server_type = network_config_testnet_3.server_type
                    network_config_testnet_4.proxy_url = network_config_testnet_3.proxy_url

        if fast_version(str(dct["VERSION"])) <= fast_version("0.2.2"):
            old_path = (
                cls.config_dir.parent
                / QCoreApplication.organizationName()
                / f"{QCoreApplication.applicationName()}.conf"
            )
            if old_path.exists():
                os.makedirs(cls.window_properties_config_file.parent, exist_ok=True)
                shutil.move(old_path, str(cls.window_properties_config_file))

        if fast_version(str(dct["VERSION"])) < fast_version("0.2.5"):
            dct["last_tab_title"] = []

        if fast_version(str(dct["VERSION"])) < fast_version("0.2.6"):
            # disable labeling of change
            dct["auto_label_change_addresses"] = False

        return super().from_dump_migration(dct=dct)

    @classmethod
    def file_migration(cls, file_content: str):
        "this class can be overwritten in child classes"

        dct = json.loads(file_content)

        # old versions
        if config := dct.get("network_config"):
            if fast_version(str(config["VERSION"])) < fast_version("0.1.0"):
                if "cbf_server_type" in config:
                    del config["cbf_server_type"]  # removed  (and removed type)

        # newer versions
        if (
            (network_configs := dct.get("network_configs"))
            and (configs := network_configs.get("configs"))
            and isinstance(configs, dict)
        ):
            for config in configs.values():
                if fast_version(str(config["VERSION"])) <= fast_version("0.1.1"):
                    if "cbf_server_type" in config:
                        del config["cbf_server_type"]  # removed  (and removed type)

                # downgrade: if NetworkConfig.VERSION is doesnt support p2p_listener_type
                if fast_version(NetworkConfig.VERSION) < fast_version("0.2.0"):
                    if "p2p_listener_type" in config:
                        del config["p2p_listener_type"]  # can contain future type P2pListenerType

        # in the function above, only default json serilizable things can be set in dct
        return json.dumps(dct)

    @classmethod
    def exists(cls, password=None, file_path=None) -> bool:
        """Exists."""
        if file_path is None:
            file_path = cls.config_file
        return os.path.isfile(file_path)

    @classmethod
    def from_file(cls, password: str | None = None, file_path: Path | None = None) -> UserConfig:
        """From file."""
        if file_path is None:
            file_path = cls.config_file
        if os.path.isfile(file_path):
            return super()._from_file(str(file_path), password=password)
        else:
            return UserConfig()

    def save(self) -> None:  # type: ignore
        """Save."""
        super().save(self.config_file)
