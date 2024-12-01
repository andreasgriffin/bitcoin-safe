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
from typing import List, Optional

from bitcoin_safe.descriptors import MultipathDescriptor
from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.analyzer_indicator import ElidedLabel
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsRegisterMultisig
from bitcoin_safe.keystore import KeyStore, KeyStoreImporterTypes
from bitcoin_safe.signals import Signals

logger = logging.getLogger(__name__)


import bdkpython as bdk
from bitcoin_usb.gui import USBGui
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...signals import Signals
from .util import Message, MessageType, generate_help_button, read_QIcon


class USBValidateAddressWidget(QWidget):
    def __init__(
        self,
        network: bdk.Network,
        signals: Signals,
    ) -> None:
        super().__init__()
        self.signals = signals
        self.network = network
        self.descriptor: Optional[MultipathDescriptor] = None
        self.expected_address = ""
        self.address_index = 0
        self.kind = bdk.KeychainKind.EXTERNAL
        self.usb = USBGui(self.network, allow_emulators_only_for_testnet_works=True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.label_expected_address = QLabel()
        self._layout.addWidget(self.label_expected_address)

        self.edit_address = AddressEdit(network=network, allow_edit=False, parent=self, signals=self.signals)
        self._layout.addWidget(self.edit_address)

        # Create buttons and layout
        self.button_box = QDialogButtonBox()
        self._layout.addWidget(self.button_box)
        self._layout.setAlignment(self.button_box, Qt.AlignmentFlag.AlignCenter)

        self.button_validate_address = QPushButton()
        self.button_validate_address.setIcon(read_QIcon(KeyStoreImporterTypes.hwi.icon_filename))
        self.button_validate_address.clicked.connect(self.on_button_click)
        self.button_box.addButton(self.button_validate_address, QDialogButtonBox.ButtonRole.AcceptRole)

        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.button_validate_address.setText(self.tr("Validate address"))
        self.label_expected_address.setText(self.tr("Validate receive address:"))

    def set_descriptor(
        self,
        descriptor: MultipathDescriptor,
        expected_address: str,
        kind: bdk.KeychainKind = bdk.KeychainKind.EXTERNAL,
        address_index: int = 0,
    ) -> None:
        self.descriptor = descriptor
        self.expected_address = expected_address
        self.kind = kind
        self.address_index = address_index
        self.edit_address.setText(self.expected_address)

        self.updateUi()

    def on_button_click(
        self,
    ) -> bool:
        if not self.descriptor:
            logger.error("descriptor not set")
            return False

        address_descriptor = self.descriptor.address_descriptor(
            kind=self.kind, address_index=self.address_index
        )
        try:
            address = self.usb.display_address(address_descriptor)
        except Exception as e:
            Message(str(e), type=MessageType.Error)
            return False

        return bool(address)


class USBRegisterMultisigWidget(USBValidateAddressWidget):
    def __init__(self, network: bdk.Network, signals: Signals) -> None:
        screenshots = ScreenshotsRegisterMultisig()
        self.button_help = generate_help_button(screenshots, title="Help")

        super().__init__(network, signals)

        self.button_box.addButton(self.button_help, QDialogButtonBox.ButtonRole.HelpRole)

        self.xpubs_widget = QWidget()
        self.xpubs_widget_layout = QHBoxLayout(self.xpubs_widget)
        self.label_title_keystore = QLabel()
        self.label_xpubs_keystore = ElidedLabel(elide_mode=Qt.TextElideMode.ElideMiddle)
        self.xpubs_widget_layout.addWidget(self.label_title_keystore)
        self.xpubs_widget_layout.addWidget(self.label_xpubs_keystore)

        self._layout.insertWidget(0, self.xpubs_widget)

    def updateUi(self) -> None:
        super().updateUi()
        self.setWindowTitle(self.tr("Register Multisig wallet on hardware signer"))
        self.button_validate_address.setText(self.tr("Register Multisig"))
        self.button_help.setText(self.tr("Help"))

    def on_button_click(
        self,
    ) -> bool:
        result = super().on_button_click()

        if result:
            self.close()
            Message(
                self.tr("Successfully registered multisig wallet on hardware signer"),
                type=MessageType.Info,
                icon=read_QIcon("checkmark.svg"),
            )
        return result

    def set_descriptor(  # type: ignore
        self,
        keystores: List[KeyStore],
        descriptor: MultipathDescriptor,
        expected_address: str,
        kind: bdk.KeychainKind = bdk.KeychainKind.EXTERNAL,
        address_index: int = 0,
    ) -> None:
        super().set_descriptor(
            descriptor=descriptor, expected_address=expected_address, kind=kind, address_index=address_index
        )

        text_titles = "\n".join([f"{keystore.label}:" for keystore in keystores])
        text_xpubs = "\n".join([keystore.xpub for keystore in keystores])
        self.label_title_keystore.setText(text_titles)
        self.label_xpubs_keystore.setText(text_xpubs)
