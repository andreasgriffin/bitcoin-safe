#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

"""Optional user-run actual wallet tests, NEVER includes actual wallet fixtures.

Environment variables:
  ELECTRUM_TEST_FILE=/path/to/your/electrum-wallet
  SPARROW_H2_TEST_FILE=/path/to/your/wallet.mv.db
  WALLET_TEST_PASSWORD=... (only for disposable test wallets)
"""

import os

import pytest

from bitcoin_safe.wallet_import import load_file, verify_sparrow_h2_password


def test_user_electrum_file():
    path = os.getenv("ELECTRUM_TEST_FILE")
    if not path:
        pytest.skip("Set ELECTRUM_TEST_FILE to run real-file smoke test")
    wallets = load_file(path, password=os.getenv("WALLET_TEST_PASSWORD"))
    assert wallets and all(w.source_wallet == "electrum" for w in wallets)
    for wallet in wallets:
        obj = wallet.to_dict()  # validates no private material passes interchange
        assert obj["format_version"] == 1
        if wallet.descriptor and wallet.extra.get("address_verification"):
            assert sum(wallet.extra["address_verification"].values()) >= 1


def test_user_sparrow_password_header():
    path = os.getenv("SPARROW_H2_TEST_FILE")
    if not path:
        pytest.skip("Set SPARROW_H2_TEST_FILE to run real-file smoke test")
    assert verify_sparrow_h2_password(path, os.environ["WALLET_TEST_PASSWORD"])


def test_user_sparrow_database_import():
    path = os.getenv("SPARROW_H2_TEST_FILE")
    if not path:
        pytest.skip("Set SPARROW_H2_TEST_FILE to run real-file smoke test")
    wallets = load_file(path, password=os.getenv("WALLET_TEST_PASSWORD"), hint="sparrow")
    assert wallets
    for wallet in wallets:
        assert wallet.source_wallet == "sparrow-h2"
        wallet.to_dict()  # checks public-only serialization
