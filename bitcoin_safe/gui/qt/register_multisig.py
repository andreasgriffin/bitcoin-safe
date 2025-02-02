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

from bitcoin_safe.gui.qt.export_data import (
    ExportDataSimple,
    FileToolButton,
    QrToolButton,
)
from bitcoin_safe.gui.qt.keystore_ui import HardwareSignerInteractionWidget
from bitcoin_safe.gui.qt.usb_register_multisig import USBRegisterMultisigWidget
from bitcoin_safe.threading_manager import ThreadingManager

logger = logging.getLogger(__name__)


import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsRegisterMultisig


class RegisterMultisigInteractionWidget(HardwareSignerInteractionWidget):
    def __init__(
        self, qt_wallet: QTWallet | None, threading_parent: ThreadingManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(self.tr("Register Multisig"))
        self.qt_wallet = qt_wallet

        # export widgets
        self.export_qr_widget = None
        if self.qt_wallet:
            self.export_qr_widget = ExportDataSimple(
                data=Data.from_str(
                    self.qt_wallet.wallet.multipath_descriptor.as_string(),
                    network=self.qt_wallet.wallet.network,
                ),
                signals_min=self.qt_wallet.signals,
                enable_clipboard=False,
                enable_usb=False,
                enable_file=False,
                enable_qr=True,
                network=self.qt_wallet.config.network,
                threading_parent=threading_parent,
                wallet_name=self.qt_wallet.wallet.id,
            )
            self.export_qr_widget.set_minimum_size_as_floating_window()

        ## help
        screenshots = ScreenshotsRegisterMultisig()
        self.add_help_button(screenshots)

        if self.export_qr_widget and self.qt_wallet:
            data = Data(
                data=self.qt_wallet.wallet.multipath_descriptor,
                data_type=DataType.MultiPathDescriptor,
                network=self.qt_wallet.wallet.network,
            )

            # qr
            self.export_qr_button = QrToolButton(
                data=data,
                signals_min=self.qt_wallet.signals,
                network=self.qt_wallet.wallet.network,
                threading_parent=threading_parent,
                parent=self,
            )
            self.add_button(self.export_qr_button)

            ## file
            self.button_export_file = FileToolButton(
                data=data,
                wallet_id=self.qt_wallet.wallet.id,
                network=self.qt_wallet.wallet.network,
                parent=self,
            )
            self.add_button(self.button_export_file)

            ## hwi

            addresses = self.qt_wallet.wallet.get_addresses()
            index = 0
            address = addresses[index] if len(addresses) > index else ""
            self.usb_widget = USBRegisterMultisigWidget(
                network=self.qt_wallet.wallet.network,
                signals=self.qt_wallet.signals,
            )
            self.usb_widget.set_descriptor(
                keystores=self.qt_wallet.wallet.keystores,
                descriptor=self.qt_wallet.wallet.multipath_descriptor,
                expected_address=address,
                kind=bdk.KeychainKind.EXTERNAL,
                address_index=index,
            )
            button_hwi = self.add_hwi_button(
                signal_end_hwi_blocker=self.usb_widget.usb_gui.signal_end_hwi_blocker
            )
            button_hwi.clicked.connect(self.usb_widget.show)

        self.updateUi()

    def set_minimum_size_as_floating_window(self):
        self.setMinimumSize(500, 200)
