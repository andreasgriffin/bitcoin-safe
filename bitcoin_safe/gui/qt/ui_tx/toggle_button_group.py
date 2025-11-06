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
import sys

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ToggleButtonGroup(QWidget):
    """A simple exclusive group of toggleable QAbstractButtons with a button-focused
    API."""

    # Emit the button instance that was selected
    selectedChanged = pyqtSignal(QAbstractButton)

    def __init__(self, parent=None):
        """Initialize instance."""
        super().__init__(parent)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(5)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        # Connect the button-based overload
        self._group.buttonClicked.connect(self.on_button_clicked)

    def on_button_clicked(self, button: QAbstractButton):
        """On button clicked."""
        self.selectedChanged.emit(button)

    def addButton(self, btn: QAbstractButton):
        """AddButton."""
        btn.setCheckable(True)
        self._layout.addWidget(btn)
        self._group.addButton(btn)

    def insertButton(self, position: int, btn: QAbstractButton):
        """Insert a new checkable QAbstractButton with `text` at layout `position`.

        Returns the created button instance.
        """
        btn.setCheckable(True)
        self._layout.insertWidget(position, btn)
        self._group.addButton(btn)

    def clear(self):
        """Remove and delete all buttons."""
        for btn in list(self._group.buttons()):
            self.removeButton(btn)

    def removeButton(self, button: QAbstractButton):
        """Remove and delete the given button instance."""
        if button in self._group.buttons():
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.setParent(None)

    def count(self) -> int:
        """Return number of buttons in the group."""
        return self._layout.count()

    def buttons(self) -> list[QAbstractButton]:
        """Return list of all buttons in layout order."""
        buttons: list[QAbstractButton] = []
        for i in range(self._layout.count()):
            if (item := self._layout.itemAt(i)) and isinstance(button := item.widget(), QAbstractButton):
                buttons.append(button)
        return buttons

    def labels(self) -> list[str]:
        """Return list of button texts in layout order."""
        return [btn.text() for btn in self.buttons()]

    def setCurrentButton(self, button: QAbstractButton):
        """Programmatically check the given button instance."""
        if button in self._group.buttons():
            button.setChecked(True)

    def currentButton(self) -> QAbstractButton | None:
        """Return the currently checked button, or None."""
        return self._group.checkedButton()

    # Index-based methods
    def setCurrentIndex(self, index: int):
        """Programmatically check the button at layout position `index`."""
        btn = self.buttonAt(index)
        if btn:
            btn.setChecked(True)

    def currentIndex(self) -> int:
        """Return the layout position of the currently checked button, or -1."""
        btn = self.currentButton()
        return self.positionOf(btn) if btn else -1

    def buttonAt(self, position: int) -> QAbstractButton | None:
        """Return the button at layout index, or None."""
        item = self._layout.itemAt(position)
        widget = item.widget() if item else None
        return widget if isinstance(widget, QAbstractButton) else None

    def positionOf(self, button: QAbstractButton) -> int:
        """Return layout index of the given button, or -1."""
        for i in range(self._layout.count()):
            if (item := self._layout.itemAt(i)) and item.widget() is button:
                return i
        return -1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = QWidget()
    vlay = QVBoxLayout(win)

    toggles = ToggleButtonGroup()
    vlay.addWidget(toggles)

    # Dynamically add and insert
    toggles.addButton(QPushButton("Apple"))
    cherry_btn = QPushButton("Cherry")
    toggles.addButton(cherry_btn)
    date_btn = toggles.insertButton(1, QPushButton("Date"))

    # Connect selection changes
    def on_selected(btn: QAbstractButton):
        """On selected."""
        print("Selected button text:", btn.text())
        current_button = toggles.currentButton()
        if current_button is not None:
            print("Current position:", toggles.positionOf(current_button))

    toggles.selectedChanged.connect(on_selected)

    # Programmatic control
    toggles.setCurrentButton(cherry_btn)

    win.setWindowTitle("Button-Focused ToggleButtonGroup")
    win.show()
    sys.exit(app.exec())
