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

from PyQt6.QtCore import QObject

from bitcoin_safe.gui.qt.ui_tx.spinbox import BTCSpinBox, FiatSpinBox

logger = logging.getLogger(__name__)


class CurrencyConverter(QObject):
    def __init__(
        self,
        btc_spin_box: BTCSpinBox,
        fiat_spin_box: FiatSpinBox,
    ):
        """
        crypto_spin_box: the spinbox showing the crypto amount
        fiat_spin_box: the spinbox showing the fiat amount
        crypto_currency: currency code passed to FX (defaults to "BTC")
        """
        super().__init__()
        self.crypto_spin = btc_spin_box
        self.fiat_spin = fiat_spin_box

        # simple guard so we don't recurse
        self._updating = False

        # connect signals
        self.crypto_spin.valueChanged.connect(self._on_bitcoin_changed)
        self.fiat_spin.valueChanged.connect(self._on_fiat_changed)

    def _target_currency(self) -> str | None:
        return self.fiat_spin.get_currency_code()

    def _on_bitcoin_changed(self, value: float):
        """On bitcoin changed."""
        if self._updating:
            return
        self._updating = True
        self.fiat_spin.setBtcValue(int(value))
        self._updating = False

    def _on_fiat_changed(self, value: float):
        """On fiat changed."""
        if self._updating:
            return
        self._updating = True
        self.crypto_spin.setValue(self.fiat_spin.btc_value())
        self._updating = False
