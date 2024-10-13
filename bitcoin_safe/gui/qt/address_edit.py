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

from bitcoin_safe.gui.qt.analyzers import AddressAnalyzer
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit, SquareButton
from bitcoin_safe.util import block_explorer_URL

logger = logging.getLogger(__name__)

from typing import Optional

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QSizePolicy, QStyle

from ...i18n import translate
from ...signals import Signals, UpdateFilter, UpdateFilterReason
from ...wallet import Wallet, get_wallet_of_address
from .dialogs import question_dialog
from .util import ColorScheme, icon_path, webopen


class AddressEdit(ButtonEdit):
    signal_text_change = pyqtSignal(str)
    signal_bip21_input = pyqtSignal(Data)

    def __init__(
        self,
        network: bdk.Network,
        text="",
        allow_edit: bool = True,
        button_vertical_align: Optional[QtCore.Qt.AlignmentFlag] = None,
        parent=None,
        signals: Signals | None = None,
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

        def on_handle_input(data: Data) -> None:
            if data.data_type == DataType.Bip21:
                if data.data.get("address"):
                    self.setText(data.data.get("address"))
                self.signal_bip21_input.emit(data)

        self.camera_button = self.add_qr_input_from_camera_button(
            network=network,
        )
        self.signal_data.connect(on_handle_input)
        self.copy_button = self.add_copy_button()
        self.mempool_button = self._add_mempool_button(self.signals) if self.signals else None

        self.input_field.setAnalyzer(AddressAnalyzer(self.network, parent=self))

        # ensure that the address_edit is the minimum vertical size
        self.setMaximumHeight(self.input_field.height())
        self.button_container.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.set_allow_edit(allow_edit)

        # signals
        self.input_field.textChanged.connect(self.on_text_changed)

    def set_allow_edit(self, allow_edit: bool):
        self.allow_edit = allow_edit

        self.setReadOnly(not allow_edit)

        if self.camera_button:
            self.camera_button.setVisible(allow_edit)
        if self.copy_button:
            self.copy_button.setHidden(allow_edit)
        if self.mempool_button:
            self.mempool_button.setHidden(allow_edit)

    def _add_mempool_button(self, signals: Signals) -> SquareButton:
        def on_click() -> None:
            mempool_url: str = signals.get_mempool_url()
            addr_URL = block_explorer_URL(mempool_url, "addr", self.address)
            if addr_URL:
                webopen(addr_URL)

        copy_button = self.add_button(
            icon_path("link.svg"), on_click, tooltip=translate("d", "View on block explorer")
        )
        return copy_button

    @property
    def address(self) -> str:
        return self.text().strip()

    @address.setter
    def address(self, value: str) -> None:
        self.setText(value)

    def updateUi(self):
        super().updateUi()

        wallet = None
        if self.signals:
            wallet = get_wallet_of_address(self.address, self.signals)
        self.format_address_field(wallet=wallet)

    def on_text_changed(self, *args):
        wallet = None
        if self.signals:
            wallet = get_wallet_of_address(self.address, self.signals)

        self.format_address_field(wallet=wallet)

        if wallet and wallet.address_is_used(self.address) and self.allow_edit:
            self.ask_to_replace_address(wallet, self.address)

        self.signal_text_change.emit(self.address)

    @staticmethod
    def color_address(address: str, wallet: Wallet) -> Optional[QtGui.QColor]:
        if wallet.is_my_address(address):
            if wallet.is_change(address):
                return ColorScheme.YELLOW.as_color(background=True)
            else:
                return ColorScheme.GREEN.as_color(background=True)
        return None

    def format_address_field(self, wallet: Optional[Wallet]) -> None:
        palette = QtGui.QPalette()
        background_color = None

        background_color = None
        if wallet:
            background_color = self.color_address(self.address, wallet)

        if background_color:
            palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
        else:
            palette = (self.input_field.style() or QStyle()).standardPalette()

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
            old_category = wallet.labels.get_category(address)
            self.address = wallet.get_unused_category_address(category=old_category).address.as_string()

            if self.signals:
                self.signals.wallet_signals[wallet.id].updated.emit(
                    UpdateFilter(addresses=set([self.address]), reason=UpdateFilterReason.UserReplacedAddress)
                )

            self.format_address_field(wallet)
