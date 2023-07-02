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


logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING

from PySide2.QtWidgets import QVBoxLayout, QLabel, QWidget, QHBoxLayout

from bitcoin_safe.gui import qt

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
from ...util import format_satoshis
from .qrcodewidget import QRLabel
from .hist_list import HistList
from ...wallet import Wallet


class AddressDialog(WindowModalDialog):
    def __init__(self, fx, config, qt_wallet, address: str, parent=None):
        WindowModalDialog.__init__(self, parent, _("Address"))
        self.address = address
        self.fx = fx
        self.config = config
        self.wallet: Wallet = qt_wallet.wallet
        self.signals = qt_wallet.signals
        self.qt_wallet = qt_wallet
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
        upper_widget_layout.addWidget(upper_left_widget)

        upper_left_widget_layout.addWidget(QLabel(_("Address") + ":"))
        self.addr_e = ShowCopyLineEdit(self.address)
        upper_left_widget_layout.addWidget(self.addr_e)

        try:
            pubkeys = self.wallet.get_public_keys(address)
        except BaseException as e:
            pubkeys = None
        if pubkeys:
            upper_left_widget_layout.addWidget(QLabel(_("Public keys") + ":"))
            for pubkey in pubkeys:
                pubkey_e = ShowQRLineEdit(pubkey, self.config, title=_("Public Key"))
                upper_left_widget_layout.addWidget(pubkey_e)

        redeem_script = self.wallet.get_redeem_script(address)
        if redeem_script:
            upper_left_widget_layout.addWidget(QLabel(_("Redeem Script") + ":"))
            redeem_e = ShowQRTextEdit(text=redeem_script, config=self.config)
            redeem_e.addCopyButton()
            upper_left_widget_layout.addWidget(redeem_e)

        witness_script = self.wallet.get_witness_script(address)
        if witness_script:
            upper_left_widget_layout.addWidget(QLabel(_("Witness Script") + ":"))
            witness_e = ShowQRTextEdit(text=witness_script, config=self.config)
            witness_e.addCopyButton()
            upper_left_widget_layout.addWidget(witness_e)

        address_path_str = self.wallet.get_address_path_str(address)
        if address_path_str:
            upper_left_widget_layout.addWidget(QLabel(_("Derivation path") + ":"))
            der_path_e = ButtonsLineEdit(address_path_str)
            der_path_e.addCopyButton()
            der_path_e.setReadOnly(True)
            upper_left_widget_layout.addWidget(der_path_e)

        self.qr_code = QRLabel()
        self.qr_code.set_data(address)
        self.qr_code.setMaximumWidth(100)
        self.qr_code.setMaximumHeight(100)
        upper_widget_layout.addWidget(self.qr_code)

        self.hist_list = HistList(
            self.fx,
            self.config,
            self.signals,
            self.wallet.id,
            hidden_columns=[
                HistList.Columns.WALLET_ID,
                HistList.Columns.BALANCE,
                HistList.Columns.SATOSHIS,
                HistList.Columns.TXID,
            ],
            txid_domain=[
                output_info.outpoint.txid
                for output_info in self.wallet.get_txs_involving_address(address)
            ],
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
