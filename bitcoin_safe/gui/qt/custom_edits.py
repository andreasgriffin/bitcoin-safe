import logging

import mnemonic

logger = logging.getLogger(__name__)

from PySide2.QtWidgets import QTextEdit, QApplication
from PySide2.QtGui import QKeySequence, QKeyEvent
from PySide2.QtCore import Qt, QEvent, Signal
from .util import ButtonsTextEdit
from ...pdfrecovery import BitcoinWalletRecoveryPDF
from ...wallet import Wallet
import os
from pathlib import Path
from ...descriptors import combined_wallet_descriptor
from .util import Message
from ...descriptors import public_descriptor_info


class DescriptorEdit(ButtonsTextEdit):
    signal_key_press = Signal(str)
    signal_pasted_text = Signal(str)

    def __init__(self, get_wallet=None):
        super().__init__()
        pdf_recovery = BitcoinWalletRecoveryPDF()

        def make_and_open_pdf():
            if not get_wallet:
                Message(
                    "Wallet setup not finished. Please finish before creating a Backup pdf."
                ).show_error()
                return

            wallet: Wallet = get_wallet()
            info = public_descriptor_info(
                wallet.public_descriptor_string_combined(), wallet.network
            )
            for i, keystore in enumerate(wallet.keystores):
                title = (
                    f"Backup of Seed {i+1} of a  ({info['threshold']} of {len(wallet.keystores)}) Multi-Sig Wallet: {wallet.id}"
                    if len(wallet.keystores) > 1
                    else f"{wallet.id }"
                )
                pdf_recovery.create_pdf(
                    title,
                    wallet.public_descriptor_string_combined(),
                    [keystore.description for keystore in wallet.keystores],
                    seed=keystore.mnemonic.as_string() if keystore.mnemonic else None,
                )
                temp_file = os.path.join(Path.home(), f"{title}.pdf")
                pdf_recovery.save_pdf(temp_file)
                pdf_recovery.open_pdf(temp_file)

        self.addCopyButton()
        if get_wallet() is not None:
            self.addPdfButton(make_and_open_pdf)

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
