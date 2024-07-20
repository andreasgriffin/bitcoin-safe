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

import bdkpython as bdk

from bitcoin_safe.config import UserConfig
from bitcoin_safe.keystore import KeyStore
from tests.test_wallet import create_test_seed_keystores

from .test_helpers import test_config  # type: ignore

logger = logging.getLogger(__name__)


def test_dump(test_config: UserConfig):
    "Tests if dump works correctly"
    network = bdk.Network.REGTEST

    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]

    keystore_restored = KeyStore.from_dump(keystore.dump())
    assert keystore.is_equal(keystore_restored)
