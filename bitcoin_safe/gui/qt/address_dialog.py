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
import typing

from bitcoin_qr_tools.qr_widgets import QRCodeWidgetSVG

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.recipients import RecipientTabWidget
from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.util import serialized_to_hex

logger = logging.getLogger(__name__)

import bdkpython as bdk
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...signals import Signals
from ...wallet import Wallet
from .hist_list import HistList
from .util import Buttons, CloseButton


class AddressDetailsAdvanced(QWidget):
    def __init__(
        self, bdk_address: bdk.Address, address_path_str: str, parent: typing.Optional["QWidget"]
    ) -> None:
        super().__init__(parent)

        form_layout = QFormLayout(self)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        try:
            script_pubkey = serialized_to_hex(bdk_address.script_pubkey().to_bytes())
        except BaseException:
            script_pubkey = None
        if script_pubkey:
            pubkey_e = ButtonEdit(script_pubkey)
            pubkey_e.button_container.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            pubkey_e.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

            pubkey_e.add_copy_button()
            pubkey_e.setReadOnly(True)

            form_layout.addRow(self.tr("Script Pubkey"), pubkey_e)

        if address_path_str:
            der_path_e = ButtonEdit(address_path_str, input_field=QTextEdit())
            der_path_e.add_copy_button()
            der_path_e.setFixedHeight(50)
            der_path_e.setReadOnly(True)

            form_layout.addRow(self.tr("Address descriptor"), der_path_e)


class QRAddress(QRCodeWidgetSVG):
    def __init__(
        self,
    ) -> None:
        super().__init__(clickable=False)
        self.setMaximumSize(150, 150)

    def set_address(self, bdk_address: bdk.Address):
        self.set_data_list([bdk_address.to_qr_uri()])


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
    ) -> None:
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
        # upper_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        upper_widget.setLayout(QHBoxLayout())
        upper_widget.layout().setContentsMargins(0, 0, 0, 0)

        vbox.addWidget(upper_widget)

        self.recipient_tabs = RecipientTabWidget(
            network=wallet.network,
            allow_edit=False,
            parent=self,
            signals=self.signals,
            tab_string=self.tr('Address of wallet "{id}"'),
            dismiss_label_on_focus_loss=True,
        )
        self.recipient_tabs.address = self.address
        label = wallet.labels.get_label(self.address)
        self.recipient_tabs.label = label if label else ""
        self.recipient_tabs.amount = wallet.get_addr_balance(self.address).total

        upper_widget.layout().addWidget(self.recipient_tabs)

        self.tab_advanced = AddressDetailsAdvanced(
            bdk_address=self.bdk_address,
            address_path_str=self.wallet.get_address_path_str(address),
            parent=self,
        )
        self.recipient_tabs.addTab(self.tab_advanced, "")

        self.qr_code = QRAddress()
        self.qr_code.set_address(self.bdk_address)
        upper_widget.layout().addWidget(self.qr_code)

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
        vbox.addWidget(self.hist_list)

        vbox.addLayout(Buttons(CloseButton(self)))
        self.setupUi()

    # Override keyPressEvent method
    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.close()

    def setupUi(self) -> None:
        self.recipient_tabs.updateUi()
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.tab_advanced), self.tr("Advanced"))
