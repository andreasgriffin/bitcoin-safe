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
import tempfile
from pathlib import Path

import bdkpython as bdk
import pytest

from bitcoin_safe.config import UserConfig
from bitcoin_safe.pythonbdk_types import BlockchainType
from tests.test_setup_bitcoin_core import (
    BITCOIN_HOST,
    BITCOIN_PORT,
    RPC_PASSWORD,
    RPC_USER,
)

logger = logging.getLogger(__name__)


class TestConfig(UserConfig):
    config_dir = Path(tempfile.mkdtemp())
    config_file = Path(config_dir) / (UserConfig.app_name + ".conf")


@pytest.fixture(scope="session")
def test_config() -> TestConfig:
    config = TestConfig()
    logger.info(f"Setting config_dir = {config.config_dir} and config_file = {config.config_file}")
    config.network = bdk.Network.REGTEST
    config.network_config.server_type = BlockchainType.RPC
    config.network_config.rpc_ip = BITCOIN_HOST
    config.network_config.rpc_port = BITCOIN_PORT
    config.network_config.rpc_username = RPC_USER
    config.network_config.rpc_password = RPC_PASSWORD
    return config
