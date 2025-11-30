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
from abc import abstractmethod
from typing import cast

from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.client import SyncStatus
from bitcoin_safe.gui.qt.descriptor_ui import DescriptorUI
from bitcoin_safe.gui.qt.wizard_base import WizardBase

from ...config import UserConfig
from ...signals import WalletFunctions
from ...wallet import ProtoWallet
from .sidebar.sidebar_tree import SidebarNode

logger = logging.getLogger(__name__)


class WrapperQWidget(QWidget):
    def __init__(self, parent=None, **kwargs) -> None:
        """Initialize instance."""
        super().__init__(parent, **kwargs)


class QtWalletBase(WrapperQWidget):
    signal_after_sync = cast(SignalProtocol[[SyncStatus]], pyqtSignal(SyncStatus))  # SyncStatus
    wizard: WizardBase | None = None
    wallet_descriptor_ui: DescriptorUI

    def __init__(
        self,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread | None,
        tutorial_index: int | None = None,
        parent=None,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, **kwargs)
        self.signal_tracker = SignalTracker()
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None

        self.config = config
        self.wallet_functions = wallet_functions
        self.signals = wallet_functions.signals
        self.tutorial_index = tutorial_index

        self.outer_layout = QVBoxLayout(self)
        current_margins = self.outer_layout.contentsMargins()
        self.outer_layout.setContentsMargins(
            0, current_margins.top() // 2, 0, 0
        )  # Left, Top, Right, Bottom margins

        # add the tab_widget for  history, utx, send tabs
        self.tabs = SidebarNode[object](title="", widget=None, data=self, closable=True)

        # self.outer_layout.addWidget(self.tabs)

    @abstractmethod
    def get_mn_tuple(self) -> tuple[int, int]:
        """Get mn tuple."""
        pass

    @abstractmethod
    def get_keystore_labels(self) -> list[str]:
        """Get keystore labels."""
        pass

    @abstractmethod
    def get_editable_protowallet(self) -> ProtoWallet:
        """Get editable protowallet."""
        pass

    def set_tutorial_index(self, value: int | None):
        """Set tutorial index."""
        self.tutorial_index = value
        if self.wizard:
            self.wizard.set_visibilities()

    def close(self) -> bool:
        """Close."""
        SignalTools.disconnect_all_signals_from(self)
        self.signal_tracker.disconnect_all()
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()
        if self.wizard:
            self.wizard.close()
            self.wizard = None
        self.setParent(None)
        return super().close()
