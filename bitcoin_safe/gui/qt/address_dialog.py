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
from typing import cast

import bdkpython as bdk
from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeyEvent, QKeySequence, QShortcut, QShowEvent
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit
from bitcoin_safe.gui.qt.dialogs import show_textedit_message
from bitcoin_safe.gui.qt.sign_message import SignMessage
from bitcoin_safe.gui.qt.ui_tx.recipients import RecipientBox
from bitcoin_safe.gui.qt.usb_register_multisig import USBValidateAddressWidget
from bitcoin_safe.gui.qt.util import center_on_screen, set_no_margins, svg_tools
from bitcoin_safe.mempool_manager import MempoolManager

from ...descriptors import get_address_bip32_path
from ...signals import SignalsMin, WalletFunctions
from ...wallet import Wallet
from .hist_list import HistList
from .util import do_copy

logger = logging.getLogger(__name__)


class AddressDetailsAdvanced(QWidget):
    def __init__(
        self,
        wallet_descriptor: bdk.Descriptor,
        kind: bdk.KeychainKind,
        address_index: int,
        network: bdk.Network,
        address_path_str: str,
        close_all_video_widgets: SignalProtocol[[]],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        parent: QWidget | None,
    ) -> None:
        """Initialize instance."""
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

        der_path_e = ButtonEdit(
            close_all_video_widgets=close_all_video_widgets,
            text=address_path_str,
            input_field=AnalyzerTextEdit(),
        )
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
            loop_in_thread=loop_in_thread,
            signals_min=signals_min,
        )
        self.sign_message.signal_signed_message.connect(self.on_signed_message)

    def on_signed_message(self, signed_message: str):
        """On signed message."""
        self.sign_message.close()
        title = self.tr("Signed Message")
        do_copy(signed_message, title=title)
        show_textedit_message(text=signed_message, label_description="", title=title)


class AddressValidateTab(QWidget):
    def __init__(
        self,
        bdk_address: bdk.Address,
        wallet_descriptor: bdk.Descriptor,
        kind: bdk.KeychainKind,
        address_index: int,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        parent: QWidget | None,
        loop_in_thread: LoopInThread,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self._layout = QHBoxLayout(self)

        edit_addr_descriptor = USBValidateAddressWidget(
            network=network, wallet_functions=wallet_functions, loop_in_thread=loop_in_thread
        )
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
        """Initialize instance."""
        super().__init__(clickable=False)
        self.setMaximumSize(150, 150)

    def set_address(self, bdk_address: bdk.Address):
        """Set address."""
        self.set_data_list([bdk_address.to_qr_uri()])


class AddressDialog(QWidget):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        fx,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        wallet: Wallet,
        address: str,
        mempool_manager: MempoolManager,
        loop_in_thread: LoopInThread,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(self.tr("Address"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self.mempool_manager = mempool_manager
        self.address = address
        self.bdk_address = bdk.Address(address, network=wallet.network)
        self.fx = fx
        self.config = config
        self.wallet: Wallet = wallet
        self.wallet_functions = wallet_functions
        self.saved = True

        self.setMinimumWidth(700)
        vbox = QVBoxLayout(self)
        self.setLayout(vbox)

        upper_widget = QWidget(self)
        # upper_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.upper_widget_layout = QHBoxLayout(upper_widget)
        set_no_margins(self.upper_widget_layout)

        vbox.addWidget(upper_widget)

        self.recipient_tabs = QTabWidget(self)
        self.recipient_box = RecipientBox(
            network=wallet.network,
            allow_edit=False,
            parent=self,
            wallet_functions=self.wallet_functions,
            fx=fx,
            show_header_bar=False,
            groupbox_style=False,
        )
        self.recipient_tabs.addTab(self.recipient_box, "")
        self.recipient_box.notification_bar.set_wallet_id(wallet_id=wallet.id)
        self.recipient_box.address = self.address
        label = wallet.labels.get_label(self.address)
        self.recipient_box.label = label if label else ""
        self.recipient_box.amount = wallet.get_addr_balance(self.address).total

        self.upper_widget_layout.addWidget(self.recipient_tabs)
        address_info = self.wallet.get_address_info_min(address)
        self.tab_advanced = (
            AddressDetailsAdvanced(
                address_path_str=self.wallet.get_address_path_str(address),
                parent=self,
                close_all_video_widgets=self.wallet_functions.signals.close_all_video_widgets,
                network=config.network,
                wallet_descriptor=self.wallet.multipath_descriptor,
                kind=address_info.keychain,
                address_index=address_info.index,
                signals_min=self.wallet_functions.signals,
                loop_in_thread=loop_in_thread,
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
                wallet_functions=self.wallet_functions,
                wallet_descriptor=self.wallet.multipath_descriptor,
                kind=address_info.keychain,
                address_index=address_info.index,
                parent=self,
                loop_in_thread=loop_in_thread,
            )
            if address_info
            else None
        )
        if self.tab_validate:
            self.recipient_tabs.addTab(self.tab_validate, "")

        self.qr_code = QRAddress()
        self.qr_code.set_address(self.bdk_address)
        self.upper_widget_layout.addWidget(self.qr_code)

        self.hist_list = HistList(
            fx=self.fx,
            config=self.config,
            wallet_functions=self.wallet_functions,
            mempool_manager=self.mempool_manager,
            wallets=[self.wallet],
            hidden_columns=[
                HistList.Columns.TXID,
                HistList.Columns.BALANCE,
            ],
            address_domain=[self.address],
        )
        vbox.addWidget(self.hist_list)

        self.close_button = QPushButton(self)
        self.close_button.clicked.connect(self.close)
        self.close_button.setDefault(True)
        vbox.addWidget(self.close_button)

        self.setupUi()

        self.shortcut_close = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close.activated.connect(self.close)
        self.shortcut_close2 = QShortcut(QKeySequence("ESC"), self)
        self.shortcut_close2.activated.connect(self.close)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        center_on_screen(self)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """KeyPressEvent."""
        if a0 and a0.key() == Qt.Key.Key_Escape:
            self.close()

        super().keyPressEvent(a0)

    def setupUi(self) -> None:
        """SetupUi."""
        self.recipient_box.updateUi()
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.recipient_box), self.tr("Address"))
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.tab_advanced), self.tr("Advanced"))
        self.recipient_tabs.setTabText(self.recipient_tabs.indexOf(self.tab_validate), self.tr("Validate"))
        self.close_button.setText(self.tr("Close"))

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)
