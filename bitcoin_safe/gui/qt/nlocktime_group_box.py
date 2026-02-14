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

import logging
import sys
from datetime import timedelta
from enum import Enum
from typing import cast

from bitcoin_safe_lib.gui.qt.util import age
from PyQt6.QtCore import QDateTime, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.signals import SignalProtocol
from bitcoin_safe.tx import LOCKTIME_THRESHOLD, MAX_NLOCKTIME, MEDIAN_TIME_PAST_LAG_MINUTES

logger = logging.getLogger(__name__)

BLOCK_HEIGHT_MAX = LOCKTIME_THRESHOLD - 1


class NLocktimeMode(Enum):
    BLOCK_HEIGHT = "block_height"
    DATE_TIME = "date_time"


class NLocktimeGroupBox(QGroupBox):
    signal_on_change = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self._current_block_height = 0
        self._mode_order = [NLocktimeMode.BLOCK_HEIGHT, NLocktimeMode.DATE_TIME]

        self.group_layout = QVBoxLayout(self)

        self.help_label = IconLabel()
        self.help_label.textLabel.setWordWrap(True)
        self.group_layout.addWidget(self.help_label)

        self.readonly_label = QLabel()
        self.readonly_label.setWordWrap(True)
        self.readonly_label.setVisible(False)
        self.group_layout.addWidget(self.readonly_label)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("", NLocktimeMode.BLOCK_HEIGHT)
        self.mode_combo.addItem("", NLocktimeMode.DATE_TIME)
        self.mode_combo.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.currentIndexChanged.connect(self.signal_on_change.emit)

        self.value_stack = QStackedWidget()
        self.value_stack.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setDecimals(0)
        self.height_spin.setSingleStep(1)
        self.height_spin.setRange(0, BLOCK_HEIGHT_MAX)
        self.height_spin.setMaximum(BLOCK_HEIGHT_MAX)
        self.height_spin.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        self.height_spin.valueChanged.connect(self.signal_on_change.emit)
        self.value_stack.addWidget(self.height_spin)

        self.time_edit = QDateTimeEdit()
        self.time_edit.setCalendarPopup(True)
        self.time_edit.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed))
        # QDateTimeEdit shows local time; we convert to/from UTC seconds explicitly.
        self.time_edit.setDateTime(QDateTime.currentDateTime())
        self.time_edit.setMinimumDateTime(QDateTime.fromSecsSinceEpoch(LOCKTIME_THRESHOLD))
        self.time_edit.setMaximumDateTime(QDateTime.fromSecsSinceEpoch(MAX_NLOCKTIME))
        self.time_edit.dateTimeChanged.connect(self.signal_on_change.emit)
        self.value_stack.addWidget(self.time_edit)

        self.group_layout.addWidget(self.mode_combo)
        self.group_layout.addWidget(self.value_stack)

        self._on_mode_changed(self.mode_combo.findData(NLocktimeMode.BLOCK_HEIGHT))
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setTitle("nLocktime")
        help_text = self.tr("Valid from")
        help_tooltip = self.tr(
            "Use block height to delay until a specific block is mined.\n"
            "Use date/time to delay until a specific network time (median-time-past).\n"
            "Median-time-past is the median timestamp of the last 11 blocks,\n"
            "so it is typically about {minutes} minutes behind the tip."
        ).format(minutes=MEDIAN_TIME_PAST_LAG_MINUTES)
        self.help_label.setText(help_text)
        self.help_label.set_icon_as_help(tooltip=help_tooltip)
        block_index = self.mode_combo.findData(NLocktimeMode.BLOCK_HEIGHT)
        if block_index >= 0:
            self.mode_combo.setItemText(block_index, self.tr("Block height"))
        time_index = self.mode_combo.findData(NLocktimeMode.DATE_TIME)
        if time_index >= 0:
            self.mode_combo.setItemText(time_index, self.tr("Date/time"))

    def _on_mode_changed(self, index: int) -> None:
        """On mode changed."""
        mode = self.mode_combo.currentData()
        if mode not in self._mode_order:
            return
        self.value_stack.setCurrentIndex(self._mode_order.index(mode))

    def set_allow_edit(self, allow_edit: bool) -> None:
        """Set allow edit."""
        self.mode_combo.setVisible(allow_edit)
        self.value_stack.setVisible(allow_edit)
        self.readonly_label.setVisible(not allow_edit)
        self.mode_combo.setEnabled(allow_edit)
        self.height_spin.setEnabled(allow_edit)
        self.time_edit.setEnabled(allow_edit)

    def _format_locktime_text(self, value: int | None) -> str:
        if value is None:
            return self.tr("No nLocktime set.")
        if value >= LOCKTIME_THRESHOLD:
            local_value = QDateTime.fromSecsSinceEpoch(value).toString("yyyy-MM-dd HH:mm")
            return self.tr("{value} (local time)").format(value=local_value)
        block_delta = value - self._current_block_height
        remaining = age(timedelta(minutes=10 * block_delta))
        return self.tr("Block height: {height} ({remaining})").format(
            height=value,
            remaining=remaining,
        )

    def set_readonly_text(self, text: str) -> None:
        """Set the read-only text shown when editing is disabled."""
        self.readonly_label.setText(text)

    def mode(self) -> NLocktimeMode:
        """Get mode."""
        mode = self.mode_combo.currentData()
        return mode if mode in self._mode_order else NLocktimeMode.BLOCK_HEIGHT

    def set_mode(self, mode: NLocktimeMode) -> None:
        """Set mode."""
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)

    def set_current_block_height(self, current_height: int) -> None:
        """Set current block height."""
        self._current_block_height = current_height

    def apply_current_block_height(self) -> None:
        """Apply the current block height to the input value."""
        value = max(0, min(self._current_block_height, int(self.height_spin.maximum())))
        self.height_spin.setValue(value)

    def reset_ui(self, current_height: int) -> None:
        self.time_edit.setDateTime(QDateTime.currentDateTime())
        self.set_mode(NLocktimeMode.BLOCK_HEIGHT)
        self.set_current_block_height(current_height)
        self.apply_current_block_height()

    def set_locktime(self, value: int | None, current_height: int) -> None:
        """Set locktime."""
        self.set_current_block_height(current_height=current_height)
        self.set_readonly_text(self._format_locktime_text(value))
        if value is None:
            self.set_mode(NLocktimeMode.BLOCK_HEIGHT)
            self.apply_current_block_height()
            return
        value = max(0, min(value, MAX_NLOCKTIME))
        if value >= LOCKTIME_THRESHOLD:
            self.set_mode(NLocktimeMode.DATE_TIME)
            # Interpret locktime as UTC seconds and display it as local time.
            self.time_edit.setDateTime(QDateTime.fromSecsSinceEpoch(value))
            return
        self.set_mode(NLocktimeMode.BLOCK_HEIGHT)
        self.height_spin.setValue(min(value, BLOCK_HEIGHT_MAX))

    def locktime(self) -> int:
        """Return the locktime in consensus format."""
        if self.mode() == NLocktimeMode.DATE_TIME:
            # Convert the local UI time to UTC seconds for consensus locktime.
            value = int(self.time_edit.dateTime().toSecsSinceEpoch())
        else:
            value = min(int(self.height_spin.value()), BLOCK_HEIGHT_MAX)
        return max(0, min(value, MAX_NLOCKTIME))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NLocktimeGroupBox()
    window.show()
    sys.exit(app.exec())
