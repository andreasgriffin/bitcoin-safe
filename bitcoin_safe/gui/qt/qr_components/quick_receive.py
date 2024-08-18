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


from typing import List

from bitcoin_qr_tools.qr_widgets import QRCodeWidgetSVG
from PyQt6.QtCore import QMargins, Qt
from PyQt6.QtGui import QColor, QFont, QPalette, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit


class TitledComponent(QWidget):
    def __init__(self, title, hex_color, parent=None) -> None:
        super().__init__(parent)

        self.title = QLabel(title, self)

        font = QFont()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # Set the background color
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(hex_color))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(3)

        self._layout.addWidget(self.title)


class ReceiveGroup(TitledComponent):
    def __init__(
        self, category: str, hex_color: str, address: str, qr_uri: str, width=170, parent=None
    ) -> None:
        super().__init__(title=category, hex_color=hex_color, parent=parent)
        self.setFixedWidth(width)

        # QR Code
        self.qr_code = QRCodeWidgetSVG(always_animate=True)
        self.qr_code.set_data_list([qr_uri])
        self._layout.addWidget(self.qr_code)

        input_field = AnalyzerTextEdit(address)
        self.text_edit = ButtonEdit(input_field=input_field)
        input_field.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setReadOnly(True)
        self.text_edit.add_copy_button()
        self.text_edit.input_field.setStyleSheet(
            f"""
            background-color: {hex_color};
            border: none;
            """
        )

        self.text_edit.setFixedHeight(60)
        self._layout.addWidget(self.text_edit)

    @property
    def address(self) -> str:
        return self.text_edit.input_field.text()

    @property
    def category(self) -> str:
        return self.title.text()


class NoVerticalScrollArea(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if scroll_bar := self.horizontalScrollBar():
            scroll_bar.valueChanged.connect(self.recenterVerticalScroll)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        # Override to do nothing, preventing vertical scrolling
        pass

    def recenterVerticalScroll(self) -> None:
        # Recenter the vertical scroll position when horizontal scrollbar state changes
        if self.widget() and (scroll_bar := self.verticalScrollBar()):
            max_scroll = scroll_bar.maximum()
            scroll_bar.setValue(max_scroll // 2)

    # Override resizeEvent to handle window resizing
    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self.recenterVerticalScroll()


class QuickReceive(QWidget):
    def __init__(self, title="Quick Receive", parent=None) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,  # Horizontal size policy
            QSizePolicy.Policy.Fixed,  # Vertical size policy
        )

        # Horizontal Layout for Scroll Area content

        # Content Widget for the Scroll Area
        self.content_widget = QWidget()
        self.content_widget_layout = QHBoxLayout(self.content_widget)

        # Scroll Area
        self.scroll_area = NoVerticalScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.content_widget)

        # Main Layout
        main_layout = QVBoxLayout(self)
        self.label_title = QLabel(title)
        font = QFont()
        font.setBold(True)
        self.label_title.setFont(font)
        main_layout.addWidget(self.label_title)
        main_layout.addWidget(self.scroll_area)

        # Group Box Management
        self.group_boxes: List[ReceiveGroup] = []

    def _qmargins_to_tuple(self, margins: QMargins) -> tuple[int, int, int, int]:
        return margins.left(), margins.top(), margins.right(), margins.bottom()

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        for group_box in self.group_boxes:
            margins = self.content_widget_layout.getContentsMargins()
            scrollbar = self.scroll_area.horizontalScrollBar()
            group_box.setFixedHeight(
                self.height()
                - sum([m for m in margins if m])
                - sum(self._qmargins_to_tuple(self.scroll_area.contentsMargins()))
                - (scrollbar.height() if scrollbar else 0)
            )

    def add_box(self, receive_group: ReceiveGroup) -> None:
        self.group_boxes.append(receive_group)
        self.content_widget_layout.addWidget(receive_group)
        self.content_widget.adjustSize()

    def remove_box(self) -> None:
        if self.group_boxes:
            group_box = self.group_boxes.pop()
            group_box.setParent(None)  # type: ignore[call-overload]
            group_box.deleteLater()
            self.content_widget.adjustSize()

    def clear_boxes(self) -> None:
        while self.group_boxes:
            self.remove_box()
