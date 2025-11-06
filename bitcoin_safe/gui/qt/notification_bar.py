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
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.icon_label import IconLabel

from .qr_components.square_buttons import CloseButton
from .util import adjust_bg_color_for_darkmode, set_margins

logger = logging.getLogger(__name__)


class NotificationBar(QWidget):
    def __init__(
        self,
        text: str = "",
        optional_button_text: str | None = None,
        callback_optional_button: Callable | None = None,
        has_close_button: bool = True,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self.color: QColor | None = None
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        set_margins(
            self._layout,
            {
                Qt.Edge.RightEdge: 4,
                Qt.Edge.BottomEdge: 2,
                Qt.Edge.TopEdge: 4,
            },
        )

        # Icon Label
        self.icon_label = IconLabel(text=text)
        self._layout.addWidget(self.icon_label)

        # Optional Button
        self.optionalButton = QPushButton()
        self.optionalButton.setVisible(bool(optional_button_text))  # Hidden by default
        self.optionalButton.setText(optional_button_text if optional_button_text else "")
        if callback_optional_button:
            self.optionalButton.clicked.connect(callback_optional_button)

        self._layout.addWidget(self.optionalButton)

        self._layout.addStretch()
        # Close Button
        self.closeButton = CloseButton()
        self.closeButton.clicked.connect(self.hide)
        self._layout.addWidget(self.closeButton)
        self.set_has_close_button(has_close_button=has_close_button)
        self.closeButton.setFixedSize(self.sizeHint().height(), self.sizeHint().height())
        logger.debug(f"initialized {self.__class__.__name__}")

    def add_styled_widget(self, widget: QWidget):
        """Add styled widget."""
        if self.color:
            self.style_widget(widget, color=self.color)
        self._layout.insertWidget(self._layout.count() - 2, widget)

    def set_has_close_button(self, has_close_button: bool):
        """Set has close button."""
        self.closeButton.setHidden(not has_close_button)

    def style_widget(self, button: QWidget, color: QColor):
        """Style widget."""
        button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        button.setObjectName(button.__class__.__name__)
        button.setStyleSheet(f"#{button.objectName()} {{ background-color: {color.name()};}}")

    def set_background_color(self, color: QColor) -> None:
        """Set background color."""
        self.color = color
        self.style_widget(self, color=color)
        self.style_widget(self.optionalButton, color=color)

    def set_icon(self, icon: QIcon | None, sizes: tuple[int | None, int | None] = (None, None)) -> None:
        """Set icon."""
        self.icon_label.set_icon(icon=icon, sizes=sizes)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.closeButton.setAccessibleName(self.tr("Close notification"))


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            """Initialize instance."""
            super().__init__()

            self.setCentralWidget(QWidget())
            layout = QVBoxLayout(self.centralWidget())
            # layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
            layout.setSpacing(0)

            self.notificationBar = NotificationBar(text="my notification")
            self.notificationBar.set_background_color(adjust_bg_color_for_darkmode(QColor("lightblue")))
            self.notificationBar.set_icon(QIcon("../icons/bitcoin-testnet.svg"))
            layout.addWidget(self.notificationBar)
            layout.addWidget(QTextEdit("some text"))

        def on_button_clicked(self) -> None:
            """On button clicked."""
            print("Optional Button Clicked")
            self.notificationBar.icon_label.setText("Button Clicked!")

    app = QApplication(sys.argv)
    mainWin = MainWindow()
    mainWin.show()
    sys.exit(app.exec())
