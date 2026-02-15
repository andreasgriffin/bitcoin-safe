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
from pathlib import Path

import bdkpython as bdk

from bitcoin_safe.config import UserConfig
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.storage import Storage
from bitcoin_safe.wallet import Wallet

from ..helpers import TestConfig


def test_011(test_config: TestConfig) -> None:
    """Test 011."""
    file_path = "tests/data/0.1.1.wallet"

    password = None

    # Older wallet files should load without a password.
    assert not Storage().has_password(file_path)

    wallet = Wallet.from_file(file_path, test_config, password=password, loop_in_thread=None)

    assert wallet


def test_config010() -> None:
    """Test config010."""
    file_path = "tests/data/config_0.1.0.conf"

    # Ensure legacy config loads and last_wallet_files is preserved.
    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.last_wallet_files == {"Network.REGTEST": [".config/bitcoin_safe/REGTEST/Coldcard.wallet"]}

    assert config


def test_config_0_1_6_testnet3_electrum() -> None:
    """Test config 0 1 6 testnet3 electrum."""
    file_path = "tests/data/0.1.6_testnet.conf"

    # Testnet3 electrum settings should be migrated correctly.
    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET
    assert config.network_config.network == bdk.Network.TESTNET
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "blockstream.info:993"
    assert config.network_config.electrum_use_ssl

    assert config.network_config.proxy_url is None


def test_config_0_1_6_testnet4_electrum() -> None:
    """Test config 0 1 6 testnet4 electrum."""
    file_path = "tests/data/config_0.1.6_testnet4_electrum.conf"

    # Testnet4 electrum settings should be migrated correctly.
    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET4
    assert config.network_config.network == bdk.Network.TESTNET4
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "mempool.space:40002"
    assert config.network_config.electrum_use_ssl

    assert config.network_config.proxy_url is None
    assert bdk.Network.TESTNET4 in config.recently_open_wallets


def test_config_0_1_6_testnet4_proxy_electrum() -> None:
    """Test config 0 1 6 testnet4 proxy electrum."""
    file_path = "tests/data/config_0.1.6_testnet4_proxy_electrum.conf"

    # Proxy settings should be preserved for testnet4.
    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.TESTNET4
    assert config.network_config.network == bdk.Network.TESTNET4
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == "mempool.space:40002"
    assert config.network_config.electrum_use_ssl

    assert config.network_config.proxy_url == "127.0.0.1:9050"
    assert bdk.Network.TESTNET4 in config.recently_open_wallets


def test_config_0_1_6_rpc() -> None:
    """Test config 0 1 6 rpc."""
    file_path = "tests/data/config_0.1.6_rpc.conf"

    # RPC config should map to electrum fields as expected.
    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.network == bdk.Network.BITCOIN
    assert config.network_config.network == bdk.Network.BITCOIN
    assert config.network_config.server_type == BlockchainType.Electrum
    assert config.network_config.electrum_url == ""  # removed because of rpc
    assert config.network_config.electrum_use_ssl

    assert config.network_config.proxy_url is None
    assert bdk.Network.TESTNET4 in config.recently_open_wallets


def test_config_0_2_8_testnet4_cbf_migrates_to_electrum(tmp_path: Path) -> None:
    """Test config 0 2 8 testnet4 cbf migrates to electrum."""
    config = UserConfig()
    config.network = bdk.Network.TESTNET4
    config.network_config.server_type = BlockchainType.CompactBlockFilter
    config.network_config.electrum_url = ""

    serialized = json.loads(config.dumps())
    serialized["VERSION"] = "0.2.8"

    file_path = tmp_path / "config_0.2.8_testnet4_cbf.conf"
    file_path.write_text(json.dumps(serialized), encoding="utf-8")

    migrated = UserConfig.from_file(file_path=file_path)
    assert migrated.network == bdk.Network.TESTNET4
    assert migrated.network_config.server_type == BlockchainType.Electrum
    assert migrated.network_config.electrum_url == "blackie.c3-soft.com:57010"
    assert migrated.network_config.electrum_use_ssl
