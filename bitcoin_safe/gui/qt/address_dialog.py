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

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.util import serialized_to_hex

from .qr_components.image_widget import QRCodeWidgetSVG
from .util import Satoshis

logger = logging.getLogger(__name__)

import bdkpython as bdk
from PySide2.QtGui import QFont, Qt
from PySide2.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import _
from ...signals import Signals
from ...wallet import Wallet
from .hist_list import HistList
from .util import Buttons, CloseButton


class AddressDialog(QDialog):
    def __init__(self, fx, config, signals: Signals, wallet: Wallet, address: str, parent=None):
        super().__init__()
        self.setWindowTitle("Address")
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
        upper_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        upper_widget_layout = QHBoxLayout(upper_widget)
        upper_widget_layout.setContentsMargins(0, 0, 0, 0)

        vbox.addWidget(upper_widget)

        tabs = QTabWidget()
        upper_widget_layout.addWidget(tabs)

        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setAlignment(Qt.AlignTop)
        tabs.addTab(tab1, "Details")
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setAlignment(Qt.AlignTop)
        tabs.addTab(tab2, "Advanced")

        address_info_min = self.wallet.address_info_min(address)
        if address_info_min:
            address_title = f"{'Receiving' if address_info_min.keychain == bdk.KeychainKind.EXTERNAL else 'Change'} address of wallet \"{wallet.id}\"   (with index {address_info_min.index})"
            tab1_layout.addWidget(QLabel(_(address_title) + ":"))
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
            tab2_layout.addWidget(QLabel(_("Script Pubkey") + ":"))
            pubkey_e = ButtonEdit(script_pubkey)
            pubkey_e.add_copy_button()
            pubkey_e.setReadOnly(True)
            tab2_layout.addWidget(pubkey_e)

        address_path_str = self.wallet.get_address_path_str(address)
        if address_path_str:
            tab2_layout.addWidget(QLabel(_("Address descriptor") + ":"))
            der_path_e = ButtonEdit(address_path_str, input_field=QTextEdit())
            der_path_e.add_copy_button()
            der_path_e.setFixedHeight(50)
            der_path_e.setReadOnly(True)
            tab2_layout.addWidget(der_path_e)

        self.qr_code = QRCodeWidgetSVG()
        self.qr_code.set_data_list([self.bdk_address.to_qr_uri()])
        self.qr_code.setMaximumWidth(150)
        upper_widget_layout.addWidget(self.qr_code)

        self.balance_label = QLabel(
            f"Balance: {Satoshis(   self.wallet.get_addr_balance(self.address).total, self.wallet.network).str_with_unit()}"
        )
        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)
        vbox.addWidget(self.balance_label)

        self.hist_list = HistList(
            self.fx,
            self.config,
            self.signals,
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

    def show_qr(self):
        text = self.address
        try:
            self.window.show_qrcode(text, "Address", parent=self)
        except Exception as e:
            self.show_message(repr(e))
