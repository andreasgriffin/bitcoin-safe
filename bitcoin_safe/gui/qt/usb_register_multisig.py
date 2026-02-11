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
from bitcoin_qr_tools.multipath_descriptor import (
    address_descriptor_from_multipath_descriptor,
)
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.analyzer_indicator import ElidedLabel
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsRegisterMultisig
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.keystore import KeyStore, KeyStoreImporterTypes

from ...signals import WalletFunctions
from .util import Message, MessageType, generate_help_button

logger = logging.getLogger(__name__)


class USBValidateAddressWidget(QWidget):
    def __init__(
        self,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.wallet_functions = wallet_functions
        self.network = network
        self.descriptor: bdk.Descriptor | None = None
        self.expected_address = ""
        self.address_index = 0
        self.kind = bdk.KeychainKind.EXTERNAL
        self.usb_gui = USBGui(
            self.network, allow_emulators_only_for_testnet_works=True, loop_in_thread=loop_in_thread
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.label_expected_address = QLabel()
        self._layout.addWidget(self.label_expected_address)

        self.edit_address = AddressEdit(
            network=network, allow_edit=False, parent=self, wallet_functions=self.wallet_functions
        )
        self._layout.addWidget(self.edit_address)

        # Create buttons and layout
        self.button_box = QDialogButtonBox()
        self._layout.addWidget(self.button_box)
        self._layout.setAlignment(self.button_box, Qt.AlignmentFlag.AlignCenter)

        self.button_validate_address = SpinningButton(
            text="",
            signal_stop_spinning=self.usb_gui.signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self,
            svg_tools=svg_tools,
        )
        self.button_validate_address.clicked.connect(self.on_button_click)
        self.button_box.addButton(self.button_validate_address, QDialogButtonBox.ButtonRole.AcceptRole)

        self.updateUi()
        self.wallet_functions.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.button_validate_address.setText(self.tr("Validate address"))
        self.label_expected_address.setText(self.tr("Validate receive address:"))

    def set_descriptor(
        self,
        descriptor: bdk.Descriptor,
        expected_address: str,
        kind: bdk.KeychainKind = bdk.KeychainKind.EXTERNAL,
        address_index: int = 0,
    ) -> None:
        """Set descriptor."""
        self.descriptor = descriptor
        self.expected_address = expected_address
        self.kind = kind
        self.address_index = address_index
        self.edit_address.setText(self.expected_address)

        self.updateUi()

    def on_button_click(
        self,
    ) -> bool:
        """On button click."""
        if not self.descriptor:
            logger.error("descriptor not set")
            return False

        address_descriptor = address_descriptor_from_multipath_descriptor(
            descriptor=self.descriptor, kind=self.kind, address_index=self.address_index
        )
        try:
            address = self.usb_gui.display_address(address_descriptor, slow_hwi_listing=True)
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), type=MessageType.Error, parent=self)
            return False

        return bool(address)


class USBRegisterMultisigWidget(USBValidateAddressWidget):
    signal_end_hwi_blocker = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
    ) -> None:
        """Initialize instance."""
        screenshots = ScreenshotsRegisterMultisig()
        self.button_help = generate_help_button(screenshots, title="Help")

        super().__init__(network, wallet_functions=wallet_functions, loop_in_thread=loop_in_thread)

        self.button_box.addButton(self.button_help, QDialogButtonBox.ButtonRole.HelpRole)

        self.xpubs_widget = QWidget()
        self.xpubs_widget_layout = QHBoxLayout(self.xpubs_widget)
        self.label_title_keystore = QLabel()
        self.label_xpubs_keystore = ElidedLabel(elide_mode=Qt.TextElideMode.ElideMiddle)
        self.xpubs_widget_layout.addWidget(self.label_title_keystore)
        self.xpubs_widget_layout.addWidget(self.label_xpubs_keystore)

        self._layout.insertWidget(0, self.xpubs_widget)

        # signals
        self.usb_gui.signal_end_hwi_blocker.connect(self.signal_end_hwi_blocker)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """CloseEvent."""
        self.signal_end_hwi_blocker.emit()
        return super().closeEvent(a0)

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        self.setWindowTitle(self.tr("Register Multisig wallet on hardware signer"))
        self.button_validate_address.setText(self.tr("Register Multisig"))
        self.button_help.setText(self.tr("Help"))

    def on_button_click(
        self,
    ) -> bool:
        """On button click."""
        result = super().on_button_click()

        if result:
            self.close()
            Message(
                self.tr("Successfully registered multisig wallet on hardware signer"),
                type=MessageType.Info,
                icon=svg_tools.get_QIcon("checkmark.svg"),
                parent=self,
            )
        return result

    def set_descriptor(  # type: ignore
        self,
        keystores: list[KeyStore],
        descriptor: bdk.Descriptor,
        expected_address: str,
        kind: bdk.KeychainKind = bdk.KeychainKind.EXTERNAL,
        address_index: int = 0,
    ) -> None:
        """Set descriptor."""
        super().set_descriptor(
            descriptor=descriptor, expected_address=expected_address, kind=kind, address_index=address_index
        )

        text_titles = "\n".join([f"{keystore.label}:" for keystore in keystores])
        text_xpubs = "\n".join([keystore.xpub for keystore in keystores])
        self.label_title_keystore.setText(text_titles)
        self.label_xpubs_keystore.setText(text_xpubs)
