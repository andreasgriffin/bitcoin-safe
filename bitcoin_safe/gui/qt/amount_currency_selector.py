#
# Bitcoin Safe
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

from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.currency_combobox import CurrencyComboBox, CurrencyGroup, CurrencyGroupFormatting
from bitcoin_safe.gui.qt.currency_converter import CurrencyConverter
from bitcoin_safe.gui.qt.ui_tx.spinbox import BTCSpinBox, FiatSpinBox
from bitcoin_safe.signals import Signals


class BaseAmountCurrencySelector(QWidget):
    """Widget encapsulating BTC/fiat spin boxes that can share an external currency combo."""

    amountChanged = cast(SignalProtocol[[float | int, str]], pyqtSignal(object, str))

    def __init__(
        self,
        network: bdk.Network,
        fx: FX,
        signals: Signals,
        parent: QWidget | None = None,
        auto_fiat_conversions=False,
    ) -> None:
        """Initialize the selector with wallet context and global signals."""
        super().__init__(parent)
        self.fx = fx
        self._current_currency = self.fx.get_currency_iso()
        self._linked_currency_combo: CurrencyComboBox | None = None

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.btc_spin = BTCSpinBox(
            network=network,
            signal_language_switch=signals.language_switch,
            btc_symbol=fx.config.bitcoin_symbol.value,
        )
        self.fiat_spin = FiatSpinBox(
            fx=fx,
            signal_currency_changed=signals.currency_switch,
            signal_language_switch=signals.language_switch,
            fixed_currency=None if auto_fiat_conversions else self._current_currency,
        )
        self._layout.addWidget(self.btc_spin, 1)
        self._layout.addWidget(self.fiat_spin, 1)

        self.btc_spin.valueChanged.connect(self._emit_amount_changed)
        self.fiat_spin.valueChanged.connect(self._emit_amount_changed)

        self._converter = CurrencyConverter(
            btc_spin_box=self.btc_spin,
            fiat_spin_box=self.fiat_spin,
        )

        self.updateUi()

    def link_currency_combo(self, currency_combo: CurrencyComboBox) -> None:
        """Link the selector to an external currency combobox."""
        if self._linked_currency_combo is currency_combo:
            return
        if self._linked_currency_combo is not None:
            try:
                self._linked_currency_combo.currentIndexChanged.disconnect(self._on_currency_changed)
            except TypeError:
                pass

        self._linked_currency_combo = currency_combo
        self._linked_currency_combo.currentIndexChanged.connect(self._on_currency_changed)
        current_currency = self._linked_currency_combo.currentData()
        if isinstance(current_currency, str):
            self._current_currency = FX.sanitize_key(current_currency)
        self.updateUi()

    def current_input_has_focus(self) -> bool:
        """Return whether the currently visible input is focused."""
        current_input = self.btc_spin if not self.btc_spin.isHidden() else self.fiat_spin
        line_edit = current_input.lineEdit()
        return current_input.hasFocus() or (line_edit.hasFocus() if line_edit else False)

    def get_currency(self) -> str:
        currency_combo = self._linked_currency_combo
        if currency_combo is not None:
            current_data = currency_combo.currentData()
            if isinstance(current_data, str):
                return FX.sanitize_key(current_data)
        return self._current_currency

    def amount_and_current_iso(self) -> tuple[int | float, str]:
        """Return the currently selected currency code."""
        unit = self.get_currency()
        if FX.is_btc(unit, network=self.btc_spin.network):
            return self.btc_spin.value(), unit
        return self.fiat_spin.value(), unit

    def set_amount(self, amount: int | float, unit: str) -> None:
        """Programmatically set the selector state."""
        unit = FX.sanitize_key(unit)
        self._set_currency(unit)

        if FX.is_btc(unit, network=self.btc_spin.network):
            sats = int(max(amount, 0))
            self.btc_spin.setValue(sats)
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
        """Handle linked currency changes."""
        self.updateUi()
        self.fiat_spin.setCurrencyCode(self.get_currency())
        self._emit_amount_changed()

    def _set_currency(self, currency: str) -> None:
        self._current_currency = FX.sanitize_key(currency)
        currency_combo = self._linked_currency_combo
        if currency_combo is None:
            return

        index = self._find_index(currency_combo, currency)
        if index >= 0:
            with QSignalBlocker(currency_combo):
                currency_combo.setCurrentIndex(index)

    @staticmethod
    def _find_index(currency_combo: CurrencyComboBox, currency: str | None) -> int:
        """Locate the index of a currency code in the combo box."""
        if not currency:
            return -1
        lookup = currency.lower()
        for index in range(currency_combo.count()):
            data = currency_combo.itemData(index)
            if isinstance(data, str) and data.lower() == lookup:
                return index
        return -1

    def _emit_amount_changed(self) -> None:
        """Emit amount change notifications."""
        amount, currency = self.amount_and_current_iso()
        self.amountChanged.emit(amount, currency)


class AmountCurrencySelector(BaseAmountCurrencySelector):
    """Widget encapsulating BTC/fiat spin boxes with a shared currency selector."""

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
        """Initialize the selector with an embedded currency combo box."""
        super().__init__(
            network=network,
            fx=fx,
            signals=signals,
            parent=parent,
            auto_fiat_conversions=auto_fiat_conversions,
        )

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

        self._layout.setSpacing(8)
        self._layout.addWidget(self.currency_combo, 0)
        self.currency_combo.populate(selected_currency=self._current_currency)
        self.link_currency_combo(self.currency_combo)
        self.updateUi()


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

    from bitcoin_safe.config import UserConfig

    class DemoWindow(QMainWindow):
        def __init__(self) -> None:
            """Simple test harness for the AmountCurrencySelector widget."""
            super().__init__()

            # minimal FX setup with static rates so the demo works offline
            self.config = UserConfig()
            self.config.currency = "USD"
            # Updated 27 January 2026 close-enough spot rates (1 BTC -> fiat)
            self.config.rates = {
                "BTC": {"name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
                "USD": {"name": "US Dollar", "unit": "USD", "value": 88_230.0, "type": "fiat"},
                "EUR": {"name": "Euro", "unit": "EUR", "value": 74_210.0, "type": "fiat"},
                "GBP": {"name": "British Pound Sterling", "unit": "GBP", "value": 64_330.0, "type": "fiat"},
            }

            self.fx = FX(config=self.config, loop_in_thread=None, update_rates=False)
            self.signals = Signals()

            container = QWidget()
            self._layout = QVBoxLayout(container)

            self.auto_checkbox = QCheckBox(self.tr("Auto convert between fiat currencies"))
            self.auto_checkbox.setChecked(True)
            self.auto_checkbox.stateChanged.connect(self._rebuild_selector)
            self._layout.addWidget(self.auto_checkbox)

            self.selector: AmountCurrencySelector | None = None
            self.label = QLabel("Enter an amount or change the currency.")

            # build initial selector
            self.selector = self._rebuild_selector()

            self._layout.addWidget(self.label)
            self._layout.addStretch()

            self.setCentralWidget(container)
            self.setWindowTitle("AmountCurrencySelector Demo")
            self.resize(520, 200)

            # preload demo values
            self.selector.set_amount(50_000, "BTC")

        def on_amount_changed(self, amount: object, currency: str) -> None:
            """Update helper label when the selector changes."""
            fiat_amount = cast(float, amount)
            if FX.is_btc(currency, network=self.config.network):
                btc_amount = int(fiat_amount)
                fiat_value = self.fx.btc_to_fiat(btc_amount, currency=self.config.currency)
                fiat_display = self.fx.fiat_to_str(fiat_value) if fiat_value is not None else "?"
                self.label.setText(f"{btc_amount} sats ({currency}) ≈ {fiat_display}")
            else:
                self.label.setText(f"{fiat_amount:,.2f} {currency}")

        def _rebuild_selector(self) -> AmountCurrencySelector:
            """Recreate the selector when the auto-convert toggle changes."""
            previous_amount: int | float = 50_000
            previous_unit = "BTC"
            if self.selector is not None:
                previous_amount, previous_unit = self.selector.amount_and_current_iso()
                self.selector.setParent(None)
                self.selector.deleteLater()

            self.selector = AmountCurrencySelector(
                network=self.config.network,
                fx=self.fx,
                signals=self.signals,
                auto_fiat_conversions=self.auto_checkbox.isChecked(),
            )
            self.selector.amountChanged.connect(self.on_amount_changed)
            # Ensure selector is first widget under the checkbox
            self._layout.insertWidget(1, self.selector)
            self.selector.set_amount(previous_amount, previous_unit)
            return self.selector

    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())
