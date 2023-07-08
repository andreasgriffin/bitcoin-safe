import sys
import random
import datetime
from PySide2.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide2.QtCharts import QtCharts
from PySide2.QtCore import QDateTime, Qt, QTimer

from ...signals import Signals

from ...wallet import Wallet
import numpy as np


class BalanceChart(QWidget):
    def __init__(self):
        super().__init__()

        # Layout
        layout = QVBoxLayout()

        # Create chart
        self.chart = QtCharts.QChart()
        self.chart.setBackgroundBrush(Qt.white)
        self.chart.legend().hide()

        # Create DateTime axis for X
        self.datetime_axis = QtCharts.QDateTimeAxis()
        self.datetime_axis.setFormat("d MMM yy")
        self.datetime_axis.setTitleText("Date")
        # self.datetime_axis.setTickCount(5)

        # Create Value axis for Y
        self.value_axis = QtCharts.QValueAxis()
        self.value_axis.setTitleText("Balance (BTC)")

        self.chart.addAxis(self.datetime_axis, Qt.AlignBottom)
        self.chart.addAxis(self.value_axis, Qt.AlignLeft)

        # Add chart to chart view
        self.chart_view = QtCharts.QChartView(self.chart)
        layout.addWidget(self.chart_view)

        # Set layout
        self.setLayout(layout)

    def update_chart(self, balance_data, project_until_now=True):
        if len(balance_data) == 0:
            return

        balance_data = np.array(balance_data)

        # Clear previous series
        self.chart.removeAllSeries()

        # Variables to store the min/max values for the axes
        min_balance = 0
        max_balance = 0
        min_timestamp = float("inf")
        max_timestamp = float("-inf")

        # add the current time as last point, if the data is in the past
        if project_until_now and datetime.datetime.now().timestamp() > max(
            balance_data[:, 0]
        ):
            balance_data = np.vstack(
                [
                    balance_data,
                    (datetime.datetime.now().timestamp(), balance_data[-1][1]),
                ]
            )

        # Create Line series
        series = QtCharts.QLineSeries()
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
            max_balance = max(max_balance, balance)
            min_balance = min(min_balance, balance)
            max_timestamp = max(max_timestamp, timestamp)
            min_timestamp = min(min_timestamp, timestamp)

        # Add the last data point
        timestamp, balance = balance_data[-1]
        series.append(
            QDateTime.fromSecsSinceEpoch(int(timestamp)).toMSecsSinceEpoch(), balance
        )
        max_balance = max(max_balance, balance)
        min_balance = min(min_balance, balance)
        max_timestamp = max(max_timestamp, timestamp)
        min_timestamp = min(min_timestamp, timestamp)

        # Adding series to the chart
        self.chart.addSeries(series)

        # Attach axes
        series.attachAxis(self.datetime_axis)
        series.attachAxis(self.value_axis)

        # Update the axis ranges
        self.datetime_axis.setRange(
            QDateTime.fromSecsSinceEpoch(int(min_timestamp)).toMSecsSinceEpoch(),
            QDateTime.fromSecsSinceEpoch(int(max_timestamp)).toMSecsSinceEpoch(),
        )
        self.value_axis.setRange(min_balance, max_balance)
        print(
            f"Actual DateTime Axis Range: {self.datetime_axis.min()} - {self.datetime_axis.max()}"
        )


class WalletBalanceChart(BalanceChart):
    def __init__(self, wallet: Wallet, signals: Signals):
        super().__init__()
        self.value_axis.setLabelFormat("%.2f")
        self.wallet = wallet
        self.signals = signals

        self.signals.utxos_updated.connect(self.update_balances)

    def update_balances(self):

        # Calculate balance
        balance = 0
        balance_data = []
        for transaction_details in self.wallet.get_list_transactions():
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
    def __init__(self):
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

    def update_chart(self):
        # Calculate balance
        balance = 0
        balance_data = []
        for timestamp, amount in self.transactions:
            balance += amount
            balance_data.append((timestamp, balance))

        # Update BalanceChart
        self.chart.update_chart(balance_data)

    def add_transaction(self):
        # Simulating a new transaction (current timestamp, random amount)
        new_transaction = (
            int(
                (
                    datetime.datetime.fromtimestamp(self.transactions[-1][0])
                    + datetime.timedelta(days=1)
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
    sys.exit(app.exec_())
