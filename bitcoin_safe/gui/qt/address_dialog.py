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

import bdkpython as bdk
from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.recipients import RecipientTabWidget
from bitcoin_safe.gui.qt.sign_message import SignMessage
from bitcoin_safe.gui.qt.usb_register_multisig import USBValidateAddressWidget
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.keystore import KeyStoreImporterTypes
from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.typestubs import TypedPyQtSignal, TypedPyQtSignalNo

from ...descriptors import get_address_bip32_path
from ...signals import Signals, SignalsMin
from ...wallet import Wallet
from .hist_list import HistList
from .util import Buttons, CloseButton

logger = logging.getLogger(__name__)


class AddressDetailsAdvanced(QWidget):
    def __init__(
        self,
        wallet_descriptor: bdk.Descriptor,
        kind: bdk.KeychainKind,
        address_index: int,
        network: bdk.Network,
        address_path_str: str,
        close_all_video_widgets: TypedPyQtSignalNo,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager | None,
        parent: typing.Optional["QWidget"],
    ) -> None:
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        form_layout = QGridLayout(self)
        # form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # try:
        #     script_pubkey = serialized_to_hex(bdk_address.script_pubkey().to_bytes())
        # except BaseException:
        #     script_pubkey = None
        # if script_pubkey:
        #     pubkey_e = ButtonEdit(close_all_video_widgets=close_all_video_widgets, text=script_pubkey)
        #     pubkey_e.button_container.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        #     pubkey_e.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        #     pubkey_e.add_copy_button()
        #     pubkey_e.setReadOnly(True)

        #     form_layout.addRow(self.tr("Script Pubkey"), pubkey_e)

        der_path_e = ButtonEdit(close_all_video_widgets=close_all_video_widgets, text=address_path_str)
        der_path_e.add_copy_button()
        der_path_e.setFixedHeight(50)
        der_path_e.setReadOnly(True)

        form_layout.addWidget(QLabel(self.tr("Address descriptor")), 0, 0)
        form_layout.addWidget(der_path_e, 0, 1, 1, 3)

        # sign message row
        self.sign_message = SignMessage(
            bip32_path=get_address_bip32_path(
                descriptor_str=str(wallet_descriptor), kind=kind, index=address_index
            ),
            network=network,
            close_all_video_widgets=close_all_video_widgets,
            parent=self,
            grid_layout=form_layout,
            threading_parent=threading_parent,
            signals_min=signals_min,
        )


class AddressValidateTab(QWidget):
    def __init__(
        self,
        bdk_address: bdk.Address,
        wallet_descriptor: bdk.Descriptor,
        kind: bdk.KeychainKind,
        address_index: int,
        network: bdk.Network,
        signals: Signals,
        parent: typing.Optional["QWidget"],
    ) -> None:
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self._layout = QHBoxLayout(self)

        edit_addr_descriptor = USBValidateAddressWidget(network=network, signals=signals)
        edit_addr_descriptor.set_descriptor(
            descriptor=wallet_descriptor,
            expected_address=str(bdk_address),
            kind=kind,
            address_index=address_index,
        )
        self._layout.addWidget(edit_addr_descriptor)


class QRAddress(QRCodeWidgetSVG):
    def __init__(
        self,
    ) -> None:
        super().__init__(clickable=False)
        self.setMaximumSize(150, 150)

    def set_address(self, bdk_address: bdk.Address):
        self.set_data_list([bdk_address.to_qr_uri()])


class AddressDialog(QWidget):
    aboutToClose: TypedPyQtSignal[QWidget] = pyqtSignal(QWidget)  # type: ignore

    def __init__(
        self,
        fx,
        config: UserConfig,
        signals: Signals,
        wallet: Wallet,
        address: str,
        mempool_data: MempoolData,
        threading_parent: ThreadingManager | None,
        parent=None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Address"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

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
        self.upper_widget_layout = QHBoxLayout(upper_widget)
        self.upper_widget_layout.setContentsMargins(0, 0, 0, 0)

        vbox.addWidget(upper_widget)

        self.recipient_tabs = RecipientTabWidget(
            network=wallet.network,
            allow_edit=False,
            parent=self,
            signals=self.signals,
            tab_string=self.tr('Address of wallet "{id}"'),
        )
        self.recipient_tabs.address = self.address
        label = wallet.labels.get_label(self.address)
        self.recipient_tabs.label = label if label else ""
        self.recipient_tabs.amount = wallet.get_addr_balance(self.address).total

        self.upper_widget_layout.addWidget(self.recipient_tabs)

        address_info = self.wallet.get_address_info_min(address)
        self.tab_advanced = (
            AddressDetailsAdvanced(
                address_path_str=self.wallet.get_address_path_str(address),
                parent=self,
                close_all_video_widgets=self.signals.close_all_video_widgets,
                network=config.network,
                wallet_descriptor=self.wallet.multipath_descriptor,
                kind=address_info.keychain,
                address_index=address_info.index,
                signals_min=self.signals,
                threading_parent=threading_parent,
            )
            if address_info
            else None
        )
        if self.tab_advanced:
            self.recipient_tabs.addTab(self.tab_advanced, "")

        self.tab_validate = (
            AddressValidateTab(
                bdk_address=self.bdk_address,
                network=config.network,
                signals=self.signals,
                wallet_descriptor=self.wallet.multipath_descriptor,
                kind=address_info.keychain,
                address_index=address_info.index,
                parent=self,
            )
            if address_info
            else None
        )
        if self.tab_validate:
            self.recipient_tabs.addTab(
                self.tab_validate, svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename), ""
            )

        self.qr_code = QRAddress()
        self.qr_code.set_address(self.bdk_address)
        self.upper_widget_layout.addWidget(self.qr_code)

        self.hist_list = HistList(
            fx=self.fx,
            config=self.config,
            signals=self.signals,
            mempool_data=self.mempool_data,
            wallets=[self.wallet],
            hidden_columns=[
                HistList.Columns.TXID,
                HistList.Columns.BALANCE,
            ],
            address_domain=[self.address],
        )
        vbox.addWidget(self.hist_list)

        vbox.addLayout(Buttons(CloseButton(self)))
        self.setupUi()

        self.shortcut_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close.activated.connect(self.close)
        self.shortcut_close2 = QShortcut(QKeySequence("ESC"), self)
        self.shortcut_close2.activated.connect(self.close)

    # Override keyPressEvent method
    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.close()

    def setupUi(self) -> None:
        self.recipient_tabs.updateUi()
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.tab_advanced), self.tr("Advanced"))
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.tab_validate), self.tr("Validate"))

    def closeEvent(self, a0: QCloseEvent | None):
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)
