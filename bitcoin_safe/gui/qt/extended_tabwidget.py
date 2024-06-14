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

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpacerItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.util import add_tab_to_tabs, read_QIcon, remove_tab


class ExtendedTabWidget(DataTabWidget):
    signal_tab_bar_visibility = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.set_top_right_widget()

        self.tabBar().installEventFilter(self)

        self.tabCloseRequested.connect(self.updateLineEditPosition)
        self.currentChanged.connect(self.updateLineEditPosition)

    def eventFilter(self, obj, event) -> bool:
        if obj == self.tabBar() and event.type() == event.Type.Show:
            if self.top_right_widget:
                self.signal_tab_bar_visibility.emit(True)
        elif obj == self.tabBar() and event.type() == event.Type.Hide:
            if self.top_right_widget:
                self.signal_tab_bar_visibility.emit(False)
        return super().eventFilter(obj, event)

    def set_top_right_widget(self, top_right_widget: QWidget = None, target_width=150) -> None:
        self.top_right_widget = top_right_widget
        self.target_width = target_width

        # Adjust the size and position of the QLineEdit
        if self.top_right_widget:
            self.top_right_widget.setParent(self)
            self.top_right_widget.setFixedWidth(self.target_width)

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        self.updateLineEditPosition()

    def updateLineEditPosition(self) -> None:
        tabBarRect = self.tabBar().geometry()
        availableWidth = self.width()

        line_width = availableWidth // 2 if availableWidth < 2 * self.target_width else self.target_width

        self.tabBar().setMaximumWidth(availableWidth - line_width - 3)

        # Update QLineEdit geometry
        lineEditX = self.width() - line_width - 2
        if self.top_right_widget:
            v_margin = (tabBarRect.height() - self.top_right_widget.height()) // 2
            self.top_right_widget.setGeometry(
                lineEditX, tabBarRect.y(), line_width, tabBarRect.height() - v_margin
            )
            self.top_right_widget.setFixedWidth(line_width)  # Ensure fixed width is maintained

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.updateLineEditPosition()
        super().resizeEvent(event)


class LoadingWalletTab(QWidget):
    def __init__(self, tabs: QTabWidget, name: str, focus=True) -> None:
        super().__init__(tabs)
        self.tabs = tabs
        self.name = name
        self.focus = focus

        # Create a QWidget to serve as a container for the QLabel
        self.setLayout(QVBoxLayout())  # Setting the layout directly

        # Create and configure QLabel
        self.emptyLabel = QLabel("Loading, please wait...", self)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.emptyLabel.setStyleSheet("font-size: 16pt;")  # Adjust the font size as needed

        # Use spacers to push the QLabel to the center
        spacerTop = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        spacerBottom = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        # Add spacers and label to the layout
        self.layout().addItem(spacerTop)
        self.layout().addWidget(self.emptyLabel)
        self.layout().addItem(spacerBottom)

    def __enter__(self) -> None:
        add_tab_to_tabs(
            self.tabs,
            self,
            read_QIcon("status_waiting.png"),
            self.name,
            self.name,
            focus=self.focus,
        )
        QApplication.processEvents()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        remove_tab(self, self.tabs)


# Usage example
if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    edit = QLineEdit(f"Ciiiiii")
    tabWidget = ExtendedTabWidget()

    # Add tabs with larger widgets
    for i in range(3):
        widget = QWidget()
        layout = QVBoxLayout()
        label = QLabel(f"Content for Tab {i+1}")
        textEdit = QTextEdit(f"This is a larger widget in Tab {i+1}.")
        layout.addWidget(label)
        layout.addWidget(textEdit)
        widget.setLayout(layout)
        tabWidget.addTab(widget, f"Tab {i+1}")

    tabWidget.show()
    sys.exit(app.exec())
