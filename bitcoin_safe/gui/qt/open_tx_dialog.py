from PySide2.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QTextEdit,
    QShortcut,
)
from PySide2.QtGui import QKeySequence
from PySide2.QtCore import Qt, Signal
from bitcoin_qrreader import bitcoin_qr
import bdkpython as bdk
from .util import CameraInputTextEdit


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

    def __init__(self, parent=None):
        super().__init__(parent)

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
    def __init__(self, on_open=None, parent=None):
        super().__init__(parent)

        self.on_open = on_open

        self.setWindowTitle("Open Transaction")
        layout = QVBoxLayout()
        button_layout = QHBoxLayout()

        self.instruction_label = QLabel(
            "Please paste your Bitcoin Transaction or PSBT in here, or drop a file:"
        )
        self.text_edit = DragAndDropTextEdit()
        self.text_edit.setPlaceholderText(
            "Paste your Bitcoin Transaction or PSBT in here or drop a file"
        )

        self.open_button = QPushButton("Open Transaction")
        self.open_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")

        # Space stretching before the open button for right alignment
        button_layout.addStretch(1)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.open_button)

        layout.addWidget(self.instruction_label)
        layout.addWidget(self.text_edit)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.open_button.clicked.connect(
            lambda: self.process_input(self.text_edit.toPlainText())
        )
        self.text_edit.signal_drop_file.connect(self.process_input)
        self.cancel_button.clicked.connect(self.close)

        shortcut = QShortcut(QKeySequence("Return"), self)
        shortcut.activated.connect(self.process_input)

    def process_input(self, s: str):
        self.close()
        if self.on_open:
            self.on_open(s)


if __name__ == "__main__":
    import sys
    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = TransactionDialog(on_open=print)
    dialog.show()

    sys.exit(app.exec_())
