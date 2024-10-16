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


import logging
from typing import Callable, Optional

import bdkpython as bdk
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit
from bitcoin_safe.i18n import translate

logger = logging.getLogger(__name__)


def is_binary(file_path) -> bool:
    """Check if a file is binary or text.

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


def file_to_str(file_path) -> str:
    if is_binary(file_path):
        with open(file_path, "rb") as f:
            return bytes(f.read()).hex()
    else:
        with open(file_path, "r") as f:
            return f.read()


class DragAndDropTextEdit(AnalyzerTextEdit):
    def __init__(
        self,
        parent=None,
        callback_enter=None,
        callback_esc=None,
        process_filepath: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(parent=parent)
        self.process_filepath = process_filepath
        self.callback_enter = callback_enter
        self.callback_esc = callback_esc

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if not event:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            if self.callback_enter:
                self.callback_enter(self.toPlainText())
        elif event.key() == Qt.Key.Key_Escape:
            if self.callback_esc:
                self.callback_esc()
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent | None) -> None:
        if not event:
            super().dragEnterEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data and mime_data.hasUrls():
            event.accept()
        else:
            event.ignore()

        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent | None) -> None:
        if not event:
            super().dropEvent(event)
            return

        mime_data = event.mimeData()
        if mime_data:
            file_path = mime_data.urls()[0].toLocalFile()
            if self.process_filepath:
                self.process_filepath(file_path)

        super().dropEvent(event)


class DragAndDropButtonEdit(ButtonEdit):
    signal_drop_file = pyqtSignal(str)

    def __init__(
        self,
        network: bdk.Network,
        parent=None,
        callback_enter=None,
        callback_esc=None,
        file_filter=translate("DragAndDropButtonEdit", "All Files (*);;PSBT (*.psbt);;Transation (*.tx)"),
    ) -> None:
        super().__init__(
            parent=parent,
            input_field=DragAndDropTextEdit(
                parent=parent,
                callback_enter=callback_enter,
                callback_esc=callback_esc,
                process_filepath=self.process_filepath,
            ),
        )
        self.network = network

        self.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.button_open_file = self.add_open_file_button(self.process_filepath, filter=file_filter)

    def process_filepath(self, file_path: str) -> None:
        s = file_to_str(file_path)
        self.setText(s)
        self.signal_drop_file.emit(s)


class ImportDialog(QDialog):
    def __init__(
        self,
        network: bdk.Network,
        window_title="Open Transaction or PSBT",
        on_open=None,
        parent=None,
        text_button_ok="OK",
        text_instruction_label="Please paste your Bitcoin Transaction or PSBT in here, or drop a file",
        instruction_widget: Optional[QWidget] = None,
        text_placeholder="Paste your Bitcoin Transaction or PSBT in here or drop a file",
    ) -> None:
        super().__init__(parent)
        self.on_open = on_open

        self.setWindowTitle(window_title)
        layout = QVBoxLayout()

        self.instruction_label = QLabel(text_instruction_label)
        self.text_edit = DragAndDropButtonEdit(
            network=network,
            callback_enter=self.process_input,
            callback_esc=self.close,
        )
        self.text_edit.setPlaceholderText(text_placeholder)

        if instruction_widget:
            layout.addWidget(instruction_widget)
        layout.addWidget(self.instruction_label)
        layout.addWidget(self.text_edit)

        self.setLayout(layout)

        # buttons
        self.buttonBox = QDialogButtonBox(self)
        self.cancel_button = self.buttonBox.addButton(QDialogButtonBox.StandardButton.Cancel)
        if self.cancel_button:
            self.cancel_button.clicked.connect(self.close)
        # self.button_file = self.buttonBox.addButton(QDialogButtonBox.Open)
        self.button_ok = self.buttonBox.addButton(QDialogButtonBox.StandardButton.Ok)
        if self.button_ok:
            self.button_ok.setDefault(True)
            self.button_ok.setText(text_button_ok)
            self.button_ok.clicked.connect(lambda: self.process_input(self.text_edit.text()))

        layout.addWidget(self.buttonBox)

        # connect signals
        self.text_edit.signal_drop_file.connect(self.process_input)

        shortcut = QShortcut(QKeySequence("Return"), self)
        shortcut.activated.connect(self.process_input)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event and event.key() == Qt.Key.Key_Escape:
            self.close()

    def process_input(self, s: str) -> None:
        if self.on_open:
            self.on_open(s)

        # close lets the entire application crash
        self.deleteLater()


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    dialog = ImportDialog(network=bdk.Network.REGTEST, on_open=print)
    dialog.show()

    sys.exit(app.exec())
