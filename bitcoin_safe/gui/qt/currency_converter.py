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

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QDoubleSpinBox

from ...fx import FX

logger = logging.getLogger(__name__)


class CurrencyConverter(QObject):
    def __init__(
        self,
        fx: FX | None,
        btc_spin_box: QDoubleSpinBox,
        fiat_spin_box: QDoubleSpinBox,
    ):
        """
        fx: your FX instance
        crypto_spin_box: the spinbox showing the crypto amount
        fiat_spin_box: the spinbox showing the fiat amount
        crypto_currency: currency code passed to FX (defaults to "BTC")
        """
        super().__init__()
        self.fx = fx
        self.crypto_spin = btc_spin_box
        self.fiat_spin = fiat_spin_box

        # simple guard so we don't recurse
        self._updating = False

        # connect signals
        self.crypto_spin.valueChanged.connect(self._on_crypto_changed)
        self.fiat_spin.valueChanged.connect(self._on_fiat_changed)

    def _on_crypto_changed(self, value: float):
        if self._updating:
            return
        if not self.fx:
            return
        self._updating = True
        try:
            # convert to fiat
            fiat_val = self.fx.btc_to_fiat(int(value))
            if fiat_val is not None:
                # this will emit fiat_spin.valueChanged,
                # but _on_fiat_changed will early‐return
                self.fiat_spin.setValue(fiat_val)
        finally:
            self._updating = False

    def _on_fiat_changed(self, value: float):
        if self._updating:
            return
        if not self.fx:
            return
        self._updating = True
        try:
            # convert back to crypto (int!)
            crypto_val = self.fx.fiat_to_btc(value)
            if crypto_val is not None:
                # emits crypto_spin.valueChanged,
                # but _on_crypto_changed will early‐return
                self.crypto_spin.setValue(crypto_val)
        finally:
            self._updating = False
