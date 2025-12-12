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

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.export_data import FileToolButton, QrToolButton
from bitcoin_safe.gui.qt.keystore_ui import HardwareSignerInteractionWidget
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsRegisterMultisig
from bitcoin_safe.gui.qt.usb_register_multisig import USBRegisterMultisigWidget
from bitcoin_safe.signals import WalletFunctions
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


class RegisterMultisigInteractionWidget(HardwareSignerInteractionWidget):
    def __init__(
        self,
        wallet_functions: WalletFunctions | None,
        wallet: Wallet | None,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
        wallet_name: str = "MultiSig",
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.wallet = wallet
        self.wallet_functions = wallet_functions
        self.setWindowTitle(self.tr("Register {wallet_name}").format(wallet_name=wallet_name))

        ## help
        screenshots = ScreenshotsRegisterMultisig()
        self.add_help_button(screenshots)

        if self.wallet and self.wallet_functions:
            data = Data(
                data=self.wallet.multipath_descriptor,
                data_type=DataType.Descriptor,
                network=self.wallet.network,
            )

            # qr
            self.export_qr_button = QrToolButton(
                data=data,
                signals_min=self.wallet_functions.signals,
                network=self.wallet.network,
                loop_in_thread=loop_in_thread,
                parent=self,
                wallet_name=wallet_name,
            )
            self.add_button(self.export_qr_button)

            ## hwi

            addresses = self.wallet.get_addresses()
            index = 0
            address = addresses[index] if len(addresses) > index else ""
            self.usb_widget = USBRegisterMultisigWidget(
                network=self.wallet.network,
                wallet_functions=self.wallet_functions,
                loop_in_thread=loop_in_thread,
            )
            self.usb_widget.set_descriptor(
                keystores=self.wallet.keystores,
                descriptor=self.wallet.multipath_descriptor,
                expected_address=address,
                kind=bdk.KeychainKind.EXTERNAL,
                address_index=index,
            )
            button_hwi = self.add_hwi_button(signal_end_hwi_blocker=self.usb_widget.signal_end_hwi_blocker)
            button_hwi.clicked.connect(self.usb_widget.show)

            ## file
            self.button_export_file = FileToolButton(
                data=data,
                wallet_id=self.wallet.id,
                network=self.wallet.network,
                parent=self,
            )
            self.add_button(self.button_export_file)

        self.updateUi()

    def set_minimum_size_as_floating_window(self) -> None:
        """Set minimum size as floating window."""
        self.setMinimumSize(500, 200)
