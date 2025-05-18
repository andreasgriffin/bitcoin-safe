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
from typing import Callable

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget, T
from bitcoin_safe.gui.qt.util import svg_tools

logger = logging.getLogger(__name__)


class ExtendedTabWidget(DataTabWidget[T]):
    def __init__(self, show_ContextMenu: Callable[[QPoint, int], None] | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.set_top_right_widget()
        self.show_ContextMenu = show_ContextMenu
        self.tabBar().installEventFilter(self)  # type: ignore

    def set_top_right_widget(self, top_right_widget: QWidget | None = None, target_width=150) -> None:
        self.target_width = target_width
        self.setCornerWidget(top_right_widget)

    def mousePressEvent(self, event: QMouseEvent | None):
        super().mousePressEvent(event)

        if not event:
            return
        if event.button() == Qt.MouseButton.RightButton:
            # Get the index of the tab under the cursor
            if tab_bar := self.tabBar():
                index = tab_bar.tabAt(event.pos())
                if index != -1:
                    self.showContextMenu(event.globalPosition().toPoint(), index)

    def showContextMenu(self, position: QPoint, index: int) -> None:
        if self.show_ContextMenu:
            self.show_ContextMenu(position, index)


class LoadingWalletTab(QWidget):
    def __init__(self, tabs: DataTabWidget, name: str, focus=True) -> None:
        super().__init__(tabs)
        self.tabs = tabs
        self.name = name
        self.focus = focus

        # Create a QWidget to serve as a container for the QLabel
        self._layout = QVBoxLayout(self)  # Setting the layout directly

        # Create and configure QLabel
        self.emptyLabel = QLabel(self.tr("Loading, please wait..."), self)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.emptyLabel.setStyleSheet("font-size: 16pt;")  # Adjust the font size as needed

        # Use spacers to push the QLabel to the center
        spacerTop = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        spacerBottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        # Add spacers and label to the layout
        self._layout.addItem(spacerTop)
        self._layout.addWidget(self.emptyLabel)
        self._layout.addItem(spacerBottom)

    def __enter__(self) -> None:
        self.tabs.add_tab(
            tab=self,
            icon=svg_tools.get_QIcon("status_waiting.svg"),
            description=self.name,
            data=None,
            focus=self.focus,
        )
        QApplication.processEvents()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        idx = self.tabs.indexOf(self)
        if idx is None or idx < 0:
            return
        self.tabs.removeTab(idx)


# Usage example
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    edit = QLineEdit(f"Ciiiiii")
    tabWidget = ExtendedTabWidget[object]()

    # Add tabs with larger widgets
    for i in range(3):
        widget = QWidget()
        layout = QVBoxLayout()
        label = QLabel(f"Content for Tab {i+1}")
        textEdit = QTextEdit(f"This is a larger widget in Tab {i+1}.")
        layout.addWidget(label)
        layout.addWidget(textEdit)
        widget.setLayout(layout)
        tabWidget.addTab(widget, description=f"Tab {i+1}")

    tabWidget.show()
    sys.exit(app.exec())
