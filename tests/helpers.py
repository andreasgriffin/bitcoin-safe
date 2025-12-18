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
import tempfile
from pathlib import Path

import bdkpython as bdk
import pytest

from bitcoin_safe.config import UserConfig
from bitcoin_safe.pythonbdk_types import BlockchainType

logger = logging.getLogger(__name__)


class TestConfig(UserConfig):
    config_dir = Path(tempfile.mkdtemp())
    config_file = Path(config_dir) / (UserConfig.app_name + ".conf")


@pytest.fixture()
def test_config(fulcrum: str) -> TestConfig:
    """Test config."""
    config = TestConfig()
    logger.info(f"Setting config_dir = {config.config_dir} and config_file = {config.config_file}")
    config.network = bdk.Network.REGTEST
    config.network_config.server_type = BlockchainType.Electrum
    config.network_config.electrum_url = fulcrum
    config.network_config.electrum_use_ssl = False
    config.auto_label_change_addresses = True
    return config


@pytest.fixture(scope="session")
def test_config_session(fulcrum: str) -> TestConfig:
    """Test config session."""
    config = TestConfig()
    logger.info(f"Setting config_dir = {config.config_dir} and config_file = {config.config_file}")
    config.network = bdk.Network.REGTEST
    config.network_config.server_type = BlockchainType.Electrum
    config.network_config.electrum_url = fulcrum
    config.network_config.electrum_use_ssl = False

    return config


@pytest.fixture()
def test_config_main_chain() -> TestConfig:
    """Test config main chain."""
    config = TestConfig()
    logger.info(f"Setting config_dir = {config.config_dir} and config_file = {config.config_file}")

    return config
