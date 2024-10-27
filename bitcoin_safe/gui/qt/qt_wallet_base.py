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
from typing import Callable, List, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.extended_tabwidget import ExtendedTabWidget
from bitcoin_safe.gui.qt.signal_carrying_object import SignalCarryingObject
from bitcoin_safe.gui.qt.wallet_steps_base import WalletStepsBase
from bitcoin_safe.threading_manager import ThreadingManager

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


class QtWalletBase(SignalCarryingObject, ThreadingManager):
    signal_after_sync = pyqtSignal(SyncStatus)  # SyncStatus
    wallet_steps: WalletStepsBase
    wallet_descriptor_tab: QWidget

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        get_lang_code: Callable[[], str],
        threading_parent: ThreadingManager | None = None,
        **kwargs
    ) -> None:
        super().__init__(threading_parent=threading_parent, **kwargs)
        self.get_lang_code = get_lang_code
        self.threading_parent = threading_parent
        self.config = config
        self.signals = signals

        self.tab = QWidget()

        self.outer_layout = QVBoxLayout(self.tab)

        # add the tab_widget for  history, utx, send tabs
        self.tabs = ExtendedTabWidget(object, parent=self.tab)

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
