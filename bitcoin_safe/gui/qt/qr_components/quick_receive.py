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
from functools import partial
from typing import cast

from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.util import insert_invisible_spaces_for_wordwrap
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QKeyEvent, QMouseEvent, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.qr_components.square_buttons import FlatSquareButton
from bitcoin_safe.gui.qt.util import do_copy, set_translucent, svg_tools
from bitcoin_safe.pythonbdk_types import AddressInfoMin

from ..util import to_color_name

logger = logging.getLogger(__name__)


class TitledComponent(QWidget):
    def __init__(self, title, hex_color: str, border_color: str | None = None, parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(3)

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

        # 2) Enable CSS painting
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self.setObjectName(str(id(self)))
        self.setStyleSheet(
            f"""
                #{self.objectName()} {{
                    background-color: {hex_color};
                    border: {"none" if border_color is None else f"2px dashed {border_color}"};
                    border-radius: 10px;
                }}
                """
        )


class ReceiveGroup(TitledComponent):
    signal_set_address_as_used = cast(SignalProtocol[[AddressInfoMin]], pyqtSignal(AddressInfoMin))

    def __init__(
        self,
        category: str,
        hex_color: str,
        address_info: AddressInfoMin,
        qr_uri: str,
        width=170,
        parent=None,
    ) -> None:
        """Initialize instance."""
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

        self.force_new_button = FlatSquareButton(
            qicon=svg_tools.get_QIcon("reset-update.svg"), parent=button_group_widget
        )
        self.force_new_button.clicked.connect(partial(self.signal_set_address_as_used.emit, address_info))
        button_group_widget_layout.addWidget(self.force_new_button)

        self.copy_button = FlatSquareButton(
            qicon=svg_tools.get_QIcon("bi--copy.svg"), parent=button_group_widget
        )
        self.copy_button.clicked.connect(
            partial(do_copy, text=address_info.address, title=self.tr("Address"))
        )
        button_group_widget_layout.addWidget(self.copy_button)

        self.qr_button = FlatSquareButton(
            qicon=svg_tools.get_QIcon("bi--qr-code.svg"), parent=button_group_widget
        )
        self.qr_button.clicked.connect(self.qr_code.enlarge_image)
        button_group_widget_layout.addWidget(self.qr_button)

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
        """Address."""
        return self.address_info.address

    @property
    def category(self) -> str:
        """Category."""
        return self.title.text()

    def updateUi(self):
        """UpdateUi."""
        self.force_new_button.setToolTip(self.tr("Get next address"))
        self.copy_button.setToolTip(self.tr("Copy address to clipboard"))
        self.qr_button.setToolTip(self.tr("Magnify QR code"))


class AddCategoryButton(TitledComponent):
    clicked = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, width=170, parent=None) -> None:
        """Initialize instance."""
        super().__init__(
            title="",
            hex_color=to_color_name(QPalette.ColorRole.Midlight),
            border_color=to_color_name(QPalette.ColorRole.Mid),
            parent=parent,
        )
        self._width = width
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setFixedWidth(self._width)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._layout.setContentsMargins(12, 12, 12, 12)

        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._content_widget = QWidget(self)
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 0, 0, 0)

        self.icon_label = QLabel(self._content_widget)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._content_layout.addSpacing(24)

        def add_label(size: int):
            """Add label."""
            label = QLabel(self._content_widget)

            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = label.font()
            font.setPixelSize(size)
            label.setFont(font)
            label.setWordWrap(True)
            opacity_effect = QGraphicsOpacityEffect()
            opacity_effect.setOpacity(0.7)  # 0.0 = transparent, 1.0 = opaque
            label.setGraphicsEffect(opacity_effect)
            self._content_layout.addWidget(label)
            return label

        self.caption_label = add_label(size=13)
        self.caption_label_sub = add_label(size=11)

        icon = svg_tools.get_QIcon("bi--plus-lg.svg")
        self.icon_label.setPixmap(icon.pixmap(QSize(36, 36)))
        opacity_effect = QGraphicsOpacityEffect()
        opacity_effect.setOpacity(0.6)  # 0.0 = transparent, 1.0 = opaque
        self.icon_label.setGraphicsEffect(opacity_effect)

        self._layout.insertWidget(1, self._content_widget)
        self._layout.addStretch(1)

        self.updateUi()

    def sizeHint(self):
        """SizeHint."""
        hint = super().sizeHint()
        hint.setWidth(self._width)
        return hint

    def updateUi(self) -> None:
        # self.title.setText(self.tr("Add New Category"))
        """UpdateUi."""
        self.caption_label.setText(self.tr("Add new category"))
        self.caption_label_sub.setText(self.tr("KYC Exchange, Private, ..."))
        self.setToolTip(self.tr("Add new category"))

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        """MouseReleaseEvent."""
        if not a0:
            return
        pos = a0.position().toPoint() if hasattr(a0, "position") else a0.pos()
        if a0.button() == Qt.MouseButton.LeftButton and self.isEnabled() and self.rect().contains(pos):
            self.clicked.emit()
            a0.accept()
            return
        super().mouseReleaseEvent(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if not a0:
            return
        if a0.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.isEnabled():
            self.clicked.emit()
            a0.accept()
            return
        super().keyPressEvent(a0)


class QuickReceive(QWidget):
    signal_manage_categories_requested = cast(SignalProtocol[[]], pyqtSignal())
    signal_add_category_requested = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, title="Quick Receive", parent=None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.signal_tracker = SignalTracker()

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)

        # Horizontal Layout for Scroll Area content

        # Content Widget for the Scroll Area
        self.content_widget = QWidget(parent)
        self.content_widget.setAutoFillBackground(True)
        self.content_widget_layout = QHBoxLayout(self.content_widget)
        # self.content_widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._trailing_spacer = QSpacerItem(
            0,
            0,
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        self.content_widget_layout.addItem(self._trailing_spacer)

        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.content_widget)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        set_translucent(self.content_widget)

        # 2) scroll‐area viewport (where it actually paints)
        if viewport := self.scroll_area.viewport():
            set_translucent(viewport)

        # Main Layout
        main_layout = QVBoxLayout(self)
        header_widget = QWidget(self)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.label_title = QLabel(title)
        font = QFont()
        # font.setBold(True)
        self.label_title.setFont(font)
        header_layout.addWidget(self.label_title)
        header_layout.addStretch(1)

        self.manage_categories_button = QPushButton(self)
        self.manage_categories_button.setIcon(svg_tools.get_QIcon("bi--gear.svg"))
        self.manage_categories_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manage_categories_button.setFlat(True)
        self.manage_categories_button.setText(self.tr("Manage Categories"))
        self.manage_categories_button.setToolTip(self.tr("Open the category manager"))
        self.manage_categories_button.clicked.connect(self.signal_manage_categories_requested.emit)
        header_layout.addWidget(self.manage_categories_button)

        main_layout.addWidget(header_widget)
        main_layout.addWidget(self.scroll_area)

        # Group Box Management
        self.group_boxes: list[ReceiveGroup] = []
        self.add_category_button = AddCategoryButton(parent=self.content_widget)
        self.add_category_button.clicked.connect(self.signal_add_category_requested.emit)
        self._insert_before_trailing_spacer(self.add_category_button)

    def add_box(self, receive_group: ReceiveGroup) -> None:
        """Add box."""
        self.group_boxes.append(receive_group)
        self._insert_before_widget(receive_group, self.add_category_button)

    def remove_box(self, group_box: ReceiveGroup) -> None:
        """Remove box."""
        self.content_widget_layout.removeWidget(group_box)
        group_box.setHidden(True)
        group_box.close()
        group_box.setParent(None)  # type: ignore[call-overload]

    def remove_last_box(self) -> None:
        """Remove last box."""
        if self.group_boxes:
            group_box = self.group_boxes.pop()
            self.remove_box(group_box)

    def clear_boxes(self) -> None:
        """Clear boxes."""
        while self.group_boxes:
            self.remove_last_box()

    def set_manage_categories_enabled(self, enabled: bool) -> None:
        """Toggle the Manage Categories button availability."""

        self.manage_categories_button.setEnabled(enabled)
        self.manage_categories_button.setVisible(True)
        self.add_category_button.setEnabled(enabled)

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)

        self.clear_boxes()
        self.setParent(None)
        return super().close()

    def _insert_before_trailing_spacer(self, widget: QWidget) -> None:
        """Insert before trailing spacer."""
        index = self.content_widget_layout.count()
        if self._trailing_spacer is not None:
            index -= 1
        self.content_widget_layout.insertWidget(index, widget)

    def _insert_before_widget(self, widget: QWidget, before_widget: QWidget) -> None:
        """Insert before widget."""
        index = self.content_widget_layout.indexOf(before_widget)
        if index == -1:
            self._insert_before_trailing_spacer(widget)
            return
        self.content_widget_layout.insertWidget(index, widget)

    def updateUi(self):
        """UpdateUi."""
        self.label_title.setText(self.tr("Quick Receive"))
        self.manage_categories_button.setText(self.tr("Manage Categories"))
        self.manage_categories_button.setToolTip(self.tr("Open the category manager"))
        self.add_category_button.updateUi()
        for gb in self.group_boxes:
            gb.updateUi()
