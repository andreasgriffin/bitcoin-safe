import logging
logger = logging.getLogger(__name__)

from PySide2.QtWidgets import QTextEdit, QApplication
from PySide2.QtGui import QKeySequence, QKeyEvent
from PySide2.QtCore import Qt, QEvent, Signal


class MyTextEdit(QTextEdit):
    signal_key_press = Signal(str)
    signal_pasted_text = Signal(str)
    
    def __init__(self, parent=None):
        super(MyTextEdit, self).__init__(parent)

    def keyPressEvent(self, e):
        # If it's a regular key press
        if e.type() == QEvent.KeyPress and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.signal_key_press.emit(e.text())
        # If it's a shortcut (like Ctrl+V), let the parent handle it
        else:
            super(MyTextEdit, self).keyPressEvent(e)

    def insertFromMimeData(self, source):
        super(MyTextEdit, self).insertFromMimeData(source)
        self.signal_pasted_text.emit(source.text())
