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
from collections.abc import Iterable
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.util import time_logger
from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QWheelEvent
from PyQt6.QtWidgets import QGraphicsPathItem, QGraphicsScene, QGraphicsView, QWidget

from bitcoin_safe.gui.qt.util import ColorScheme
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugins.walletgraph.wallet_graph_items import (
    GraphTransactionNode,
    GraphUtxoCircle,
    TransactionItem,
    TransactionLabelItem,
    UtxoEllipseItem,
)
from bitcoin_safe.pythonbdk_types import FullTxDetail
from bitcoin_safe.signals import WalletSignals
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


class WalletGraphView(QGraphicsView):
    transactionClicked = cast(SignalProtocol[[str]], pyqtSignal(str))

    MIN_TX_SPACING = 180.0
    MIN_SCENE_WIDTH = 900.0
    AXIS_Y = 0.0

    def __init__(self, network: bdk.Network, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.wallet_signals: WalletSignals | None = None
        self.network = network
        self.is_drawing = False

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self._utxo_items: dict[str, GraphUtxoCircle] = {}
        self._transactions: dict[str, GraphTransactionNode] = {}
        self._tx_positions: dict[str, float] = {}
        self._current_wallet: Wallet | None = None
        self._current_details: list[FullTxDetail] = []

    def clear(self) -> None:
        """Clear."""
        self._utxo_items.clear()
        self._transactions.clear()
        self._tx_positions.clear()
        self._current_wallet = None
        self._current_details = []
        self._scene.clear()
        logger.info("clear scene")
        self.resetTransform()
        self._scene.setSceneRect(-400, -200, 800, 400)

    @property
    def current_wallet(self) -> Wallet | None:
        """Current wallet."""
        return self._current_wallet

    @property
    def current_details(self) -> list[FullTxDetail]:
        """Current details."""
        return list(self._current_details)

    def wheelEvent(self, event: QWheelEvent | None) -> None:
        """WheelEvent."""
        if not event:
            return
        if event.angleDelta().y() > 0:
            factor = 1.2
        else:
            factor = 1 / 1.2
        self.scale(factor, factor)
        event.accept()

    @time_logger
    def render_graph(
        self,
        wallet: Wallet,
        full_tx_details: Iterable[FullTxDetail],
        wallet_signals: WalletSignals,
    ) -> None:
        """Render graph."""
        self.is_drawing = True
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

        timestamped: list[tuple[FullTxDetail, float]] = []
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
        positions: list[float] = []
        for detail, timestamp in zip(sorted_details, times, strict=False):
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

        for detail, x_pos, timestamp in zip(sorted_details, positions, times, strict=False):
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
            self._render_outputs(detail, tx_node, max_utxo_value, wallet_signals=wallet_signals)

        scene_rect = self._scene.itemsBoundingRect().adjusted(-150, -200, 150, 200)
        self._scene.setSceneRect(scene_rect)
        self.centerOn((scene_rect.left() + scene_rect.right()) / 2, self.AXIS_Y)
        self.is_drawing = False

    def center_on_transaction(self, txid: str) -> bool:
        """Center on transaction."""
        position = self._tx_positions.get(txid)
        if position is None:
            return False
        self.centerOn(position, self.AXIS_Y)
        return True

    def has_transaction(self, txid: str) -> bool:
        """Has transaction."""
        return txid in self._transactions

    def jump_to_transaction(self, txid: str) -> bool:
        """Jump to transaction."""
        return self.center_on_transaction(txid)

    def _detail_timestamp(self, detail: FullTxDetail, fallback: float) -> float:
        """Detail timestamp."""
        try:
            dt = detail.tx.get_datetime(fallback_timestamp=fallback)
        except ValueError:
            dt = datetime.datetime.fromtimestamp(fallback)
        return dt.timestamp()

    def _max_output_value(self, details: Iterable[FullTxDetail]) -> int:
        """Max output value."""
        values = [
            python_utxo.value for detail in details for python_utxo in detail.outputs.values() if python_utxo
        ]
        return max(values) if values else 0

    def _render_inputs(self, detail: FullTxDetail, tx_node: GraphTransactionNode) -> None:
        """Render inputs."""
        inputs = list(detail.inputs.items())
        if not inputs:
            return
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
                tx_item=tx_node.item,
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
        self,
        detail: FullTxDetail,
        tx_node: GraphTransactionNode,
        max_utxo_value: int,
        wallet_signals: WalletSignals,
    ) -> None:
        """Render outputs."""
        for index, (outpoint_str, python_utxo) in enumerate(detail.outputs.items()):
            if not python_utxo:
                continue
            ellipse = UtxoEllipseItem.create_output(
                detail,
                outpoint_str,
                python_utxo,
                transaction_signal=self.transactionClicked,
                network=self.network,
                wallet=self._current_wallet,
                label_max_chars=UtxoEllipseItem.LABEL_MAX_CHARS,
                max_utxo_value=max_utxo_value,
                min_radius=UtxoEllipseItem.MIN_RADIUS,
                max_radius=UtxoEllipseItem.MAX_RADIUS,
                tx_item=tx_node.item,
                axis_y=self.AXIS_Y,
                tx_width=TransactionItem.DEFAULT_WIDTH,
                output_gap=UtxoEllipseItem.OUTPUT_GAP,
                vertical_spacing=UtxoEllipseItem.VERTICAL_SPACING,
                index=index,
                wallet_signals=wallet_signals,
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
        utxo_is_input: bool,
    ) -> QGraphicsPathItem:
        """Connect transaction and utxo."""
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
        """Connect points."""
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
