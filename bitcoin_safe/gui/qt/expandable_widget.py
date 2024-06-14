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


import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CustomHeader(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setLayout(QHBoxLayout())
        current_margins = self.layout().contentsMargins()
        self.layout().setContentsMargins(current_margins.top(), 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.layout().setSpacing(2)  # Reduce horizontal spacing

        # Set the policy to expanding to use all available space
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Optional border setup
        self.setStyleSheet(
            "border: 1px solid orange; background-color: lightblue;"
        )  # Optional colorful border and background


class ExpandableWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setLayout(QVBoxLayout())

        # Always visible widget
        self.header = CustomHeader(self)
        self.layout().addWidget(self.header)

        # Button for expanding/collapsing
        self.toggleButton = QToolButton(self)
        self.toggleButton.setArrowType(Qt.ArrowType.LeftArrow)  # Initially, the arrow points left
        self.toggleButton.setStyleSheet(
            """
            QToolButton { 
                border: none; 
                background-color: transparent;
            }
            QToolButton:hover {
                background-color: lightgrey;
                border-radius: 3px;
            }
        """
        )
        self.toggleButton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.toggleButton.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.toggleButton.setFixedWidth(25)
        self.toggleButton.clicked.connect(self.toggle)

        # Position the button on the right within the header
        self.header.layout().addWidget(self.toggleButton)

        # Expandable widget
        self.expandableWidget = QWidget()  # Use a QWidget to allow adding custom content
        self.expandableWidget.setLayout(QVBoxLayout())  # Set the layout for the content
        self.expandableWidget.setVisible(False)
        self.expandableWidget.setStyleSheet("background: white; padding: 15px; border: 1px solid grey;")
        self.layout().addWidget(self.expandableWidget)

        self.layout().setSpacing(0)
        self.layout().setContentsMargins(0, 0, 0, 0)

    def toggle(self) -> None:
        is_visible = self.expandableWidget.isVisible()
        self.expandableWidget.setVisible(not is_visible)
        # Change the arrow direction based on visibility
        arrow_type = Qt.ArrowType.LeftArrow if is_visible else Qt.ArrowType.DownArrow
        self.toggleButton.setArrowType(arrow_type)

    def add_header_widget(self, widget: QWidget) -> None:
        """Add custom widget to the header."""
        # Clear any existing widgets in the layout, except the toggle button
        while self.header.layout().count() > 1:  # Leave the toggle button
            child = self.header.layout().takeAt(0)
            if child.widget() is not self.toggleButton:
                child.widget().deleteLater()

        # Add the new widget before the toggle button
        self.header.layout().insertWidget(0, widget, 1)

    def add_content_widget(self, widget: QWidget) -> None:
        """Add custom widget to the content area."""
        # Clear any existing widgets in the layout (optional)
        while self.expandableWidget.layout().count():
            child = self.expandableWidget.layout().takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.expandableWidget.layout().addWidget(widget)


# Main application
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ExpandableWidget()

    # Example of adding custom widgets
    header_label = QLabel("Custom Header Content")
    content_label = QLabel("Custom Content Widget")
    window.add_header_widget(header_label)
    window.add_content_widget(content_label)

    window.show()
    sys.exit(app.exec())
