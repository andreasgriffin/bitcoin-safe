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

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.util import serialized_to_hex

from .qr_components.image_widget import QRCodeWidgetSVG

logger = logging.getLogger(__name__)

import bdkpython as bdk
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...signals import Signals
from ...wallet import Wallet
from .hist_list import HistList, HistListWithToolbar
from .util import Buttons, CloseButton


class AddressDialog(QWidget):
    def __init__(
        self,
        fx,
        config: UserConfig,
        signals: Signals,
        wallet: Wallet,
        address: str,
        mempool_data: MempoolData,
        parent=None,
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Address"))
        self.mempool_data = mempool_data
        self.address = address
        self.bdk_address = bdk.Address(address, network=wallet.network)
        self.fx = fx
        self.config = config
        self.wallet: Wallet = wallet
        self.signals = signals
        self.saved = True

        self.setMinimumWidth(700)
        vbox = QVBoxLayout()
        self.setLayout(vbox)

        upper_widget = QWidget()
        upper_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        upper_widget_layout = QHBoxLayout(upper_widget)
        upper_widget_layout.setContentsMargins(0, 0, 0, 0)

        vbox.addWidget(upper_widget)

        self.tabs = QTabWidget()
        upper_widget_layout.addWidget(self.tabs)

        self.tab_details = QWidget()
        tab1_layout = QVBoxLayout(self.tab_details)
        tab1_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tabs.addTab(self.tab_details, "")
        self.tab_advanced = QWidget()
        tab2_layout = QVBoxLayout(self.tab_advanced)
        tab2_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.tabs.addTab(self.tab_advanced, "")

        address_info_min = self.wallet.get_address_info_min(address)
        if address_info_min:

            address_title = (
                self.tr("Receiving address of wallet '{wallet_id}' (with index {index})")
                if address_info_min.keychain == bdk.KeychainKind.EXTERNAL
                else self.tr("Change address of wallet '{wallet_id}' (with index {index})")
            ).format(wallet_id=wallet.id, index=address_info_min.index)
            tab1_layout.addWidget(QLabel(self.tr(address_title) + ":"))
        self.addr_e = ButtonEdit(self.address)
        self.addr_e.setReadOnly(True)
        self.addr_e.add_copy_button()
        # self.addr_e.setStyleSheet(f"background-color: {ColorScheme.GREEN.as_color(True).name()};")
        tab1_layout.addWidget(self.addr_e)

        try:
            script_pubkey = serialized_to_hex(self.bdk_address.script_pubkey().to_bytes())
        except BaseException:
            script_pubkey = None
        if script_pubkey:
            tab2_layout.addWidget(QLabel(self.tr("Script Pubkey") + ":"))
            pubkey_e = ButtonEdit(script_pubkey)
            pubkey_e.add_copy_button()
            pubkey_e.setReadOnly(True)
            tab2_layout.addWidget(pubkey_e)

        address_path_str = self.wallet.get_address_path_str(address)
        if address_path_str:
            tab2_layout.addWidget(QLabel(self.tr("Address descriptor") + ":"))
            der_path_e = ButtonEdit(address_path_str, input_field=QTextEdit())
            der_path_e.add_copy_button()
            der_path_e.setFixedHeight(50)
            der_path_e.setReadOnly(True)
            tab2_layout.addWidget(der_path_e)

        self.qr_code = QRCodeWidgetSVG()
        self.qr_code.set_data_list([self.bdk_address.to_qr_uri()])
        self.qr_code.setMaximumWidth(150)
        upper_widget_layout.addWidget(self.qr_code)

        self.hist_list = HistList(
            self.fx,
            self.config,
            self.signals,
            self.mempool_data,
            self.wallet.id,
            hidden_columns=[
                HistList.Columns.TXID,
                HistList.Columns.BALANCE,
            ],
            address_domain=[self.address],
            column_widths={HistList.Columns.TXID: 100},
        )
        toolbar = HistListWithToolbar(self.hist_list, self.config, parent=self)
        vbox.addWidget(toolbar)

        vbox.addLayout(Buttons(CloseButton(self)))
        self.setupUi()

    def setupUi(self):
        self.tabs.setTabText(self.tabs.indexOf(self.tab_details), self.tr("Details"))
        self.tabs.setTabText(self.tabs.indexOf(self.tab_advanced), self.tr("Advanced"))
