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

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import partial
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeyEvent,
    QKeySequence,
    QShortcut,
    QShowEvent,
)
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit
from bitcoin_safe.gui.qt.util import center_on_screen
from bitcoin_safe.i18n import translate

logger = logging.getLogger(__name__)


def is_binary(file_path) -> bool:
    """Check if a file is binary or text.

    Returns True if binary, False if text.
    """
    try:
        with open(file_path) as f:
            for chunk in iter(partial(f.read, 1024), ""):
                if "\0" in chunk:  # found null byte
                    return True
    except UnicodeDecodeError:
        return True

    return False


def file_to_str(file_path) -> str:
    """File to str."""
    if is_binary(file_path):
        with open(file_path, "rb") as f:
            return bytes(f.read()).hex()
    else:
        with open(file_path) as f:
            return f.read()


class DragAndDropTextEdit(AnalyzerTextEdit):
    def __init__(
        self,
        parent=None,
        callback_enter=None,
        callback_esc=None,
        process_filepath: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.process_filepath = process_filepath
        self.callback_enter = callback_enter
        self.callback_esc = callback_esc

    def keyPressEvent(self, e: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if not e:
            super().keyPressEvent(e)
            return

        if e.key() == Qt.Key.Key_Return or e.key() == Qt.Key.Key_Enter:
            if self.callback_enter:
                self.callback_enter(self.toPlainText())
        elif e.key() == Qt.Key.Key_Escape:
            if self.callback_esc:
                self.callback_esc()
        super().keyPressEvent(e)

    def dragEnterEvent(self, e: QDragEnterEvent | None) -> None:
        """DragEnterEvent."""
        if not e:
            super().dragEnterEvent(e)
            return

        mime_data = e.mimeData()
        if mime_data and mime_data.hasUrls():
            e.accept()
        else:
            e.ignore()

        super().dragEnterEvent(e)

    def dropEvent(self, e: QDropEvent | None) -> None:
        """DropEvent."""
        if not e:
            super().dropEvent(e)
            return

        mime_data = e.mimeData()
        if mime_data:
            file_path = mime_data.urls()[0].toLocalFile()
            if self.process_filepath:
                self.process_filepath(file_path)
                return  # prevent         super().dropEvent(event)

        super().dropEvent(e)


class DragAndDropButtonEdit(ButtonEdit):
    signal_drop_file = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        network: bdk.Network,
        close_all_video_widgets: SignalProtocol[[]],
        parent=None,
        callback_enter=None,
        callback_esc=None,
        file_filter: str | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            parent=parent,
            input_field=DragAndDropTextEdit(
                parent=parent,
                callback_enter=callback_enter,
                callback_esc=callback_esc,
                process_filepath=self.process_filepath,
            ),
            close_all_video_widgets=close_all_video_widgets,
        )
        self.network = network
        file_filter = (
            file_filter
            if file_filter
            else translate("DragAndDropButtonEdit", "All Files (*);;PSBT (*.psbt);;Transaction (*.tx)")
        )

        self.add_qr_input_from_camera_button(network=self.network, set_data_as_string=True)
        self.button_open_file = self.add_open_file_button(self.process_filepath, filter_str=file_filter)

    def process_filepath(self, file_path: str) -> None:
        """Process filepath."""
        s = file_to_str(file_path)
        self.setText(s)
        self.signal_drop_file.emit(s)


class ImportDialog(QWidget):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        network: bdk.Network,
        close_all_video_widgets: SignalProtocol[[]],
        window_title="Open Transaction or PSBT",
        on_open=None,
        text_button_ok="OK",
        text_instruction_label="Please paste your Bitcoin Transaction or PSBT in here, or drop a file",
        instruction_widget: QWidget | None = None,
        text_placeholder="Paste your Bitcoin Transaction or PSBT in here or drop a file",
    ) -> None:
        """Initialize instance."""
        super().__init__()

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.on_open = on_open

        self.setWindowTitle(window_title)
        layout = QVBoxLayout(self)

        self.instruction_label = QLabel(text_instruction_label)
        self.text_edit = DragAndDropButtonEdit(
            network=network,
            callback_enter=self.on_ok_button,
            callback_esc=self.close,
            close_all_video_widgets=close_all_video_widgets,
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
            self.button_ok.clicked.connect(self.on_button_ok_clicked)

        layout.addWidget(self.buttonBox)

        shortcut = QShortcut(QKeySequence("Return"), self)
        shortcut.activated.connect(self.on_ok_button)
        self.shortcut_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close.activated.connect(self.close)
        self.shortcut_close = QShortcut(QKeySequence("ESC"), self)
        self.shortcut_close.activated.connect(self.close)

    def on_button_ok_clicked(self):
        """On button ok clicked."""
        self.on_ok_button(self.text_edit.text())

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if a0 and a0.key() == Qt.Key.Key_Escape:
            self.close()

    def on_ok_button(self, s: str) -> None:
        """On ok button."""
        if self.on_open:
            self.close()
            self.on_open(s)

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        center_on_screen(self)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    class My(QObject):
        close_all_video_widgets = cast(SignalProtocol[[]], pyqtSignal())

    my = My()

    app = QApplication(sys.argv)

    dialog = ImportDialog(
        network=bdk.Network.REGTEST, on_open=print, close_all_video_widgets=my.close_all_video_widgets
    )
    dialog.show()

    sys.exit(app.exec())
