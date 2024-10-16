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


def test_config010(config: UserConfig):
    file_path = "tests/data/config_0.1.0.conf"

    config = UserConfig.from_file(file_path=Path(file_path))
    assert config.last_wallet_files == {"Network.REGTEST": [".config/bitcoin_safe/REGTEST/Coldcard.wallet"]}
    assert config.data_dir == rel_home_path_to_abs_path(".local/share/bitcoin_safe")

    assert config
