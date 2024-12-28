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
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.analyzers import AmountAnalyzer
from bitcoin_safe.gui.qt.custom_edits import AnalyzerState

from ...util import Satoshis


class AnalyzerSpinBox(QtWidgets.QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._smart_state: Optional[AmountAnalyzer] = None
        self.valueChanged.connect(self.format_and_apply_validator)

    def setAnalyzer(self, smart_state: AmountAnalyzer):
        """Set a custom validator."""
        self._smart_state = smart_state

    def analyzer(self) -> Optional[AmountAnalyzer]:
        return self._smart_state

    def format_as_error(self, value: bool) -> None:
        if value:
            self.setStyleSheet(f"{self.__class__.__name__}" + " { background-color: #ff6c54; }")
        else:
            self.setStyleSheet("")

    def format_and_apply_validator(self) -> None:
        analyzer = self.analyzer()
        if not analyzer:
            self.format_as_error(False)
            return

        analysis = analyzer.analyze(self.value())
        error = bool(self.text()) and (analysis.state != AnalyzerState.Valid)
        self.format_as_error(error)
        self.setToolTip(analysis.msg if error else "")


class BTCSpinBox(AnalyzerSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(self, network: bdk.Network, parent=None) -> None:
        super().__init__(parent)
        self.network = network
        self._is_max = False
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6 * 1e8)  # Define range as required

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
        return Satoshis(text if text else 0, self.network).value

    def validate(self, text: str | None, pos: int) -> Tuple[QtGui.QValidator.State, str, int]:
        if text is None:
            text = ""
        try:
            # Try to convert the text to a float
            self.valueFromText(text)
            # If it succeeds, the text is valid
            return QtGui.QValidator.State.Acceptable, text, pos
        except ValueError:
            # If it fails, the text is not valid
            return QtGui.QValidator.State.Invalid, text, pos

    def set_warning_maximum(self, value: int) -> None:
        if not self._smart_state:
            return
        self._smart_state.max_amount = value
        self.format_and_apply_validator()
