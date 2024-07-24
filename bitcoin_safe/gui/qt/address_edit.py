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

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit

logger = logging.getLogger(__name__)

from typing import Optional

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QWidget

from ...i18n import translate
from ...signals import Signals
from ...wallet import Wallet, get_wallets
from .dialogs import question_dialog
from .util import ColorScheme


class AddressEdit(ButtonEdit):
    signal_text_change = pyqtSignal(str)
    signal_bip21_input = pyqtSignal(Data)

    def __init__(
        self,
        network: bdk.Network,
        text="",
        allow_edit: bool = True,
        button_vertical_align: Optional[QtCore.Qt] = None,
        parent=None,
        signals: Signals = None,
    ) -> None:
        self.signals = signals
        self.network = network
        self.allow_edit = allow_edit
        super().__init__(
            text=text,
            button_vertical_align=button_vertical_align,
            parent=parent,
            signal_update=signals.language_switch if signals else None,
        )

        self.setPlaceholderText(self.tr("Enter address here"))

        def on_handle_input(data: Data, parent: QWidget) -> None:
            if data.data_type == DataType.Bip21:
                if data.data.get("address"):
                    self.setText(data.data.get("address"))
                self.signal_bip21_input.emit(data)

        if allow_edit:
            self.add_qr_input_from_camera_button(
                network=network,
                custom_handle_input=on_handle_input,
            )
        else:
            self.add_copy_button()
            self.setReadOnly(True)

        def is_valid() -> bool:
            if not self.text():
                # if it is empty, show no error
                return True
            try:
                bdk_address = bdk.Address(self.address, network=network)
                return bool(bdk_address)
            except:
                return False

        self.set_validator(is_valid)
        self.input_field.textChanged.connect(self.on_text_changed)

    @property
    def address(self) -> str:
        return self.text().strip()

    @address.setter
    def address(self, value: str) -> None:
        self.setText(value)

    def get_wallet_of_address(self) -> Optional[Wallet]:
        if not self.signals:
            return None
        for wallet in get_wallets(self.signals):
            if wallet.is_my_address(self.address):
                return wallet
        return None

    def updateUi(self):
        super().updateUi()

        wallet = self.get_wallet_of_address()
        self.format_address_field(wallet=wallet)

    def on_text_changed(self, *args):
        wallet = self.get_wallet_of_address()

        self.format_address_field(wallet=wallet)

        if wallet and wallet.address_is_used(self.address) and self.allow_edit:
            self.ask_to_replace_address(wallet, self.address)

        self.signal_text_change.emit(self.address)

    def format_address_field(self, wallet: Optional[Wallet]) -> None:
        palette = QtGui.QPalette()
        background_color = None

        if wallet:
            if wallet.is_change(self.address):
                background_color = ColorScheme.YELLOW.as_color(background=True)
                palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
            else:
                background_color = ColorScheme.GREEN.as_color(background=True)
                palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)

        else:
            palette = self.input_field.style().standardPalette()

        self.input_field.setPalette(palette)
        self.input_field.update()
        self.update()
        logger.debug(
            f"{self.__class__.__name__} format_address_field for self.address {self.address}, background_color = {background_color.name() if background_color else None}"
        )

    def ask_to_replace_address(self, wallet: Wallet, address: str) -> None:
        if question_dialog(
            text=translate(
                "recipients",
                f"Address {address} was used already. Would you like to get a fresh receiving address?",
            ),
            title=translate("recipients", "Address Already Used"),
            buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
        ):
            self.address = wallet.get_address().address.as_string()
