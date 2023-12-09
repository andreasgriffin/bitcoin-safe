#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2012 thomasv@gitorious
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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

from bitcoin_safe.gui.qt.qr_components.image_widget import QRCodeWidgetSVG


logger = logging.getLogger(__name__)
import bdkpython as bdk
from typing import TYPE_CHECKING


from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from ...i18n import _

from .util import (
    WindowModalDialog,
    ButtonsLineEdit,
    ShowQRLineEdit,
    ColorScheme,
    Buttons,
    CloseButton,
    ShowCopyLineEdit,
)
from .qrtextedit import ShowQRTextEdit
from ...signals import Signals
from ...util import format_satoshis, serialized_to_hex
from .hist_list import HistList
from ...wallet import Wallet
from .util import ColorScheme


class AddressDialog(WindowModalDialog):
    def __init__(
        self, fx, config, signals: Signals, wallet: Wallet, address: str, parent=None
    ):
        WindowModalDialog.__init__(self, parent, _("Address"))
        self.address = address
        self.bdk_address = bdk.Address(address)
        self.fx = fx
        self.config = config
        self.wallet: Wallet = wallet
        self.signals = signals
        self.saved = True

        self.setMinimumWidth(700)
        vbox = QVBoxLayout()
        self.setLayout(vbox)

        upper_widget = QWidget()
        upper_widget_layout = QHBoxLayout(upper_widget)
        upper_widget_layout.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(upper_widget)

        upper_left_widget = QWidget()
        upper_left_widget_layout = QVBoxLayout(upper_left_widget)
        upper_left_widget_layout.setContentsMargins(0, 0, 0, 0)
        upper_left_widget_layout.setAlignment(Qt.AlignTop)
        upper_widget_layout.addWidget(upper_left_widget)

        address_info_min = self.wallet.address_info_min(address)
        address_title = f"{'Receiving' if address_info_min.keychain == bdk.KeychainKind.EXTERNAL else 'Change'} address of wallet \"{wallet.id}\"   (with index {address_info_min.index})"
        upper_left_widget_layout.addWidget(QLabel(_(address_title) + ":"))
        self.addr_e = ShowCopyLineEdit(self.address)
        # self.addr_e.setStyleSheet(f"background-color: {ColorScheme.GREEN.as_color(True).name()};")
        upper_left_widget_layout.addWidget(self.addr_e)

        # try:
        #     script_pubkey = serialized_to_hex( self.bdk_address.script_pubkey().to_bytes())
        # except BaseException as e:
        #     script_pubkey = None
        # if script_pubkey:
        #     upper_left_widget_layout.addWidget(QLabel(_("Script Pubkey") + ":"))
        #     pubkey_e = ButtonsLineEdit(script_pubkey)
        #     upper_left_widget_layout.addWidget(pubkey_e)

        # redeem_script = self.wallet.get_redeem_script(address)
        # if redeem_script:
        #     upper_left_widget_layout.addWidget(QLabel(_("Redeem Script") + ":"))
        #     redeem_e = ShowQRTextEdit(text=redeem_script, config=self.config)
        #     redeem_e.addCopyButton()
        #     upper_left_widget_layout.addWidget(redeem_e)

        # witness_script = self.wallet.get_witness_script(address)
        # if witness_script:
        #     upper_left_widget_layout.addWidget(QLabel(_("Witness Script") + ":"))
        #     witness_e = ShowQRTextEdit(text=witness_script, config=self.config)
        #     witness_e.addCopyButton()
        #     upper_left_widget_layout.addWidget(witness_e)

        address_path_str = self.wallet.get_address_path_str(address)
        if address_path_str:
            upper_left_widget_layout.addWidget(QLabel(_("Derivation path") + ":"))
            der_path_e = ButtonsLineEdit(address_path_str)
            der_path_e.addCopyButton()
            der_path_e.setReadOnly(True)
            upper_left_widget_layout.addWidget(der_path_e)

        self.qr_code = QRCodeWidgetSVG()
        self.qr_code.set_data(self.bdk_address.to_qr_uri())
        self.qr_code.setMinimumWidth(100)
        upper_widget_layout.addWidget(self.qr_code)

        self.hist_list = HistList(
            self.fx,
            self.config,
            self.signals,
            self.wallet.id,
            hidden_columns=[
                HistList.Columns.BALANCE,
                HistList.Columns.SATOSHIS,
                HistList.Columns.AMOUNT,
            ],
            txid_domain=[
                output_info.tx.txid
                for output_info in self.wallet.get_txs_involving_address(address)
            ],
            column_widths={HistList.Columns.TXID: 100},
        )
        vbox.addWidget(self.hist_list)

        vbox.addLayout(Buttons(CloseButton(self)))
        self.format_amount = format_satoshis

    def show_qr(self):
        text = self.address
        try:
            self.window.show_qrcode(text, "Address", parent=self)
        except Exception as e:
            self.show_message(repr(e))
