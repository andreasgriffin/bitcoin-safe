from typing import Tuple

import bdkpython as bdk
from PyQt6 import QtGui, QtWidgets

from ...util import Satoshis


class BTCSpinBox(QtWidgets.QDoubleSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(self, network: bdk.Network, parent=None):
        super().__init__(parent)
        self.network = network
        self._is_max = False
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6 * 1e8)  # Define range as required

    def set_max(self, value: bool):
        self.setDisabled(value)
        self._is_max = value
        self.update()

    def value(self) -> int:
        return round(super().value())

    def textFromValue(self, value: int):
        if self._is_max:
            return "Max"
        return str(Satoshis(value, self.network))

    def valueFromText(self, text: str) -> int:
        if self._is_max:
            return 0
        return Satoshis(text, self.network).value

    def validate(self, text: str, pos: int) -> Tuple[QtGui.QValidator.State, str, int]:
        try:
            # Try to convert the text to a float
            self.valueFromText(text)
            # If it succeeds, the text is valid
            return QtGui.QValidator.State.Acceptable, text, pos
        except ValueError:
            # If it fails, the text is not valid
            return QtGui.QValidator.State.Invalid, text, pos
