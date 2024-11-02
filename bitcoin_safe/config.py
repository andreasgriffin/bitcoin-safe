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
from pathlib import Path

from packaging import version

from bitcoin_safe.gui.qt.unique_deque import UniqueDeque

from .execute_config import DEFAULT_MAINNET

logger = logging.getLogger(__name__)

import os
from typing import Any, Dict, List, Optional

import appdirs
import bdkpython as bdk

from .network_config import NetworkConfig, NetworkConfigs
from .storage import BaseSaveableClass
from .util import (
    briefcase_project_dir,
    path_to_rel_home_path,
    rel_home_path_to_abs_path,
)

MIN_RELAY_FEE = 1
FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this
NO_FEE_WARNING_BELOW = 10  # sat/vB


RECENT_WALLET_MAXLEN = 15


class UserConfig(BaseSaveableClass):
    known_classes = {**BaseSaveableClass.known_classes, "NetworkConfigs": NetworkConfigs}
    VERSION = "0.1.6"

    app_name = "bitcoin_safe"
    locales_path = briefcase_project_dir() / "gui" / "locales"
    config_dir = Path(appdirs.user_config_dir(app_name))
    config_file = config_dir / (app_name + ".conf")

    fee_ranges = {
        bdk.Network.BITCOIN: [1.0, 1000],
        bdk.Network.REGTEST: [0.0, 1000],
        bdk.Network.SIGNET: [0.0, 1000],
        bdk.Network.TESTNET: [0.0, 1000],
    }

    def __init__(self) -> None:
        self.network_configs = NetworkConfigs()
        self.network: bdk.Network = bdk.Network.BITCOIN if DEFAULT_MAINNET else bdk.Network.TESTNET
        self.last_wallet_files: Dict[str, List[str]] = {}  # network:[file_path0]
        self.opened_txlike: Dict[str, List[str]] = {}  # network:[serializedtx, serialized psbt]
        self.data_dir = appdirs.user_data_dir(self.app_name)
        self.is_maximized = False
        self.recently_open_wallets: Dict[bdk.Network, UniqueDeque[str]] = {
            network: UniqueDeque(maxlen=RECENT_WALLET_MAXLEN) for network in bdk.Network
        }
        self.language_code: Optional[str] = None

    def add_recently_open_wallet(self, file_path: str) -> None:
        self.recently_open_wallets[self.network].append(file_path)

    @property
    def network_config(self) -> NetworkConfig:
        return self.network_configs.configs[self.network.name]

    @property
    def wallet_dir(self) -> str:
        return os.path.join(self.config_dir, self.network.name)

    def get(self, key: str, default=None) -> Any:
        "For legacy reasons"
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d.update(self.__dict__.copy())

        # for better portability between computers we make this relative to the home folder
        d["data_dir"] = str(path_to_rel_home_path(self.data_dir))

        d["recently_open_wallets"] = {
            network.name: list(v) for network, v in self.recently_open_wallets.items()
        }
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs=None) -> "UserConfig":
        super()._from_dump(dct, class_kwargs=class_kwargs)
        dct["recently_open_wallets"] = {
            bdk.Network._member_map_[k]: UniqueDeque(v, maxlen=RECENT_WALLET_MAXLEN)
            for k, v in dct.get(
                "recently_open_wallets",
                {network.name: UniqueDeque(maxlen=RECENT_WALLET_MAXLEN) for network in bdk.Network},
            ).items()
        }
        # for better portability between computers the saved string is relative to the home folder
        dct["data_dir"] = rel_home_path_to_abs_path(dct["data_dir"])
        # dct["config_dir"] = rel_home_path_to_abs_path(dct["config_dir"])
        # dct["config_file"] = rel_home_path_to_abs_path(dct["config_file"])

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
            if "enable_opportunistic_merging_fee_rate" in dct:
                del dct["enable_opportunistic_merging_fee_rate"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.2"):
            if "network_configs" in dct:
                del dct["network_configs"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.3"):
            if "recently_open_wallets" in dct:
                del dct["recently_open_wallets"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.4"):
            if "recently_open_wallets" in dct:
                del dct["recently_open_wallets"]
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.6"):
            if "config_dir" in dct:
                del dct["config_dir"]
            if "config_file" in dct:
                del dct["config_file"]

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    @classmethod
    def exists(cls, password=None, file_path=None) -> bool:
        if file_path is None:
            file_path = cls.config_file
        return os.path.isfile(file_path)

    @classmethod
    def from_file(cls, password: str | None = None, file_path: Path | None = None) -> "UserConfig":
        if file_path is None:
            file_path = cls.config_file
        if os.path.isfile(file_path):
            return super()._from_file(str(file_path), password=password)
        else:
            return UserConfig()

    def save(self) -> None:  # type: ignore
        super().save(self.config_file)
