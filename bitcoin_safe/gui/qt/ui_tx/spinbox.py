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

from typing import Optional, Tuple

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
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
from bitcoin_safe.typestubs import TypedPyQtSignalNo


class LabelStyleReadOnlQDoubleSpinBox(QDoubleSpinBox):

    def get_style_sheet(self, ro: bool) -> str:
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
            return ""

    def setReadOnly(self, r: bool):
        # first, tell the base class about it
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
        super().__init__(parent)
        self._smart_state: Optional[AmountAnalyzer] = None
        self.valueChanged.connect(self.format_and_apply_validator)
        self.setObjectName(f"{id(self)}")

    def setAnalyzer(self, smart_state: AmountAnalyzer):
        """Set a custom validator."""
        self._smart_state = smart_state

    def analyzer(self) -> Optional[AmountAnalyzer]:
        return self._smart_state

    def format_as_error(self, value: bool) -> None:
        if value:
            self.setStyleSheet(f"#{self.objectName()} {{ background-color: #ff6c54; }}")
        else:
            self.setStyleSheet(self.get_style_sheet(self.isReadOnly()))

    def format_and_apply_validator(self) -> None:
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
        signal_currency_changed: TypedPyQtSignalNo | pyqtBoundSignal,
        signal_language_switch: TypedPyQtSignalNo | pyqtBoundSignal,
        include_currrency_symbol=False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.fx = fx
        self.include_currrency_symbol = include_currrency_symbol
        self._btc_amount: int = 0
        self._is_max = False
        self.setDecimals(2)  # Set the number of decimal places
        self.setRange(0, 1e12)
        self.set_currency()
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # signals
        signal_currency_changed.connect(self.set_currency)
        signal_language_switch.connect(self.set_currency)

    def set_currency(self):
        if not self.fx:
            return

        # use Qt's default locale for symbol/format
        locale = self.fx.get_locale()
        currency_symbol = self.fx.get_currency_symbol()
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

        new_fiat_value = self.fx.btc_to_fiat(self.btc_value())
        if new_fiat_value is not None:
            with QSignalBlocker(self):
                # do not set the btc value new, as it should be unchanged
                super().setValue(new_fiat_value)

    def set_max(self, value: bool) -> None:
        if value == self._is_max:
            return
        self.setDisabled(value)
        self._is_max = value
        self.setValue(super().value())

    def btc_value(self) -> int:
        return self._btc_amount

    def setBtcValue(self, btc_amount: int) -> None:
        self._btc_amount = btc_amount
        if self.fx and (fiat_value := self.fx.btc_to_fiat(btc_amount)) is not None:
            self.setValue(fiat_value)

    def _set_btc_from_fiat(self, val: float):
        if self.fx:
            self._btc_amount = self.fx.fiat_to_btc(val) or 0

    def setValue(self, val: float) -> None:
        self._set_btc_from_fiat(val)
        super().setValue(val)

    def value(self) -> int:
        return round(super().value())

    def textFromValue(self, fiat_value: float) -> str:  # type: ignore[override]
        if not self.fx:
            return ""
        fiat_str = self.fx.fiat_to_str(fiat_value, use_currency_symbol=False)
        if self._is_max:
            return self.tr("Max ≈ {amount}").format(amount=fiat_str)
        return fiat_str

    def valueFromText(self, text: str | None) -> float:
        if self._is_max:
            return 0
        if not self.fx:
            return 0
        value = self.fx.parse_fiat(text if text else "0")
        if value is None:
            raise ValueError()
        return value


class BTCSpinBox(AnalyzerSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(self, network: bdk.Network, signal_language_switch: TypedPyQtSignalNo, parent=None) -> None:
        super().__init__(parent)
        self.network = network
        self._is_max = False
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6 * 1e8)  # Define range as required
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        signal_language_switch.connect(self.on_language_switch)

    def on_language_switch(self):
        self.setValue(self.value())

    def setValue(self, val: float) -> None:
        super().setValue(val)
        self.format_and_apply_validator()

    def set_max(self, value: bool) -> None:
        self.setDisabled(value)
        self._is_max = value
        self.setValue(super().value())

    def value(self) -> int:
        return round(super().value())

    def textFromValue(self, value: int) -> str:  # type: ignore[override]
        if self._is_max:
            return self.tr("Max ≈ {amount}").format(amount=str(Satoshis(value, self.network)))
        return str(Satoshis(value, self.network))

    def valueFromText(self, text: str | None) -> int:
        if self._is_max:
            return 0
        return Satoshis.from_btc_str(text if text else "0", self.network).value

    def validate(self, input: str | None, pos: int) -> Tuple[QtGui.QValidator.State, str, int]:
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
        if not self._smart_state:
            return
        self._smart_state.max_amount = value
        self.format_and_apply_validator()


class FeerateSpinBox(LabelStyleReadOnlQDoubleSpinBox):
    def __init__(
        self,
        signal_currency_changed: TypedPyQtSignalNo | pyqtBoundSignal,
        signal_language_switch: TypedPyQtSignalNo | pyqtBoundSignal,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setSingleStep(1)
        self.setLocale(QLocale())

        # signals
        signal_currency_changed.connect(self.on_language_switch)
        signal_language_switch.connect(self.on_language_switch)

    def on_language_switch(self):
        self.setLocale(QLocale())
        self.setValue(self.value())


if __name__ == "__main__":
    import sys

    config = UserConfig()
    fx = FX(config=config)

    app = QApplication(sys.argv)
    window = QWidget()
    layout = QFormLayout(window)

    # — your spin‑boxes —
    btc_spin = BTCSpinBox(network=bdk.Network.REGTEST, signal_language_switch=fx.signal_data_updated)
    fiat_spin = FiatSpinBox(
        fx=fx,
        signal_currency_changed=fx.signal_data_updated,
        signal_language_switch=fx.signal_data_updated,
        include_currrency_symbol=True,
    )

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
    layout.addRow("BTC Amount:", btc_spin)
    layout.addRow("Fiat Amount:", fiat_spin)

    window.setWindowTitle("BTC / Fiat SpinBox Tester")
    window.show()
    sys.exit(app.exec())
