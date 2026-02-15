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
from typing import cast

from PyQt6.QtCore import QObject, pyqtSignal
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.hist_list import HistList
from bitcoin_safe.gui.qt.history_range import DateRangePicker, DateRangePreset, HistoryRangeController
from bitcoin_safe.gui.qt.wallet_balance_chart import WalletBalanceChart


class DummyWalletBalanceChart(QObject):
    signal_time_range_changed = pyqtSignal(object, object)
    signal_full_range_changed = pyqtSignal(object, object)
    signal_zoom_reset = pyqtSignal(object, object)
    signal_zoom_state_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.reset_zoom_calls = 0
        now = datetime.datetime.now()
        self._full_range = (now - datetime.timedelta(days=3), now)
        self._zoomed = True

    def get_full_range(self) -> tuple[datetime.datetime, datetime.datetime]:
        return self._full_range

    def reset_zoom(self) -> None:
        self.reset_zoom_calls += 1
        self._zoomed = False
        self.signal_zoom_reset.emit(*self._full_range)
        self.signal_zoom_state_changed.emit(False)

    def set_time_range(self, _start: datetime.datetime, _end: datetime.datetime) -> None:
        return

    def is_zoomed(self) -> bool:
        return self._zoomed


class DummyHistList:
    def __init__(self) -> None:
        self.set_date_range_calls = 0

    def set_date_range(self, _start: datetime.datetime, _end: datetime.datetime) -> None:
        self.set_date_range_calls += 1


def test_history_range_reset_shortcut_alt_zero(qtbot: QtBot) -> None:
    date_range_picker = DateRangePicker()
    wallet_balance_chart = DummyWalletBalanceChart()
    history_list = DummyHistList()
    controller = HistoryRangeController(
        date_range_picker=date_range_picker,
        wallet_balance_chart=cast(WalletBalanceChart, wallet_balance_chart),
        history_list=cast(HistList, history_list),
    )
    qtbot.addWidget(controller)
    assert controller._reset_shortcut.key().toString() == "Alt+0"
    controller._reset_shortcut.activated.emit()

    assert wallet_balance_chart.reset_zoom_calls == 1
    assert history_list.set_date_range_calls >= 1


def test_history_range_plain_r_no_longer_resets(qtbot: QtBot) -> None:
    date_range_picker = DateRangePicker()
    wallet_balance_chart = DummyWalletBalanceChart()
    history_list = DummyHistList()
    controller = HistoryRangeController(
        date_range_picker=date_range_picker,
        wallet_balance_chart=cast(WalletBalanceChart, wallet_balance_chart),
        history_list=cast(HistList, history_list),
    )
    qtbot.addWidget(controller)
    assert controller._reset_shortcut.key().toString() != "R"


def test_history_range_all_time_without_available_range_keeps_selected_dates(qtbot: QtBot) -> None:
    date_range_picker = DateRangePicker()
    qtbot.addWidget(date_range_picker)

    initial_start = date_range_picker.start_edit.date().toPyDate()
    initial_end = date_range_picker.end_edit.date().toPyDate()
    date_range_picker.set_preset(DateRangePreset.ALL_TIME)

    assert date_range_picker.start_edit.date().toPyDate() == initial_start
    assert date_range_picker.end_edit.date().toPyDate() == initial_end
