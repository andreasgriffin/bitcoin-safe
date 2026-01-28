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
from dataclasses import dataclass, field
from functools import partial
from typing import Protocol

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import BitcoinSymbol, Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import Qt, pyqtBoundSignal
from PyQt6.QtGui import QBrush, QColor, QPen, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QMenu,
)

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.util import ColorScheme, ColorSchemeItem
from bitcoin_safe.i18n import translate
from bitcoin_safe.pythonbdk_types import FullTxDetail, PythonUtxo
from bitcoin_safe.signals import WalletSignals
from bitcoin_safe.tx import short_tx_id
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)
ENABLE_WALLET_GRAPH_TOOLTIPS = False


def elide_text(text: str, max_length: int) -> str:
    """Elide text."""
    if max_length <= 0 or len(text) <= max_length:
        return text
    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


class Highlightable(Protocol):
    def set_highlighted(self, highlighted: bool) -> None:
        """Set highlighted."""
        ...


def _apply_connection_highlight(connection: QGraphicsPathItem, original_pen: QPen, highlighted: bool) -> None:
    """Apply connection highlight."""
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
        """Initialize instance."""
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
        """Set highlight target."""
        self._highlight_target = target
        self.value_label.set_highlight_target(target)

    def mousePressEvent(self, event) -> None:
        """MousePressEvent."""
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
        """Append label line."""
        if not text:
            return None
        self.value_label.append_line(text, color=color)
        if self._tooltip_text:
            if ENABLE_WALLET_GRAPH_TOOLTIPS:
                self.value_label.setToolTip(self._tooltip_text)
        return self.value_label

    def set_composite_tooltip(self, tooltip: str) -> None:
        """Set composite tooltip."""
        self._tooltip_text = tooltip
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.setToolTip(tooltip)
            self.value_label.setToolTip(tooltip)

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        """HoverEnterEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        """HoverLeaveEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    def _center_view_on_transaction(self, txid: str | None) -> None:
        """Center view on transaction."""
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
        """Radius for value."""
        if max_value <= 0:
            return min_radius
        ratio = value / max_value
        return min_radius + ratio * (max_radius - min_radius)

    @staticmethod
    def _color_for_utxo(utxo: PythonUtxo, wallet: Wallet | None, wallet_signals: WalletSignals) -> QColor:
        """Color for utxo."""
        if not wallet:
            return ColorScheme.Purple.as_color()
        color = AddressEdit.color_address(utxo.address, wallet, wallet_signals)
        if color:
            return color
        return ColorScheme.Purple.as_color()

    @classmethod
    def create_output(
        cls,
        detail: FullTxDetail,
        outpoint_str: str,
        python_utxo: PythonUtxo,
        transaction_signal: SignalProtocol[[str]],
        network: bdk.Network,
        wallet: Wallet | None,
        wallet_signals: WalletSignals,
        label_max_chars: int,
        max_utxo_value: int,
        min_radius: float,
        max_radius: float,
        tx_item: TransactionItem,
        axis_y: float,
        tx_width: float,
        output_gap: float,
        vertical_spacing: float,
        index: int,
        horizontal_offset: float | None = None,
    ) -> UtxoEllipseItem:
        """Create output."""
        radius = cls._radius_for_value(python_utxo.value, max_utxo_value, min_radius, max_radius)
        label_text = Satoshis(python_utxo.value, network).str_with_unit(
            color_formatting=None,
            btc_symbol=wallet.config.bitcoin_symbol.value if wallet else BitcoinSymbol.ISO.value,
        )
        ellipse = cls(
            detail.txid,
            python_utxo.is_spent_by_txid,
            radius,
            transaction_signal=transaction_signal,  # type: ignore
            value_text=label_text,
            value_label_color=ColorScheme.DEFAULT,
        )

        color = cls._color_for_utxo(python_utxo, wallet, wallet_signals)
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
                logger.exception(f"Failed to fetch label for address {python_utxo.address}")
                utxo_label = ""
            utxo_label_value = utxo_label.strip() if utxo_label else ""
            display_utxo_label = elide_text(utxo_label_value, label_max_chars) if utxo_label_value else ""
            ellipse.append_label_line(display_utxo_label)

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
        transaction_signal: SignalProtocol[[str]],
        axis_y: float,
        tx_item: TransactionItem,
        tx_width: float,
        input_gap: float,
        vertical_spacing: float,
        min_radius: float,
        index: int,
        horizontal_offset: float | None = None,
    ) -> UtxoEllipseItem:
        """Create input placeholder."""
        creating_txid = outpoint_str.split(":", 1)[0] if outpoint_str else ""
        label_text = translate("WalletGraphClient", "External input") if not python_utxo else outpoint_str
        offset = -min_radius - 20
        ellipse = cls(
            creating_txid,
            python_utxo.is_spent_by_txid if python_utxo else None,
            min_radius,
            transaction_signal=transaction_signal,  # type: ignore
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
    incoming_connections: list[tuple[QGraphicsPathItem, QPen]] = field(default_factory=list)
    outgoing_connections: list[tuple[QGraphicsPathItem, QPen]] = field(default_factory=list)
    _is_highlighted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Post init."""
        self.default_opacity = self.ellipse.opacity()
        self.default_z_value = self.ellipse.zValue()
        self.ellipse.set_highlight_target(self)

    def add_connection(self, connection: QGraphicsPathItem, incoming: bool) -> None:
        """Add connection."""
        original_pen = QPen(connection.pen())
        if incoming:
            self.incoming_connections.append((connection, original_pen))
        else:
            self.outgoing_connections.append((connection, original_pen))

    def update_default_opacity(self, opacity: float) -> None:
        """Update default opacity."""
        self.default_opacity = opacity
        if not self._is_highlighted:
            self.ellipse.setOpacity(opacity)

    def set_highlighted(self, highlighted: bool) -> None:
        """Set highlighted."""
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
    item: TransactionItem
    default_pen: QPen = field(init=False)
    default_brush: QBrush = field(init=False)
    default_z_value: float = field(init=False)
    incoming_connections: list[tuple[QGraphicsPathItem, QPen, GraphUtxoCircle | None]] = field(
        default_factory=list
    )
    outgoing_connections: list[tuple[QGraphicsPathItem, QPen, GraphUtxoCircle | None]] = field(
        default_factory=list
    )
    _is_highlighted: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        """Post init."""
        self.default_pen = QPen(self.item.pen())
        self.default_brush = QBrush(self.item.brush())
        self.default_z_value = self.item.zValue()
        self.item.set_highlight_target(self)
        self.item.label_item.set_highlight_target(self)

    def add_connection(
        self,
        connection: QGraphicsPathItem,
        circle: GraphUtxoCircle | None,
        incoming: bool,
    ) -> None:
        """Add connection."""
        original_pen = QPen(connection.pen())
        record = (connection, original_pen, circle)
        if incoming:
            self.incoming_connections.append(record)
        else:
            self.outgoing_connections.append(record)

    def set_highlighted(self, highlighted: bool) -> None:
        """Set highlighted."""
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
        """Initialize instance."""
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

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """MousePressEvent."""
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self._signal_id)
            event.accept()
            return
        super().mousePressEvent(event)

    def set_highlight_target(self, target: Highlightable | None) -> None:
        """Set highlight target."""
        self._highlight_target = target

    def hoverEnterEvent(self, event) -> None:  # type: ignore[override]
        """HoverEnterEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        """HoverLeaveEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    def _apply_color(self, color: QColor | ColorSchemeItem | None) -> None:
        """Apply color."""
        if isinstance(color, ColorSchemeItem):
            self.setDefaultTextColor(color.as_color())
        elif isinstance(color, QColor):
            self.setDefaultTextColor(color)
        else:
            self.setDefaultTextColor(ColorScheme.DEFAULT.as_color())

    def _configure_alignment(self) -> None:
        """Configure alignment."""
        document = self.document()
        if not document:
            return

        option = document.defaultTextOption()
        option.setAlignment(Qt.AlignmentFlag.AlignCenter)
        document.setDefaultTextOption(option)
        document.setTextWidth(self.boundingRect().width())

        self.setDocument(document)

    def _update_position(self) -> None:
        """Update position."""
        rect = self.boundingRect()
        self.setPos(-rect.width() / 2, self._vertical_offset)

    @property
    def bottom_y(self) -> float:
        """Bottom y."""
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
        """Initialize instance."""
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
        """Initialize instance."""
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
        """Append line."""
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
        transaction_signal: SignalProtocol[[str]],
        timestamp: datetime.datetime,
        position_x: float,
        axis_y: float,
        network: bdk.Network,
        wallet: Wallet | None,
        label_max_chars: int,
        label_color: QColor | ColorSchemeItem | None = ColorScheme.DEFAULT,
        show_txid=False,
    ) -> None:
        """Initialize instance."""
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
            transaction_signal=transaction_signal,  # type: ignore
            vertical_offset=label_offset,
            color=label_color,
            parent=self,
        )

        tooltip = self._transaction_tooltip(
            detail,
            timestamp,
            network,
            btc_symbol=wallet.config.bitcoin_symbol.value if wallet else BitcoinSymbol.ISO.value,
        )
        label_tooltip = f"{detail.txid}\n{label_value}" if label_value else detail.txid
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.setToolTip(tooltip)
            self.label_item.setToolTip(label_tooltip)

    def set_highlight_target(self, target: Highlightable | None) -> None:
        """Set highlight target."""
        self._highlight_target = target

    def apply_color(self, color_item: ColorSchemeItem) -> None:
        """Apply color."""
        border_color = color_item.as_color()
        fill_color = color_item.as_color(background=True)
        fill_color.setAlphaF(0.25)

        pen = QPen(border_color)
        pen.setWidthF(self.BORDER_WIDTH)
        self.setPen(pen)
        self.setBrush(fill_color)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent | None) -> None:
        """MousePressEvent."""
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self.txid)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        """ContextMenuEvent."""
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
        """HoverEnterEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # type: ignore[override]
        """HoverLeaveEvent."""
        if self._highlight_target:
            self._highlight_target.set_highlighted(False)
        super().hoverLeaveEvent(event)

    @staticmethod
    def _transaction_input_color(wallet: Wallet | None, detail: FullTxDetail) -> ColorSchemeItem | None:
        """Transaction input color."""
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
        """Graph view."""
        scene = self.scene()
        if not scene:
            return None
        for view in scene.views():
            if hasattr(view, "jump_to_transaction"):
                return view
        return None

    @staticmethod
    def _split_outpoint(outpoint: str) -> tuple[str, str]:
        """Split outpoint."""
        if ":" not in outpoint:
            return outpoint, ""
        txid, vout = outpoint.split(":", 1)
        return txid, vout

    def _format_input_label(self, txid: str, vout: str, python_utxo: PythonUtxo | None) -> str:
        """Format input label."""
        short_id = short_tx_id(txid) if txid else translate("WalletGraphClient", "Unknown")
        base = f"{short_id}:{vout}" if vout else short_id
        if python_utxo and python_utxo.address:
            return f"{base} • {python_utxo.address}"
        return base

    def _handle_jump_to_input(self, txid: str) -> None:
        """Handle jump to input."""
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
        """View has transaction."""
        has_method = getattr(view, "has_transaction", None)
        if callable(has_method):
            try:
                return bool(has_method(txid))
            except Exception:  # pragma: no cover - defensive against unexpected view types
                logger.exception(f"Failed to determine if view has transaction {txid}")
        return False

    @staticmethod
    def _resolve_label_value(
        wallet: Wallet | None, detail: FullTxDetail, label_max_chars: int
    ) -> tuple[str, str]:
        """Resolve label value."""
        label_value = ""
        if wallet:
            try:
                tx_label = wallet.get_label_for_txid(detail.txid)
            except Exception:  # pragma: no cover - defensive: label lookup should not crash UI
                logger.exception(f"Failed to fetch label for txid {detail.txid}")
                tx_label = ""
            label_value = tx_label.strip() if tx_label else ""
        display_label = elide_text(label_value, label_max_chars) if label_value else ""
        return label_value, display_label

    @staticmethod
    def _transaction_tooltip(
        detail: FullTxDetail, timestamp: datetime.datetime, network: bdk.Network, btc_symbol: str
    ) -> str:
        """Transaction tooltip."""
        abbreviated = short_tx_id(detail.txid)
        sent = Satoshis(detail.tx.sent, network).str_with_unit(color_formatting=None, btc_symbol=btc_symbol)
        received = Satoshis(detail.tx.received, network).str_with_unit(
            color_formatting=None, btc_symbol=btc_symbol
        )
        fee = (
            Satoshis(detail.tx.fee, network).str_with_unit(color_formatting=None, btc_symbol=btc_symbol)
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
