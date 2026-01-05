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
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.util_os import webopen
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QMessageBox, QSizePolicy

from bitcoin_safe.gui.qt.analyzers import AddressAnalyzer
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit, SquareButton
from bitcoin_safe.gui.qt.tx_util import advance_tip_to_address_info

from ...i18n import translate
from ...signals import (
    UpdateFilter,
    UpdateFilterReason,
    WalletFunctions,
    WalletSignals,
)
from ...wallet import Wallet, get_wallet_of_address
from .util import ColorScheme, block_explorer_URL, get_icon_path

logger = logging.getLogger(__name__)
MIN_ADVANCE_IF_PEEK_DISCOVERS_MINE = 20


class AddressEdit(ButtonEdit):
    signal_text_change = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_bip21_input = cast(SignalProtocol[[Data]], pyqtSignal(Data))

    def __init__(
        self,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        text="",
        allow_edit: bool = True,
        button_vertical_align: QtCore.Qt.AlignmentFlag | None = None,
        ask_to_replace_if_was_used=True,
        parent=None,
    ) -> None:
        """Initialize instance."""
        self.wallet_functions = wallet_functions
        self.signals = wallet_functions.signals
        self.network = network
        self.allow_edit = allow_edit
        self.ask_to_replace_if_was_used = ask_to_replace_if_was_used
        super().__init__(
            text=text,
            button_vertical_align=button_vertical_align,
            parent=parent,
            signal_update=self.signals.language_switch,
            close_all_video_widgets=self.signals.close_all_video_widgets,
        )

        self.setPlaceholderText(self.tr("Enter address here"))

        self.camera_button = self.add_qr_input_from_camera_button(
            network=network,
        )
        self.signal_data.connect(self._on_handle_input)
        self.copy_button = self.add_copy_button()
        self.mempool_button = self._add_mempool_button()

        self.input_field.setAnalyzer(AddressAnalyzer(self.network, parent=self))

        # ensure that the address_edit is the minimum vertical size
        self.setMaximumHeight(self.input_field.height())
        self.button_container.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.set_allow_edit(allow_edit)

        # signals
        self.input_field.textChanged.connect(self.on_text_changed)

    def _on_handle_input(self, data: Data) -> None:
        """On handle input."""
        if data.data_type == DataType.Bip21:
            if address := data.data.get("address"):
                self.setText(address)
            self.signal_bip21_input.emit(data)

    def set_allow_edit(self, allow_edit: bool):
        """Set allow edit."""
        self.allow_edit = allow_edit

        self.setReadOnly(not allow_edit)

        if self.camera_button:
            self.camera_button.setVisible(allow_edit)
        if self.copy_button:
            self.copy_button.setHidden(allow_edit)
        if self.mempool_button:
            self.mempool_button.setHidden(allow_edit)

    def _on_click(self) -> None:
        """On click."""
        mempool_url = self.signals.get_mempool_url()
        if mempool_url is None:
            return
        addr_URL = block_explorer_URL(mempool_url, "addr", self.address)
        if addr_URL:
            webopen(addr_URL)

    def _add_mempool_button(self) -> SquareButton:
        """Add mempool button."""
        copy_button = self.add_button(
            get_icon_path("block-explorer.svg"),
            self._on_click,
            tooltip=translate("d", "View on block explorer"),
        )
        return copy_button

    @property
    def address(self) -> str:
        """Address."""
        return self.text().strip()

    @address.setter
    def address(self, value: str) -> None:
        """Address."""
        self.setText(value)

    def updateUi(self):
        """UpdateUi."""
        super().updateUi()

        wallet = None
        if self.wallet_functions:
            wallet = get_wallet_of_address(self.address, self.wallet_functions)
        self.format_address_field(wallet=wallet)

    def on_text_changed(self, *args):
        """On text changed."""
        wallet = None
        if self.wallet_functions:
            wallet = get_wallet_of_address(self.address, self.wallet_functions)

        self.format_address_field(wallet=wallet)

        if (
            self.ask_to_replace_if_was_used
            and wallet
            and wallet.address_is_used(self.address)
            and self.allow_edit
        ):
            self.ask_to_replace_address(wallet, self.address)

        self.signal_text_change.emit(self.address)

    @classmethod
    def color_address(
        cls, address: str, wallet: Wallet, wallet_signals: WalletSignals
    ) -> QtGui.QColor | None:
        """Color address."""

        def get_color(is_change: bool) -> QtGui.QColor:
            """Get color."""
            if is_change:
                return ColorScheme.YELLOW.as_color(background=True)
            else:
                return ColorScheme.GREEN.as_color(background=True)

        if wallet.is_my_address(address):
            return get_color(is_change=wallet.is_change(address))
        else:
            address_info = wallet.is_my_address_with_peek(address=address)
            if not address_info:
                return None

            advance_tip_to_address_info(
                address_info=address_info,
                wallet=wallet,
                wallet_signals=wallet_signals,
                min_advance=MIN_ADVANCE_IF_PEEK_DISCOVERS_MINE,
            )
            return get_color(is_change=address_info.is_change())

    def format_address_field(self, wallet: Wallet | None) -> None:
        """Format address field."""
        palette = QtGui.QPalette()
        background_color = None

        background_color = None
        if wallet:
            background_color = self.color_address(
                self.address, wallet, wallet_signals=self.wallet_functions.wallet_signals[wallet.id]
            )

        if background_color:
            palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)

        self.input_field.setPalette(palette)
        self.input_field.update()
        self.update()
        # logger.debug(
        #     f"{self.__class__.__name__} format_address_field for self.address {str(self.address)[:6]}, background_color = {background_color.name() if background_color else None}"
        # )

    def ask_to_replace_address(self, wallet: Wallet, address: str) -> None:
        """Ask to replace address."""
        if question_dialog(
            text=translate(
                "recipients",
                f"Address {address} was used already. Would you like to get a fresh receiving address?",
            ),
            title=translate("recipients", "Address Already Used"),
            true_button=QMessageBox.StandardButton.Yes,
            false_button=QMessageBox.StandardButton.No,
        ):
            old_category = wallet.labels.get_category(address)
            self.address = str(wallet.get_unused_category_address(category=old_category).address)

            if self.wallet_functions:
                self.wallet_functions.wallet_signals[wallet.id].updated.emit(
                    UpdateFilter(addresses=set([self.address]), reason=UpdateFilterReason.UserReplacedAddress)
                )

            self.format_address_field(wallet)
