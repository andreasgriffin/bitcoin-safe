import bdkpython as bdk
from PySide2 import QtGui, QtWidgets

from ...util import Satoshis


class BTCSpinBox(QtWidgets.QDoubleSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."

    def __init__(self, network: bdk.Network, parent=None):
        super().__init__(parent)
        self.network = network
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6 * 1e8)  # Define range as required

    def textFromValue(self, value):
        return str(Satoshis(value, self.network))

    def valueFromText(self, text):
        return Satoshis(text, self.network).value

    def validate(self, text, pos):
        try:
            # Try to convert the text to a float
            self.valueFromText(text)
            # If it succeeds, the text is valid
            return QtGui.QValidator.Acceptable, text, pos
        except ValueError:
            # If it fails, the text is not valid
            return QtGui.QValidator.Invalid, text, pos
