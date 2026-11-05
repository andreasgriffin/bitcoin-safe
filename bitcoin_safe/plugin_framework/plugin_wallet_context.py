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

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import bdkpython as bdk

from bitcoin_safe.labels import Labels
from bitcoin_safe.signals import Signals, WalletFunctions, WalletSignals
from bitcoin_safe.wallet import Wallet

if TYPE_CHECKING:
    from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore


@dataclass(frozen=True)
class PluginWalletContext:
    """The wallet a plugin client is attached to. Plain accessors, no permission checks."""

    wallet_id: str
    wallet_functions: WalletFunctions

    @property
    def signals(self) -> Signals:
        return self.wallet_functions.signals

    @property
    def wallet_signals(self) -> WalletSignals | None:
        return self.wallet_functions.wallet_signals.get(self.wallet_id)

    def wallet(self) -> Wallet | None:
        return self.wallet_functions.get_wallets().get(self.wallet_id)

    def labels(self) -> Labels | None:
        wallet = self.wallet()
        return wallet.labels if wallet else None

    def descriptor(self) -> bdk.Descriptor | None:
        wallet = self.wallet()
        return wallet.multipath_descriptor if wallet else None

    def category_core(self) -> CategoryCore | None:
        qt_wallet = self.wallet_functions.get_qt_wallets().get(self.wallet_id)
        return qt_wallet.category_core if qt_wallet else None
