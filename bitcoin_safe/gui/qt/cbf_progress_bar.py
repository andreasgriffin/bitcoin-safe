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

from bitcoin_safe_lib.gui.qt.util import age
from PyQt6.QtWidgets import QProgressBar, QWidget

from bitcoin_safe.client import ProgressInfo, SyncStatus
from bitcoin_safe.config import UserConfig
from bitcoin_safe.pythonbdk_types import BlockchainType

logger = logging.getLogger(__name__)


class CBFProgressBar(QProgressBar):
    def __init__(self, config: UserConfig, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.config = config
        self.setMinimumWidth(300)
        self.setRange(0, 100)
        self.set_progressbar(progress=0, text="0%", tooltip="")

    def _set_progress_info(self, progress_info: ProgressInfo):
        """Set progress info."""

        def format_timedelta(td: timedelta) -> str:
            """Format timedelta."""
            total_seconds = int(td.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        text = (
            progress_info.status_msg
            if progress_info.status_msg
            else self.tr("{percent}% - Finished {remaining_time}").format(
                percent=int(progress_info.progress * 100),
                remaining_time=age(from_date=progress_info.remaining_time),
            )
        )

        self.set_progressbar(
            progress=int(progress_info.progress * 100),
            text=text,
            tooltip=self.tr("Past time: {passed_time}").format(
                passed_time=format_timedelta(progress_info.passed_time)
            ),
        )

    def _set_visibility(self):
        """Set visibility."""
        self.setVisible(
            (self.value() < 100)
            and (self.config.network_config.server_type == BlockchainType.CompactBlockFilter)
        )

    def set_progressbar_sync_status(self, sync_status: SyncStatus):
        """Set progressbar sync status."""
        if sync_status in [SyncStatus.synced]:
            self.setValue(100)

        self._set_visibility()

    def set_progressbar(self, progress: int | None, text: str, tooltip: str):
        """Set progressbar."""
        if progress is not None:
            self.setValue(progress)
        self._set_visibility()

        if sys.platform.startswith("darwin"):
            self.setFormat(text)  # not visible
            self.setToolTip(text + "\n" + tooltip)
        else:
            self.setFormat(text)
            self.setToolTip(tooltip)
