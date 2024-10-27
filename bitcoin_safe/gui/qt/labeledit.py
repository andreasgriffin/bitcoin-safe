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
from typing import List

from PyQt6 import QtGui
from PyQt6.QtCore import QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.category_list import CategoryEditor

logger = logging.getLogger(__name__)


class LabelLineEdit(QLineEdit):
    signal_enterPressed = pyqtSignal()  # Signal for Enter key
    signal_textEditedAndFocusLost = pyqtSignal()  # Signal for text edited and focus lost

    def __init__(self, parent=None):
        super().__init__(parent)
        self.originalText = ""
        self.textChangedSinceFocus = False
        self.installEventFilter(self)  # Install an event filter

        self._model = QStringListModel()
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompleter(self._completer)

        # signals
        self.textChanged.connect(self.onTextChanged)  # Connect the textChanged signal

    def set_completer_list(self, strings: List[str]):
        self._model.setStringList(strings)
        self._completer.setModel(self._model)

    def onTextChanged(self):
        self.textChangedSinceFocus = True  # Set flag when text changes

    def eventFilter(self, obj, event):
        if obj == self:
            if event.type() == QKeyEvent.Type.FocusIn:
                self.originalText = self.text()  # Store text when focused
                self.textChangedSinceFocus = False  # Reset change flag
            elif event.type() == QKeyEvent.Type.FocusOut:
                if self.textChangedSinceFocus:
                    self.signal_textEditedAndFocusLost.emit()  # Emit signal if text was edited
                self.textChangedSinceFocus = False  # Reset change flag
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent | None):
        if not event:
            super().keyPressEvent(event)
            return

        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self.signal_enterPressed.emit()  # Emit Enter pressed signal
        elif event.key() == Qt.Key.Key_Escape:
            self.setText(self.originalText)  # Reset text on ESC
        elif self._model.stringList() and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            popup = self._completer.popup()
            if popup and not popup.isVisible():
                self._completer.complete()
        else:
            super().keyPressEvent(event)


class LabelAndCategoryEdit(QWidget):
    def __init__(
        self,
        parent=None,
        dismiss_label_on_focus_loss=False,
    ) -> None:
        super().__init__(parent=parent)
        self.label_edit = LabelLineEdit(parent=self)
        self.category_edit = QLineEdit(parent=self)
        self.category_edit.setReadOnly(True)
        self.category_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.category_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # self.category_edit.setFixedWidth(100)

        self.main_layout = QHBoxLayout(
            self
        )  # Horizontal layout to place the input field and buttons side by side

        # Add the input field and buttons layout to the main layout
        self.main_layout.addWidget(self.category_edit)
        self.main_layout.addWidget(self.label_edit)

        # Ensure there's no spacing that could affect the alignment
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        if dismiss_label_on_focus_loss:
            self.label_edit.signal_textEditedAndFocusLost.connect(
                lambda: self.label_edit.setText(self.label_edit.originalText)
            )

    def _format_category_edit(self) -> None:
        palette = QtGui.QPalette()
        background_color = None

        if self.category_edit.text():
            background_color = CategoryEditor.color(self.category_edit.text())
            palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
        else:
            palette = (self.category_edit.style() or QStyle()).standardPalette()

        self.category_edit.setPalette(palette)
        self.category_edit.update()

    def set(self, label: str, category: str):

        self.set_label(label)
        self.set_category(category)

    def set_category(self, category: str):

        self.category_edit.setText(category)
        self._format_category_edit()

    def set_label(
        self,
        label: str,
    ):
        self.label_edit.setText(label)
        self.label_edit.originalText = label

    def set_placeholder(
        self,
        text: str,
    ):
        self.label_edit.setPlaceholderText(text)

    def set_category_visible(self, value: bool):

        self.category_edit.setVisible(value)

    def category(self) -> str:
        return self.category_edit.text()

    def label(self) -> str:
        return self.label_edit.text().strip()

    def set_label_readonly(self, value: bool):
        self.label_edit.setReadOnly(value)


# Example usage
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    widget_layout = QVBoxLayout(widget)
    widget_layout.setContentsMargins(0, 0, 0, 0)
    widget_layout.setSpacing(0)

    edit = LabelAndCategoryEdit()
    edit.set("some label", "KYC")
    widget_layout.addWidget(edit)

    widget.show()
    sys.exit(app.exec())
