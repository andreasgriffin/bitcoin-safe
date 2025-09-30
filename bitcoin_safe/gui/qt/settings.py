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


from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QTabWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.language_chooser import LanguageChooser
from bitcoin_safe.gui.qt.language_settings_ui import InterfaceSettingsUi
from bitcoin_safe.gui.qt.network_settings.main import NetworkSettingsUI
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.signals import Signals


class Settings(QTabWidget):
    def __init__(
        self,
        config: UserConfig,
        signals: Optional[Signals],
        language_chooser: LanguageChooser,
        fx: FX,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.signals = signals
        self.language_chooser = language_chooser

        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        # lannguage ui
        self.langauge_ui = InterfaceSettingsUi(config=config, fx=fx, language_chooser=language_chooser)
        self.addTab(self.langauge_ui, "")

        self.network_settings_ui = NetworkSettingsUI(
            network=config.network, network_configs=config.network_configs, signals=signals, parent=self
        )
        self.addTab(self.network_settings_ui, "")
        self.network_settings_ui.signal_cancel.connect(self.close)

        # category manager(s)
        # self.category_tab=QWidget()
        # self.addTab(self.category_tab, "")
        # self.category_tab_layout = QVBoxLayout(self.category_tab)
        # self.category_wallet_combobox = QComboBox()
        # self.category_tab_layout.addWidget(self.category_wallet_combobox)
        # self.current_category_manager:QWidget|None= None

        # self.fill_category_box()
        self.updateUi()

        # signals
        # self.category_wallet_combobox .currentIndexChanged.connect(self.on_category_wallet_combobox)

    # def showEvent(self, a0: Optional[QShowEvent]) -> None:
    #     self.fill_category_box()

    # def on_category_wallet_combobox(self ):
    #     if self.count()<=0:
    #         return
    #     if self.current_category_manager:
    #         self.current_category_manager.setHidden(True)
    #         self.current_category_manager.setParent(None)

    #     qt_wallet = self.category_wallet_combobox.currentData()
    #     if isinstance(qt_wallet, QTWallet):
    #         self.current_category_manager=qt_wallet.category_manager
    #         self.category_tab_layout.addWidget(self.current_category_manager)

    # def fill_category_box(self):
    #     self.category_wallet_combobox.clear()
    #     if not self.signals:
    #         return
    #     qt_wallets: List[QTWallet] = list(self.signals.get_qt_wallets.emit().values())
    #     for qt_wallet in qt_wallets:
    #         self.category_wallet_combobox.addItem(qt_wallet.wallet.id, qt_wallet)
    #         self.category_tab_layout.addWidget(self.current_category_manager)

    def updateUi(self) -> None:
        self.network_settings_ui.updateUi()
        self.langauge_ui.updateUi()
        self.setTabText(self.indexOf(self.network_settings_ui), self.tr("Network"))
        self.setTabText(self.indexOf(self.langauge_ui), self.tr("General"))
        # self.setTabText(self.indexOf(self.category_tab), self.tr("Category Manager"))

    def keyPressEvent(self, a0: QKeyEvent | None):
        # Check if the pressed key is 'Esc'
        if a0 and a0.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.close()

        super().keyPressEvent(a0)
