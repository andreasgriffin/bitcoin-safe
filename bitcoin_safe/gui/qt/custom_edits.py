import logging
from typing import Callable, Dict, List, Optional

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


import bdkpython as bdk
from bitcoin_qrreader.bitcoin_qr import MultipathDescriptor
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent
from PyQt6.QtWidgets import QLineEdit, QTextEdit

from ...pdfrecovery import make_and_open_pdf
from .util import Message, MessageType


class MyTextEdit(QTextEdit):
    def __init__(self, preferred_height=50):
        super().__init__()
        self.preferred_height = preferred_height

    def sizeHint(self):
        size = super().sizeHint()
        size.setHeight(self.preferred_height)
        return size


class DescriptorEdit(ButtonEdit):
    signal_change = pyqtSignal(str)

    def __init__(self, network: bdk.Network, get_wallet: Optional[Callable[[], Wallet]] = None):
        super().__init__(
            input_field=MyTextEdit(preferred_height=50), button_vertical_align=Qt.AlignmentFlag.AlignBottom
        )
        self.network = network

        def do_pdf():
            if not get_wallet:
                Message(
                    "Wallet setup not finished. Please finish before creating a Backup pdf.",
                    type=MessageType.Error,
                )
                return

            make_and_open_pdf(get_wallet())

        from bitcoin_qrreader import bitcoin_qr

        def custom_handle_camera_input(data: bitcoin_qr.Data, parent):
            self.setText(str(data.data_as_string()))
            self.signal_change.emit(str(data.data_as_string()))

        self.add_copy_button()
        self.add_qr_input_from_camera_button(custom_handle_input=custom_handle_camera_input)
        if get_wallet is not None:
            self.add_pdf_buttton(do_pdf)
        self.set_validator(self._check_if_valid)

    def _check_if_valid(self):
        if not self.text():
            return True
        try:
            MultipathDescriptor.from_descriptor_str(self.text(), self.network)
            return True
        except:
            return False

    def keyReleaseEvent(self, e: QKeyEvent):
        # print(e.type(), e.modifiers(),  [key for key in Qt.Key if  key.value == e.key() ] , e.matches(QKeySequence.StandardKey.Paste) )
        # If it's a regular key press
        if e.type() == QEvent.Type.KeyRelease:
            self.signal_change.emit(self.text())
        # If it's another type of shortcut, let the parent handle it
        else:
            super().keyReleaseEvent(e)


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCompleter, QLineEdit


class QCompleterLineEdit(QLineEdit):
    signal_focus_out = pyqtSignal()

    def __init__(self, network: bdk.Network, suggestions: Dict[bdk.Network, List[str]] = None, parent=None):
        super().__init__(parent)
        # Dictionary to store suggestions for each network
        self.suggestions = suggestions if suggestions else {network: [] for network in bdk.Network}
        self.network = network  # Set the initial network
        self._completer = QCompleter(self.suggestions[self.network], self)
        self.setCompleter(self._completer)

    def set_network(self, network):
        """Set the network and update the completer."""
        self.network = network
        if network not in self.suggestions:
            self.suggestions[network] = []
        self._update_completer()

    def reset_memory(self):
        """Clears the memory for the current network."""
        if self.network:
            self.suggestions[self.network].clear()
            self._update_completer()

    def add_current_to_memory(self):
        """Adds the current text to the memory of the current network."""
        current_text = self.text()
        if self.network and current_text and current_text not in self.suggestions[self.network]:
            self.suggestions[self.network].append(current_text)
            self._update_completer()

    def add_to_memory(self, text):
        """Adds a specific string to the memory of the current network."""
        if self.network and text and text not in self.suggestions[self.network]:
            self.suggestions[self.network].append(text)
            self._update_completer()

    def _update_completer(self):
        """Updates the completer with the current network's suggestions
        list."""
        if self.network:
            self._completer.model().setStringList(self.suggestions[self.network])

    def keyPressEvent(self, event: QKeyEvent):
        if self.network and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if not self._completer.popup().isVisible():
                self._completer.complete()
        super(QCompleterLineEdit, self).keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent):
        super().focusOutEvent(event)
        self.signal_focus_out.emit()
