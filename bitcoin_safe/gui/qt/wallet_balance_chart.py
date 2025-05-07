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


import datetime
import logging
import math
import random
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

import bdkpython as bdk
import numpy as np
from bitcoin_tools.gui.qt.satoshis import Satoshis, unit_str
from bitcoin_tools.gui.qt.util import adjust_brightness, is_dark_mode
from PyQt6.QtCharts import (
    QChart,
    QChartView,
    QDateTimeAxis,
    QLineSeries,
    QScatterSeries,
    QValueAxis,
)
from PyQt6.QtCore import QDateTime, QMargins, QPointF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsLayout,
    QMainWindow,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.execute_config import ENABLE_TIMERS
from bitcoin_safe.gui.qt.util import ColorScheme, blend_qcolors
from bitcoin_safe.pythonbdk_types import TransactionDetails
from bitcoin_safe.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe.signals import UpdateFilter, WalletSignals
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.util import monotone_increasing_timestamps
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


Point = Tuple[float, float]


def find_nearest_point(
    points: Sequence[Point],
    reference: Point,
    width: float,
    height: float,
) -> Tuple[Optional[Point], Optional[int], Optional[float]]:
    """
    Find the closest point to `reference` after linearly mapping all
    points (and reference) into a [0…width]×[0…height] rectangle.

    Returns (nearest_point, distance) where distance is the Euclidean
    pixel‐distance on that rectangle, or (None, None) if points is empty.
    """
    if not points:
        return None, None, None

    # Convert to numpy arrays
    pts = np.array(points, dtype=float)  # shape (N,2)
    ref = np.array(reference, dtype=float)  # shape (2,)

    # Compute data‐range including the reference
    mins = np.minimum(pts.min(axis=0), ref)
    maxs = np.maximum(pts.max(axis=0), ref)
    spans = maxs - mins
    spans[spans == 0] = 1.0  # avoid zero‐span

    # Map into widget pixel space
    scale = np.array([width, height], dtype=float)
    pts_px = (pts - mins) / spans * scale  # shape (N,2)
    ref_px = (ref - mins) / spans * scale  # shape (2,)

    # Compute squared distances and pick the minimum
    deltas = pts_px - ref_px  # shape (N,2)
    d2 = np.einsum("ij,ij->i", deltas, deltas)  # shape (N,)
    idx = int(np.argmin(d2))

    nearest = tuple(pts[idx].tolist())
    distance = math.sqrt(d2[idx])

    return nearest, idx, distance


class TrackingChartView(QChartView):
    signal_click: TypedPyQtSignal[int] = pyqtSignal(int)  # type: ignore

    def __init__(
        self,
        chart: QChart,
        line_series: QLineSeries,
        highlight_series: QScatterSeries,
        network: bdk.Network,
        highlight_radius=150,
        parent: Optional[QWidget] = None,
        show_tooltip=False,
    ) -> None:
        super().__init__(chart, parent)
        self.setMouseTracking(True)
        self.line_series = line_series
        self.highlight_series = highlight_series
        self.highlight_radius = highlight_radius
        self.network = network
        self.show_tooltip = show_tooltip

    def to_float(self, v: float | QDateTime) -> float:
        return v.toSecsSinceEpoch() if isinstance(v, QDateTime) else v

    def get_highlight_point(self, ref_data: Point) -> None | Tuple[Point, int, float]:
        chart = self.chart()
        if not chart:
            return None

        # 2) Extract raw data-space points
        raw_qpts = self.line_series.points()
        if not raw_qpts:
            return None
        data_points = [(p.x(), p.y()) for p in raw_qpts]

        # 3) Axis spans
        x_axis = chart.axes(Qt.Orientation.Horizontal, self.line_series)[0]
        y_axis = chart.axes(Qt.Orientation.Vertical, self.line_series)[0]
        if not isinstance(x_axis, (QValueAxis, QDateTimeAxis)):
            return None
        if not isinstance(y_axis, (QValueAxis, QDateTimeAxis)):
            return None

        # 4) Find nearest (normalized data-space)
        nearest_xy, index, distance = find_nearest_point(
            points=data_points, reference=ref_data, width=self.width(), height=self.height()
        )
        if nearest_xy is None or index is None or distance is None:
            return None

        return nearest_xy, index, distance

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        chart = self.chart()
        if not chart:
            return

        # 1) Get data-space mouse position
        point: QPointF = chart.mapToValue(event.position(), self.line_series)
        ref_data = (point.x(), point.y())

        # 4) Find nearest (normalized data-space)
        infos = self.get_highlight_point(ref_data=ref_data)
        if not infos:
            return super().mouseMoveEvent(event)
        nearest_xy, index, distance = infos
        # logger.info(str(distance))

        # 5) Highlight & tooltip
        nearest_qt = QPointF(*nearest_xy)
        self.highlight_series.clear()

        if distance > self.highlight_radius:
            return None

        self.highlight_series.append(nearest_qt)

        if self.show_tooltip:
            date_str = QDateTime.fromMSecsSinceEpoch(int(nearest_qt.x())).toString("d MMM yy  HH:mm")
            value_str = Satoshis(value=int(nearest_qt.y() * 1e8), network=self.network).str_with_unit(
                color_formatting=None
            )
            QToolTip.showText(
                event.globalPosition().toPoint(), f"{ value_str} on {date_str}", self, self.rect()
            )

        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not (chart := self.chart()):
            return
        # 1) map click → data coords (using your series)
        point: QPointF = chart.mapToValue(event.position(), self.line_series)

        ref_data = (point.x(), point.y())

        # 4) Find nearest (normalized data-space)
        infos = self.get_highlight_point(ref_data=ref_data)
        if not infos:
            return super().mouseMoveEvent(event)
        nearest_xy, index, distance = infos

        self.signal_click.emit(index)

        # 3) let the base class handle the rest (zooming, panning, etc.)
        super().mousePressEvent(event)


@dataclass
class ChartPoint:
    x: float
    y: float
    id: str


class BalanceChart(QWidget):
    def __init__(
        self, network: bdk.Network, y_axis_text="Balance", highlight_radius=150, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.signal_tracker = SignalTracker()
        self.y_axis_text = y_axis_text
        color_text = blend_qcolors(
            self.palette().color(QPalette.ColorRole.Dark), self.palette().color(QPalette.ColorRole.Text)
        )
        color_major_grid = (
            adjust_brightness(color_text, -0.3) if is_dark_mode() else adjust_brightness(color_text, 0.5)
        )

        self.chart = QChart()
        if legend := self.chart.legend():
            legend.hide()

        # Create Line series
        self.line_series = QLineSeries()
        self.line_series.setPointsVisible(False)

        # -- 2) Set up a scatter series as our highlight marker --
        self.highlight_series = QScatterSeries()
        self.highlight_series.setMarkerSize(6)
        self.highlight_series.setColor(ColorScheme.Purple.as_color())
        self.highlight_series.setBorderColor(Qt.GlobalColor.transparent)

        # Adding series to the chart
        self.chart.addSeries(self.line_series)
        self.chart.addSeries(self.highlight_series)

        # Layout
        self._layout = QVBoxLayout()

        # Reduce the overall chart margins
        self.chart.setMargins(QMargins(0, 0, 0, 0))  # Smaller margins (left, top, right, bottom)

        # Create DateTime axis for X
        self.datetime_axis = QDateTimeAxis()
        self.datetime_axis.setLabelsColor(color_text)
        self.datetime_axis.setTitleBrush(color_text)
        self.datetime_axis.setGridLineColor(color_major_grid)

        # Create Value axis for Y
        self.value_axis = QValueAxis()
        self.value_axis.setLabelsColor(color_text)
        self.value_axis.setTitleBrush(color_text)
        self.value_axis.setGridLineColor(color_major_grid)

        self.chart.addAxis(self.datetime_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.value_axis, Qt.AlignmentFlag.AlignLeft)
        self.chart.setBackgroundRoundness(0)

        # Attach axes
        self.line_series.attachAxis(self.datetime_axis)
        self.line_series.attachAxis(self.value_axis)
        self.highlight_series.attachAxis(self.datetime_axis)
        self.highlight_series.attachAxis(self.value_axis)

        # Add chart to chart view
        self.chart_view = TrackingChartView(
            chart=self.chart,
            line_series=self.line_series,
            highlight_series=self.highlight_series,
            network=network,
            highlight_radius=highlight_radius,
        )
        self._layout.addWidget(self.chart_view)

        self.chart.setBackgroundVisible(False)
        # let the view widget itself be transparent
        self.chart_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # ensure the style sheet takes effect
        self.chart_view.setStyleSheet("background: transparent;")

        if isinstance(chart_layout := self.chart.layout(), QGraphicsLayout):
            # chart_layout has its own margin and it is difficult to set its color
            # to match the widget color.  So disabling is easiest here
            chart_layout.setContentsMargins(0, 0, 0, 0)

        # Set layout
        self.setLayout(self._layout)

    def set_value_axis_label_format(self, max_value: float) -> None:
        if max_value != 0:
            # Determine the number of digits before the decimal
            import math

            magnitude = int(math.log10(abs(max_value)))
            decimals = -min(magnitude, 0) + 1

        else:
            # Default to three decimal places if max_value is 0
            decimals = 3

        # Set the label format on the axis
        format_string = f"%.{decimals}f"
        self.value_axis.setLabelFormat(format_string)

    def update_chart(self, points: List[ChartPoint], project_until_now=True) -> None:
        self.points = points
        if len(points) == 0:
            return
        self.line_series.clear()

        self.datetime_axis.setTickCount(6)
        x_values = [p.x for p in points]
        y_values = [p.y for p in points]
        self.set_value_axis_label_format(max(y_values))

        # Variables to store the min/max values for the axes
        min_balance: float = 0
        max_balance: float = 0
        min_timestamp = float("inf")
        max_timestamp = float("-inf")
        for p in points:
            max_balance = max(max_balance, p.y)
            min_balance = min(min_balance, p.y)
            max_timestamp = max(max_timestamp, p.x)
            min_timestamp = min(min_timestamp, p.x)

        #  add the 0 balance as first data point
        points.insert(0, ChartPoint(x=min_timestamp, y=0, id="initial balance"))

        # add the current time as last point, if the data is in the past
        if project_until_now and datetime.datetime.now().timestamp() > max(x_values):
            points.append(
                ChartPoint(x=datetime.datetime.now().timestamp(), y=points[-1].y, id="today balance")
            )

        if np.max(x_values) - np.min(x_values) < 24 * 60 * 60:
            self.datetime_axis.setFormat("HH:mm")
        else:
            self.datetime_axis.setFormat("d MMM")

        for p in points:
            self.line_series.append(
                QDateTime.fromSecsSinceEpoch(int(p.x)).toMSecsSinceEpoch(),
                p.y,
            )

        buffer_time = (max_timestamp - min_timestamp) * 0.02
        self.datetime_axis.setMin(QDateTime.fromSecsSinceEpoch(int(min_timestamp - buffer_time)))
        self.datetime_axis.setMax(QDateTime.fromSecsSinceEpoch(int(max_timestamp + buffer_time)))

        buffer_factor = 0.1
        self.value_axis.setMin(0)
        self.value_axis.setMax(max_balance * (1 + buffer_factor))

        pen = QPen()
        pen.setColor(ColorScheme.OrangeBitcoin.as_color())
        pen.setWidth(2)
        self.line_series.setPen(pen)

        print(f"Actual DateTime Axis Range: {self.datetime_axis.min()} - {self.datetime_axis.max()}")

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        super().close()


class WalletBalanceChart(BalanceChart):
    signal_click_transaction: TypedPyQtSignal[TransactionDetails] = pyqtSignal(TransactionDetails)  # type: ignore

    def __init__(
        self,
        wallet: Wallet,
        wallet_signals: WalletSignals,
        highlight_radius=30,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            network=wallet.network, y_axis_text="", parent=parent, highlight_radius=highlight_radius
        )
        self.value_axis.setLabelFormat("%.2f")
        self.wallet = wallet
        self.wallet_signals = wallet_signals
        self.chart_view.signal_click.connect(self.on_signal_click)
        self.updateUi()

        # signals
        self.signal_tracker.connect(self.wallet_signals.updated, self.update_balances)
        self.signal_tracker.connect(self.wallet_signals.language_switch, self.updateUi)

    def highlight_txids(self, txids: Set[str]):
        self.highlight_series.clear()
        for p in self.points:
            if p.id in txids:
                self.highlight_series.append(
                    QPointF(QDateTime.fromSecsSinceEpoch(int(p.x)).toMSecsSinceEpoch(), p.y)
                )

    def on_signal_click(self, index: int):
        tx_index = max(0, index - 1)
        if tx_index >= len(self.transactions):
            return
        self.signal_click_transaction.emit(self.transactions[tx_index])

    def updateUi(self) -> None:
        self.y_axis_text = self.tr("Balance ({unit})").format(unit=unit_str(self.wallet.network))

        # self.datetime_axis.setTitleText(self.tr("Date"))
        # self.value_axis.setTitleText(self.y_axis_text)
        self.chart.update()

    def update_balances(self, update_filter: UpdateFilter) -> None:
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter")

        # Calculate balance
        balance = 0
        balance_data: List[ChartPoint] = []
        self.transactions = self.wallet.sorted_delta_list_transactions()
        time_values = monotone_increasing_timestamps(
            [
                (
                    transaction_details.get_height(unconfirmed_height=self.wallet.get_height()),
                    transaction_details.get_datetime(fallback_timestamp=datetime.datetime.now().timestamp()),
                )
                for transaction_details in self.transactions
            ]
        )
        for time_value, transaction_details in zip(time_values, self.transactions):
            balance += transaction_details.received - transaction_details.sent
            balance_data.append(
                ChartPoint(x=time_value.timestamp(), y=balance / 1e8, id=transaction_details.txid)
            )

        # Update BalanceChart
        self.update_chart(balance_data)


class TransactionSimulator(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.transactions: List[Tuple[float, float]] = [
            (1625692800, 0.1),  # July 8, 2021
            (1626111600, -0.03),  # July 13, 2021
            (1626520000, 0.15),  # July 18, 2021
            (1629138000, -0.05),  # August 17, 2021
            (1630547200, 0.08),  # September 3, 2021
        ]

        # Create BalanceChart
        self.chart = BalanceChart(network=bdk.Network.REGTEST)
        self.setCentralWidget(self.chart)

        # QTimer to simulate incoming transactions
        self.timer = QTimer()
        self.timer.timeout.connect(self.add_transaction)
        if ENABLE_TIMERS:
            self.timer.start(3000)

        # Initial chart update
        self.update_chart()

    def update_chart(self) -> None:
        # Calculate balance
        balance: float = 0
        balance_data: List[ChartPoint] = []
        for i, (timestamp, amount) in enumerate(self.transactions):
            balance += amount
            balance_data.append(ChartPoint(x=timestamp, y=balance, id=f"{i}"))

        # Update BalanceChart
        self.chart.update_chart(balance_data)

    def add_transaction(self) -> None:
        # Simulating a new transaction (current timestamp, random amount)
        new_transaction = (
            int(
                (
                    datetime.datetime.fromtimestamp(self.transactions[-1][0]) + datetime.timedelta(days=5)
                ).timestamp()
            ),
            random.uniform(-0.1, 0.1),
        )
        self.transactions.append(new_transaction)

        # Update the chart
        self.update_chart()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main = TransactionSimulator()
    main.show()
    sys.exit(app.exec())
