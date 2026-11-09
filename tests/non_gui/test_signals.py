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

from bitcoin_safe.signals import Signals, WalletFunctions


def test_closed_wallet_id_can_be_reused_for_rename() -> None:
    wallet_functions = WalletFunctions(Signals())
    closed_wallet_signals = wallet_functions.wallet_signals["closed"]
    renamed_wallet_signals = wallet_functions.wallet_signals["open"]

    wallet_functions.remove_wallet_signals("closed", closed_wallet_signals)
    wallet_functions.rename_wallet("open", "closed")

    assert wallet_functions.wallet_signals["closed"] is renamed_wallet_signals
    assert "open" not in wallet_functions.wallet_signals


def test_stale_wallet_close_does_not_remove_replacement_signals() -> None:
    wallet_functions = WalletFunctions(Signals())
    stale_wallet_signals = wallet_functions.wallet_signals["wallet"]
    del wallet_functions.wallet_signals["wallet"]
    replacement_signals = wallet_functions.wallet_signals["wallet"]

    wallet_functions.remove_wallet_signals("wallet", stale_wallet_signals)

    assert wallet_functions.wallet_signals["wallet"] is replacement_signals
