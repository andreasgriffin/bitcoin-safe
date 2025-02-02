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


import enum
import logging
from abc import abstractmethod
from typing import List, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.wizard_base import WizardBase
from bitcoin_safe.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.typestubs import TypedPyQtSignal

from ...config import UserConfig
from ...signals import Signals
from ...wallet import ProtoWallet

logger = logging.getLogger(__name__)


class SyncStatus(enum.Enum):
    unknown = enum.auto()
    unsynced = enum.auto()
    syncing = enum.auto()
    synced = enum.auto()
    error = enum.auto()


class WrapperQWidget(QWidget):
    def __init__(self, parent=None, **kwargs) -> None:
        super().__init__(parent, **kwargs)


class QtWalletBase(WrapperQWidget, ThreadingManager):
    signal_after_sync: TypedPyQtSignal[SyncStatus] = pyqtSignal(SyncStatus)  # type: ignore  # SyncStatus
    wizard: WizardBase | None = None
    wallet_descriptor_tab: QWidget

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        threading_parent: ThreadingManager | None = None,
        tutorial_index: int | None = None,
        parent=None,
        **kwargs,
    ) -> None:
        super().__init__(threading_parent=threading_parent, parent=parent, **kwargs)
        self.signal_tracker = SignalTracker()

        self.config = config
        self.signals = signals
        self.tutorial_index = tutorial_index

        self.outer_layout = QVBoxLayout(self)
        current_margins = self.outer_layout.contentsMargins()
        self.outer_layout.setContentsMargins(
            0, current_margins.top() // 2, 0, 0
        )  # Left, Top, Right, Bottom margins

        # add the tab_widget for  history, utx, send tabs
        self.tabs = QTabWidget(self)

        self.outer_layout.addWidget(self.tabs)

    @abstractmethod
    def get_mn_tuple(self) -> Tuple[int, int]:
        pass

    @abstractmethod
    def get_keystore_labels(self) -> List[str]:
        pass

    @abstractmethod
    def get_editable_protowallet(self) -> ProtoWallet:
        pass

    def set_tutorial_index(self, value: int | None):
        self.tutorial_index = value
        if self.wizard:
            self.wizard.set_visibilities()

    def close(self) -> bool:
        SignalTools.disconnect_all_signals_from(self)
        self.signal_tracker.disconnect_all()
        self.end_threading_manager()
        if self.wizard:
            self.wizard.close()
            self.wizard = None
        self.setParent(None)
        return super().close()
