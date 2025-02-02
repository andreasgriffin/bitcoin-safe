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


import logging

from bitcoin_safe.gui.qt.export_data import (
    CopyToolButton,
    FileToolButton,
    QrToolButton,
    SyncChatToolButton,
)
from bitcoin_safe.gui.qt.keystore_ui import BaseHardwareSignerInteractionWidget
from bitcoin_safe.gui.qt.sync_tab import SyncTab
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.threading_manager import ThreadingManager

logger = logging.getLogger(__name__)


import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from PyQt6.QtWidgets import QWidget


class TxExport(BaseHardwareSignerInteractionWidget):
    def __init__(
        self,
        data: Data | None,
        network: bdk.Network,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager,
        sync_tabs: dict[str, SyncTab] | None = None,
        parent: QWidget | None = None,
    ) -> None:
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
            threading_parent=threading_parent,
            parent=self,
        )
        self.add_button(self.export_qr_button)

        ## file
        self.button_export_file = FileToolButton(data=self.data, network=network, parent=self)
        self.add_button(self.button_export_file)

        ## copy
        self.button_copy = CopyToolButton(data=self.data, network=network, parent=self)
        self.add_button(self.button_copy)

        # Sync & Chat
        self.button_sync_share = SyncChatToolButton(
            data=self.data, network=network, sync_tabs=sync_tabs, parent=self
        )
        self.add_button(self.button_sync_share)

        self.updateUi()

    def set_data(self, data: Data, sync_tabs: dict[str, SyncTab] | None = None):
        self.export_qr_button.set_data(data=data)
        self.button_export_file.set_data(data=data)
        self.button_copy.set_data(data=data)
        self.button_sync_share.set_data(data=data, sync_tabs=sync_tabs)

        self.updateUi()

    def set_minimum_size_as_floating_window(self):
        self.setMinimumSize(500, 200)
