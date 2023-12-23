import logging

import mnemonic

logger = logging.getLogger(__name__)

from PySide2.QtWidgets import QTextEdit, QApplication
from PySide2.QtGui import QKeySequence, QKeyEvent
from PySide2.QtCore import Qt, QEvent, Signal
from .util import ButtonsTextEdit
from ...pdfrecovery import BitcoinWalletRecoveryPDF, make_and_open_pdf
from ...wallet import Wallet
import os
from pathlib import Path
from .util import Message


class DescriptorEdit(ButtonsTextEdit):
    signal_key_press = Signal(str)
    signal_pasted_text = Signal(str)

    def __init__(self, get_wallet=None):
        super().__init__()

        def do_pdf():
            if not get_wallet:
                Message(
                    "Wallet setup not finished. Please finish before creating a Backup pdf."
                ).show_error()
                return

            make_and_open_pdf(get_wallet())

        from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui

        def custom_handle_camera_input(data: bitcoin_qr.Data, parent):
            self.setText(str(data.data_as_string()))
            self.signal_pasted_text.emit(str(data.data_as_string()))

        self.addCopyButton()
        self.add_qr_input_from_camera_button(
            custom_handle_input=custom_handle_camera_input
        )
        if get_wallet() is not None:
            self.addPdfButton(do_pdf)

    def keyPressEvent(self, e):
        # If it's a regular key press
        if e.type() == QEvent.KeyPress and not e.modifiers() & (
            Qt.ControlModifier | Qt.AltModifier
        ):
            self.signal_key_press.emit(e.text())
        # If it's a shortcut (like Ctrl+V), let the parent handle it
        else:
            super().keyPressEvent(e)

    def insertFromMimeData(self, source):
        super().insertFromMimeData(source)
        self.signal_pasted_text.emit(source.text())
