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
import random
import sys

import numpy as np
from PyQt6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PyQt6.QtCore import QDateTime, QMargins, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QFrame, QMainWindow, QVBoxLayout, QWidget

from bitcoin_safe.util import unit_str

from ...signals import UpdateFilter, WalletSignals
from ...wallet import Wallet

logger = logging.getLogger(__name__)


class BalanceChart(QWidget):
    def __init__(self, y_axis_text="Balance") -> None:
        super().__init__()
        self.y_axis_text = y_axis_text

        # Layout
        layout = QVBoxLayout()

        # Create chart
        self.chart = QChart()
        self.chart.setBackgroundBrush(Qt.GlobalColor.white)
        if legend := self.chart.legend():
            legend.hide()

        # Reduce the overall chart margins
        layout.setContentsMargins(QMargins(0, 0, 0, 0))  # Smaller margins (left, top, right, bottom)
        self.chart.setMargins(QMargins(0, 0, 0, 0))  # Smaller margins (left, top, right, bottom)

        # Create DateTime axis for X
        self.datetime_axis = QDateTimeAxis()

        # Create Value axis for Y
        self.value_axis = QValueAxis()

        self.chart.addAxis(self.datetime_axis, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.value_axis, Qt.AlignmentFlag.AlignLeft)
        self.chart.setBackgroundRoundness(0)

        # Add chart to chart view
        self.chart_view = QChartView(self.chart)
        layout.addWidget(self.chart_view)

        self.chart_view.setFrameStyle(QFrame.Shape.NoFrame)
        self.chart_view.setBackgroundBrush(self.chart.backgroundBrush())

        # Set layout
        self.setLayout(layout)

    def set_value_axis_label_format(self, max_value) -> None:
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

    def update_chart(self, balance_data, project_until_now=True) -> None:
        if len(balance_data) == 0:
            return
        balance_data = np.array(balance_data).copy()

        self.datetime_axis.setTitleText(self.tr("Date"))
        self.datetime_axis.setTickCount(6)
        self.value_axis.setTitleText(self.y_axis_text)
        self.set_value_axis_label_format(np.max(balance_data[:, 1]))

        # Clear previous series
        self.chart.removeAllSeries()

        # Variables to store the min/max values for the axes
        min_balance = 0
        max_balance = 0
        min_timestamp = float("inf")
        max_timestamp = float("-inf")
        for timestamp, balance in balance_data:
            max_balance = max(max_balance, balance)
            min_balance = min(min_balance, balance)
            max_timestamp = max(max_timestamp, timestamp)
            min_timestamp = min(min_timestamp, timestamp)

        #  add the 0 balance as first data point
        balance_data = np.vstack(
            [
                (min_timestamp, min_balance),
                balance_data,
            ]
        )

        # add the current time as last point, if the data is in the past
        if project_until_now and datetime.datetime.now().timestamp() > max(balance_data[:, 0]):
            balance_data = np.vstack(
                [
                    balance_data,
                    (datetime.datetime.now().timestamp(), balance_data[-1][1]),
                ]
            )

        if np.max(balance_data[:, 0]) - np.min(balance_data[:, 0]) < 24 * 60 * 60:
            self.datetime_axis.setFormat("HH:mm")
        else:
            self.datetime_axis.setFormat("d MMM yy")

        # Create Line series
        series = QLineSeries()

        for i, (timestamp, balance) in enumerate(balance_data[:-1]):
            next_timestamp, _ = balance_data[i + 1]
            series.append(
                QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(),
                balance,
            )
            series.append(
                QDateTime.fromSecsSinceEpoch(int(next_timestamp)).toMSecsSinceEpoch(),
                balance,
            )

        # Add the last data point
        timestamp, balance = balance_data[-1]
        series.append(QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(), balance)

        self.datetime_axis.setRange(
            QDateTime.fromSecsSinceEpoch(int(min_timestamp)),
            QDateTime.fromSecsSinceEpoch(int(max_timestamp)),
        )
        self.value_axis.setRange(
            0,
            max_balance,
        )

        buffer_time = (max_timestamp - min_timestamp) * 0.02
        self.datetime_axis.setMin(QDateTime.fromSecsSinceEpoch(int(min_timestamp - buffer_time)))
        self.datetime_axis.setMax(QDateTime.fromSecsSinceEpoch(int(max_timestamp + buffer_time)))
        self.value_axis.setMin(min_balance)
        buffer_factor = 0.01
        self.value_axis.setMax(max_balance * (1 + buffer_factor))

        # Adding series to the chart
        self.chart.addSeries(series)

        # Attach axes
        series.attachAxis(self.datetime_axis)
        series.attachAxis(self.value_axis)

        print(f"Actual DateTime Axis Range: {self.datetime_axis.min()} - {self.datetime_axis.max()}")

        # scatter_series = QScatterSeries()
        # for (timestamp, balance) in balance_data:
        #     scatter_series.append(
        #         QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(),
        #         balance,
        #     )

        # scatter_series = QScatterSeries()
        # for (timestamp, balance) in balance_data:
        #     scatter_series.append(
        #         QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(),
        #         balance,
        #     )

        # # Set marker shape and size
        # scatter_series.setMarkerShape(QScatterSeries.MarkerShape.MarkerShapeCircle)
        # scatter_series.setMarkerSize(5)

        # # Set marker color
        # border_color = QColor("#209fdf")  # Blue
        # brush_color = QColor("#209fdf")  # Semi-transparent blue
        # scatter_series.setPen(border_color)
        # scatter_series.setBrush(brush_color)

        # self.chart.addSeries(scatter_series)
        # scatter_series.attachAxis(self.datetime_axis)
        # scatter_series.attachAxis(self.value_axis)


class WalletBalanceChart(BalanceChart):
    def __init__(self, wallet: Wallet, wallet_signals: WalletSignals) -> None:
        super().__init__(y_axis_text="")
        self.value_axis.setLabelFormat("%.2f")
        self.wallet = wallet
        self.wallet_signals = wallet_signals

        self.updateUi()

        # signals
        self.wallet_signals.updated.connect(self.update_balances)
        self.wallet_signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.y_axis_text = self.tr("Balance ({unit})").format(unit=unit_str(self.wallet.network))

        self.datetime_axis.setTitleText(self.tr("Date"))
        self.value_axis.setTitleText(self.y_axis_text)
        self.chart.update()

    def update_balances(self, update_filter: UpdateFilter) -> None:
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")

        # Calculate balance
        balance = 0
        balance_data = []
        for transaction_details in self.wallet.sorted_delta_list_transactions():
            balance += transaction_details.received - transaction_details.sent
            time = (
                transaction_details.confirmation_time.timestamp
                if transaction_details.confirmation_time
                else datetime.datetime.now().timestamp()
            )
            balance_data.append((time, balance / 1e8))

        # Update BalanceChart
        self.update_chart(balance_data)


class TransactionSimulator(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.transactions = [
            (1625692800, 0.1),  # July 8, 2021
            (1626111600, -0.03),  # July 13, 2021
            (1626520000, 0.15),  # July 18, 2021
            (1629138000, -0.05),  # August 17, 2021
            (1630547200, 0.08),  # September 3, 2021
        ]

        # Create BalanceChart
        self.chart = BalanceChart()
        self.setCentralWidget(self.chart)

        # QTimer to simulate incoming transactions
        self.timer = QTimer()
        self.timer.timeout.connect(self.add_transaction)
        self.timer.start(3000)

        # Initial chart update
        self.update_chart()

    def update_chart(self) -> None:
        # Calculate balance
        balance: float = 0
        balance_data = []
        for timestamp, amount in self.transactions:
            balance += amount
            balance_data.append((timestamp, balance))

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
