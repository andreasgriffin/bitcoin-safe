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

import datetime
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import partial
from typing import Dict, Iterable, List, Optional, Protocol, Tuple

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import QPointF, Qt, pyqtBoundSignal, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QWheelEvent,
)
from PyQt6.QtWidgets import (
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.packaged_tx_like import PackagedTxLike, UiElements
from bitcoin_safe.gui.qt.util import (
    ColorScheme,
    ColorSchemeItem,
    Message,
    MessageType,
    svg_tools,
)
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_conditions import PluginConditions
from bitcoin_safe.plugin_framework.plugins.walletgraph.server import WalletGraphServer
from bitcoin_safe.pythonbdk_types import FullTxDetail, PythonUtxo
from bitcoin_safe.signals import Signals, UpdateFilter
from bitcoin_safe.tx import short_tx_id
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)
ENABLE_WALLET_GRAPH_TOOLTIPS = False


def elide_text(text: str, max_length: int) -> str:
    if max_length <= 0 or len(text) <= max_length:
        return text
    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


class Highlightable(Protocol):
    def set_highlighted(self, highlighted: bool) -> None: ...


def _apply_connection_highlight(connection: QGraphicsPathItem, original_pen: QPen, highlighted: bool) -> None:
    if highlighted:
        boosted_pen = QPen(original_pen)
        new_width = max(original_pen.widthF() * 1.6, original_pen.widthF() + 1.0)
        boosted_pen.setWidthF(new_width)
        color = QColor(boosted_pen.color())
        color.setAlphaF(1.0)
        boosted_pen.setColor(color)
        connection.setPen(boosted_pen)
    else:
        connection.setPen(original_pen)


class UtxoEllipseItem(QGraphicsEllipseItem):
    DEFAULT_HORIZONTAL_OFFSET = 40.0
    MIN_RADIUS = 10.0
    MAX_RADIUS = 28.0
    OUTPUT_GAP = 120.0
    INPUT_GAP = 120.0
    VERTICAL_SPACING = 90.0
    LABEL_MAX_CHARS = 40

    def __init__(
        self,
        creating_txid: str,
        spending_txid: str | None,
        radius: float,
        transaction_signal: pyqtBoundSignal,
        value_text: str,
        value_label_color: QColor | ColorSchemeItem | None = ColorScheme.DEFAULT,
        value_label_offset: float | None = None,
    ) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.creating_txid = creating_txid
        self._spending_txid = spending_txid
        self._transaction_signal = transaction_signal
        self._highlight_target: Highlightable | None = None
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.value_label = UtxoLabelItem(
            creating_txid,
            value_text,
            transaction_signal=transaction_signal,
            vertical_offset=value_label_offset if value_label_offset is not None else radius + 8,
            color=value_label_color,
            parent=self,
        )
        self._tooltip_text: str | None = None

    def set_highlight_target(self, target: Highlightable | None) -> None:
        self._highlight_target = target
        self.value_label.set_highlight_target(target)

    def mousePressEvent(self, event) -> None:
        if not event:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self.creating_txid)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            menu = QMenu()
            center_funding_action = menu.addAction(
                translate("WalletGraphClient", "Center funding transaction")
            )
            center_spending_action = None
            if self._spending_txid:
                center_spending_action = menu.addAction(
                    translate("WalletGraphClient", "Center spending transaction")
                )

            selected_action = menu.exec(event.screenPos().toPointF().toPoint())
            if selected_action == center_funding_action:
                self._center_view_on_transaction(self.creating_txid)
            elif center_spending_action and self._spending_txid and selected_action == center_spending_action:
                self._center_view_on_transaction(self._spending_txid)
            event.accept()
            return
        super().mousePressEvent(event)

    def append_label_line(
        self,
        text: str,
        color: QColor | ColorSchemeItem | None = None,
    ) -> UtxoLabelItem | None:
        if not text:
            return None
        self.value_label.append_line(text, color=color)
        if self._tooltip_text:
            if ENABLE_WALLET_GRAPH_TOOLTIPS:
                self.value_label.setToolTip(self._tooltip_text)
        return self.value_label

    def append_wallet_label(
        self,
        text: str,
        color: QColor | ColorSchemeItem | None = None,
    ) -> UtxoLabelItem | None:
        return self.append_label_line(text, color=color)

    def set_composite_tooltip(self, tooltip: str) -> None:
        self._tooltip_text = tooltip
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.setToolTip(tooltip)
            self.value_label.setToolTip(tooltip)

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    def _center_view_on_transaction(self, txid: str | None) -> None:
        if not txid:
            return
        scene = self.scene()
        if not scene:
            return
        for view in scene.views():
            center_method = getattr(view, "center_on_transaction", None)
            if callable(center_method):
                center_method(txid)
                break

    @staticmethod
    def _radius_for_value(value: int, max_value: int, min_radius: float, max_radius: float) -> float:
        if max_value <= 0:
            return min_radius
        ratio = value / max_value
        return min_radius + ratio * (max_radius - min_radius)

    @staticmethod
    def _color_for_utxo(
        utxo: PythonUtxo,
        wallet: Wallet | None,
        signals: Signals,
    ) -> QColor:
        if not wallet:
            return ColorScheme.Purple.as_color()
        color = AddressEdit.color_address(utxo.address, wallet, signals)
        if color:
            return color
        return ColorScheme.Purple.as_color()

    @classmethod
    def create_output(
        cls,
        detail: FullTxDetail,
        outpoint_str: str,
        python_utxo: PythonUtxo,
        *,
        transaction_signal: pyqtBoundSignal,
        network: bdk.Network,
        wallet: Wallet | None,
        signals: Signals,
        label_max_chars: int,
        max_utxo_value: int,
        min_radius: float,
        max_radius: float,
        tx_item: "TransactionItem",
        axis_y: float,
        tx_width: float,
        output_gap: float,
        vertical_spacing: float,
        index: int,
        horizontal_offset: float | None = None,
    ) -> "UtxoEllipseItem":
        radius = cls._radius_for_value(python_utxo.value, max_utxo_value, min_radius, max_radius)
        label_text = Satoshis(python_utxo.value, network).str_with_unit(color_formatting=None)
        ellipse = cls(
            detail.txid,
            python_utxo.is_spent_by_txid,
            radius,
            transaction_signal=transaction_signal,
            value_text=label_text,
            value_label_color=ColorScheme.DEFAULT,
        )

        color = cls._color_for_utxo(python_utxo, wallet, signals)
        brush_color = QColor(color)
        alpha = 0.45 if python_utxo.is_spent_by_txid else 0.95
        brush_color.setAlphaF(alpha)
        ellipse.setBrush(brush_color)
        ellipse.setPen(QPen(color))

        horizontal_offset = (
            horizontal_offset if horizontal_offset is not None else cls.DEFAULT_HORIZONTAL_OFFSET
        )
        x_pos = tx_item.pos().x() + tx_width / 2 + horizontal_offset
        y_offset = axis_y + output_gap + vertical_spacing * index
        ellipse.setPos(x_pos, y_offset)
        ellipse.setZValue(1)

        utxo_label_value = ""
        if wallet:
            try:
                utxo_label = wallet.get_label_for_address(python_utxo.address)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to fetch label for address %s", python_utxo.address)
                utxo_label = ""
            utxo_label_value = utxo_label.strip() if utxo_label else ""
            display_utxo_label = elide_text(utxo_label_value, label_max_chars) if utxo_label_value else ""
            ellipse.append_wallet_label(display_utxo_label)

        tooltip_lines = [
            f"{translate('WalletGraphClient', 'UTXO')}: {outpoint_str}",
            f"{translate('WalletGraphClient', 'Address')}: {python_utxo.address}",
            f"{translate('WalletGraphClient', 'Value')}: {label_text}",
            translate("WalletGraphClient", "Status: {status}").format(
                status=(
                    translate("WalletGraphClient", "Spent")
                    if python_utxo.is_spent_by_txid
                    else translate("WalletGraphClient", "Unspent")
                )
            ),
        ]
        if utxo_label_value:
            tooltip_lines.append(f"{translate('WalletGraphClient', 'Label')}: {utxo_label_value}")
        tooltip_lines.append(translate("WalletGraphClient", "Click to open the creating transaction."))
        ellipse.set_composite_tooltip("\n".join(tooltip_lines))

        return ellipse

    @classmethod
    def create_input_placeholder(
        cls,
        outpoint_str: str,
        python_utxo: PythonUtxo | None,
        *,
        transaction_signal: pyqtBoundSignal,
        axis_y: float,
        tx_item: "TransactionItem",
        tx_width: float,
        input_gap: float,
        vertical_spacing: float,
        min_radius: float,
        index: int,
        horizontal_offset: float | None = None,
    ) -> "UtxoEllipseItem":
        creating_txid = outpoint_str.split(":", 1)[0] if outpoint_str else ""
        label_text = translate("WalletGraphClient", "External input") if not python_utxo else outpoint_str
        offset = -min_radius - 20
        ellipse = cls(
            creating_txid,
            python_utxo.is_spent_by_txid if python_utxo else None,
            min_radius,
            transaction_signal=transaction_signal,
            value_text=label_text,
            value_label_color=ColorScheme.GRAY,
            value_label_offset=offset,
        )

        placeholder_color = ColorScheme.Purple.as_color(background=True)
        placeholder_color.setAlphaF(0.4)
        ellipse.setBrush(placeholder_color)
        ellipse.setPen(QPen(ColorScheme.Purple.as_color()))
        ellipse.setCursor(Qt.CursorShape.ArrowCursor)
        ellipse.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        ellipse.value_label.setCursor(Qt.CursorShape.ArrowCursor)
        ellipse.value_label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

        horizontal_offset = (
            horizontal_offset if horizontal_offset is not None else cls.DEFAULT_HORIZONTAL_OFFSET
        )
        x_pos = tx_item.pos().x() - tx_width / 2 - horizontal_offset
        y_pos = axis_y - input_gap - vertical_spacing * index
        ellipse.setPos(x_pos, y_pos)
        ellipse.setZValue(1)
        return ellipse


@dataclass
class GraphUtxoCircle:
    utxo: PythonUtxo | None
    ellipse: UtxoEllipseItem
    default_opacity: float = field(init=False)
    default_z_value: float = field(init=False)
    incoming_connections: List[Tuple[QGraphicsPathItem, QPen]] = field(default_factory=list)
    outgoing_connections: List[Tuple[QGraphicsPathItem, QPen]] = field(default_factory=list)
    _is_highlighted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.default_opacity = self.ellipse.opacity()
        self.default_z_value = self.ellipse.zValue()
        self.ellipse.set_highlight_target(self)

    def add_connection(self, connection: QGraphicsPathItem, incoming: bool) -> None:
        original_pen = QPen(connection.pen())
        if incoming:
            self.incoming_connections.append((connection, original_pen))
        else:
            self.outgoing_connections.append((connection, original_pen))

    def update_default_opacity(self, opacity: float) -> None:
        self.default_opacity = opacity
        if not self._is_highlighted:
            self.ellipse.setOpacity(opacity)

    def set_highlighted(self, highlighted: bool) -> None:
        if highlighted == self._is_highlighted:
            return
        self._is_highlighted = highlighted
        if highlighted:
            self.ellipse.setOpacity(1.0)
            self.ellipse.setZValue(self.default_z_value + 1)
        else:
            self.ellipse.setOpacity(self.default_opacity)
            self.ellipse.setZValue(self.default_z_value)
        for connection, original_pen in self.incoming_connections + self.outgoing_connections:
            _apply_connection_highlight(connection, original_pen, highlighted)


@dataclass
class GraphTransactionNode:
    detail: FullTxDetail
    item: "TransactionItem"
    default_pen: QPen = field(init=False)
    default_brush: QBrush = field(init=False)
    default_z_value: float = field(init=False)
    incoming_connections: List[Tuple[QGraphicsPathItem, QPen, GraphUtxoCircle | None]] = field(
        default_factory=list
    )
    outgoing_connections: List[Tuple[QGraphicsPathItem, QPen, GraphUtxoCircle | None]] = field(
        default_factory=list
    )
    _is_highlighted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.default_pen = QPen(self.item.pen())
        self.default_brush = QBrush(self.item.brush())
        self.default_z_value = self.item.zValue()
        self.item.set_highlight_target(self)
        self.item.label_item.set_highlight_target(self)

    def add_connection(
        self,
        connection: QGraphicsPathItem,
        circle: GraphUtxoCircle | None,
        *,
        incoming: bool,
    ) -> None:
        original_pen = QPen(connection.pen())
        record = (connection, original_pen, circle)
        if incoming:
            self.incoming_connections.append(record)
        else:
            self.outgoing_connections.append(record)

    def set_highlighted(self, highlighted: bool) -> None:
        if highlighted == self._is_highlighted:
            return
        self._is_highlighted = highlighted

        if highlighted:
            boosted_pen = QPen(self.default_pen)
            new_width = max(self.default_pen.widthF() * 1.5, self.default_pen.widthF() + 0.8)
            boosted_pen.setWidthF(new_width)
            pen_color = QColor(boosted_pen.color())
            pen_color.setAlphaF(1.0)
            boosted_pen.setColor(pen_color)

            boosted_brush = QBrush(self.default_brush)
            brush_color = QColor(boosted_brush.color())
            brush_color.setAlphaF(min(1.0, brush_color.alphaF() + 0.25))
            boosted_brush.setColor(brush_color)

            self.item.setPen(boosted_pen)
            self.item.setBrush(boosted_brush)
            self.item.setZValue(self.default_z_value + 1)
        else:
            self.item.setPen(QPen(self.default_pen))
            self.item.setBrush(QBrush(self.default_brush))
            self.item.setZValue(self.default_z_value)

        for connection, original_pen, circle in self.incoming_connections + self.outgoing_connections:
            _apply_connection_highlight(connection, original_pen, highlighted)
            if circle:
                circle.set_highlighted(highlighted)


class GraphLabelItem(QGraphicsTextItem):
    def __init__(
        self,
        signal_id: str,
        text: str,
        transaction_signal: pyqtBoundSignal,
        vertical_offset: float,
        color: QColor | ColorSchemeItem | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._signal_id = signal_id
        self._transaction_signal = transaction_signal
        self._vertical_offset = vertical_offset
        self._highlight_target: Highlightable | None = None
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._configure_alignment()
        self._apply_color(color)
        self._update_position()

    def mousePressEvent(self, event: Optional[QGraphicsSceneMouseEvent]) -> None:
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self._signal_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def set_highlight_target(self, target: Highlightable | None) -> None:
        self._highlight_target = target

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    def _apply_color(self, color: QColor | ColorSchemeItem | None) -> None:
        if isinstance(color, ColorSchemeItem):
            self.setDefaultTextColor(color.as_color())
        elif isinstance(color, QColor):
            self.setDefaultTextColor(color)
        else:
            self.setDefaultTextColor(ColorScheme.DEFAULT.as_color())

    def _configure_alignment(self) -> None:
        document = self.document()
        if not document:
            return

        option = document.defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        document.setDefaultTextOption(option)
        document.setTextWidth(self.boundingRect().width())

        self.setDocument(document)

    def _update_position(self) -> None:
        rect = self.boundingRect()
        self.setPos(-rect.width() / 2, self._vertical_offset)

    @property
    def bottom_y(self) -> float:
        rect = self.boundingRect()
        return self.pos().y() + rect.height()


class TransactionLabelItem(GraphLabelItem):
    MAX_LABEL_CHARS = 30

    def __init__(
        self,
        txid: str,
        text: str,
        transaction_signal: pyqtBoundSignal,
        vertical_offset: float,
        color: QColor | ColorSchemeItem | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(
            txid,
            text,
            transaction_signal=transaction_signal,
            vertical_offset=vertical_offset,
            color=color,
            parent=parent,
        )


class UtxoLabelItem(GraphLabelItem):
    def __init__(
        self,
        creating_txid: str,
        text: str,
        transaction_signal: pyqtBoundSignal,
        vertical_offset: float,
        color: QColor | ColorSchemeItem | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        self.creating_txid = creating_txid
        super().__init__(
            creating_txid,
            text,
            transaction_signal=transaction_signal,
            vertical_offset=vertical_offset,
            color=color,
            parent=parent,
        )

    def append_line(
        self,
        text: str,
        color: QColor | ColorSchemeItem | None = None,
    ) -> None:
        if not text:
            return

        document = self.document()
        if not document:
            return

        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if document.blockCount() > 0 and document.toPlainText():
            cursor.insertBlock()

        insert_color: QColor | None
        if isinstance(color, ColorSchemeItem):
            insert_color = color.as_color()
        elif isinstance(color, QColor):
            insert_color = color
        else:
            insert_color = None

        if insert_color is not None:
            char_format = QTextCharFormat()
            char_format.setForeground(insert_color)
            cursor.insertText(text, char_format)
        else:
            cursor.insertText(text)

        self._configure_alignment()
        self._update_position()


class TransactionItem(QGraphicsRectItem):
    BORDER_WIDTH = 1.6
    LABEL_MARGIN = 12.0
    DEFAULT_WIDTH = 100.0
    DEFAULT_HEIGHT = 44.0

    def __init__(
        self,
        detail: FullTxDetail,
        width: float,
        height: float,
        transaction_signal: pyqtBoundSignal,
        timestamp: datetime.datetime,
        position_x: float,
        axis_y: float,
        network: bdk.Network,
        wallet: Wallet | None,
        label_max_chars: int,
        label_color: QColor | ColorSchemeItem | None = ColorScheme.DEFAULT,
        show_txid=False,
    ) -> None:
        super().__init__(-width / 2, -height / 2, width, height)
        self.txid = detail.txid
        self.detail = detail
        self._transaction_signal = transaction_signal

        self.apply_color(ColorScheme.Purple)

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(2)
        self._highlight_target: Highlightable | None = None

        self.setPos(position_x, axis_y)

        highlight_color = self._transaction_input_color(wallet, detail)
        if highlight_color:
            self.apply_color(highlight_color)

        label_offset = self.rect().height() / 2 + self.LABEL_MARGIN
        label_value, display_label = self._resolve_label_value(wallet, detail, label_max_chars)
        display_identifier = (
            display_label if display_label else (short_tx_id(detail.txid) if show_txid else "")
        )
        label_text = f"{timestamp.strftime('%Y-%m-%d')}\n{display_identifier}"
        self.label_item = TransactionLabelItem(
            detail.txid,
            label_text,
            transaction_signal=transaction_signal,
            vertical_offset=label_offset,
            color=label_color,
            parent=self,
        )

        tooltip = self._transaction_tooltip(detail, timestamp, network)
        label_tooltip = f"{detail.txid}\n{label_value}" if label_value else detail.txid
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.setToolTip(tooltip)
            self.label_item.setToolTip(label_tooltip)

    def set_highlight_target(self, target: Highlightable | None) -> None:
        self._highlight_target = target

    def apply_color(self, color_item: ColorSchemeItem) -> None:
        border_color = color_item.as_color()
        fill_color = color_item.as_color(background=True)
        fill_color.setAlphaF(0.25)

        pen = QPen(border_color)
        pen.setWidthF(self.BORDER_WIDTH)
        self.setPen(pen)
        self.setBrush(fill_color)

    def mousePressEvent(self, event: Optional[QGraphicsSceneMouseEvent]) -> None:
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self.txid)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        if not event:
            return super().contextMenuEvent(event)

        menu = QMenu()
        jump_menu = menu.addMenu(translate("WalletGraphClient", "Jump to Input"))
        if jump_menu:

            inputs = list(self.detail.inputs.items()) if self.detail.inputs else []
            view = self._graph_view()
            has_jump_action = False

            if inputs:
                for outpoint_str, python_utxo in inputs:
                    txid, vout = self._split_outpoint(outpoint_str)
                    label = self._format_input_label(txid, vout, python_utxo)
                    action = jump_menu.addAction(label)
                    if action and (not txid or not view or not self._view_has_transaction(view, txid)):
                        action.setEnabled(False)
                        continue
                    has_jump_action = True
                    if action:
                        action.triggered.connect(partial(self._handle_jump_to_input, txid))
            else:
                placeholder = jump_menu.addAction(translate("WalletGraphClient", "No known inputs"))
                if placeholder:
                    placeholder.setEnabled(False)

            if not has_jump_action and inputs:
                placeholder = jump_menu.addAction(translate("WalletGraphClient", "No jump targets available"))
                if placeholder:
                    placeholder.setEnabled(False)

        menu.exec(event.screenPos().toPointF().toPoint())
        event.accept()

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    @staticmethod
    def _transaction_input_color(wallet: Wallet | None, detail: FullTxDetail) -> ColorSchemeItem | None:
        if not wallet:
            return None

        for python_utxo in detail.inputs.values():
            if not python_utxo:
                continue
            if wallet.is_change(python_utxo.address):
                return ColorScheme.YELLOW
            if wallet.is_my_address(python_utxo.address):
                return ColorScheme.GREEN

        return None

    def _graph_view(self):
        scene = self.scene()
        if not scene:
            return None
        for view in scene.views():
            if hasattr(view, "jump_to_transaction"):
                return view
        return None

    @staticmethod
    def _split_outpoint(outpoint: str) -> Tuple[str, str]:
        if ":" not in outpoint:
            return outpoint, ""
        txid, vout = outpoint.split(":", 1)
        return txid, vout

    def _format_input_label(self, txid: str, vout: str, python_utxo: PythonUtxo | None) -> str:
        short_id = short_tx_id(txid) if txid else translate("WalletGraphClient", "Unknown")
        base = f"{short_id}:{vout}" if vout else short_id
        if python_utxo and python_utxo.address:
            return f"{base} • {python_utxo.address}"
        return base

    def _handle_jump_to_input(self, txid: str) -> None:
        view = self._graph_view()
        if not view:
            if txid:
                self._transaction_signal.emit(txid)
            return

        jump_method = getattr(view, "jump_to_transaction", None)
        if callable(jump_method) and jump_method(txid):
            return
        if txid:
            self._transaction_signal.emit(txid)

    @staticmethod
    def _view_has_transaction(view, txid: str) -> bool:
        has_method = getattr(view, "has_transaction", None)
        if callable(has_method):
            try:
                return bool(has_method(txid))
            except Exception:  # pragma: no cover - defensive against unexpected view types
                logger.exception("Failed to determine if view has transaction %s", txid)
        return False

    @staticmethod
    def _resolve_label_value(
        wallet: Wallet | None, detail: FullTxDetail, label_max_chars: int
    ) -> Tuple[str, str]:
        label_value = ""
        if wallet:
            try:
                tx_label = wallet.get_label_for_txid(detail.txid)
            except Exception:  # pragma: no cover - defensive: label lookup should not crash UI
                logger.exception("Failed to fetch label for txid %s", detail.txid)
                tx_label = ""
            label_value = tx_label.strip() if tx_label else ""
        display_label = elide_text(label_value, label_max_chars) if label_value else ""
        return label_value, display_label

    @staticmethod
    def _transaction_tooltip(detail: FullTxDetail, timestamp: datetime.datetime, network: bdk.Network) -> str:
        abbreviated = short_tx_id(detail.txid)
        sent = Satoshis(detail.tx.sent, network).str_with_unit(color_formatting=None)
        received = Satoshis(detail.tx.received, network).str_with_unit(color_formatting=None)
        fee = (
            Satoshis(detail.tx.fee, network).str_with_unit(color_formatting=None)
            if detail.tx.fee is not None
            else translate("WalletGraphClient", "Unknown fee")
        )
        return (
            f"{translate('WalletGraphClient', 'Transaction')}: {abbreviated}\n"
            f"{translate('WalletGraphClient', 'Full txid')}: {detail.txid}\n"
            f"{translate('WalletGraphClient', 'Date')}: {timestamp.isoformat()}\n"
            f"{translate('WalletGraphClient', 'Received')}: {received}\n"
            f"{translate('WalletGraphClient', 'Sent')}: {sent}\n"
            f"{translate('WalletGraphClient', 'Fee')}: {fee}"
        )


class WalletGraphView(QGraphicsView):
    transactionClicked = pyqtSignal(str)

    MIN_TX_SPACING = 180.0
    MIN_SCENE_WIDTH = 900.0
    AXIS_Y = 0.0

    def __init__(self, signals: Signals, network: bdk.Network, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.signals = signals
        self.network = network

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._utxo_items: Dict[str, GraphUtxoCircle] = {}
        self._transactions: Dict[str, GraphTransactionNode] = {}
        self._tx_positions: Dict[str, float] = {}
        self._current_wallet: Wallet | None = None
        self._current_details: List[FullTxDetail] = []

    def clear(self) -> None:
        self._scene.clear()
        self._utxo_items.clear()
        self._transactions.clear()
        self._tx_positions.clear()
        self._current_wallet = None
        self._current_details = []
        self.resetTransform()
        self._scene.setSceneRect(-400, -200, 800, 400)

    @property
    def current_wallet(self) -> Wallet | None:
        return self._current_wallet

    @property
    def current_details(self) -> List[FullTxDetail]:
        return list(self._current_details)

    def wheelEvent(self, event: Optional[QWheelEvent]) -> None:
        if not event:
            return
        if event.angleDelta().y() > 0:
            factor = 1.2
        else:
            factor = 1 / 1.2
        self.scale(factor, factor)
        event.accept()

    def render_graph(self, wallet: Wallet, full_tx_details: Iterable[FullTxDetail]) -> None:
        self.clear()
        details_list = list(full_tx_details)
        self._current_wallet = wallet
        self._current_details = details_list

        if not details_list:
            empty_text = self._scene.addText(translate("WalletGraphClient", "No transactions to display."))
            if empty_text:
                empty_text.setDefaultTextColor(ColorScheme.GRAY.as_color())
                empty_text.setPos(
                    -empty_text.boundingRect().width() / 2, -empty_text.boundingRect().height() / 2
                )
            return

        timestamped: List[Tuple[FullTxDetail, float]] = []
        fallback_base = time.time()
        for index, detail in enumerate(details_list):
            fallback = fallback_base + index
            timestamped.append((detail, self._detail_timestamp(detail, fallback=fallback)))

        timestamped.sort(key=lambda item: item[1])
        sorted_details = [item[0] for item in timestamped]
        times = [item[1] for item in timestamped]

        min_time = min(times)
        max_time = max(times)
        time_range = max(max_time - min_time, 1.0)
        target_width = max((len(times) - 1) * self.MIN_TX_SPACING, self.MIN_SCENE_WIDTH)
        scale = target_width / time_range if time_range else self.MIN_TX_SPACING

        self._tx_positions.clear()
        positions: List[float] = []
        for idx, (detail, timestamp) in enumerate(zip(sorted_details, times)):
            x_pos = (timestamp - min_time) * scale
            if positions:
                x_pos = max(x_pos, positions[-1] + self.MIN_TX_SPACING)
            positions.append(x_pos)
            self._tx_positions[detail.txid] = x_pos

        max_utxo_value = self._max_output_value(sorted_details)

        axis_left = positions[0] - 200.0
        axis_right = positions[-1] + 200.0
        axis_pen = QPen(ColorScheme.GRAY.as_color())
        axis_pen.setStyle(Qt.PenStyle.DashLine)
        self._scene.addLine(axis_left, self.AXIS_Y, axis_right, self.AXIS_Y, axis_pen)

        for detail, x_pos, timestamp in zip(sorted_details, positions, times):
            dt = datetime.datetime.fromtimestamp(timestamp)
            tx_item = TransactionItem(
                detail,
                TransactionItem.DEFAULT_WIDTH,
                TransactionItem.DEFAULT_HEIGHT,
                transaction_signal=self.transactionClicked,
                timestamp=dt,
                position_x=x_pos,
                axis_y=self.AXIS_Y,
                network=self.network,
                wallet=self._current_wallet,
                label_max_chars=TransactionLabelItem.MAX_LABEL_CHARS,
                label_color=ColorScheme.DEFAULT,
            )
            self._scene.addItem(tx_item)
            tx_node = GraphTransactionNode(detail=detail, item=tx_item)
            self._transactions[detail.txid] = tx_node

            tick_pen = QPen(ColorScheme.GRAY.as_color())
            tick_pen.setWidthF(1.0)
            self._scene.addLine(x_pos, self.AXIS_Y - 6, x_pos, self.AXIS_Y + 6, tick_pen)

            self._render_inputs(detail, tx_node)
            self._render_outputs(detail, tx_node, max_utxo_value)

        scene_rect = self._scene.itemsBoundingRect().adjusted(-150, -200, 150, 200)
        self._scene.setSceneRect(scene_rect)
        self.centerOn((scene_rect.left() + scene_rect.right()) / 2, self.AXIS_Y)

    def center_on_transaction(self, txid: str) -> bool:
        position = self._tx_positions.get(txid)
        if position is None:
            return False
        self.centerOn(position, self.AXIS_Y)
        return True

    def has_transaction(self, txid: str) -> bool:
        return txid in self._transactions

    def jump_to_transaction(self, txid: str) -> bool:
        return self.center_on_transaction(txid)

    def _detail_timestamp(self, detail: FullTxDetail, fallback: float) -> float:
        try:
            dt = detail.tx.get_datetime(fallback_timestamp=fallback)
        except ValueError:
            dt = datetime.datetime.fromtimestamp(fallback)
        return dt.timestamp()

    def _max_output_value(self, details: Iterable[FullTxDetail]) -> int:
        values = [
            python_utxo.value for detail in details for python_utxo in detail.outputs.values() if python_utxo
        ]
        return max(values) if values else 0

    def _render_inputs(self, detail: FullTxDetail, tx_node: GraphTransactionNode) -> None:
        inputs = list(detail.inputs.items())
        if not inputs:
            return
        tx_item = tx_node.item
        for index, (outpoint_str, python_utxo) in enumerate(inputs):
            if python_utxo and outpoint_str in self._utxo_items:
                circle = self._utxo_items[outpoint_str]
                self._connect_transaction_and_utxo(
                    tx_node,
                    circle,
                    utxo_is_input=True,
                )
                continue

            ellipse = UtxoEllipseItem.create_input_placeholder(
                outpoint_str,
                python_utxo,
                transaction_signal=self.transactionClicked,
                axis_y=self.AXIS_Y,
                tx_item=tx_item,
                tx_width=TransactionItem.DEFAULT_WIDTH,
                input_gap=UtxoEllipseItem.INPUT_GAP,
                vertical_spacing=UtxoEllipseItem.VERTICAL_SPACING,
                min_radius=UtxoEllipseItem.MIN_RADIUS,
                index=index,
            )
            self._scene.addItem(ellipse)
            placeholder_circle = GraphUtxoCircle(
                utxo=python_utxo,
                ellipse=ellipse,
            )
            self._connect_transaction_and_utxo(
                tx_node,
                placeholder_circle,
                utxo_is_input=True,
            )

    def _render_outputs(
        self, detail: FullTxDetail, tx_node: GraphTransactionNode, max_utxo_value: int
    ) -> None:
        outputs = list(detail.outputs.items())
        if not outputs:
            return

        tx_item = tx_node.item
        for index, (outpoint_str, python_utxo) in enumerate(outputs):
            if not python_utxo:
                continue
            ellipse = UtxoEllipseItem.create_output(
                detail,
                outpoint_str,
                python_utxo,
                transaction_signal=self.transactionClicked,
                network=self.network,
                wallet=self._current_wallet,
                signals=self.signals,
                label_max_chars=UtxoEllipseItem.LABEL_MAX_CHARS,
                max_utxo_value=max_utxo_value,
                min_radius=UtxoEllipseItem.MIN_RADIUS,
                max_radius=UtxoEllipseItem.MAX_RADIUS,
                tx_item=tx_item,
                axis_y=self.AXIS_Y,
                tx_width=TransactionItem.DEFAULT_WIDTH,
                output_gap=UtxoEllipseItem.OUTPUT_GAP,
                vertical_spacing=UtxoEllipseItem.VERTICAL_SPACING,
                index=index,
            )
            self._scene.addItem(ellipse)

            circle = GraphUtxoCircle(
                utxo=python_utxo,
                ellipse=ellipse,
            )
            self._utxo_items[outpoint_str] = circle

            self._connect_transaction_and_utxo(
                tx_node,
                circle,
                utxo_is_input=False,
            )

            if python_utxo.is_spent_by_txid and python_utxo.is_spent_by_txid in self._tx_positions:
                # draw a subtle hint towards the spending transaction
                spending_x = self._tx_positions[python_utxo.is_spent_by_txid]
                connection = self._connect_points(
                    ellipse.pos(),
                    QPointF(spending_x - TransactionItem.DEFAULT_WIDTH / 2, self.AXIS_Y),
                    ellipse.pen().color(),
                )
                circle.add_connection(connection, incoming=False)
                spending_node = self._transactions.get(python_utxo.is_spent_by_txid)
                if spending_node:
                    spending_node.add_connection(connection, circle, incoming=True)

    def _connect_transaction_and_utxo(
        self,
        tx_node: GraphTransactionNode,
        circle: GraphUtxoCircle,
        *,
        utxo_is_input: bool,
    ) -> QGraphicsPathItem:
        if utxo_is_input and circle.utxo:
            circle.ellipse.setOpacity(0.45)
            circle.update_default_opacity(circle.ellipse.opacity())

        if utxo_is_input:
            start = circle.ellipse.pos()
            end_point = QPointF(
                tx_node.item.pos().x() - TransactionItem.DEFAULT_WIDTH / 2,
                self.AXIS_Y,
            )
        else:
            start = QPointF(
                tx_node.item.pos().x() + TransactionItem.DEFAULT_WIDTH / 2,
                self.AXIS_Y,
            )
            end_point = circle.ellipse.pos()

        color = circle.ellipse.pen().color()
        connection = self._connect_points(start, end_point, color)
        circle.add_connection(connection, incoming=not utxo_is_input)
        tx_node.add_connection(connection, circle, incoming=utxo_is_input)
        return connection

    def _connect_points(self, start: QPointF, end: QPointF, color: QColor) -> QGraphicsPathItem:
        path = QPainterPath(start)
        control_offset = (end.x() - start.x()) / 2
        control_point_1 = QPointF(start.x() + control_offset, start.y())
        control_point_2 = QPointF(end.x() - control_offset, end.y())
        path.cubicTo(control_point_1, control_point_2, end)

        pen = QPen(color)
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        connection = QGraphicsPathItem(path)
        connection.setPen(pen)
        connection.setZValue(0)
        self._scene.addItem(connection)
        return connection


class WalletGraphClient(PluginClient):
    plugin_conditions = PluginConditions()
    title = translate("WalletGraphClient", "Wallet Graph")
    description = translate(
        "WalletGraphClient",
        "Visualize how your wallet transactions create and spend UTXOs across time.",
    )
    provider = "Bitcoin Safe"

    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        enabled: bool = False,
    ) -> None:
        super().__init__(enabled=enabled, icon=svg_tools.get_QIcon("wallet-graph-icon.svg"))
        self.signals = signals
        self.network = network
        self.server: WalletGraphServer | None = None
        self.wallet_id: str | None = None
        self._wallet_signal_connected = False

        self.graph_view = WalletGraphView(signals=signals, network=network)

        self.refresh_button = QPushButton()
        self.refresh_button.clicked.connect(self.refresh_graph)
        self.refresh_button.setEnabled(enabled)

        self.export_button = QPushButton()
        self.export_button.clicked.connect(self.on_export_graph)
        self.export_button.setEnabled(False)

        self.instructions_label = QLabel(
            translate(
                "WalletGraphClient",
                "Drag to explore the timeline. Click or right-click a transaction, txid, or UTXO for options.",
            )
        )
        self.instructions_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(self.instructions_label)
        controls.addStretch()
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        layout.addWidget(self.graph_view)

        self.graph_view.transactionClicked.connect(self._on_transaction_clicked)

        self.updateUi()

    def get_widget(self) -> QWidget:
        return self

    def save_connection_details(self, server: WalletGraphServer) -> None:
        self.server = server
        self.wallet_id = server.wallet_id
        server.set_enabled(self.enabled)
        if self.enabled:
            self.refresh_graph()

    def load(self) -> None:
        if self.server:
            self.server.set_enabled(True)
        self._connect_wallet_signal()
        self.refresh_graph()
        logger.debug("WalletGraphClient loaded")

    def unload(self) -> None:
        self._disconnect_wallet_signal()
        if self.server:
            self.server.set_enabled(False)
        self.graph_view.clear()
        self.export_button.setEnabled(False)
        logger.debug("WalletGraphClient unloaded")

    def on_set_enabled(self, value: bool) -> None:
        super().on_set_enabled(value)
        self.refresh_button.setEnabled(value)
        if self.server:
            self.server.set_enabled(value)

    def refresh_graph(self) -> None:
        if not self.enabled or not self.server:
            return
        wallet = self.server.get_wallet()
        if not wallet:
            self.graph_view.clear()
            self.export_button.setEnabled(False)
            return
        details_dict = wallet.get_dict_fulltxdetail()
        # ensure it is sorted, such that parent child relationships can be resolved
        full_tx_details = [
            full_tx_detail
            for tx in wallet.sorted_delta_list_transactions()
            if (full_tx_detail := details_dict.get(tx.txid))
        ]
        if not full_tx_details:
            self.graph_view.clear()
            self.export_button.setEnabled(False)
            return

        self.graph_view.render_graph(wallet=wallet, full_tx_details=full_tx_details)
        self.export_button.setEnabled(bool(full_tx_details))

    def _on_transaction_clicked(self, txid: str) -> None:
        self.signals.open_tx_like.emit(PackagedTxLike(tx_like=txid, focus_ui_elements=UiElements.diagram))

    def _connect_wallet_signal(self) -> None:
        if self._wallet_signal_connected or not self.wallet_id:
            return
        wallet_signal = self.signals.wallet_signals.get(self.wallet_id)
        if not wallet_signal:
            logger.warning("Wallet signal not found for wallet %s", self.wallet_id)
            return
        wallet_signal.updated.connect(self.on_wallet_updated)
        self._wallet_signal_connected = True

    def _disconnect_wallet_signal(self) -> None:
        if not self._wallet_signal_connected or not self.wallet_id:
            return
        wallet_signal = self.signals.wallet_signals.get(self.wallet_id)
        if not wallet_signal:
            logger.warning("Wallet signal not found for wallet %s", self.wallet_id)
            self._wallet_signal_connected = False
            return
        try:
            wallet_signal.updated.disconnect(self.on_wallet_updated)
        except TypeError:
            pass
        self._wallet_signal_connected = False

    def on_wallet_updated(self, update_filter: UpdateFilter) -> None:
        if not self.enabled:
            return
        logger.debug("WalletGraphClient refreshing after wallet update %s", update_filter)
        self.refresh_graph()

    def on_export_graph(self) -> None:
        if not self.server or not self.graph_view.current_details or not self.graph_view.current_wallet:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export wallet graph"),
            f"{self.server.wallet_id}.graphml",
            filter="GraphML (*.graphml);;All Files (*.*)",
            initialFilter="GraphML (*.graphml)",
        )
        if not file_path:
            return

        graphml = self._build_graphml(details=self.graph_view.current_details)
        try:
            with open(file_path, "wb") as fp:
                fp.write(graphml)
        except OSError as exc:
            Message(
                self.tr("Could not export the wallet graph: {error}").format(error=str(exc)),
                type=MessageType.Error,
            )
            logger.exception("Failed to export wallet graph")
            return

        Message(
            self.tr("Wallet graph exported to {path}").format(path=file_path),
            type=MessageType.Info,
        )

    def _build_graphml(self, details: Iterable[FullTxDetail]) -> bytes:
        # Ensure the default GraphML namespace is registered (avoids ns0 prefixes)
        ET.register_namespace("", "http://graphml.graphdrawing.org/xmlns")
        root = ET.Element("graphml")

        key_specs = [
            ("d0", "node", "type", "string"),
            ("d1", "node", "timestamp", "string"),
            ("d2", "node", "label", "string"),
            ("d3", "node", "address", "string"),
            ("d4", "node", "status", "string"),
            ("d5", "node", "value_sats", "long"),  # prefer numeric type for sats
            ("d6", "node", "color", "string"),
            ("d7", "node", "is_mine", "boolean"),
        ]
        for key_id, domain, name, key_type in key_specs:
            ET.SubElement(
                root,
                "key",
                attrib={"for": domain, "attr.name": name, "attr.type": key_type},
                id=key_id,
            )

        graph = ET.SubElement(root, "graph", id="G", edgedefault="directed")

        utxo_nodes: Dict[str, PythonUtxo] = {}
        edge_counter = 0

        def _utxo_id(utxo: PythonUtxo) -> str:
            # Single source of truth for UTXO node ids
            return str(utxo.outpoint)

        fallback_base = time.time()
        timestamped_details = [
            (detail, self.graph_view._detail_timestamp(detail, fallback_base + idx))
            for idx, detail in enumerate(details)
        ]
        timestamped_details.sort(key=lambda item: item[1])

        for detail, timestamp in timestamped_details:
            tx_node = ET.SubElement(graph, "node", id=detail.txid)
            self._set_data(tx_node, "d0", "transaction")

            # Use explicit UTC ISO-8601 with 'Z'
            ts_iso = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat()
            if ts_iso.endswith("+00:00"):
                ts_iso = ts_iso[:-6] + "Z"
            self._set_data(tx_node, "d1", ts_iso)

            self._set_data(tx_node, "d2", detail.txid)

            # Outputs: edge from transaction -> UTXO
            for _, _utxo in detail.outputs.items():
                if not _utxo:
                    continue
                node_id = _utxo_id(_utxo)
                if node_id not in utxo_nodes:
                    utxo_nodes[node_id] = _utxo
                    self._create_utxo_node(graph, _utxo)  # must create with the same node_id
                ET.SubElement(
                    graph,
                    "edge",
                    id=f"e{edge_counter}",
                    source=detail.txid,
                    target=node_id,
                )
                edge_counter += 1

            # Inputs: edge from UTXO -> transaction
            for index, (_, utxo) in enumerate(detail.inputs.items()):
                if utxo:
                    node_id = _utxo_id(utxo)
                    if node_id not in utxo_nodes:
                        utxo_nodes[node_id] = utxo
                        self._create_utxo_node(graph, utxo)
                    ET.SubElement(
                        graph,
                        "edge",
                        id=f"e{edge_counter}",
                        source=node_id,
                        target=detail.txid,
                    )
                    edge_counter += 1
                    continue

                # External/spent-but-unknown input
                external_id = f"external-{detail.txid}-{index}"
                node = ET.SubElement(graph, "node", id=external_id)
                self._set_data(node, "d0", "external_utxo")
                self._set_data(node, "d2", external_id)
                self._set_data(node, "d4", "spent")
                self._set_data(node, "d6", ColorScheme.Purple.as_color().name())
                ET.SubElement(
                    graph,
                    "edge",
                    id=f"e{edge_counter}",
                    source=external_id,
                    target=detail.txid,
                )
                edge_counter += 1

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _create_utxo_node(self, graph: ET.Element, utxo: PythonUtxo) -> None:
        node_id = str(utxo.outpoint)
        node = ET.SubElement(graph, "node", id=node_id)
        status = "spent" if utxo.is_spent_by_txid else "unspent"
        wallet = self.graph_view.current_wallet
        color = UtxoEllipseItem._color_for_utxo(utxo, wallet=wallet, signals=self.signals)
        is_mine = wallet.is_my_address(utxo.address) if wallet else False
        self._set_data(node, "d0", "utxo")
        self._set_data(node, "d2", node_id)
        self._set_data(node, "d3", utxo.address)
        self._set_data(node, "d4", status)
        self._set_data(node, "d5", str(utxo.value))
        self._set_data(node, "d6", color.name())
        self._set_data(node, "d7", "true" if is_mine else "false")

    @staticmethod
    def _set_data(node: ET.Element, key: str, value: str) -> None:
        ET.SubElement(node, "data", key=key).text = value

    def updateUi(self) -> None:
        self.export_button.setText(self.tr("Export graph…"))
        self.refresh_button.setText(self.tr("Refresh"))
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.refresh_button.setToolTip(self.tr("Redraw the wallet graph."))
        self.instructions_label.setText(
            self.tr(
                "Drag to explore the timeline. Click or right-click a transaction, txid, or UTXO for options."
            )
        )
        super().updateUi()
