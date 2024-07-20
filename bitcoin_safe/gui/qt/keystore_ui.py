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
from typing import Optional

from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget

from ...dynamic_lib_load import setup_libsecp256k1

setup_libsecp256k1()

from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import MyTextEdit, QCompleterLineEdit
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsExportXpub

from .dialog_import import ImportDialog

logger = logging.getLogger(__name__)

from typing import Callable, List

import bdkpython as bdk
from bitcoin_qr_tools.data import (
    Data,
    DataType,
    SignerInfo,
    convert_slip132_to_bip32,
    is_slip132,
)
from bitcoin_usb.address_types import AddressType
from bitcoin_usb.gui import USBGui
from bitcoin_usb.software_signer import SoftwareSigner
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...keystore import KeyStore, KeyStoreImporterTypes
from ...signals import SignalsMin, pyqtSignal
from ...signer import AbstractSignatureImporter
from .block_change_signals import BlockChangesSignals
from .util import (
    Message,
    MessageType,
    add_tab_to_tabs,
    add_to_buttonbox,
    icon_path,
    read_QIcon,
)


def icon_for_label(label: str) -> QIcon:
    return read_QIcon("key-gray.png") if label.startswith("Recovery") else read_QIcon("key.png")


class KeyStoreUI(QObject):
    def __init__(
        self,
        keystore: Optional[KeyStore],
        tabs: DataTabWidget,
        network: bdk.Network,
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        label: str = "",
    ) -> None:
        super().__init__()
        self.signals_min = signals_min

        self._label = label
        self.tabs = tabs
        self.keystore = keystore
        self.network = network
        self.get_address_type = get_address_type

        self.tab = QWidget()

        self.tab.setLayout(QHBoxLayout())
        # self.tabs.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.tabs_import_type = QTabWidget()
        self.tab.layout().addWidget(self.tabs_import_type)

        self.tab_import = QWidget()
        self.tab_import.setLayout(QVBoxLayout())
        self.tabs_import_type.addTab(self.tab_import, "")
        self.tab_manual = QWidget()
        self.tabs_import_type.addTab(self.tab_manual, "")

        self.label_keystore_label = QLabel()
        self.edit_label = QLineEdit()
        self.label_keystore_label.setHidden(True)
        self.edit_label.setHidden(True)
        self.label_fingerprint = QLabel()
        self.edit_fingerprint = ButtonEdit(
            signal_update=self.signals_min.language_switch,
        )
        self.edit_fingerprint.add_qr_input_from_camera_button(
            network=self.network,
            custom_handle_input=self._on_handle_input,
        )

        def fingerprint_validator() -> bool:
            txt = self.edit_fingerprint.text()
            if not txt:
                return True
            return KeyStore.is_fingerprint_valid(txt)

        self.edit_fingerprint.set_validator(fingerprint_validator)
        self.label_key_origin = QLabel()
        self.edit_key_origin = ButtonEdit(
            input_field=QCompleterLineEdit(self.network),
            signal_update=self.signals_min.language_switch,
        )
        self.edit_key_origin.add_qr_input_from_camera_button(
            network=self.network,
            custom_handle_input=self._on_handle_input,
        )
        self.label_xpub = QLabel()
        self.edit_xpub = ButtonEdit(
            input_field=MyTextEdit(preferred_height=50),
            signal_update=self.signals_min.language_switch,
        )
        self.edit_xpub.add_qr_input_from_camera_button(
            network=self.network,
            custom_handle_input=self._on_handle_input,
        )
        self.edit_xpub.setMinimumHeight(30)
        self.edit_xpub.setMinimumWidth(400)

        self.edit_xpub.set_validator(self.xpub_validator)
        self.label_seed = QLabel()
        self.edit_seed = ButtonEdit()

        def callback_seed(seed: str) -> None:
            keystore = self.get_ui_values_as_keystore()
            self.edit_fingerprint.setText(keystore.fingerprint)
            self.edit_xpub.setText(keystore.xpub)
            self.key_origin = keystore.key_origin

        self.edit_seed.add_random_mnemonic_button(callback_seed=callback_seed)

        def seed_validator() -> bool:
            if not self.edit_seed.text():
                return True
            return KeyStore.is_seed_valid(self.edit_seed.text())

        self.edit_seed.set_validator(seed_validator)

        # put them on the formLayout
        self.formLayout = QFormLayout(self.tab_manual)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_keystore_label)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.edit_label)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.label_key_origin)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.edit_key_origin)
        self.formLayout.setWidget(4, QFormLayout.ItemRole.LabelRole, self.label_xpub)
        self.formLayout.setWidget(4, QFormLayout.ItemRole.FieldRole, self.edit_xpub)
        self.formLayout.setWidget(5, QFormLayout.ItemRole.LabelRole, self.label_seed)
        self.formLayout.setWidget(5, QFormLayout.ItemRole.FieldRole, self.edit_seed)
        self.seed_visibility(self.network in KeyStoreImporterTypes.seed.networks)

        # add the buttons
        self.buttonBox = QDialogButtonBox()

        # Create custom buttons
        self.button_file = add_to_buttonbox(
            self.buttonBox, self.tr(""), KeyStoreImporterTypes.file.icon_filename
        )
        self.button_qr = add_to_buttonbox(self.buttonBox, (""), KeyStoreImporterTypes.qr.icon_filename)
        self.button_hwi = add_to_buttonbox(self.buttonBox, (""), KeyStoreImporterTypes.hwi.icon_filename)
        self.button_qr.clicked.connect(lambda: self.edit_xpub.buttons[0].click())
        self.button_hwi.clicked.connect(lambda: self.on_hwi_click())

        def process_input(s: str) -> None:
            res = Data.from_str(s, self.network)
            self._on_handle_input(res)

        self.button_file.clicked.connect(
            lambda: ImportDialog(
                self.network,
                on_open=process_input,
                window_title=self.tr("Import fingerprint and xpub"),
                text_button_ok=self.tr("OK"),
                text_instruction_label=self.tr(
                    "Please paste the exported file (like coldcard-export.json or sparrow-export.json):"
                ),
                instruction_widget=ScreenshotsExportXpub(),
                text_placeholder=self.tr(
                    "Please paste the exported file (like coldcard-export.json or sparrow-export.json)"
                ),
            ).exec()
        )

        screenshot = ScreenshotsExportXpub()
        self.tab_import.layout().setAlignment(screenshot, Qt.AlignmentFlag.AlignCenter)

        # self.tab_import.layout().addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.tab_import.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tab_import.layout().addWidget(self.buttonBox)
        self.tab_import.layout().setAlignment(self.buttonBox, Qt.AlignmentFlag.AlignCenter)
        # self.tab_import.layout().addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.right_widget = QWidget()
        self.right_widget.setLayout(QVBoxLayout())
        # self.right_widget.layout().setContentsMargins(0,0,0,0)

        self.label_description = QLabel()

        self.right_widget.layout().addWidget(self.label_description)

        self.textEdit_description = MyTextEdit(preferred_height=60)
        self.right_widget.layout().addWidget(self.textEdit_description)

        self.tab.layout().addWidget(self.right_widget)

        self.updateUi()

        self.edit_key_origin.input_field.textChanged.connect(self.format_all_fields)
        self.edit_label.textChanged.connect(self.on_label_change)
        self.signals_min.language_switch.connect(self.updateUi)

        add_tab_to_tabs(
            self.tabs, self.tab, icon_for_label(self.label), self.label, self.label, focus=True, data=self
        )

    @property
    def label(self) -> str:
        return self.keystore.label if self.keystore else self._label

    @label.setter
    def label(self, value: str) -> None:
        if self.keystore:
            self.keystore.label = value
        else:
            self._label = value

    def remove_tab(self) -> None:
        self.tabs.removeTab(self.tabs.indexOf(self.tab))

    def seed_visibility(self, visible=False) -> None:

        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

        # self.edit_xpub.setHidden(visible)
        # self.edit_fingerprint.setHidden(visible)
        # self.label_xpub.setHidden(visible)
        # self.label_fingerprint.setHidden(visible)

    def on_label_change(self) -> None:
        self.tabs.setTabText(self.tabs.indexOf(self.tab), self.edit_label.text())

    @property
    def key_origin(self) -> str:
        try:
            standardized = SimplePubKeyProvider.format_key_origin(self.edit_key_origin.text().strip())
        except:
            return ""

        return standardized

    @key_origin.setter
    def key_origin(self, value: str) -> None:
        self.edit_key_origin.setText(value if value else "")

    def format_all_fields(self) -> None:
        self.edit_fingerprint.format()

        expected_key_origin = self.get_expected_key_origin()
        if expected_key_origin != self.key_origin:
            self.edit_key_origin.format_as_error(True)
            self.edit_key_origin.setToolTip(
                self.tr(
                    "Standart for the selected address type {type} is {expected_key_origin}.  Please correct if you are not sure."
                ).format(expected_key_origin=expected_key_origin, type=self.get_address_type().name)
            )
            self.edit_xpub.format_as_error(True)
            self.edit_xpub.setToolTip(
                self.tr(
                    "The xPub origin {key_origin} and the xPub belong together. Please choose the correct xPub origin pair."
                ).format(key_origin=self.key_origin)
            )
        else:
            self.edit_xpub.format()
            self.edit_xpub.setToolTip("")
            self.edit_key_origin.format()
            self.edit_key_origin.setToolTip(f"")
        self.edit_key_origin.setPlaceholderText(expected_key_origin)
        self.edit_key_origin.input_field.reset_memory()
        self.edit_key_origin.input_field.add_to_memory(expected_key_origin)

    def successful_import_signer_info(self) -> None:
        this_index = self.tabs.indexOf(self.tab)

        self.tabs_import_type.setCurrentWidget(self.tab_manual)
        self.tabs.setTabIcon(this_index, QIcon(icon_path("checkmark.png")))

        if this_index + 1 < self.tabs.count():
            self.tabs.setCurrentIndex(this_index + 1)

    def get_expected_key_origin(self) -> str:
        return self.get_address_type().key_origin(self.network)

    def set_using_signer_info(self, signer_info: SignerInfo) -> None:
        def check_key_origin(signer_info: SignerInfo) -> bool:
            expected_key_origin = self.get_expected_key_origin()
            if signer_info.key_origin != expected_key_origin:
                Message(
                    self.tr(
                        "The xPub Origin {key_origin} is not the expected {expected_key_origin} for {self.get_address_type().name}"
                    ).format(key_origin=signer_info.key_origin, expected_key_origin=expected_key_origin),
                    type=MessageType.Error,
                )
                return False
            return True

        if not check_key_origin(signer_info):
            return
        self.edit_xpub.setText(signer_info.xpub)
        self.key_origin = signer_info.key_origin
        self.edit_fingerprint.setText(signer_info.fingerprint)
        self.successful_import_signer_info()

    def _on_handle_input(self, data: Data, parent: QWidget = None) -> None:

        if data.data_type == DataType.SignerInfo:
            self.set_using_signer_info(data.data)
        elif data.data_type == DataType.SignerInfos:
            expected_key_origin = self.get_expected_key_origin()
            # pick the right signer data
            for signer_info in data.data:
                if signer_info.key_origin == expected_key_origin:
                    self.set_using_signer_info(signer_info)
                    break
            else:
                # none found
                Message(
                    self.tr("No signer data for the expected key_origin {expected_key_origin} found.").format(
                        expected_key_origin=expected_key_origin
                    )
                )

        elif data.data_type == DataType.Xpub:
            self.edit_xpub.setText(data.data)
        elif data.data_type == DataType.Fingerprint:
            self.edit_fingerprint.setText(data.data)
        elif data.data_type in [
            DataType.Descriptor,
            DataType.MultiPathDescriptor,
        ]:
            Message(self.tr("Please paste descriptors into the descriptor field in the top right."))
        elif isinstance(data.data, str) and parent:
            parent.setText(data.data)
        elif isinstance(data, Data):
            Message(
                self.tr("{data_type} cannot be used here.").format(data_type=data.data_type),
                type=MessageType.Error,
            )
        else:
            Exception("Could not recognize the QR Code")

    def xpub_validator(self) -> bool:
        xpub = self.edit_xpub.text()
        # automatically convert slip132
        if is_slip132(xpub):
            Message(
                self.tr("The xpub is in SLIP132 format. Converting to standard format."),
                title="Converting format",
            )
            try:
                self.edit_xpub.setText(convert_slip132_to_bip32(xpub))
            except:
                return False

        return KeyStore.is_xpub_valid(self.edit_xpub.text(), network=self.network)

    def updateUi(self) -> None:
        self.tabs.setTabText(
            self.tabs.indexOf(self.tab),
            self.label,
        )

        self.tabs_import_type.setTabText(self.tabs_import_type.indexOf(self.tab_import), self.tr("Import"))
        self.tabs_import_type.setTabText(self.tabs_import_type.indexOf(self.tab_manual), self.tr("Manual"))

        self.label_description.setText(self.tr("Description"))
        self.label_keystore_label.setText(self.tr("Label"))
        self.label_fingerprint.setText(self.tr("Fingerprint"))
        self.label_key_origin.setText(self.tr("xPub Origin"))
        self.label_xpub.setText(self.tr("xPub"))
        self.label_seed.setText(self.tr("Seed"))
        self.textEdit_description.setPlaceholderText(
            self.tr(
                "Name of signing device: ......\nLocation of signing device: .....",
            )
        )

        self.button_file.setText(self.tr("Import file or text"))
        self.button_qr.setText(self.tr("Scan"))
        self.button_hwi.setText(self.tr("Connect USB"))

    def on_hwi_click(self) -> None:
        address_type = self.get_address_type()
        usb = USBGui(self.network)
        key_origin = address_type.key_origin(self.network)
        try:
            result = usb.get_fingerprint_and_xpub(key_origin=key_origin)
        except Exception as e:
            Message(
                str(e)
                + "\n\n"
                + self.tr("Please ensure that there are no other programs accessing the Hardware signer"),
                type=MessageType.Error,
            )
            return
        if not result:
            return

        fingerprint, xpub = result
        self.set_using_signer_info(SignerInfo(fingerprint=fingerprint, key_origin=key_origin, xpub=xpub))

    def get_ui_values_as_keystore(self) -> KeyStore:
        seed_str = self.edit_seed.text().strip()

        if seed_str:
            mnemonic = bdk.Mnemonic.from_string(seed_str).as_string()
            software_signer = SoftwareSigner(mnemonic, self.network)
            xpub = software_signer.get_xpubs().get(self.get_address_type())
            fingerprint = software_signer.get_fingerprint()
            key_origin = self.get_address_type().key_origin(self.network)
        else:
            mnemonic = None
            fingerprint = self.edit_fingerprint.text()
            xpub = self.edit_xpub.text()
            key_origin = self.key_origin

            # try to validate
            # if this works, then these are valid values
            if not KeyStore.is_xpub_valid(xpub, self.network):
                if xpub:
                    raise ValueError(self.tr("{xpub} is not a valid public xpub").format(xpub=xpub))
                else:
                    raise ValueError(
                        self.tr("Please import the public key information from the hardware wallet first")
                    )

        return KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            label=self.edit_label.text(),
            mnemonic=mnemonic if mnemonic else None,
            description=self.textEdit_description.toPlainText(),
            network=self.network,
        )

    def set_ui_from_keystore(self, keystore: KeyStore) -> None:
        with BlockChangesSignals([self.tab]):
            logger.debug(f"{self.__class__.__name__} set_ui_from_keystore")
            self.edit_xpub.setText(keystore.xpub if keystore.xpub else "")
            self.edit_fingerprint.setText(keystore.fingerprint if keystore.fingerprint else "")
            self.key_origin = keystore.key_origin
            self.edit_label.setText(self.label)
            self.textEdit_description.setPlainText(keystore.description)
            self.edit_seed.setText(keystore.mnemonic if keystore.mnemonic else "")


class SignedUI(QWidget):
    def __init__(
        self,
        text: str,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
    ) -> None:
        super().__init__()
        self.text = text
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QHBoxLayout(self)

        self.edit_signature = QTextEdit()
        self.edit_signature.setMinimumHeight(30)
        self.edit_signature.setReadOnly(True)
        self.edit_signature.setText(str(self.text))
        self.layout_keystore_buttons.addWidget(self.edit_signature)


class SignerUI(QWidget):
    signal_signature_added = pyqtSignal(bdk.PartiallySignedTransaction)
    signal_tx_received = pyqtSignal(bdk.Transaction)

    def __init__(
        self,
        signature_importers: List[AbstractSignatureImporter],
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
    ) -> None:
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        for signer in self.signature_importers:

            def callback_generator(signer: AbstractSignatureImporter) -> Callable:
                def f() -> None:
                    signer.sign(self.psbt)

                return f

            button = QPushButton(signer.label)
            button.setMinimumHeight(30)
            button.setIcon(QIcon(icon_path(signer.keystore_type.icon_filename)))
            button.clicked.connect(callback_generator(signer))
            self.layout_keystore_buttons.addWidget(button)

            # forward the signal_signature_added from each signer to self.signal_signature_added
            signer.signal_signature_added.connect(self.signal_signature_added.emit)
            signer.signal_final_tx_received.connect(self.signal_tx_received.emit)


class SignerUIHorizontal(QWidget):
    signal_signature_added = pyqtSignal(bdk.PartiallySignedTransaction)
    signal_tx_received = pyqtSignal(bdk.Transaction)

    def __init__(
        self,
        signature_importers: List[AbstractSignatureImporter],
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
    ) -> None:
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        for signer in self.signature_importers:

            def callback_generator(signer: AbstractSignatureImporter) -> Callable:
                def f() -> None:
                    signer.sign(self.psbt)

                return f

            button = QPushButton(signer.label)
            button.setMinimumHeight(30)
            button.setIcon(QIcon(icon_path(signer.keystore_type.icon_filename)))
            button.clicked.connect(callback_generator(signer))
            self.layout_keystore_buttons.addWidget(button)

            # forward the signal_signature_added from each signer to self.signal_signature_added
            signer.signal_signature_added.connect(self.signal_signature_added.emit)
            signer.signal_final_tx_received.connect(self.signal_tx_received.emit)
