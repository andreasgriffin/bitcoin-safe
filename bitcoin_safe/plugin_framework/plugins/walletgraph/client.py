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
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from PyQt6.QtCore import QPointF, Qt, pyqtBoundSignal, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QWheelEvent
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


def elide_text(text: str, max_length: int) -> str:
    if max_length <= 0 or len(text) <= max_length:
        return text
    if max_length == 1:
        return "…"
    return f"{text[: max_length - 1]}…"


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
        self._additional_labels: List[UtxoLabelItem] = []
        self._tooltip_text: str | None = None

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

    def add_secondary_label(
        self,
        text: str,
        color: QColor | ColorSchemeItem | None = None,
        spacing: float = 1.0,
    ) -> UtxoLabelItem:
        previous_bottom = (
            self._additional_labels[-1].bottom_y if self._additional_labels else self.value_label.bottom_y
        )
        label = UtxoLabelItem(
            self.creating_txid,
            text,
            transaction_signal=self._transaction_signal,
            vertical_offset=previous_bottom + spacing,
            color=color,
            parent=self,
        )
        self._additional_labels.append(label)
        if self._tooltip_text:
            label.setToolTip(self._tooltip_text)
        return label

    def set_wallet_label(
        self,
        text: str,
        color: QColor | ColorSchemeItem | None = None,
        spacing: float = 1.0,
    ) -> UtxoLabelItem | None:
        if not text:
            return None
        return self.add_secondary_label(text, color=color, spacing=spacing)

    def set_composite_tooltip(self, tooltip: str) -> None:
        self._tooltip_text = tooltip
        self.setToolTip(tooltip)
        self.value_label.setToolTip(tooltip)
        for label in self._additional_labels:
            label.setToolTip(tooltip)

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
            ellipse.set_wallet_label(display_utxo_label)

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
        ellipse.setAcceptHoverEvents(False)
        ellipse.setCursor(Qt.CursorShape.ArrowCursor)
        ellipse.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        ellipse.value_label.setAcceptHoverEvents(False)
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


class TransactionLabelItem(QGraphicsTextItem):
    MAX_LABEL_CHARS = 40

    def __init__(
        self,
        txid: str,
        text: str,
        transaction_signal: pyqtBoundSignal,
        vertical_offset: float,
        color: QColor | ColorSchemeItem | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.txid = txid
        self._transaction_signal = transaction_signal
        self._vertical_offset = vertical_offset
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_color(color)
        self._update_position()

    def mousePressEvent(self, event: Optional[QGraphicsSceneMouseEvent]) -> None:
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self.txid)
            event.accept()
            return
        super().mousePressEvent(event)

    def _apply_color(self, color: QColor | ColorSchemeItem | None) -> None:
        if isinstance(color, ColorSchemeItem):
            self.setDefaultTextColor(color.as_color())
        elif isinstance(color, QColor):
            self.setDefaultTextColor(color)
        else:
            self.setDefaultTextColor(ColorScheme.DEFAULT.as_color())

    def _update_position(self) -> None:
        rect = self.boundingRect()
        self.setPos(-rect.width() / 2, self._vertical_offset)

    @property
    def bottom_y(self) -> float:
        rect = self.boundingRect()
        return self.pos().y() + rect.height()


class UtxoLabelItem(QGraphicsTextItem):
    def __init__(
        self,
        creating_txid: str,
        text: str,
        transaction_signal: pyqtBoundSignal,
        vertical_offset: float,
        color: QColor | ColorSchemeItem | None = None,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.creating_txid = creating_txid
        self._transaction_signal = transaction_signal
        self._vertical_offset = vertical_offset
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_color(color)
        self._update_position()

    def mousePressEvent(self, event: Optional[QGraphicsSceneMouseEvent]) -> None:
        if not event:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._transaction_signal.emit(self.creating_txid)
            event.accept()
            return
        super().mousePressEvent(event)

    def _apply_color(self, color: QColor | ColorSchemeItem | None) -> None:
        if isinstance(color, ColorSchemeItem):
            self.setDefaultTextColor(color.as_color())
        elif isinstance(color, QColor):
            self.setDefaultTextColor(color)
        else:
            self.setDefaultTextColor(ColorScheme.DEFAULT.as_color())

    def _update_position(self) -> None:
        rect = self.boundingRect()
        self.setPos(-rect.width() / 2, self._vertical_offset)

    @property
    def bottom_y(self) -> float:
        rect = self.boundingRect()
        return self.pos().y() + rect.height()


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
        self._transaction_signal = transaction_signal

        self.apply_color(ColorScheme.Purple)

        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(2)

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
        self.setToolTip(tooltip)
        label_tooltip = f"{detail.txid}\n{label_value}" if label_value else detail.txid
        self.label_item.setToolTip(label_tooltip)

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

    @staticmethod
    def _transaction_input_color(wallet: Wallet | None, detail: FullTxDetail) -> ColorSchemeItem | None:
        if not wallet:
            return None

        has_receive_input = False
        has_change_input = False

        for python_utxo in detail.inputs.values():
            if not python_utxo:
                continue
            is_my = wallet.is_my_address(python_utxo.address)
            if is_my:
                has_receive_input = True
            is_change = wallet.is_change(python_utxo.address)
            if is_change:
                has_change_input = True

        if has_receive_input and has_change_input:
            return ColorScheme.BLUE
        if has_receive_input:
            return ColorScheme.GREEN
        if has_change_input:
            return ColorScheme.OrangeBitcoin
        return None

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
        self._tx_positions: Dict[str, float] = {}
        self._current_wallet: Wallet | None = None
        self._current_details: List[FullTxDetail] = []

    def clear(self) -> None:
        self._scene.clear()
        self._utxo_items.clear()
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

            tick_pen = QPen(ColorScheme.GRAY.as_color())
            tick_pen.setWidthF(1.0)
            self._scene.addLine(x_pos, self.AXIS_Y - 6, x_pos, self.AXIS_Y + 6, tick_pen)

            self._render_inputs(detail, tx_item)
            self._render_outputs(detail, tx_item, max_utxo_value)

        scene_rect = self._scene.itemsBoundingRect().adjusted(-150, -200, 150, 200)
        self._scene.setSceneRect(scene_rect)
        self.centerOn((scene_rect.left() + scene_rect.right()) / 2, self.AXIS_Y)

    def center_on_transaction(self, txid: str) -> bool:
        position = self._tx_positions.get(txid)
        if position is None:
            return False
        self.centerOn(position, self.AXIS_Y)
        return True

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

    def _render_inputs(self, detail: FullTxDetail, tx_item: TransactionItem) -> None:
        inputs = list(detail.inputs.items())
        if not inputs:
            return
        for index, (outpoint_str, python_utxo) in enumerate(inputs):
            if python_utxo and outpoint_str in self._utxo_items:
                circle = self._utxo_items[outpoint_str]
                self._connect_utxo_to_transaction(circle, tx_item, incoming=True)
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

            self._connect_points(
                ellipse.pos(),
                QPointF(tx_item.pos().x() - TransactionItem.DEFAULT_WIDTH / 2, self.AXIS_Y),
                ellipse.pen().color(),
            )

    def _render_outputs(self, detail: FullTxDetail, tx_item: TransactionItem, max_utxo_value: int) -> None:
        outputs = list(detail.outputs.items())
        if not outputs:
            return

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

            self._connect_points(
                QPointF(tx_item.pos().x() + TransactionItem.DEFAULT_WIDTH / 2, self.AXIS_Y),
                ellipse.pos(),
                ellipse.pen().color(),
            )

            if python_utxo.is_spent_by_txid and python_utxo.is_spent_by_txid in self._tx_positions:
                # draw a subtle hint towards the spending transaction
                spending_x = self._tx_positions[python_utxo.is_spent_by_txid]
                self._connect_points(
                    ellipse.pos(),
                    QPointF(spending_x - TransactionItem.DEFAULT_WIDTH / 2, self.AXIS_Y),
                    ellipse.pen().color(),
                )

    def _connect_utxo_to_transaction(
        self, circle: GraphUtxoCircle, tx_item: TransactionItem, incoming: bool
    ) -> None:
        if circle.utxo:
            circle.ellipse.setOpacity(0.45)
        start = circle.ellipse.pos()
        end_x = (
            tx_item.pos().x() - TransactionItem.DEFAULT_WIDTH / 2
            if incoming
            else tx_item.pos().x() + TransactionItem.DEFAULT_WIDTH / 2
        )
        end_point = QPointF(end_x, self.AXIS_Y)
        color = circle.ellipse.pen().color()
        self._connect_points(start, end_point, color)

    def _connect_points(self, start: QPointF, end: QPointF, color: QColor) -> None:
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
                "Drag to explore the timeline. Click a transaction, txid, or UTXO to inspect it.",
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
        self.refresh_button.setToolTip(self.tr("Redraw the wallet graph."))
        self.instructions_label.setText(
            self.tr("Drag to explore the timeline. Click a transaction, txid, or UTXO to inspect it.")
        )
        super().updateUi()
