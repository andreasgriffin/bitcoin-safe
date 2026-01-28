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
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6 import QtGui
from PyQt6.QtCore import QLocale, QSignalBlocker, Qt, pyqtBoundSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QWidget,
)

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.analyzers import AmountAnalyzer
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState


class LabelStyleReadOnlQDoubleSpinBox(QDoubleSpinBox):
    def get_style_sheet(self, ro: bool) -> str:
        """Get style sheet."""
        self.setObjectName(f"{id(self)}")

        if ro:
            # transparent background + no borders/outlines
            return f"""
                #{self.objectName()} {{
                    background: transparent;
                    border: none;
                    outline: none;
                }}
                #{self.objectName()}:focus {{
                    background: transparent;
                    border: none;
                    outline: none;
                }}
                /* ensure the embedded line‑edit is also transparent */
                #{self.objectName()} {{
                    background: transparent;
                }}
            """
        else:
            # restore default look
            return f"""
                #{self.objectName()} {{ 
                }} 
            """

    def setReadOnly(self, r: bool):
        # first, tell the base class about it
        """SetReadOnly."""
        super().setReadOnly(r)  # <<-- this flips the widget’s readOnly flag
        # then your other adjustments:
        super().setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons if r else QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )
        super().setFrame(not r)
        super().setFocusPolicy(Qt.FocusPolicy.NoFocus if r else Qt.FocusPolicy.StrongFocus)

        if lineedit := self.lineEdit():
            lineedit.setReadOnly(r)

        self.setStyleSheet(self.get_style_sheet(r))


class AnalyzerSpinBox(LabelStyleReadOnlQDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._smart_state: AmountAnalyzer | None = None
        self.valueChanged.connect(self.format_and_apply_validator)
        self.setObjectName(f"{id(self)}")

    def setAnalyzer(self, smart_state: AmountAnalyzer):
        """Set a custom validator."""
        self._smart_state = smart_state

    def analyzer(self) -> AmountAnalyzer | None:
        """Analyzer."""
        return self._smart_state

    def format_as_error(self, value: bool) -> None:
        """Format as error."""
        if value:
            self.setStyleSheet(f"#{self.objectName()} {{ background-color: #ff6c54; }}")
        else:
            self.setStyleSheet(self.get_style_sheet(self.isReadOnly()))

    def format_and_apply_validator(self) -> None:
        """Format and apply validator."""
        analyzer = self.analyzer()
        if not analyzer:
            self.format_as_error(False)
            return

        analysis = analyzer.analyze(self.value())
        error = bool(self.text()) and (analysis.state != AnalyzerState.Valid)
        self.format_as_error(error)
        self.setToolTip(analysis.msg if error else "")


class FiatSpinBox(LabelStyleReadOnlQDoubleSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(
        self,
        fx: FX | None,
        signal_currency_changed: SignalProtocol[[]] | pyqtBoundSignal,
        signal_language_switch: SignalProtocol[[]] | pyqtBoundSignal,
        include_currrency_symbol=False,
        fixed_currency: None | str = None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)

        self.fx = fx
        self.include_currrency_symbol = include_currrency_symbol
        self._btc_amount: int = 0
        self._is_max = False
        self.fixed_currency = fixed_currency
        self._currency_code: str | None = fixed_currency

        # simple guard so we don't recurse
        self._prevent_update_btc_amount = False

        self.setDecimals(2)  # Set the number of decimal places
        self.setRange(0, 1e12)
        self.update_currency()
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # signals
        signal_currency_changed.connect(self.update_currency)
        signal_language_switch.connect(self.update_currency)
        self.valueChanged.connect(self._set_btc_from_fiat)

    def setCurrencyCode(self, currency_code: str | None) -> None:
        """SetCurrencyCode."""
        normalized = currency_code.upper() if currency_code else None
        if normalized == self._currency_code:
            return
        self._currency_code = normalized
        self.update_currency()

    def get_currency_code(self) -> str | None:
        """Get currency code."""
        if self._currency_code:
            return self._currency_code
        if self.fx:
            return self.fx.config.currency.upper()
        return None

    def get_code_symbol_locale(self, fx: FX):
        currency_code = self.get_currency_code() or fx.get_currency_iso()
        currency_symbol = fx.get_currency_symbol_from_iso(currency_code)
        locale = fx.get_currency_locale(currency_code) or fx.get_locale()

        return currency_code, currency_symbol, locale

    def update_currency(self):
        """Update currency."""
        if not self.fx or self.fixed_currency:
            return

        currency_code, currency_symbol, locale = self.get_code_symbol_locale(self.fx)

        self.setLocale(locale)

        # clear any old prefix/suffix
        self.setPrefix("")
        self.setSuffix("")

        if self.include_currrency_symbol:
            sample = locale.toCurrencyString(1.23)
            if sample.startswith(currency_symbol):
                self.setPrefix(currency_symbol + " ")
            else:
                self.setSuffix(" " + currency_symbol)

        new_fiat_value = self.fx.btc_to_fiat(self.btc_value(), currency=currency_code)
        if new_fiat_value is not None:
            with QSignalBlocker(self):
                # do not set the btc value new, as it should be unchanged
                super().setValue(new_fiat_value)

    def set_max(self, value: bool) -> None:
        """Set max."""
        if value == self._is_max:
            return
        self.setDisabled(value)
        self._is_max = value
        self.setValue(super().value())

    def btc_value(self) -> int:
        """Btc value."""
        return self._btc_amount

    def validate(self, input: str | None, pos: int) -> tuple[QtGui.QValidator.State, str, int]:
        if not input:
            input = "0"
        if not self.fx:
            return QtGui.QValidator.State.Intermediate, input or "", pos

        currency_code, currency_symbol, locale = self.get_code_symbol_locale(self.fx)

        value = self.fx.parse_fiat_custom(formatted=input, currency_symbol=currency_symbol)
        if value is None:
            return QtGui.QValidator.State.Intermediate, input or "", pos
        return QtGui.QValidator.State.Acceptable, input or "", pos

    def fiat_value(self) -> float | None:
        """Fiat value."""
        if not self.fx:
            return None
        return self.fx.btc_to_fiat(self.btc_value(), currency=self.get_currency_code())

    def setBtcValue(self, btc_amount: int) -> None:
        """SetBtcValue."""
        self._btc_amount = btc_amount
        if (
            self.fx
            and (fiat_value := self.fx.btc_to_fiat(btc_amount, currency=self.get_currency_code())) is not None
        ):
            self._prevent_update_btc_amount = True
            try:
                self.setValue(fiat_value)
            finally:
                self._prevent_update_btc_amount = False

    def _set_btc_from_fiat(self, val: float):
        """Set btc from fiat."""
        if not self._prevent_update_btc_amount and self.fx:
            self._btc_amount = self.fx.fiat_to_btc(val, currency=self.get_currency_code()) or 0

    def value(self) -> float:
        """Value."""
        return super().value()

    def textFromValue(self, fiat_value: float) -> str:  # type: ignore[override]
        """TextFromValue."""
        if not self.fx:
            return ""

        currency_code, currency_symbol, locale = self.get_code_symbol_locale(self.fx)

        fiat_str = self.fx.fiat_to_str_custom(
            fiat_value, use_currency_symbol=False, currency_symbol=currency_symbol
        )
        if self._is_max:
            return self.tr("Max ≈ {amount}").format(amount=fiat_str)
        return fiat_str

    def valueFromText(self, text: str | None) -> float:
        """ValueFromText."""
        if self._is_max:
            return 0
        if not self.fx:
            return 0
        currency_code, currency_symbol, locale = self.get_code_symbol_locale(self.fx)

        value = self.fx.parse_fiat_custom(formatted=text if text else "0", currency_symbol=currency_symbol)
        if value is None:
            raise ValueError()
        return value


class BTCSpinBox(AnalyzerSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(
        self, network: bdk.Network, signal_language_switch: SignalProtocol[[]], btc_symbol: str, parent=None
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.network = network
        self.btc_symbol = btc_symbol
        self._is_max = False
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6 * 1e8)  # Define range as required
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        signal_language_switch.connect(self.on_language_switch)

    def on_language_switch(self):
        """On language switch."""
        self.setValue(self.value())

    def setValue(self, val: float) -> None:
        """SetValue."""
        super().setValue(val)
        self.format_and_apply_validator()

    def set_max(self, value: bool) -> None:
        """Set max."""
        self.setDisabled(value)
        self._is_max = value
        self.setValue(super().value())

    def value(self) -> int:
        """Value."""
        return round(super().value())

    def textFromValue(self, value: int) -> str:  # type: ignore[override]
        """TextFromValue."""
        if self._is_max:
            return self.tr("Max ≈ {amount}").format(amount=str(Satoshis(value, self.network)))
        return str(Satoshis(value, self.network))

    def valueFromText(self, text: str | None) -> int:
        """ValueFromText."""
        if self._is_max:
            return 0
        return Satoshis.from_btc_str(text if text else "0", self.network, btc_symbol=self.btc_symbol).value

    def validate(self, input: str | None, pos: int) -> tuple[QtGui.QValidator.State, str, int]:
        """Validate."""
        if input is None:
            input = ""
        try:
            # Try to convert the text to a float
            self.valueFromText(input)
            # If it succeeds, the text is valid
            return QtGui.QValidator.State.Acceptable, input, pos
        except ValueError:
            # If it fails, the text is not valid
            return QtGui.QValidator.State.Invalid, input, pos

    def set_warning_maximum(self, value: int) -> None:
        """Set warning maximum."""
        if not self._smart_state:
            return
        self._smart_state.max_amount = value
        self.format_and_apply_validator()


class FeerateSpinBox(LabelStyleReadOnlQDoubleSpinBox):
    def __init__(
        self,
        signal_currency_changed: SignalProtocol[[]] | pyqtBoundSignal,
        signal_language_switch: SignalProtocol[[]] | pyqtBoundSignal,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setSingleStep(1)
        self.setLocale(QLocale())

        # signals
        signal_currency_changed.connect(self.on_language_switch)
        signal_language_switch.connect(self.on_language_switch)

    def on_language_switch(self):
        """On language switch."""
        self.setLocale(QLocale())
        self.setValue(self.value())


if __name__ == "__main__":
    import sys

    config = UserConfig()
    fx = FX(config=config, loop_in_thread=None)

    app = QApplication(sys.argv)
    window = QWidget()
    layout = QFormLayout(window)

    # — your spin‑boxes —
    btc_spin = BTCSpinBox(
        network=bdk.Network.REGTEST, signal_language_switch=fx.signal_data_updated, btc_symbol="BTC"
    )
    fiat_spin = FiatSpinBox(
        fx=fx,
        signal_currency_changed=fx.signal_data_updated,
        signal_language_switch=fx.signal_data_updated,
        include_currrency_symbol=True,
    )
    btc_symbol = config.bitcoin_symbol.value

    # — locale selector —
    locale_combo = QComboBox()
    locales = [
        QLocale(QLocale.Language.English, QLocale.Country.UnitedStates),
        QLocale(QLocale.Language.German, QLocale.Country.Germany),
        QLocale(QLocale.Language.French, QLocale.Country.France),
        QLocale(QLocale.Language.Japanese, QLocale.Country.Japan),
    ]
    for loc in locales:
        locale_combo.addItem(f"{loc.nativeLanguageName()} ({loc.name()})", loc)

    def switch_locale(idx):
        """Switch locale."""
        loc = locale_combo.itemData(idx)
        QLocale.setDefault(loc)

        # let FX rebuild its locale/symbol internally
        fx.signal_data_updated.emit()
        # force the widget to re‑format with the new currency
        fiat_spin.setValue(fiat_spin.value())
        btc_spin.setValue(btc_spin.value())

    locale_combo.currentIndexChanged.connect(switch_locale)
    switch_locale(locale_combo.currentIndex())

    # — currency selector —
    currency_combo = QComboBox()
    # list whatever ISO codes you want to test:
    for code in ("USD", "EUR", "GBP", "JPY"):
        currency_combo.addItem(code, code)

    def switch_currency(idx):
        """Switch currency."""
        new_code = currency_combo.itemData(idx)
        config.currency = new_code
        # let FX rebuild its locale/symbol internally
        fx.signal_data_updated.emit()
        # force the widget to re‑format with the new currency
        fiat_spin.setValue(fiat_spin.value())

    currency_combo.currentIndexChanged.connect(switch_currency)
    # set initial to match config.currency if present
    try:
        i = currency_combo.findData(config.currency.upper())
        currency_combo.setCurrentIndex(i)
    except Exception:
        currency_combo.setCurrentIndex(0)  # fallback

    # — assemble form —
    layout.addRow("Locale:", locale_combo)
    layout.addRow("Currency:", currency_combo)
    layout.addRow(f"{btc_symbol} Amount:", btc_spin)
    layout.addRow("Fiat Amount:", fiat_spin)

    window.setWindowTitle(f"{btc_symbol} / Fiat SpinBox Tester")
    window.show()
    sys.exit(app.exec())
