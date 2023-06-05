from PySide2 import QtCore, QtWidgets, QtGui
from ...util import Satoshis


class CustomDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    "A Satoshi Spin Box.  The value stored is in Satoshis."
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(0)  # Set the number of decimal places
        self.setRange(0, 21e6*1e8) # Define range as required

    def textFromValue(self, value):
        return str(Satoshis(value))

    def valueFromText(self, text):
        f = float(text.strip().replace(' ', ''))*1e8
        return f

    def validate(self, text, pos):
        try:
            # Try to convert the text to a float
            self.valueFromText(text)
            # If it succeeds, the text is valid
            return QtGui.QValidator.Acceptable, text, pos
        except ValueError:
            # If it fails, the text is not valid
            return QtGui.QValidator.Invalid, text, pos
