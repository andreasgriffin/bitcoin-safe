#
# Bitcoin Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QEvent, QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.icon_label import ClickableLabel
from bitcoin_safe.gui.qt.invisible_scroll_area import InvisibleScrollArea

from .styled_card_frame import BaseCardFrame
from .util import get_neutral_surface_colors, set_no_margins, svg_tools


class CardExpansionMode(enum.Enum):
    EXPANDABLE = enum.auto()
    FIXED_COLLAPSED = enum.auto()
    FIXED_EXPANDED = enum.auto()


class CardBase(BaseCardFrame):
    signal_header_clicked = cast(SignalProtocol[[]], pyqtSignal())
    signal_expand_requested = cast(SignalProtocol[[]], pyqtSignal())
    signal_layout_changed = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        parent: QWidget | None = None,
        expansion_mode: CardExpansionMode = CardExpansionMode.EXPANDABLE,
    ) -> None:
        super().__init__(parent)
        self._expansion_mode = expansion_mode
        self._expanded = expansion_mode != CardExpansionMode.FIXED_COLLAPSED
        self._body_content_visible = True
        self._header_clickable = False
        self._header_click_targets: list[QWidget] = []

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 10, 10, 10)
        self.root_layout.setSpacing(10)

        self.header_widget = QWidget(self)
        self.header_layout = QHBoxLayout(self.header_widget)
        set_no_margins(self.header_layout)
        self.header_layout.setSpacing(12)
        self.root_layout.addWidget(self.header_widget)

        self.header_icon = ClickableLabel(self.header_widget)
        self.header_icon.setFixedSize(40, 40)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_layout.addWidget(self.header_icon, alignment=Qt.AlignmentFlag.AlignTop)

        self.header_text_widget = QWidget(self.header_widget)
        self.header_text_layout = QVBoxLayout(self.header_text_widget)
        set_no_margins(self.header_text_layout)
        self.header_text_layout.setSpacing(4)
        self.header_layout.addWidget(self.header_text_widget, stretch=1)

        self.header_title_row = QHBoxLayout()
        set_no_margins(self.header_title_row)
        self.header_title_row.setSpacing(8)
        self.header_text_layout.addLayout(self.header_title_row)

        self.header_title = QLabel(self.header_text_widget)
        title_font = self.header_title.font()
        title_font.setBold(True)
        self.header_title.setFont(title_font)
        self.header_title_row.addWidget(self.header_title)

        self.header_subtitle = QLabel(self.header_text_widget)
        self.header_subtitle.setWordWrap(True)
        subtitle_palette = self.header_subtitle.palette()
        surface_colors = get_neutral_surface_colors()
        subtitle_palette.setColor(self.header_subtitle.foregroundRole(), surface_colors.muted_text)
        self.header_subtitle.setPalette(subtitle_palette)
        self.header_text_layout.addWidget(self.header_subtitle)

        self.header_right_widget = QWidget(self.header_widget)
        self.header_right_layout = QHBoxLayout(self.header_right_widget)
        set_no_margins(self.header_right_layout)
        self.header_right_layout.setSpacing(8)
        self.header_right_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.header_layout.addWidget(self.header_right_widget, alignment=Qt.AlignmentFlag.AlignTop)

        self.separator = QWidget(self)
        self.separator.setVisible(False)

        self.content_widget = QWidget(self)
        self.content_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._content_layout = QVBoxLayout(self.content_widget)
        set_no_margins(self._content_layout)
        self.content_layout: QVBoxLayout | QHBoxLayout = self._content_layout
        self.root_layout.addWidget(self.content_widget, stretch=1)

        for widget in (
            self.header_widget,
            self.header_icon,
            self.header_text_widget,
            self.header_title,
            self.header_subtitle,
            self.header_right_widget,
        ):
            self.register_header_click_target(widget)

        self._refresh_body_visibility()
        self._update_header_cursor()

        self.refresh_style()

    @property
    def is_expanded(self) -> bool:
        if self._expansion_mode == CardExpansionMode.FIXED_COLLAPSED:
            return False
        if self._expansion_mode == CardExpansionMode.FIXED_EXPANDED:
            return True
        return self._expanded

    def expansion_mode(self) -> CardExpansionMode:
        return self._expansion_mode

    def set_expansion_mode(self, mode: CardExpansionMode) -> None:
        self._expansion_mode = mode
        if mode == CardExpansionMode.FIXED_COLLAPSED:
            self._expanded = False
        elif mode == CardExpansionMode.FIXED_EXPANDED:
            self._expanded = True
        self._refresh_body_visibility()
        self._update_header_cursor()

    def expand(self) -> None:
        self.set_expanded(True)

    def collapse(self) -> None:
        self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        if self._expansion_mode == CardExpansionMode.FIXED_COLLAPSED:
            self._expanded = False
        elif self._expansion_mode == CardExpansionMode.FIXED_EXPANDED:
            self._expanded = True
        else:
            self._expanded = expanded
        self._refresh_body_visibility()
        self._update_header_cursor()

    def set_body_content_visible(self, visible: bool) -> None:
        self._body_content_visible = visible
        self._refresh_body_visibility()

    def set_header_clickable(self, clickable: bool) -> None:
        self._header_clickable = clickable
        self._update_header_cursor()

    def set_title(self, title: str) -> None:
        self.header_title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.header_subtitle.setText(subtitle)

    def set_icon(
        self,
        icon: QIcon | QPixmap | str | None,
        size: tuple[int, int] | None = None,
    ) -> None:
        if icon is None:
            self.header_icon.clear()
            return

        icon_size = size or (self.header_icon.width(), self.header_icon.height())
        pixmap = self._coerce_pixmap(icon=icon, size=icon_size)
        self.header_icon.setPixmap(pixmap)
        self.header_icon.setText("")

    def set_content_widget(self, widget: QWidget, stretch: int = 0) -> None:
        index = self._content_layout.indexOf(widget)
        if index == -1:
            self._content_layout.addWidget(widget, stretch=stretch)
            return
        self._content_layout.setStretch(index, stretch)

    def preferred_size_hint(self, expanded: bool) -> QSize:
        margins = self.root_layout.contentsMargins()
        spacing = self.root_layout.spacing()
        header_size = self.header_widget.sizeHint()
        content_size = self.content_widget.sizeHint() if expanded and self._body_content_visible else QSize()

        width = margins.left() + margins.right() + max(header_size.width(), content_size.width())
        height = margins.top() + margins.bottom() + header_size.height()
        if not content_size.isEmpty():
            height += spacing + content_size.height()
        return QSize(width, height)

    def clear_content_widget(self, widget: QWidget) -> None:
        if self._content_layout.indexOf(widget) == -1:
            return
        self._content_layout.removeWidget(widget)
        widget.setParent(None)

    def register_header_click_target(self, widget: QWidget) -> None:
        if widget in self._header_click_targets:
            return
        self._header_click_targets.append(widget)
        widget.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if (
            a0 in self._header_click_targets
            and isinstance(a1, QMouseEvent)
            and a1.type() == QEvent.Type.MouseButtonRelease
            and a1.button() == Qt.MouseButton.LeftButton
        ):
            return self.on_header_activated()
        return super().eventFilter(a0, a1)

    def on_header_activated(self) -> bool:
        if not self._is_header_activatable():
            return False
        self.signal_header_clicked.emit()
        if self._expansion_mode == CardExpansionMode.EXPANDABLE:
            if self.is_expanded:
                self.collapse()
            else:
                self.signal_expand_requested.emit()
        return True

    def _is_header_activatable(self) -> bool:
        return self._header_clickable or self._expansion_mode == CardExpansionMode.EXPANDABLE

    def _effective_body_visible(self) -> bool:
        return self._body_content_visible and self.is_expanded

    def _refresh_body_visibility(self) -> None:
        show_body = self._effective_body_visible()
        self.content_widget.setVisible(show_body)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding if show_body else QSizePolicy.Policy.Fixed,
        )
        self.updateGeometry()
        self.signal_layout_changed.emit()

    def _update_header_cursor(self) -> None:
        if self._header_clickable or (
            self._expansion_mode == CardExpansionMode.EXPANDABLE and not self.is_expanded
        ):
            cursor_shape = Qt.CursorShape.PointingHandCursor
        else:
            cursor_shape = Qt.CursorShape.ArrowCursor
        for widget in self._header_click_targets:
            widget.setCursor(cursor_shape)

    def _coerce_pixmap(
        self,
        icon: QIcon | QPixmap | str,
        size: tuple[int, int],
    ) -> QPixmap:
        if isinstance(icon, QPixmap):
            return icon.scaled(
                QSize(*size),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        if isinstance(icon, QIcon):
            return icon.pixmap(QSize(*size), self.devicePixelRatioF())
        return svg_tools.get_pixmap(icon, size=size)


class CardList(QWidget):
    signal_current_index_changed = cast(SignalProtocol[[int]], pyqtSignal(int))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[CardBase] = []
        self._current_index = -1
        self._only_one_expanded_at_a_time = False
        self._expand_request_handlers: dict[CardBase, Callable[[], None]] = {}

        self.layout_main = QVBoxLayout(self)
        set_no_margins(self.layout_main)

        self.scroll_area = InvisibleScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.layout_main.addWidget(self.scroll_area)

        self.scroll_area.setWidget(self.scroll_area.content_widget)
        self.content_layout = QVBoxLayout(self.scroll_area.content_widget)
        set_no_margins(self.content_layout)
        self.content_layout.setSpacing(12)
        self.content_layout.addStretch()

    def add_card(self, card: CardBase) -> None:
        self.insert_card(self.count(), card)

    def insert_card(self, index: int, card: CardBase) -> None:
        bounded_index = max(0, min(index, self.count()))
        self._cards.insert(bounded_index, card)
        self.content_layout.insertWidget(bounded_index, card)

        def handler() -> None:
            self._on_expand_requested(card)

        self._expand_request_handlers[card] = handler
        card.signal_expand_requested.connect(handler)
        card.signal_layout_changed.connect(self._refresh_card_stretches)
        if self._current_index == -1:
            self._set_current_index(0)
        elif bounded_index <= self._current_index:
            self._current_index += 1
        self._refresh_card_stretches()

    def remove_card(self, card_or_index: CardBase | int) -> CardBase:
        index = card_or_index if isinstance(card_or_index, int) else self.index_of(card_or_index)
        card = self._cards.pop(index)
        self.content_layout.removeWidget(card)
        try:
            handler = self._expand_request_handlers.pop(card)
            card.signal_expand_requested.disconnect(handler)
        except TypeError:
            pass
        try:
            card.signal_layout_changed.disconnect(self._refresh_card_stretches)
        except TypeError:
            pass
        if not self._cards:
            self._current_index = -1
        else:
            self._set_current_index(min(self._current_index, self.count() - 1))
        self._refresh_card_stretches()
        return card

    def cards(self) -> list[CardBase]:
        return list(self._cards)

    def count(self) -> int:
        return len(self._cards)

    def index_of(self, card: CardBase) -> int:
        return self._cards.index(card)

    def current_index(self) -> int:
        return self._current_index

    def set_current_index(self, index: int) -> None:
        if not self._cards:
            self._current_index = -1
            return
        bounded_index = max(0, min(index, self.count() - 1))
        self._set_current_index(bounded_index)
        self.scroll_area.ensureWidgetVisible(self._cards[bounded_index])

    def expand_all(self) -> None:
        for card in self._cards:
            if card.expansion_mode() == CardExpansionMode.EXPANDABLE:
                card.expand()

    def collapse_all(self) -> None:
        for card in self._cards:
            if card.expansion_mode() == CardExpansionMode.EXPANDABLE:
                card.collapse()

    def expand_only(self, index: int) -> None:
        if not self._cards:
            self._current_index = -1
            return
        bounded_index = max(0, min(index, self.count() - 1))
        selected = self._cards[bounded_index]
        self._set_current_index(bounded_index)
        for i, card in enumerate(self._cards):
            if card.expansion_mode() != CardExpansionMode.EXPANDABLE:
                continue
            if i == bounded_index:
                card.expand()
            elif self._only_one_expanded_at_a_time:
                card.collapse()
        self.scroll_area.ensureWidgetVisible(selected)

    def set_only_one_expanded_at_a_time(self, enabled: bool) -> None:
        self._only_one_expanded_at_a_time = enabled

    def only_one_expanded_at_a_time(self) -> bool:
        return self._only_one_expanded_at_a_time

    def sizeHint(self) -> QSize:
        return self._preferred_list_size()

    def _on_expand_requested(self, card: CardBase) -> None:
        index = self.index_of(card)
        if self._only_one_expanded_at_a_time:
            self.expand_only(index)
            return
        self._set_current_index(index)
        card.expand()
        self.scroll_area.ensureWidgetVisible(card)

    def _set_current_index(self, index: int) -> None:
        if self._current_index == index:
            self._refresh_card_stretches()
            return
        self._current_index = index
        self._refresh_card_stretches()
        self.signal_current_index_changed.emit(index)

    def _refresh_card_stretches(self) -> None:
        for index, card in enumerate(self._cards):
            stretch = 1 if index == self._current_index and card.is_expanded else 0
            self.content_layout.setStretch(index, stretch)
        self.content_layout.setStretch(self.content_layout.count() - 1, 0)
        self.updateGeometry()

    def _preferred_list_size(self) -> QSize:
        if not self._cards:
            return super().sizeHint()

        expanded_index = self._preferred_expanded_index()
        content_margins = self.content_layout.contentsMargins()
        layout_margins = self.layout_main.contentsMargins()
        spacing = self.content_layout.spacing() * max(0, len(self._cards) - 1)

        width = 0
        height = content_margins.top() + content_margins.bottom() + spacing
        for index, card in enumerate(self._cards):
            card_size = card.preferred_size_hint(expanded=index == expanded_index)
            width = max(width, card_size.width())
            height += card_size.height()

        width += content_margins.left() + content_margins.right()
        width += layout_margins.left() + layout_margins.right()
        height += layout_margins.top() + layout_margins.bottom()
        height += self.scroll_area.frameWidth() * 2
        width += self.scroll_area.frameWidth() * 2
        return QSize(width, height)

    def _preferred_expanded_index(self) -> int:
        for index, card in enumerate(self._cards):
            if card.is_expanded:
                return index
        if 0 <= self._current_index < len(self._cards):
            return self._current_index
        return 0
