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

import inspect
import logging
from datetime import datetime, timedelta
from datetime import time as dt_time

import pytest
from PyQt6.QtCore import QDate, QDateTime
from PyQt6.QtGui import QStandardItem
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.dialogs import WalletIdDialog
from bitcoin_safe.gui.qt.history_range import DateRangePreset
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from bitcoin_safe.gui.qt.qt_wallet import QTProtoWallet, QTWallet
from bitcoin_safe.gui.qt.wallet_balance_chart import ChartPoint

from ...helpers import TestConfig
from .helpers import Shutter, do_modal_click, main_window_context, save_wallet

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_3
def test_history_range_coupling(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: TestConfig,
    wallet_name: str = "history_range_coupling",
) -> None:
    """Ensure date range picker and chart zoom stay in sync."""
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10_000)  # type: ignore
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        wallet_id = f"{wallet_name}_{int(mytest_start_time.timestamp())}"
        button = main_window.welcome_screen.pushButton_custom_wallet

        def on_wallet_id_dialog(dialog: WalletIdDialog) -> None:
            shutter.save(dialog)
            dialog.name_input.setText(wallet_id)
            dialog.buttonbox.button(QDialogButtonBox.StandardButton.Ok).click()

        do_modal_click(button, on_wallet_id_dialog, qtbot, cls=WalletIdDialog)

        qt_protowallet = main_window.tab_wallets.root.findNodeByTitle(wallet_id).data
        assert isinstance(qt_protowallet, QTProtoWallet)

        qt_protowallet.wallet_descriptor_ui.spin_req.setValue(1)
        qt_protowallet.wallet_descriptor_ui.spin_signers.setValue(1)
        key = list(qt_protowallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values())[0]
        key.tabs_import_type.setCurrentWidget(key.tab_manual)
        if key.edit_seed.mnemonic_button:
            key.edit_seed.mnemonic_button.click()

        save_wallet(
            test_config=test_config,
            wallet_name=wallet_id,
            save_button=qt_protowallet.wallet_descriptor_ui.button_box.button(
                QDialogButtonBox.StandardButton.Apply
            ),
        )

        qt_wallet = main_window.tab_wallets.root.findNodeByTitle(wallet_id).data
        assert isinstance(qt_wallet, QTWallet)

        history_list = qt_wallet.history_list

        now = datetime.now()
        older = now - timedelta(days=10)
        middle = now - timedelta(days=5)
        recent = now - timedelta(days=1)

        model = history_list._source_model
        timestamps_by_row = [older, middle, recent]
        for row, timestamp in enumerate(timestamps_by_row):
            items = [QStandardItem("") for _ in range(len(history_list.Columns))]
            txid_item = items[history_list.Columns.TXID]
            nlocktime_time_item = items[history_list.Columns.NLOCKTIME_TIME]
            txid_item.setText(f"mock-tx-{row}")
            txid_item.setData(f"mock-tx-{row}", MyItemDataRole.ROLE_KEY)
            nlocktime_time_item.setData(timestamp.timestamp(), MyItemDataRole.ROLE_CLIPBOARD_DATA)
            nlocktime_time_item.setData(timestamp.timestamp(), MyItemDataRole.ROLE_SORT_ORDER)
            model.appendRow(items)
        shutter.save(main_window)

        qt_wallet.wallet_balance_chart.update_chart(
            [
                ChartPoint(x=older.timestamp(), y=0.1, id="old"),
                ChartPoint(x=middle.timestamp(), y=0.15, id="mid"),
                ChartPoint(x=recent.timestamp(), y=0.2, id="new"),
            ]
        )

        date_picker = qt_wallet.history_list_with_toolbar.date_range_picker

        qtbot.waitUntil(lambda: history_list._date_range is not None, timeout=5_000)
        qtbot.waitUntil(
            lambda: date_picker.preset_combo.currentData() == DateRangePreset.ALL_TIME,
            timeout=5_000,
        )
        qtbot.waitUntil(lambda: not date_picker.start_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: not date_picker.end_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: not date_picker.to_label.isVisible(), timeout=5_000)
        shutter.save(main_window)

        def expected_hidden_rows(start_ts: float, end_ts: float) -> set[int]:
            expected: set[int] = set()
            for row in range(model.rowCount()):
                item = model.item(row, history_list.Columns.NLOCKTIME_TIME)
                assert item
                timestamp = item.data(MyItemDataRole.ROLE_CLIPBOARD_DATA)
                assert isinstance(timestamp, (float, int))
                ts = float(timestamp)
                if ts < start_ts or ts > end_ts:
                    expected.add(row)
            return expected

        def hidden_rows() -> set[int]:
            return {int(i) for i in history_list.base_hidden_rows}

        def chart_axis_range_ts() -> tuple[float, float]:
            return (
                float(qt_wallet.wallet_balance_chart.datetime_axis.min().toSecsSinceEpoch()),
                float(qt_wallet.wallet_balance_chart.datetime_axis.max().toSecsSinceEpoch()),
            )

        def chart_axis_matches(expected_start_ts: float, expected_end_ts: float) -> bool:
            actual_start_ts, actual_end_ts = chart_axis_range_ts()
            return abs(actual_start_ts - expected_start_ts) <= 1 and abs(actual_end_ts - expected_end_ts) <= 1

        def expected_chart_range_for_picker(
            requested_start_ts: float,
            requested_end_ts: float,
        ) -> tuple[float, float]:
            start_ts, end_ts = sorted((requested_start_ts, requested_end_ts))
            return float(int(start_ts)), float(int(end_ts))

        full_start = qt_wallet.wallet_balance_chart.datetime_axis.min().toSecsSinceEpoch()
        full_end = qt_wallet.wallet_balance_chart.datetime_axis.max().toSecsSinceEpoch()
        full_expected_hidden = expected_hidden_rows(full_start, full_end)
        qtbot.waitUntil(lambda: hidden_rows() == full_expected_hidden, timeout=5_000)
        assert not date_picker.reset_button.isVisible()
        assert not date_picker.reset_button.icon().isNull()
        shutter.save(main_window)

        date_picker.set_preset(DateRangePreset.LAST_7_DAYS)
        qtbot.waitUntil(lambda: date_picker.reset_button.isVisible(), timeout=5_000)
        last_7_start = datetime.combine((now - timedelta(days=7)).date(), dt_time.min).timestamp()
        last_7_end = datetime.combine(now.date(), dt_time.max).timestamp()
        expected_last_7_hidden = expected_hidden_rows(last_7_start, last_7_end)
        qtbot.waitUntil(lambda: hidden_rows() == expected_last_7_hidden, timeout=5_000)
        assert len(hidden_rows()) >= 1
        shutter.save(main_window)

        date_picker.set_preset(DateRangePreset.LAST_30_DAYS)
        qtbot.waitUntil(lambda: not date_picker.start_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: not date_picker.end_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: not date_picker.to_label.isVisible(), timeout=5_000)

        start_date = (now - timedelta(days=2)).date()
        end_date = now.date()
        date_picker.set_preset(DateRangePreset.CUSTOM)
        qtbot.waitUntil(lambda: date_picker.start_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: date_picker.end_edit.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: date_picker.to_label.isVisible(), timeout=5_000)
        shutter.save(main_window)
        date_picker.start_edit.setDate(QDate(start_date.year, start_date.month, start_date.day))
        date_picker.end_edit.setDate(QDate(end_date.year, end_date.month, end_date.day))

        custom_start = datetime.combine(start_date, dt_time.min).timestamp()
        custom_end = datetime.combine(end_date, dt_time.max).timestamp()
        expected_custom_hidden = expected_hidden_rows(custom_start, custom_end)
        qtbot.waitUntil(lambda: hidden_rows() == expected_custom_hidden, timeout=5_000)
        custom_chart_start_ts, custom_chart_end_ts = expected_chart_range_for_picker(
            custom_start,
            custom_end,
        )
        qtbot.waitUntil(
            lambda: chart_axis_matches(custom_chart_start_ts, custom_chart_end_ts),
            timeout=5_000,
        )
        assert len(hidden_rows()) >= 2
        shutter.save(main_window)

        assert date_picker.reset_button.isVisible()

        zoomed_chart_start = QDateTime.fromSecsSinceEpoch(int((now - timedelta(days=6)).timestamp()))
        zoomed_chart_end = QDateTime.fromSecsSinceEpoch(int((now - timedelta(days=4)).timestamp()))
        qt_wallet.wallet_balance_chart.datetime_axis.setRange(zoomed_chart_start, zoomed_chart_end)
        zoomed_chart_start_date = zoomed_chart_start.date().toPyDate()
        zoomed_chart_end_date = zoomed_chart_end.date().toPyDate()
        qtbot.waitUntil(
            lambda: date_picker.start_edit.date().toPyDate() == zoomed_chart_start_date, timeout=5_000
        )
        qtbot.waitUntil(
            lambda: date_picker.end_edit.date().toPyDate() == zoomed_chart_end_date, timeout=5_000
        )
        zoomed_chart_hidden = expected_hidden_rows(
            float(zoomed_chart_start.toSecsSinceEpoch()),
            float(zoomed_chart_end.toSecsSinceEpoch()),
        )
        qtbot.waitUntil(lambda: hidden_rows() == zoomed_chart_hidden, timeout=5_000)
        shutter.save(main_window)

        zoomed_out_chart_start = QDateTime.fromSecsSinceEpoch(int((now - timedelta(days=20)).timestamp()))
        zoomed_out_chart_end = QDateTime.fromSecsSinceEpoch(int((now + timedelta(days=2)).timestamp()))
        qt_wallet.wallet_balance_chart.datetime_axis.setRange(zoomed_out_chart_start, zoomed_out_chart_end)
        zoomed_out_start_date = zoomed_out_chart_start.date().toPyDate()
        zoomed_out_end_date = zoomed_out_chart_end.date().toPyDate()
        qtbot.waitUntil(
            lambda: date_picker.start_edit.date().toPyDate() == zoomed_out_start_date, timeout=5_000
        )
        qtbot.waitUntil(lambda: date_picker.end_edit.date().toPyDate() == zoomed_out_end_date, timeout=5_000)
        zoomed_out_hidden = expected_hidden_rows(
            float(zoomed_out_chart_start.toSecsSinceEpoch()),
            float(zoomed_out_chart_end.toSecsSinceEpoch()),
        )
        qtbot.waitUntil(lambda: hidden_rows() == zoomed_out_hidden, timeout=5_000)
        shutter.save(main_window)

        panned_chart_start = QDateTime.fromSecsSinceEpoch(int((now - timedelta(days=30)).timestamp()))
        panned_chart_end = QDateTime.fromSecsSinceEpoch(int((now - timedelta(days=8)).timestamp()))
        qt_wallet.wallet_balance_chart.datetime_axis.setRange(panned_chart_start, panned_chart_end)
        panned_chart_start_date = panned_chart_start.date().toPyDate()
        panned_chart_end_date = panned_chart_end.date().toPyDate()
        qtbot.waitUntil(
            lambda: date_picker.start_edit.date().toPyDate() == panned_chart_start_date, timeout=5_000
        )
        qtbot.waitUntil(
            lambda: date_picker.end_edit.date().toPyDate() == panned_chart_end_date, timeout=5_000
        )
        panned_hidden = expected_hidden_rows(
            float(panned_chart_start.toSecsSinceEpoch()),
            float(panned_chart_end.toSecsSinceEpoch()),
        )
        qtbot.waitUntil(lambda: hidden_rows() == panned_hidden, timeout=5_000)
        shutter.save(main_window)

        picker_start_date = (now - timedelta(days=9)).date()
        picker_end_date = (now - timedelta(days=4)).date()
        date_picker.start_edit.setDate(
            QDate(picker_start_date.year, picker_start_date.month, picker_start_date.day)
        )
        date_picker.end_edit.setDate(QDate(picker_end_date.year, picker_end_date.month, picker_end_date.day))
        picker_start_ts = datetime.combine(picker_start_date, dt_time.min).timestamp()
        picker_end_ts = datetime.combine(picker_end_date, dt_time.max).timestamp()
        picker_chart_start_ts, picker_chart_end_ts = expected_chart_range_for_picker(
            picker_start_ts,
            picker_end_ts,
        )
        qtbot.waitUntil(
            lambda: chart_axis_matches(picker_chart_start_ts, picker_chart_end_ts),
            timeout=5_000,
        )
        picker_hidden = expected_hidden_rows(picker_start_ts, picker_end_ts)
        qtbot.waitUntil(lambda: hidden_rows() == picker_hidden, timeout=5_000)
        shutter.save(main_window)

        date_picker.set_preset(DateRangePreset.LAST_7_DAYS)
        last_7_start_ts = datetime.combine((now - timedelta(days=7)).date(), dt_time.min).timestamp()
        last_7_end_ts = datetime.combine(now.date(), dt_time.max).timestamp()
        last_7_chart_start_ts, last_7_chart_end_ts = expected_chart_range_for_picker(
            last_7_start_ts,
            last_7_end_ts,
        )
        qtbot.waitUntil(
            lambda: chart_axis_matches(last_7_chart_start_ts, last_7_chart_end_ts),
            timeout=5_000,
        )
        qtbot.waitUntil(
            lambda: hidden_rows() == expected_hidden_rows(last_7_start_ts, last_7_end_ts), timeout=5_000
        )
        shutter.save(main_window)

        date_picker.set_preset(DateRangePreset.ALL_TIME)
        qtbot.waitUntil(lambda: not date_picker.reset_button.isVisible(), timeout=5_000)
        qtbot.waitUntil(lambda: hidden_rows() == set(), timeout=5_000)
        shutter.save(main_window)

        date_picker.set_preset(DateRangePreset.LAST_30_DAYS)
        qtbot.waitUntil(lambda: hidden_rows() == set(), timeout=5_000)
        last_30_start_ts = datetime.combine((now - timedelta(days=30)).date(), dt_time.min).timestamp()
        last_30_end_ts = datetime.combine(now.date(), dt_time.max).timestamp()
        last_30_chart_start_ts, last_30_chart_end_ts = expected_chart_range_for_picker(
            last_30_start_ts, last_30_end_ts
        )
        qtbot.waitUntil(
            lambda: chart_axis_matches(last_30_chart_start_ts, last_30_chart_end_ts),
            timeout=5_000,
        )
        shutter.save(main_window)

        date_picker.reset_button.click()
        qtbot.waitUntil(lambda: not date_picker.reset_button.isVisible(), timeout=5_000)
        qtbot.waitUntil(
            lambda: date_picker.preset_combo.currentData() == DateRangePreset.ALL_TIME, timeout=5_000
        )
        qtbot.waitUntil(lambda: hidden_rows() == set(), timeout=5_000)
        shutter.save(main_window)
