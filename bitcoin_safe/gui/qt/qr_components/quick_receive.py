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
from functools import partial
from typing import List

from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from bitcoin_tools.util import insert_invisible_spaces_for_wordwrap
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.util import do_copy, svg_tools
from bitcoin_safe.pythonbdk_types import AddressInfoMin
from bitcoin_safe.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe.typestubs import TypedPyQtSignal

logger = logging.getLogger(__name__)


class TitledComponent(QWidget):
    def __init__(self, title, hex_color, parent=None) -> None:
        super().__init__(parent=parent)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(3)

        # 1) Give this widget a unique objectName
        self.setObjectName("titledComponent")

        self.title = QLabel(title, self)
        self._radius = 20

        font = QFont()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # # Set the background color
        # palette = self.palette()
        # palette.setColor(QPalette.ColorRole.Window, QColor(hex_color))
        # self.setPalette(palette)
        # self.setAutoFillBackground(True)

        self._layout.addWidget(self.title)

        # 1) Give this widget a unique objectName
        self.setObjectName("titledComponent")

        # 2) Enable CSS painting
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # 3) Apply a stylesheet that only matches #titledComponent
        self.setStyleSheet(
            f"""
            /* only the widget with objectName 'titledComponent' */
            #titledComponent {{
                background-color: {hex_color};
                border-radius: 10px;
            }}
        """
        )


class FlatSquareButton(QPushButton):
    def __init__(self, qicon: QIcon, parent) -> None:
        super().__init__(parent)
        self.setIcon(qicon)
        self.setFlat(True)
        self.setFixedSize(QSize(24, 24))


class ReceiveGroup(TitledComponent):
    signal_set_address_as_used: TypedPyQtSignal[AddressInfoMin] = pyqtSignal(AddressInfoMin)  # type: ignore

    def __init__(
        self,
        category: str,
        hex_color: str,
        address_info: AddressInfoMin,
        qr_uri: str,
        width=170,
        parent=None,
    ) -> None:
        super().__init__(title=category, hex_color=hex_color, parent=parent)
        self.address_info = address_info
        self.setFixedWidth(width)
        self._layout.setContentsMargins(12, 12, 12, 12)  # Left, Top, Right, Bottom margins

        # QR Code
        self.qr_code = QRCodeWidgetSVG(always_animate=True, parent=self)
        self.qr_code.set_data_list([qr_uri])
        self._layout.addWidget(self.qr_code)

        button_group_widget = QWidget()
        button_group_widget_layout = QHBoxLayout(button_group_widget)
        button_group_widget_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(button_group_widget)
        button_group_widget_layout.addStretch()

        force_new_button = FlatSquareButton(
            qicon=svg_tools.get_QIcon("reset-update.svg"), parent=button_group_widget
        )
        force_new_button.clicked.connect(partial(self.signal_set_address_as_used.emit, address_info))
        button_group_widget_layout.addWidget(force_new_button)

        copy_button = FlatSquareButton(qicon=svg_tools.get_QIcon("bi--copy.svg"), parent=button_group_widget)
        copy_button.clicked.connect(partial(do_copy, text=address_info.address, title=self.tr("Address")))
        button_group_widget_layout.addWidget(copy_button)

        qr_button = FlatSquareButton(qicon=svg_tools.get_QIcon("bi--qr-code.svg"), parent=button_group_widget)
        qr_button.clicked.connect(self.qr_code.enlarge_image)
        button_group_widget_layout.addWidget(qr_button)

        button_group_widget_layout.addStretch()

        self.label = QLabel(
            insert_invisible_spaces_for_wordwrap(address_info.address, max_word_length=1), parent=self
        )
        self.label.setWordWrap(True)
        font = self.label.font()
        font.setPixelSize(11)
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)  # center horizontally & vertically
        self._layout.addWidget(self.label)

    @property
    def address(self) -> str:
        return self.address_info.address

    @property
    def category(self) -> str:
        return self.title.text()


class QuickReceive(QWidget):
    def __init__(self, title="Quick Receive", parent=None) -> None:
        super().__init__(parent)
        self.signal_tracker = SignalTracker()

        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,  # Horizontal size policy
            QSizePolicy.Policy.Fixed,  # Vertical size policy
        )

        # Horizontal Layout for Scroll Area content

        # Content Widget for the Scroll Area
        self.content_widget = QWidget(parent)
        self.content_widget.setAutoFillBackground(True)
        self.content_widget_layout = QHBoxLayout(self.content_widget)
        # self.content_widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.content_widget)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        # — make backgrounds transparent —
        # 1) content widget (the inner holder)
        self.content_widget.setAutoFillBackground(False)
        self.content_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content_widget.setStyleSheet("background: transparent;")

        # 2) scroll‐area viewport (where it actually paints)
        if viewport := self.scroll_area.viewport():
            viewport.setAutoFillBackground(False)
            viewport.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            viewport.setStyleSheet("background: transparent;")

        # Main Layout
        main_layout = QVBoxLayout(self)
        self.label_title = QLabel(title)
        font = QFont()
        # font.setBold(True)
        self.label_title.setFont(font)
        main_layout.addWidget(self.label_title)
        main_layout.addWidget(self.scroll_area)

        # Group Box Management
        self.group_boxes: List[ReceiveGroup] = []

    def add_box(self, receive_group: ReceiveGroup) -> None:
        self.group_boxes.append(receive_group)
        self.content_widget_layout.addWidget(receive_group)
        self.content_widget.adjustSize()

    def remove_box(self) -> None:
        if self.group_boxes:
            group_box = self.group_boxes.pop()
            group_box.setParent(None)  # type: ignore[call-overload]
            self.content_widget.adjustSize()

    def clear_boxes(self) -> None:
        while self.group_boxes:
            self.remove_box()

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.clear_boxes()
        self.setParent(None)
        super().close()
