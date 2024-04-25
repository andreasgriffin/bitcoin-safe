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

logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QSlider, QVBoxLayout, QWidget


class CustomSlider(QWidget):
    def __init__(
        self,
        min_val=0,
        max_val=100,
        tick_interval=10,
        unit="BTC",
        label_text="",
        parent=None,
    ):
        super(CustomSlider, self).__init__(parent)
        self._unit = unit
        self._color_ranges = []
        self._label_text = label_text

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setTickInterval(tick_interval)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.valueChanged.connect(self.update_label)

        self.label = QLabel(parent)

        self.layout = QVBoxLayout(parent)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.layout.addWidget(self.slider)
        self.layout.addWidget(self.label)
        self.setLayout(self.layout)

        self.update_label(self.slider.value())

    @property
    def value(self):
        return self.slider.value()

    @value.setter
    def value(self, value):
        self.slider.setValue(value)

    @property
    def unit(self):
        return self._unit

    @unit.setter
    def unit(self, value):
        self._unit = value

    @property
    def label_text(self):
        return self._label_text

    @label_text.setter
    def label_text(self, value):
        self._label_text = value

    @property
    def color_ranges(self):
        return self._color_ranges

    @color_ranges.setter
    def color_ranges(self, value):
        self._color_ranges = value

    @property
    def min_val(self):
        return self.slider.minimum()

    @min_val.setter
    def min_val(self, value):
        self.slider.setMinimum(value)

    @property
    def max_val(self):
        return self.slider.maximum()

    @max_val.setter
    def max_val(self, value):
        self.slider.setMaximum(value)

    @property
    def tick_interval(self):
        return self.slider.tickInterval()

    @tick_interval.setter
    def tick_interval(self, value):
        self.slider.setTickInterval(value)

    def update_label(self, value):
        for range in self.color_ranges:
            if range[0] <= value <= range[1]:
                self.label.setText(f"{self.label_text}<font color='{range[2]}'>{value}</font> {self.unit}")
                return
        self.label.setText(f"{self.label_text}{value} {self.unit}")

    def add_color_range(self, min_val, max_val, color):
        self._color_ranges.append((min_val, max_val, color))


def main():
    app = QApplication([])

    widget = CustomSlider(min_val=0, max_val=70, tick_interval=10, unit="BTC", label_text="Amount: ")
    widget.add_color_range(20, 30, "#FFFFFF")
    widget.add_color_range(30, 35, "#FF00FF")
    widget.add_color_range(40, 60, "#FFFF11")
    widget.show()

    app.exec()


if __name__ == "__main__":
    main()
