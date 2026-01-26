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

import bdkpython as bdk
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.currency_combobox import CurrencyComboBox, CurrencyGroup, CurrencyGroupFormatting
from bitcoin_safe.gui.qt.currency_converter import CurrencyConverter
from bitcoin_safe.gui.qt.ui_tx.spinbox import BTCSpinBox, FiatSpinBox
from bitcoin_safe.signals import Signals


class AmountCurrencySelector(QWidget):
    """Widget encapsulating BTC/fiat spin boxes with a shared currency selector."""

    amountChanged = pyqtSignal(object, str)

    def __init__(
        self,
        network: bdk.Network,
        fx: FX,
        signals: Signals,
        parent: QWidget | None = None,
        groups: list[CurrencyGroup] | None = None,
        formatting: CurrencyGroupFormatting = CurrencyGroupFormatting.Short,
        auto_fiat_conversions=False,
    ) -> None:
        """Initialize the selector with wallet context and global signals."""
        super().__init__(parent)
        self.fx = fx

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        selected_currency = self.fx.get_currency_iso()

        self.btc_spin = BTCSpinBox(network=network, signal_language_switch=signals.language_switch)
        self.fiat_spin = FiatSpinBox(
            fx=fx,
            signal_currency_changed=signals.currency_switch,
            signal_language_switch=signals.language_switch,
            fixed_currency=None if auto_fiat_conversions else selected_currency,
        )
        self._layout.addWidget(self.btc_spin, 1)
        self._layout.addWidget(self.fiat_spin, 1)

        self.currency_combo = CurrencyComboBox(
            self.fx,
            groups=groups
            if groups is not None
            else [
                CurrencyGroup.TOP_FIAT,
                CurrencyGroup.BTC_ONLY,
                CurrencyGroup.BITCOIN_OTHER,
                CurrencyGroup.FIAT,
                CurrencyGroup.Commodity,
            ],
            formatting=formatting,
        )

        self._layout.addWidget(self.currency_combo, 0)

        self._converter = CurrencyConverter(
            btc_spin_box=self.btc_spin,
            fiat_spin_box=self.fiat_spin,
        )

        self.currency_combo.populate(selected_currency=selected_currency)
        self.currency_combo.currentIndexChanged.connect(self._on_currency_changed)

        self.btc_spin.valueChanged.connect(self._emit_amount_changed)
        self.fiat_spin.valueChanged.connect(self._emit_amount_changed)
        self.currency_combo.currentIndexChanged.connect(self._emit_amount_changed)

        self.updateUi()

    def get_currency(self) -> str:
        return self.currency_combo.currentData()

    def amount_and_current_iso(self) -> tuple[int | float, str]:
        """Return the currently selected currency code."""
        unit = self.get_currency()
        if FX.is_btc(unit, network=self.btc_spin.network):
            return self.btc_spin.value(), unit
        return self.fiat_spin.value(), unit

    def set_amount(self, amount: int | float, unit: str) -> None:
        """Programmatically set the selector state."""
        unit = FX.sanitize_key(unit)

        self.currency_combo.populate(selected_currency=unit.lower())
        index = self._find_index(unit)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)

        if FX.is_btc(unit, network=self.btc_spin.network):
            sats = int(max(amount, 0))
            self.btc_spin.setValue(sats)
            if self.fx:
                self.fiat_spin.setCurrencyCode(self.fx.get_currency_iso())
                self.fiat_spin.setBtcValue(sats)
        else:
            target_value = max(float(amount), 0.0)
            self.fiat_spin.setCurrencyCode(unit)
            self.fiat_spin.setValue(target_value)
            self.btc_spin.setValue(self.fiat_spin.btc_value())

        self.updateUi()
        self._emit_amount_changed()

    def reset(self) -> None:
        """Reset the selector to its default amount and unit."""
        self.set_amount(0, "BTC")

    def updateUi(self) -> None:  # type: ignore[override]
        """Refresh translated content after a language switch."""

        _, unit = self.amount_and_current_iso()
        is_btc = FX.is_btc(unit, network=self.btc_spin.network)
        self.btc_spin.setHidden(not is_btc)
        self.fiat_spin.setHidden(is_btc)

        self.fiat_spin.setCurrencyCode(unit)

    def _on_currency_changed(self, _: int) -> None:
        """Handle currency combo changes."""

        self.updateUi()
        self.fiat_spin.setCurrencyCode(self.get_currency())
        self._emit_amount_changed()

    def _find_index(self, currency: str | None) -> int:
        """Locate the index of a currency code in the combo box."""
        if not currency:
            return -1
        lookup = currency.lower()
        for index in range(self.currency_combo.count()):
            data = self.currency_combo.itemData(index)
            if isinstance(data, str) and data.lower() == lookup:
                return index
        return -1

    def _emit_amount_changed(self) -> None:
        """Emit amount change notifications."""

        amount, currency = self.amount_and_current_iso()
        self.amountChanged.emit(amount, currency)
