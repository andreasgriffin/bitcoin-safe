from typing import List
from PySide2.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QTextEdit,
    QShortcut,
    QDialogButtonBox,
    QFileDialog,
)
from PySide2.QtGui import QKeySequence
from PySide2.QtCore import Qt, Signal
from bitcoin_qrreader import bitcoin_qr
import bdkpython as bdk
from .util import CameraInputTextEdit
from PySide2.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QApplication,
    QPushButton,
)
import logging

logger = logging.getLogger(__name__)


def is_binary(file_path):
    """
    Check if a file is binary or text.
    Returns True if binary, False if text.
    """
    try:
        with open(file_path, "r") as f:
            for chunk in iter(lambda: f.read(1024), ""):
                if "\0" in chunk:  # found null byte
                    return True
    except UnicodeDecodeError:
        return True

    return False


def file_to_str(file_path):
    if is_binary(file_path):
        with open(file_path, "rb") as f:
            return bytes(f.read()).hex()
    else:
        with open(file_path, "r") as f:
            return f.read()


class DragAndDropTextEdit(CameraInputTextEdit):
    signal_drop_file = Signal(str)

    def __init__(self, parent=None, callback_enter=None, callback_esc=None):
        super().__init__(parent)
        self.callback_enter = callback_enter
        self.callback_esc = callback_esc

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self.callback_enter:
                self.callback_enter(self.toPlainText())
        elif event.key() == Qt.Key_Escape:
            if self.callback_esc:
                self.callback_esc()
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        s = bitcoin_qr.Data.from_str(
            file_to_str(file_path), bdk.Network.REGTEST
        ).data_as_string()
        self.setText(s)
        self.signal_drop_file.emit(s)


class TransactionDialog(QDialog):
    def __init__(self, title="Open Transaction or PSBT", on_open=None, parent=None):
        super().__init__(parent)
        self.on_open = on_open

        self.setWindowTitle(title)
        layout = QVBoxLayout()

        self.instruction_label = QLabel(
            "Please paste your Bitcoin Transaction or PSBT in here, or drop a file:"
        )
        self.text_edit = DragAndDropTextEdit(
            callback_enter=self.process_input, callback_esc=self.close
        )
        self.text_edit.setPlaceholderText(
            "Paste your Bitcoin Transaction or PSBT in here or drop a file"
        )

        layout.addWidget(self.instruction_label)
        layout.addWidget(self.text_edit)

        self.setLayout(layout)

        # buttons
        self.buttonBox = QDialogButtonBox(self)
        self.cancel_button = self.buttonBox.addButton(QDialogButtonBox.Cancel)
        self.button_file = self.buttonBox.addButton(QDialogButtonBox.Open)
        self.button_ok = self.buttonBox.addButton(QDialogButtonBox.Ok)
        self.button_ok.setDefault(True)

        layout.addWidget(self.buttonBox)

        # connect signals
        self.button_ok.clicked.connect(
            lambda: self.process_input(self.text_edit.toPlainText())
        )
        self.text_edit.signal_drop_file.connect(self.process_input)
        self.cancel_button.clicked.connect(self.close)
        self.button_file.clicked.connect(self.on_open_file_clicked)

        shortcut = QShortcut(QKeySequence("Return"), self)
        shortcut.activated.connect(self.process_input)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def process_input(self, s: str):
        self.close()

        if self.on_open:
            self.on_open(s)

    def on_open_file_clicked(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Transaction/PSBT",
                "",
                "All Files (*);;PSBT (*.psbt);;Transation (*.tx)",
            )
            if not file_path:
                logger.debug("No file selected")
                return

        logger.debug(f"Selected file: {file_path}")
        with open(file_path, "rb") as file:
            string_content = file.read()
            self.process_input(string_content)


class UTXOAddDialog(TransactionDialog):
    def __init__(self, on_open=None, parent=None):
        super().__init__(on_open=on_open, parent=parent)

        self.setWindowTitle("Add Inputs")

        self.button_ok.setText("Load UTXOs")
        self.instruction_label.setText(
            "Please paste UTXO here in the format  txid:outpoint\ntxid:outpoint"
        )
        self.text_edit.setPlaceholderText("Please paste UTXO here")


class DescriptorDialog(TransactionDialog):
    def __init__(self, on_open=None, parent=None):
        super().__init__(on_open=on_open, parent=parent)

        self.setWindowTitle("Import Public Key (xPub)")

        self.button_ok.setText("Load")
        self.instruction_label.setText("Please paste xPub here")
        self.text_edit.setPlaceholderText("Please paste xPub here")


if __name__ == "__main__":
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = TransactionDialog(on_open=print)
    dialog.show()

    sys.exit(app.exec_())
