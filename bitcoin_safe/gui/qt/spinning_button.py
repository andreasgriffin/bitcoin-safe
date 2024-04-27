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

from PyQt6.QtCore import QRectF, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPaintEvent
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget

from .util import icon_path


class SpinningButton(QPushButton):
    def __init__(self, text: str, enable_signal=None, svg_path=None, parent=None):
        super().__init__(text, parent)
        if svg_path is None:
            svg_path = icon_path("loader-icon.svg")
        self.svg_renderer = QSvgRenderer(svg_path)
        self.rotation_angle = 0
        self._icon_size = QSize(18, 18)  # Default icon size
        self.timer = QTimer(self)
        self.padding = 3

        self.clicked.connect(self.on_clicked)

        # Connect the external signal to the button's enable method
        self.set_enable_signal(enable_signal)

    def on_clicked(self):
        self.start_spin()
        self.setDisabled(True)

    def enable_button(self, *args, **kwargs):
        self.stop_spin()
        self.setEnabled(True)

    def set_enable_signal(self, enable_signal: pyqtSignal):
        if enable_signal:
            enable_signal.connect(self.enable_button)

    def start_spin(self):

        # Timer to update rotation
        self.timer.timeout.connect(self.rotate_svg)
        self.timer.start(100)  # Update rotation every 100 ms

    def stop_spin(self):
        self.timer.stop()

    def setIconSize(self, size: QSize):
        if isinstance(size, QSize):
            self._icon_size = size
        else:
            raise TypeError("Size must be a QSize object")
        self.update()  # Redraw the button

    def iconSize(self):
        return self._icon_size

    def rotate_svg(self):
        self.rotation_angle = (self.rotation_angle + 10) % 360
        self.update()  # Trigger repaint

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)

        if self.timer.isActive():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Calculate the SVG's drawing rectangle
            icon_size = self.iconSize()
            icon_rect = QRectF(
                self.padding,
                (self.height() - icon_size.height()) / 2,
                icon_size.width(),
                icon_size.height(),
            )

            # Save painter's state to restore after drawing the icon
            painter.save()

            # Transform for rotation
            painter.translate(icon_rect.center())
            painter.rotate(self.rotation_angle)
            painter.translate(-icon_rect.center())

            # Draw SVG
            self.svg_renderer.render(painter, icon_rect)

            # Restore painter's state to draw the text
            painter.restore()

    def sizeHint(self):
        # Get the default size hint from the superclass
        default_size_hint = super().sizeHint()

        # Add icon width and padding to the width
        total_width = default_size_hint.width() + self._icon_size.width() + 2 * self.padding

        # Ensure the height is enough for the text and the icon
        total_height = max(default_size_hint.height(), self._icon_size.height())

        return QSize(total_width, total_height)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        # Replace 'path/to/your.svg' with the path to your SVG file
        self.button = SpinningButton("Button Text", icon_path("loader-icon.svg"))

        layout = QVBoxLayout()
        layout.addWidget(self.button)

        central_widget = QWidget()
        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)


if __name__ == "__main__":
    # Initialize the application
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    # Run the application's event loop
    sys.exit(app.exec())
