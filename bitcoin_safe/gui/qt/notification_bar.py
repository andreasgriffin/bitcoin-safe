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
import sys
from typing import Callable, Optional, Tuple

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .recipients import CloseButton

logger = logging.getLogger(__name__)


class NotificationBar(QWidget):
    def __init__(
        self,
        text: str = "",
        optional_button_text: str | None = None,
        callback_optional_button: Optional[Callable] = None,
        additional_widget: QWidget | None = None,
        has_close_button: bool = True,
        parent=None,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._layout = QVBoxLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._layout.setSpacing(0)  # Remove any default spacing

        main_widget = QWidget()
        main_widget_layout = QHBoxLayout(main_widget)
        current_margins = main_widget_layout.contentsMargins()
        main_widget_layout.setContentsMargins(
            current_margins.left(), 4, 4, 2
        )  # Left, Top, Right, Bottom margins
        self._layout.addWidget(main_widget)

        # Icon Label
        self.icon_label = QLabel()
        self.icon_label.setVisible(False)
        main_widget_layout.addWidget(self.icon_label)
        # Text Label
        self.textLabel = QLabel(text)
        main_widget_layout.addWidget(self.textLabel)

        # Optional Button
        self.optionalButton = QPushButton()
        self.optionalButton.setVisible(bool(optional_button_text))  # Hidden by default
        self.optionalButton.setText(optional_button_text if optional_button_text else "")
        if callback_optional_button:
            self.optionalButton.clicked.connect(callback_optional_button)
        main_widget_layout.addWidget(self.optionalButton)

        # additional_widget
        if additional_widget:
            main_widget_layout.addWidget(additional_widget)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_widget_layout.addWidget(spacer)

        # Close Button
        self.closeButton = CloseButton()
        self.closeButton.clicked.connect(self.hide)
        if has_close_button:
            main_widget_layout.addWidget(self.closeButton)
        self.closeButton.setFixedSize(self.sizeHint().height(), self.sizeHint().height())
        logger.debug(f"initialized {self}")

    def set_background_color(self, color: str) -> None:
        self.setStyleSheet(f"background-color: {color};")  # Set the background color for the notification bar

        # Set the background color for all child widgets, including the spacer
        self.textLabel.setStyleSheet(f"background-color: {color};")
        # self.optionalButton.setStyleSheet(f"background-color: {color};")
        # self.closeButton.setStyleSheet(f"background-color: {color};")

    def set_icon(self, icon: Optional[QIcon], sizes: Tuple[int | None, int | None] = (None, None)) -> None:
        self.icon_label.setVisible(bool(icon))
        if icon:
            pixmap_sizes = [(s if s else self.textLabel.sizeHint().height()) for s in sizes]
            self.icon_label.setPixmap(icon.pixmap(*pixmap_sizes))  # type: ignore


if __name__ == "__main__":

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()

            self.setCentralWidget(QWidget())
            layout = QVBoxLayout(self.centralWidget())
            # layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
            layout.setSpacing(0)

            self.notificationBar = NotificationBar(text="my notification")
            self.notificationBar.set_background_color("lightblue")
            self.notificationBar.set_icon(QIcon("../icons/bitcoin-testnet.svg"))
            layout.addWidget(self.notificationBar)
            layout.addWidget(QTextEdit("some text"))

        def on_button_clicked(self) -> None:
            print("Optional Button Clicked")
            self.notificationBar.textLabel.setText("Button Clicked!")

    app = QApplication(sys.argv)
    mainWin = MainWindow()
    mainWin.show()
    sys.exit(app.exec())
