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


from pathlib import Path

import bdkpython as bdk
import pytest

from bitcoin_safe.config import UserConfig
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.storage import Storage
from bitcoin_safe.util import rel_home_path_to_abs_path
from bitcoin_safe.wallet import Wallet


@pytest.fixture
def config() -> UserConfig:
    config = UserConfig()
    config.network = bdk.Network.REGTEST

    return config


def test_011(config: UserConfig):
    file_path = "tests/data/0.1.1.wallet"

    password = None

    assert not Storage().has_password(file_path)

    wallet = Wallet.from_file(file_path, config, password)

    assert wallet


def test_config010():
    file_path = "tests/data/config_0.1.0.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.last_wallet_files == {"Network.REGTEST": [".config/bitcoin_safe/REGTEST/Coldcard.wallet"]}
    assert config.data_dir == rel_home_path_to_abs_path(".local/share/bitcoin_safe")

    assert config


def test_config_0_1_6_testnet3_electrum():
    file_path = "tests/data/0.1.6_testnet.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET
    assert config.network_config.network == bdk.Network.TESTNET
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "blockstream.info:993"
    assert config.network_config.electrum_use_ssl == True

    assert config.network_config.proxy_url == None


def test_config_0_1_6_testnet4_electrum():
    file_path = "tests/data/config_0.1.6_testnet4_electrum.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET4
    assert config.network_config.network == bdk.Network.TESTNET4
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "mempool.space:40002"
    assert config.network_config.electrum_use_ssl == True

    assert config.network_config.proxy_url == None
    assert bdk.Network.TESTNET4 in config.recently_open_wallets


def test_config_0_1_6_testnet4_proxy_electrum():
    file_path = "tests/data/config_0.1.6_testnet4_proxy_electrum.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET4
    assert config.network_config.network == bdk.Network.TESTNET4
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "mempool.space:40002"
    assert config.network_config.electrum_use_ssl == True

    assert config.network_config.proxy_url == "127.0.0.1:9050"
    assert bdk.Network.TESTNET4 in config.recently_open_wallets


def test_config_0_1_6_rpc():
    file_path = "tests/data/config_0.1.6_rpc.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.BITCOIN
    assert config.network_config.network == bdk.Network.BITCOIN
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == ""  # removed because of rpc
    assert config.network_config.electrum_use_ssl == True

    assert config.network_config.proxy_url == None
    assert bdk.Network.TESTNET4 in config.recently_open_wallets
