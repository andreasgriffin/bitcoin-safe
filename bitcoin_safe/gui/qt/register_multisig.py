#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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
#

from __future__ import annotations

import logging
from functools import partial

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.unified_encoder import QrExportType
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QPushButton, QWidget

from bitcoin_safe.gui.qt.export_data import FileToolButton, QrToolButton
from bitcoin_safe.gui.qt.hardware_signer_interaction_widget import HardwareSignerInteractionWidget
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsRegisterMultisig
from bitcoin_safe.gui.qt.usb_register_multisig import USBRegisterMultisigWidget
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.hardware_signers import DescriptorQrExportTypes, HardwareSigner
from bitcoin_safe.signals import WalletFunctions
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


def preferred_register_multisig_qr_type(hardware_signer: HardwareSigner) -> QrExportType | None:
    descriptor_qr_type_names = {item.name for item in DescriptorQrExportTypes.as_list()}
    descriptor_qr_types = [
        qr_type for qr_type in hardware_signer.qr_types if qr_type.name in descriptor_qr_type_names
    ]
    for qr_type in descriptor_qr_types:
        if qr_type.name == DescriptorQrExportTypes.coldcard_legacy.name:
            return qr_type
    return descriptor_qr_types[0] if descriptor_qr_types else None


class RegisterMultisigInteractionWidget(HardwareSignerInteractionWidget):
    def __init__(
        self,
        wallet_functions: WalletFunctions | None,
        wallet: Wallet | None,
        loop_in_thread: LoopInThread,
        hardware_signer: HardwareSigner | None = None,
        parent: QWidget | None = None,
        wallet_name: str = "MultiSig",
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.wallet = wallet
        self.wallet_functions = wallet_functions
        self.hardware_signer = hardware_signer
        self._help_widget: ScreenshotsRegisterMultisig | None = None
        self.setWindowTitle(self.tr("Register {wallet_name}").format(wallet_name=wallet_name))

        help_button = self.add_help_button()
        help_button.clicked.connect(self._show_help_widget)

        if self.wallet and self.wallet_functions:
            data = Data(
                data=self.wallet.multipath_descriptor,
                data_type=DataType.Descriptor,
                network=self.wallet.network,
            )
            preferred_qr_type = (
                preferred_register_multisig_qr_type(self.hardware_signer) if self.hardware_signer else None
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

            self.simple_button_export_qr = QPushButton(self)
            self.simple_button_export_qr.setIcon(svg_tools.get_QIcon("bi--qr-code.svg"))
            self.simple_button_export_qr.clicked.connect(
                partial(self.export_qr_button.show_export_widget, preferred_qr_type)
            )
            self.add_button(self.simple_button_export_qr)

            if preferred_qr_type:
                self.export_qr_button.select_export_type(preferred_qr_type)
                self.export_qr_button.setVisible(False)
            else:
                self.simple_button_export_qr.setVisible(False)

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

    def _show_help_widget(self) -> None:
        """Show a fresh help window each time to avoid stale deleted child widgets."""
        if self._help_widget:
            try:
                self._help_widget.destroyed.disconnect(self._clear_help_widget)
            except TypeError:
                pass
            self._help_widget.close()

        self._help_widget = ScreenshotsRegisterMultisig(parent=None)
        self._help_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._help_widget.destroyed.connect(self._clear_help_widget)
        self._help_widget.setWindowTitle(self.tr("Device instructions"))
        self._help_widget.setWindowFlag(Qt.WindowType.Window, True)
        self._help_widget.show()
        self._help_widget.raise_()
        self._help_widget.activateWindow()

    def _clear_help_widget(self, destroyed_widget: QObject | None = None) -> None:
        """Clear the cached help window reference after the window is destroyed."""
        _ = destroyed_widget
        self._help_widget = None

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Close any detached help window alongside the parent widget."""
        if self._help_widget:
            self._help_widget.close()
        super().closeEvent(a0)

    def set_minimum_size_as_floating_window(self) -> None:
        """Set minimum size as floating window."""
        self.setMinimumSize(500, 200)
