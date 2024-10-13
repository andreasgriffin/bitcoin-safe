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
from typing import Iterable, Optional, Tuple, Union

from bitcoin_safe.gui.qt.analyzer_indicator import AnalyzerIndicator
from bitcoin_safe.gui.qt.analyzers import (
    FingerprintAnalyzer,
    KeyOriginAnalyzer,
    SeedAnalyzer,
    XpubAnalyzer,
)
from bitcoin_safe.gui.qt.data_tab_widget import DataTabWidget
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate

from ...dynamic_lib_load import setup_libsecp256k1

setup_libsecp256k1()

from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit, QCompleterLineEdit
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
from bitcoin_usb.seed_tools import get_network_index
from bitcoin_usb.software_signer import SoftwareSigner
from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QToolButton,
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
    add_to_buttonbox,
    generate_help_button,
    icon_path,
    read_QIcon,
)


def icon_for_label(label: str) -> QIcon:
    return (
        read_QIcon("key-gray.png") if label.startswith(translate("d", "Recovery")) else read_QIcon("key.png")
    )


class HardwareSignerInteractionWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        # add the buttons
        self.buttonBox = QDialogButtonBox()
        self.button_import_file: Optional[QPushButton] = None
        self.button_import_qr: Optional[QPushButton] = None
        self.button_export_qr: Optional[QToolButton] = None
        self.button_hwi: Optional[QPushButton] = None
        self.help_button: Optional[QPushButton] = None
        self.button_export_file: Optional[QPushButton] = None

        self._layout.addWidget(self.buttonBox)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.setAlignment(self.buttonBox, Qt.AlignmentFlag.AlignCenter)

    def add_import_file_button(self) -> QPushButton:

        # Create custom buttons
        self.button_import_file = button_import_file = add_to_buttonbox(
            self.buttonBox, self.tr(""), KeyStoreImporterTypes.file.icon_filename
        )
        return button_import_file

    def add_export_file_button(self) -> QPushButton:

        # Create custom buttons
        self.button_export_file = button_export_file = add_to_buttonbox(
            self.buttonBox, self.tr(""), KeyStoreImporterTypes.file.icon_filename
        )
        return button_export_file

    def add_qr_import_buttonn(self) -> QPushButton:
        self.button_import_qr = button_import_qr = add_to_buttonbox(
            self.buttonBox, (""), KeyStoreImporterTypes.qr.icon_filename
        )
        return button_import_qr

    def add_export_qr_button(self) -> Tuple[QToolButton, Menu]:

        # Create a custom QPushButton with an icon
        button = QToolButton(self)
        button.setIcon(QIcon(icon_path(KeyStoreImporterTypes.qr.icon_filename)))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Add the button to the QDialogButtonBox
        self.buttonBox.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)

        menu = Menu(self)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.button_export_qr = button
        return self.button_export_qr, menu

    def add_hwi_button(self) -> QPushButton:
        button_hwi = add_to_buttonbox(self.buttonBox, (""), KeyStoreImporterTypes.hwi.icon_filename)
        self.button_hwi = button_hwi
        return button_hwi

    def add_help_button(self, help_widget: QWidget) -> QPushButton:
        self.buttonBoxHelp = QDialogButtonBox()
        help_button = generate_help_button(help_widget)

        self.buttonBoxHelp.addButton(help_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._layout.addWidget(self.buttonBoxHelp)
        self._layout.setAlignment(self.buttonBoxHelp, Qt.AlignmentFlag.AlignCenter)

        self.help_button = help_button
        return help_button

    def updateUi(self) -> None:
        if self.button_import_file:
            self.button_import_file.setText(self.tr("Import File or Text"))
        if self.button_export_file:
            self.button_export_file.setText(self.tr("Export File"))
        if self.button_import_qr:
            self.button_import_qr.setText(self.tr("QR Code"))
        if self.button_export_qr:
            self.button_export_qr.setText(self.tr("QR Code"))
        if self.button_hwi:
            self.button_hwi.setText(self.tr("USB"))
        if self.help_button:
            self.help_button.setText(self.tr("Help"))


class KeyStoreUI(QObject):
    signal_signer_infos = pyqtSignal(list)

    def __init__(
        self,
        tabs: DataTabWidget,
        network: bdk.Network,
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        label: str = "",
        hardware_signer_label="",
    ) -> None:
        super().__init__()
        self.signals_min = signals_min

        self.label = label
        self.hardware_signer_label = hardware_signer_label
        self.tabs = tabs
        self.network = network
        self.get_address_type = get_address_type

        self.tab = QWidget()
        self.tab_layout = QHBoxLayout(self.tab)

        self.tabs_import_type = QTabWidget()
        self.tab_layout.addWidget(self.tabs_import_type)

        self.tab_import = QWidget()
        self.tab_import_layout = QVBoxLayout(self.tab_import)
        self.tabs_import_type.addTab(self.tab_import, "")
        self.tab_manual = QWidget()
        self.tabs_import_type.addTab(self.tab_manual, "")

        self.label_fingerprint = QLabel()
        self.edit_fingerprint = ButtonEdit(
            signal_update=self.signals_min.language_switch,
        )
        self.edit_fingerprint.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_fingerprint.signal_data.connect(self._on_handle_input)

        self.edit_fingerprint.input_field.setAnalyzer(FingerprintAnalyzer(parent=self))
        # key_origin
        self.label_key_origin = QLabel()
        self.edit_key_origin_input = QCompleterLineEdit(self.network)
        self.edit_key_origin = ButtonEdit(
            input_field=self.edit_key_origin_input,
            signal_update=self.signals_min.language_switch,
        )
        self.edit_key_origin.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_key_origin.signal_data.connect(self._on_handle_input)
        self.edit_key_origin_input.setAnalyzer(
            KeyOriginAnalyzer(get_expected_key_origin=self.get_expected_key_origin, parent=self)
        )

        # xpub
        self.label_xpub = QLabel()
        self.edit_xpub = ButtonEdit(
            input_field=AnalyzerTextEdit(),
            signal_update=self.signals_min.language_switch,
        )
        self.edit_xpub.setFixedHeight(50)
        self.edit_xpub.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_xpub.signal_data.connect(self._on_handle_input)

        self.edit_xpub.input_field.setAnalyzer(XpubAnalyzer(self.network, parent=self))
        self.label_seed = QLabel()
        self.edit_seed = ButtonEdit()

        def callback_seed(seed: str) -> None:
            try:
                keystore = self.get_ui_values_as_keystore()
            except Exception as e:
                Message(str(e), type=MessageType.Error)
                return
            self.edit_fingerprint.setText(keystore.fingerprint)
            self.edit_xpub.setText(keystore.xpub)
            self.key_origin = keystore.key_origin

        self.edit_seed.add_random_mnemonic_button(callback_seed=callback_seed)
        self.edit_seed.input_field.setAnalyzer(SeedAnalyzer(parent=self))

        # put them on the formLayout
        self.formLayout = QFormLayout(self.tab_manual)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label_key_origin)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.edit_key_origin)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.label_xpub)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.edit_xpub)
        self.formLayout.setWidget(4, QFormLayout.ItemRole.LabelRole, self.label_seed)
        self.formLayout.setWidget(5, QFormLayout.ItemRole.FieldRole, self.edit_seed)
        self.seed_visibility(self.network in KeyStoreImporterTypes.seed.networks)

        # tab_import

        self.hardware_signer_interaction = HardwareSignerInteractionWidget()
        button_file = self.hardware_signer_interaction.add_import_file_button()
        button_qr = self.hardware_signer_interaction.add_qr_import_buttonn()
        self.hardware_signer_interaction.add_help_button(ScreenshotsExportXpub())

        button_qr.clicked.connect(lambda: self.edit_xpub.button_container.buttons[0].click())

        button_hwi = self.hardware_signer_interaction.add_hwi_button()
        button_hwi.clicked.connect(lambda: self.on_hwi_click())

        def process_input(s: str) -> None:
            res = Data.from_str(s, self.network)
            self._on_handle_input(res)

        def import_dialog():
            ImportDialog(
                self.network,
                on_open=process_input,
                window_title=self.tr("Import fingerprint and xpub"),
                text_button_ok=self.tr("OK"),
                text_instruction_label=self.tr("Please paste the exported file (like sparrow-export.json):"),
                text_placeholder=self.tr("Please paste the exported file (like sparrow-export.json)"),
            ).exec()

        button_file.clicked.connect(import_dialog)

        # self.tab_import_layout.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.tab_import_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_width = 50
        self.analyzer_indicator = AnalyzerIndicator(
            line_edits=[
                self.edit_fingerprint.input_field,
                self.edit_key_origin_input,
                self.edit_xpub.input_field,
            ],
            icon_OK=read_QIcon("checkmark.svg").pixmap(QSize(icon_width, icon_width)),
            icon_warning=read_QIcon("warning.png").pixmap(QSize(icon_width, icon_width)),
            icon_error=read_QIcon("error.png").pixmap(QSize(icon_width, icon_width)),
            hide_if_all_empty=True,
        )
        self.analyzer_indicator.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tab_import_layout.addWidget(self.analyzer_indicator)
        self.tab_import_layout.addWidget(self.hardware_signer_interaction)

        # self.tab_import_layout.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.right_widget = QWidget()
        self.right_widget_layout = QVBoxLayout(self.right_widget)
        # self.right_widget_layout.setContentsMargins(0,0,0,0)

        self.label_description = QLabel()

        self.right_widget_layout.addWidget(self.label_description)

        self.textEdit_description = AnalyzerTextEdit()
        self.right_widget_layout.addWidget(self.textEdit_description)

        self.tab_layout.addWidget(self.right_widget)

        self.updateUi()

        self.edit_key_origin_input.textChanged.connect(self.format_all_fields)
        self.signals_min.language_switch.connect(self.updateUi)

    def seed_visibility(self, visible=False) -> None:

        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

        # self.edit_xpub.setHidden(visible)
        # self.edit_fingerprint.setHidden(visible)
        # self.label_xpub.setHidden(visible)
        # self.label_fingerprint.setHidden(visible)

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
        self.edit_fingerprint.format_and_apply_validator()

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
            self.edit_xpub.format_and_apply_validator()
            self.edit_xpub.setToolTip("")
            self.edit_key_origin.format_and_apply_validator()
            self.edit_key_origin.setToolTip(f"")
        self.edit_key_origin.setPlaceholderText(expected_key_origin)
        self.edit_key_origin_input.reset_memory()
        self.edit_key_origin_input.add_to_memory(expected_key_origin)
        self.analyzer_indicator.updateUi()

    def get_expected_key_origin(self) -> str:
        return self.get_address_type().key_origin(self.network)

    def set_using_signer_info(self, signer_info: SignerInfo) -> None:
        def check_key_origin(signer_info: SignerInfo) -> bool:
            expected_key_origin = self.get_expected_key_origin()
            if signer_info.key_origin != expected_key_origin:
                if get_network_index(signer_info.key_origin) != get_network_index(expected_key_origin):
                    Message(
                        self.tr(
                            "The provided information is for {key_origin_network}. Please provide xPub for network {network}"
                        ).format(
                            key_origin_network=(
                                bdk.Network.BITCOIN
                                if get_network_index(signer_info.key_origin) == 1
                                else bdk.Network.REGTEST
                            ),
                            network=self.network,
                        ),
                        type=MessageType.Error,
                    )
                else:
                    Message(
                        self.tr(
                            "The xPub Origin {key_origin} is not the expected {expected_key_origin} for {address_type}"
                        ).format(
                            key_origin=signer_info.key_origin,
                            expected_key_origin=expected_key_origin,
                            address_type=self.get_address_type().name,
                        ),
                        type=MessageType.Error,
                    )
                return False
            return True

        if not check_key_origin(signer_info):
            return
        self.edit_xpub.setText(signer_info.xpub)
        self.key_origin = signer_info.key_origin
        self.edit_fingerprint.setText(signer_info.fingerprint)

    def _on_handle_input(self, data: Data, parent: Union[QLineEdit, QTextEdit] | None = None) -> None:

        if data.data_type == DataType.SignerInfo:
            self.set_using_signer_info(data.data)
        elif data.data_type == DataType.SignerInfos:
            expected_key_origin = self.get_expected_key_origin()

            matching_signer_infos = [
                signer_info
                for signer_info in data.data
                if isinstance(signer_info, SignerInfo) and (signer_info.key_origin == expected_key_origin)
            ]

            if len(matching_signer_infos) == 1:
                self.set_using_signer_info(matching_signer_infos[0])
            elif len(matching_signer_infos) > 1:
                self.signal_signer_infos.emit(matching_signer_infos)
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

        self.label_fingerprint.setText(self.tr("Fingerprint"))
        self.edit_fingerprint.input_field.setObjectName(self.label_fingerprint.text())

        self.label_key_origin.setText(self.tr("xPub Origin"))
        self.edit_key_origin_input.setObjectName(self.label_key_origin.text())

        self.label_xpub.setText(self.tr("xPub"))
        self.edit_xpub.input_field.setObjectName(self.label_xpub.text())

        self.label_seed.setText(self.tr("Seed"))
        self.edit_seed.input_field.setObjectName(self.label_seed.text())

        self.textEdit_description.setPlaceholderText(
            self.tr(
                "Name of signing device: ......\nLocation of signing device: .....",
            )
        )
        self.analyzer_indicator.updateUi()
        self.hardware_signer_interaction.updateUi()

    def on_hwi_click(self) -> None:
        address_type = self.get_address_type()
        usb = USBGui(self.network, initalization_label=self.hardware_signer_label)
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

        device, fingerprint, xpub = result
        self.set_using_signer_info(SignerInfo(fingerprint=fingerprint, key_origin=key_origin, xpub=xpub))
        if not self.textEdit_description.text():
            self.textEdit_description.setText(f"{device.get('type', '')} - {device.get('model', '')}")

    def get_ui_values_as_keystore(self) -> KeyStore:
        seed_str = self.edit_seed.text().strip()

        if seed_str:
            mnemonic = bdk.Mnemonic.from_string(seed_str).as_string()
            software_signer = SoftwareSigner(mnemonic, self.network)
            key_origin = self.edit_key_origin.text().strip()
            # if key_origin is empty  fill it with the default
            key_origin = key_origin if key_origin else self.get_address_type().key_origin(self.network)
            xpub = software_signer.derive(key_origin)
            fingerprint = software_signer.get_fingerprint()
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
                    raise ValueError(self.tr("Please import the information from all hardware signers first"))

        return KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            label=self.label,
            mnemonic=mnemonic if mnemonic else None,
            description=self.textEdit_description.toPlainText(),
            network=self.network,
        )

    def set_ui_from_keystore(self, keystore: KeyStore) -> None:
        with BlockChangesSignals([self.tab]):
            self.label = keystore.label

            logger.debug(f"{self.__class__.__name__} set_ui_from_keystore")
            xpub = keystore.xpub if keystore.xpub else ""
            if xpub != self.edit_xpub.text():
                self.edit_xpub.setText(xpub)

            fingerprint = keystore.fingerprint if keystore.fingerprint else ""
            if fingerprint != self.edit_fingerprint.text():
                self.edit_fingerprint.setText(fingerprint)

            if self.key_origin != keystore.key_origin:
                self.key_origin = keystore.key_origin

            if self.textEdit_description.toPlainText() != keystore.description:
                self.textEdit_description.setPlainText(keystore.description)

            mnemonic = keystore.mnemonic if keystore.mnemonic else ""
            if self.edit_seed.text() != mnemonic:
                self.edit_seed.setText(mnemonic)


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
        signature_importers: Iterable[AbstractSignatureImporter],
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
    ) -> None:
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        def callback_generator(signer: AbstractSignatureImporter) -> Callable:
            def f() -> None:
                signer.sign(self.psbt)

            return f

        for signer in self.signature_importers:
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
