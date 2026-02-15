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
import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from .util import add_item_with_top_spacer, svg_tools

if TYPE_CHECKING:
    from .hist_list import HistList
    from .wallet_balance_chart import WalletBalanceChart


@dataclass(frozen=True)
class DateRange:
    start: datetime.datetime
    end: datetime.datetime


class DateRangePreset(enum.Enum):
    ALL_TIME = "all_time"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    LAST_YEAR = "last_year"
    LAST_2_YEARS = "last_2_years"
    YEAR_TO_DATE = "year_to_date"
    CUSTOM = "custom"

    def label(self) -> str:
        return {
            DateRangePreset.ALL_TIME: "All time",
            DateRangePreset.LAST_7_DAYS: "Last 7 days",
            DateRangePreset.LAST_30_DAYS: "Last 30 days",
            DateRangePreset.LAST_90_DAYS: "Last 90 days",
            DateRangePreset.LAST_YEAR: "Last year",
            DateRangePreset.LAST_2_YEARS: "Last 2 years",
            DateRangePreset.YEAR_TO_DATE: "Year to date",
            DateRangePreset.CUSTOM: "Custom",
        }[self]


class DateRangePicker(QWidget):
    _MACOS_PRESET_TOP_OFFSET_PX = 7
    _MACOS_START_EDIT_TOP_OFFSET_PX = 3
    _MACOS_TO_LABEL_TOP_OFFSET_PX = 0
    _MACOS_END_EDIT_TOP_OFFSET_PX = 3

    signal_range_changed = cast(
        SignalProtocol[[datetime.datetime, datetime.datetime]], pyqtSignal(object, object)
    )
    signal_reset_requested = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._available_range: DateRange | None = None

        self.preset_combo = QComboBox(self)
        self.start_edit = QDateEdit(self)
        self.end_edit = QDateEdit(self)
        self.to_label = QLabel(self.tr("to"))
        self.reset_button = QPushButton(self)
        self.reset_button.setIcon(svg_tools.get_QIcon("reset-zoom.svg"))
        self.reset_button.setText(self.tr("Reset zoom"))
        self.reset_button.setToolTip(self.tr("Reset zoom"))
        self.reset_button.setVisible(False)

        self._custom_index: int | None = None

        for preset in DateRangePreset:
            self.preset_combo.addItem(self.tr(preset.label()), preset)
        self._custom_index = self.preset_combo.findData(DateRangePreset.CUSTOM)

        self.start_edit.setCalendarPopup(True)
        self.end_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_edit.dateChanged.connect(self._on_date_changed)
        self.end_edit.dateChanged.connect(self._on_date_changed)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.reset_button.clicked.connect(self.signal_reset_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        add_item_with_top_spacer(layout, self.preset_combo, top_offset_px=self._MACOS_PRESET_TOP_OFFSET_PX)
        add_item_with_top_spacer(layout, self.start_edit, top_offset_px=self._MACOS_START_EDIT_TOP_OFFSET_PX)
        add_item_with_top_spacer(layout, self.to_label, top_offset_px=self._MACOS_TO_LABEL_TOP_OFFSET_PX)
        add_item_with_top_spacer(layout, self.end_edit, top_offset_px=self._MACOS_END_EDIT_TOP_OFFSET_PX)
        layout.addWidget(self.reset_button)

        today = datetime.date.today()
        self.set_range(
            datetime.datetime.combine(today, datetime.time.min),
            datetime.datetime.combine(today, datetime.time.max),
            update_preset=False,
        )
        self.set_preset(DateRangePreset.ALL_TIME)
        self._update_custom_visibility()

    def set_reset_visible(self, visible: bool) -> None:
        self.reset_button.setVisible(visible)

    def set_available_range(self, start: datetime.datetime, end: datetime.datetime) -> None:
        normalized = self._normalize_range(DateRange(start=start, end=end))
        self._available_range = normalized

    def get_range(self) -> DateRange:
        start = self._to_datetime(self.start_edit.date(), datetime.time.min)
        end = self._to_datetime(self.end_edit.date(), datetime.time.max)
        return self._normalize_range(DateRange(start=start, end=end))

    def set_range(
        self, start: datetime.datetime, end: datetime.datetime, *, update_preset: bool = True
    ) -> None:
        normalized = self._normalize_range(DateRange(start=start, end=end))
        self.start_edit.blockSignals(True)
        self.end_edit.blockSignals(True)
        self.start_edit.setDate(self._to_qdate(normalized.start))
        self.end_edit.setDate(self._to_qdate(normalized.end))
        self.start_edit.blockSignals(False)
        self.end_edit.blockSignals(False)
        if update_preset:
            self._set_custom_preset()
        self._update_custom_visibility()

    def set_preset(self, preset: DateRangePreset) -> None:
        index = self.preset_combo.findData(preset)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _set_custom_preset(self) -> None:
        if self._custom_index is None:
            return
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(self._custom_index)
        self.preset_combo.blockSignals(False)

    def _on_preset_changed(self) -> None:
        preset = self.preset_combo.currentData()
        if not isinstance(preset, DateRangePreset):
            return
        if preset == DateRangePreset.CUSTOM:
            self._update_custom_visibility()
            return
        date_range = self._range_for_preset(preset, datetime.datetime.now())
        self.set_range(date_range.start, date_range.end, update_preset=False)
        if preset == DateRangePreset.ALL_TIME and self._available_range is not None:
            normalized_range = self._available_range
        else:
            normalized_range = self.get_range()
        self._update_custom_visibility()
        self.signal_range_changed.emit(normalized_range.start, normalized_range.end)

    def _on_date_changed(self) -> None:
        date_range = self.get_range()
        self.set_range(date_range.start, date_range.end)
        self.signal_range_changed.emit(date_range.start, date_range.end)
        self._update_custom_visibility()

    def _range_for_preset(self, preset: DateRangePreset, now: datetime.datetime) -> DateRange:
        if preset == DateRangePreset.ALL_TIME:
            if self._available_range is not None:
                return self._available_range
            # Keep current dates until chart data publishes a full range.
            return self.get_range()
        if preset == DateRangePreset.YEAR_TO_DATE:
            start = datetime.datetime(year=now.year, month=1, day=1)
            end = now
            return DateRange(start=start, end=end)

        deltas = {
            DateRangePreset.LAST_7_DAYS: datetime.timedelta(days=7),
            DateRangePreset.LAST_30_DAYS: datetime.timedelta(days=30),
            DateRangePreset.LAST_90_DAYS: datetime.timedelta(days=90),
            DateRangePreset.LAST_YEAR: datetime.timedelta(days=365),
            DateRangePreset.LAST_2_YEARS: datetime.timedelta(days=365 * 2),
        }
        delta = deltas.get(preset, datetime.timedelta(days=365))
        start = now - delta
        return DateRange(start=start, end=now)

    def _update_custom_visibility(self) -> None:
        preset = self.preset_combo.currentData()
        is_custom = preset == DateRangePreset.CUSTOM
        self.start_edit.setVisible(is_custom)
        self.to_label.setVisible(is_custom)
        self.end_edit.setVisible(is_custom)

    @staticmethod
    def _normalize_range(date_range: DateRange) -> DateRange:
        start, end = date_range.start, date_range.end
        if start <= end:
            return date_range
        return DateRange(start=end, end=start)

    @staticmethod
    def _to_qdate(date_value: datetime.datetime) -> QDate:
        return QDate(date_value.year, date_value.month, date_value.day)

    @staticmethod
    def _to_datetime(date_value: QDate, time_value: datetime.time) -> datetime.datetime:
        return datetime.datetime.combine(date_value.toPyDate(), time_value)


class HistoryRangeController(QWidget):
    def __init__(
        self,
        date_range_picker: DateRangePicker,
        wallet_balance_chart: WalletBalanceChart,
        history_list: HistList,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.date_range_picker = date_range_picker
        self.wallet_balance_chart = wallet_balance_chart
        self.history_list = history_list

        self._reset_shortcut = QShortcut(self._reset_shortcut_key(), self)
        self._reset_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._reset_shortcut.activated.connect(self.reset_range)

        self.date_range_picker.signal_range_changed.connect(self._on_picker_range_changed)
        self.date_range_picker.signal_reset_requested.connect(self.reset_range)
        self.wallet_balance_chart.signal_time_range_changed.connect(self._on_chart_range_changed)
        self.wallet_balance_chart.signal_full_range_changed.connect(self._on_chart_full_range_changed)
        self.wallet_balance_chart.signal_zoom_reset.connect(self._on_chart_zoom_reset)
        self.wallet_balance_chart.signal_zoom_state_changed.connect(self._update_reset_hint)

    def reset_range(self) -> None:
        full_range = self.wallet_balance_chart.get_full_range()
        if not full_range:
            return
        self.wallet_balance_chart.reset_zoom()
        self.date_range_picker.set_preset(DateRangePreset.ALL_TIME)
        self.date_range_picker.set_range(full_range[0], full_range[1], update_preset=False)
        self.history_list.set_date_range(full_range[0], full_range[1])
        self._update_reset_hint()

    def _on_picker_range_changed(self, start: datetime.datetime, end: datetime.datetime) -> None:
        self.wallet_balance_chart.set_time_range(start, end)
        self.history_list.set_date_range(start, end)
        self._update_reset_hint()

    def _on_chart_range_changed(self, start: datetime.datetime, end: datetime.datetime) -> None:
        normalized_start, normalized_end = sorted((start, end))
        self.date_range_picker.set_range(start, end)
        self.history_list.set_date_range(normalized_start, normalized_end)
        self._update_reset_hint()

    def _on_chart_full_range_changed(self, start: datetime.datetime, end: datetime.datetime) -> None:
        self.date_range_picker.set_available_range(start, end)
        if not self.wallet_balance_chart.is_zoomed():
            self.date_range_picker.set_preset(DateRangePreset.ALL_TIME)
            self.date_range_picker.set_range(start, end, update_preset=False)
            self.history_list.set_date_range(start, end)
        self._update_reset_hint()

    def _on_chart_zoom_reset(self, start: datetime.datetime, end: datetime.datetime) -> None:
        self.date_range_picker.set_preset(DateRangePreset.ALL_TIME)
        self.date_range_picker.set_range(start, end, update_preset=False)
        self.history_list.set_date_range(start, end)
        self._update_reset_hint()

    def _update_reset_hint(self, _zoomed: bool | None = None) -> None:
        self.date_range_picker.set_reset_visible(self.wallet_balance_chart.is_zoomed())

    @staticmethod
    def _reset_shortcut_key() -> QKeySequence:
        # Keep exactly one reset shortcut.
        return QKeySequence("Alt+0")
