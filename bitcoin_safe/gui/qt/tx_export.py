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

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.export_data import (
    FileToolButton,
    QrToolButton,
    SyncChatToolButton,
)
from bitcoin_safe.gui.qt.keystore_ui import BaseHardwareSignerInteractionWidget
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)


class TxExport(BaseHardwareSignerInteractionWidget):
    def __init__(
        self,
        data: Data | None,
        network: bdk.Network,
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        sync_client: dict[str, SyncClient] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.setWindowTitle(self.tr("Export Transaction"))
        self.data = data

        if not self.data:
            return

        ## qr
        self.export_qr_button = QrToolButton(
            data=self.data,
            signals_min=signals_min,
            network=network,
            loop_in_thread=loop_in_thread,
            parent=self,
        )
        self.add_button(self.export_qr_button)

        ## file
        self.button_export_file = FileToolButton(data=self.data, network=network, parent=self)
        self.add_button(self.button_export_file)

        # Sync & Chat
        self.button_sync_share = SyncChatToolButton(
            data=self.data, network=network, sync_client=sync_client, parent=self
        )
        self.add_button(self.button_sync_share)

        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.export_qr_button.updateUi()
        self.button_export_file.updateUi()
        self.button_sync_share.updateUi()
        super().updateUi()

    def set_data(self, data: Data, sync_client: dict[str, SyncClient] | None = None):
        """Set data."""
        self.export_qr_button.set_data(data=data)
        self.button_export_file.set_data(data=data)
        self.button_sync_share.set_data(data=data, sync_clients=sync_client)

        self.updateUi()

    def set_minimum_size_as_floating_window(self):
        """Set minimum size as floating window."""
        self.setMinimumSize(500, 200)
