import logging
from typing import Optional

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import QCompleterLineEdit
from bitcoin_safe.gui.qt.qr_components.image_widget import EnlargableImageWidget

from .dialog_import import ImportDialog

logger = logging.getLogger(__name__)

from typing import Callable, List

import bdkpython as bdk
from bitcoin_qrreader import bitcoin_qr
from bitcoin_usb.address_types import AddressType
from bitcoin_usb.gui import USBGui
from bitcoin_usb.software_signer import SoftwareSigner
from PySide2.QtCore import QObject, Signal
from PySide2.QtGui import QIcon, Qt
from PySide2.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...keystore import KeyStore, KeyStoreTypes
from ...signals import Signal
from ...signer import AbstractSigner
from .block_change_signals import BlockChangesSignals
from .util import (
    Message,
    MessageType,
    add_tab_to_tabs,
    add_to_buttonbox,
    icon_path,
    read_QIcon,
)


def icon_for_label(label):
    return read_QIcon("key-gray.png") if label.startswith("Recovery") else read_QIcon("key.png")


class KeyStoreUI(QObject):
    def __init__(
        self,
        keystore: Optional[KeyStore],
        tabs: QTabWidget,
        network: bdk.Network,
        get_address_type: Callable[[], AddressType],
        label: str = "",
    ) -> None:
        super().__init__()

        self.tabs = tabs
        self.keystore = keystore
        self.network = network
        self.get_address_type = get_address_type

        self.tab = self.create()

        self._label = "unknown_label" if keystore else label
        add_tab_to_tabs(
            self.tabs,
            self.tab,
            icon_for_label(self.label),
            self.label,
            self.label,
            focus=True,
        )

    @property
    def label(self):
        return self.keystore.label if self.keystore else self._label

    @label.setter
    def label(self, value):
        if self.keystore:
            self.keystore.label = value
        else:
            self._label = value

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.tab))

    def seed_visibility(self, visible=False):

        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

        # self.edit_xpub.setHidden(visible)
        # self.edit_fingerprint.setHidden(visible)
        # self.label_xpub.setHidden(visible)
        # self.label_fingerprint.setHidden(visible)

    def on_label_change(self):
        self.tabs.setTabText(self.tabs.indexOf(self.tab), self.edit_label.text())

    def format_all_fields(self):
        self.edit_fingerprint.format()

        standardized = self.edit_key_origin.text().replace("'", "h")
        if standardized != self.edit_key_origin.text():
            # setText will call format_key_origin again
            self.edit_key_origin.setText(standardized)
            return

        address_type: AddressType = self.get_address_type()
        expected = address_type.key_origin(self.network)
        if expected != self.edit_key_origin.text():
            self.edit_key_origin.format_as_error(True)
            self.edit_key_origin.setToolTip(
                f"Standart for the selected address type {address_type.name} is {expected}.  Please correct if you are not sure."
            )
            self.edit_xpub.format_as_error(True)
            self.edit_xpub.setToolTip(
                f"The xPub origin {self.edit_key_origin.text()} and the xPub belong together. Please choose the correct xPub origin pair."
            )
        else:
            self.edit_xpub.format()
            self.edit_xpub.setToolTip("")
            self.edit_key_origin.format()
            self.edit_key_origin.setToolTip(f"")
        self.edit_key_origin.setPlaceholderText(expected)
        self.edit_key_origin.input_field.reset_memory()
        self.edit_key_origin.input_field.add_to_memory(expected)

    def successful_import_signer_info(self):
        this_index = self.tabs.indexOf(self.tab)

        self.tabs_left.setCurrentWidget(self.tab_manual)
        self.tabs.setTabIcon(this_index, QIcon(icon_path("checkmark.png")))

        if this_index + 1 < self.tabs.count():
            self.tabs.setCurrentIndex(this_index + 1)

    def set_using_signer_info(self, signer_info: bitcoin_qr.SignerInfo):
        def check_key_origin(signer_info: bitcoin_qr.SignerInfo):
            address_type = self.get_address_type()
            expected = address_type.key_origin(self.network)
            if signer_info.key_origin != expected:
                Message(
                    f"The xPub Origin {signer_info.key_origin} is not the expected {expected} for {address_type.name}",
                    type=MessageType.Error,
                )
                return False
            return True

        if not check_key_origin(signer_info):
            return
        self.edit_xpub.setText(signer_info.xpub)
        self.edit_key_origin.setText(signer_info.key_origin)
        self.edit_fingerprint.setText(signer_info.fingerprint)
        self.successful_import_signer_info()

    def _on_handle_input(self, data: bitcoin_qr.Data, parent: QWidget = None):

        if data.data_type == bitcoin_qr.DataType.SignerInfo:
            self.set_using_signer_info(data.data)
        elif data.data_type == bitcoin_qr.DataType.SignerInfos:
            expected_key_origin = self.get_address_type().key_origin(self.network)
            # pick the right signer data
            for signer_info in data.data:
                if signer_info.key_origin == expected_key_origin:
                    self.set_using_signer_info(signer_info)
                    break
            else:
                # none found
                Message(f"No signer data for the expected key_origin {expected_key_origin} found.")

        elif data.data_type == bitcoin_qr.DataType.Xpub:
            self.edit_xpub.setText(data.data)
        elif data.data_type == bitcoin_qr.DataType.Fingerprint:
            self.edit_fingerprint.setText(data.data)
        elif data.data_type in [
            bitcoin_qr.DataType.Descriptor,
            bitcoin_qr.DataType.MultiPathDescriptor,
        ]:
            Message("Please paste descriptors into the descriptor field in the top right.")
        elif isinstance(data.data, str) and parent:
            parent.setText(data.data)
        elif isinstance(data, bitcoin_qr.Data):
            Message(f"{data.data_type} cannot be used here.", type=MessageType.Error)
        else:
            Exception("Could not recognize the QR Code")

    def create(self):
        tab = QWidget()
        self.tabs.setTabText(
            self.tabs.indexOf(tab),
            "Signer",
        )
        tab.setLayout(QHBoxLayout())
        # self.tabs.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.tabs_left = QTabWidget()
        tab.layout().addWidget(self.tabs_left)

        self.tab_import = QWidget()
        self.tab_import.setLayout(QVBoxLayout())
        self.tabs_left.addTab(self.tab_import, "Import")
        self.tab_manual = QWidget()
        self.tabs_left.addTab(self.tab_manual, "Manual")

        label_keystore_label = QLabel()
        self.edit_label = QLineEdit()
        label_keystore_label.setHidden(True)
        self.edit_label.setHidden(True)
        self.label_fingerprint = QLabel()
        self.edit_fingerprint = ButtonEdit()
        self.edit_fingerprint.add_qr_input_from_camera_button(custom_handle_input=self._on_handle_input)

        def fingerprint_validator():
            txt = self.edit_fingerprint.text()
            if not txt:
                return True
            return KeyStore.is_fingerprint_valid(txt)

        self.edit_fingerprint.set_validator(fingerprint_validator)
        label_key_origin = QLabel()
        self.edit_key_origin = ButtonEdit(input_field=QCompleterLineEdit(self.network))
        self.edit_key_origin.add_qr_input_from_camera_button(custom_handle_input=self._on_handle_input)
        self.label_xpub = QLabel()
        self.edit_xpub = ButtonEdit(input_field=QTextEdit())
        self.edit_xpub.add_qr_input_from_camera_button(custom_handle_input=self._on_handle_input)
        self.edit_xpub.setMinimumHeight(30)
        self.edit_xpub.setMinimumWidth(400)

        self.edit_xpub.set_validator(
            lambda: KeyStore.is_xpub_valid(self.edit_xpub.text(), network=self.network)
        )
        self.label_seed = QLabel()
        self.edit_seed = ButtonEdit()

        def callback_seed(seed: str):
            keystore = self.get_ui_values_as_keystore()
            self.edit_fingerprint.setText(keystore.fingerprint)
            self.edit_xpub.setText(keystore.xpub)
            self.edit_key_origin.setText(keystore.key_origin)

        self.edit_seed.add_random_mnemonic_button(callback_seed=callback_seed)

        def seed_validator():
            if not self.edit_seed.text():
                return True
            return KeyStore.is_seed_valid(self.edit_seed.text())

        self.edit_seed.set_validator(seed_validator)

        # put them on the formLayout
        self.formLayout = QFormLayout(self.tab_manual)
        self.formLayout.setWidget(1, QFormLayout.LabelRole, label_keystore_label)
        self.formLayout.setWidget(1, QFormLayout.FieldRole, self.edit_label)
        self.formLayout.setWidget(2, QFormLayout.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(3, QFormLayout.LabelRole, label_key_origin)
        self.formLayout.setWidget(3, QFormLayout.FieldRole, self.edit_key_origin)
        self.formLayout.setWidget(4, QFormLayout.LabelRole, self.label_xpub)
        self.formLayout.setWidget(4, QFormLayout.FieldRole, self.edit_xpub)
        self.formLayout.setWidget(5, QFormLayout.LabelRole, self.label_seed)
        self.formLayout.setWidget(5, QFormLayout.FieldRole, self.edit_seed)
        self.seed_visibility(self.network in KeyStoreTypes.seed.networks)

        # add the buttons
        self.buttonBox = QDialogButtonBox()

        # Create custom buttons
        self.button_hwi = add_to_buttonbox(self.buttonBox, "Connect USB", KeyStoreTypes.hwi.icon_filename)
        self.button_file = add_to_buttonbox(
            self.buttonBox, "Import file or text", KeyStoreTypes.file.icon_filename
        )
        self.button_qr = add_to_buttonbox(self.buttonBox, "Scan", KeyStoreTypes.qr.icon_filename)
        self.button_qr.clicked.connect(lambda: self.edit_xpub.buttons[0].click())
        self.button_hwi.clicked.connect(lambda: self.on_hwi_click())

        def process_input(s: str):
            res = bitcoin_qr.Data.from_str(s, self.network)
            self._on_handle_input(res)

        coldcard_groupbox = QGroupBox("Coldcard wallet export")
        coldcard_groupbox.setLayout(QVBoxLayout())
        image_widget = EnlargableImageWidget()
        image_widget.load_from_file(icon_path("coldcard-wallet-export.png"))
        coldcard_groupbox.layout().addWidget(image_widget)

        self.button_file.clicked.connect(
            lambda: ImportDialog(
                self.network,
                on_open=process_input,
                window_title="Import fingerprint and xpub",
                text_button_ok="OK",
                text_instruction_label="Please paste the exported file (like coldcard-export.json or sparrow-export.json):",
                instruction_widget=coldcard_groupbox,
                text_placeholder="Please paste the exported file (like coldcard-export.json or sparrow-export.json)",
            ).show()
        )

        self.tab_import.layout().setAlignment(image_widget, Qt.AlignCenter)

        # self.tab_import.layout().addItem(QSpacerItem(1, 1, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.tab_import.layout().setAlignment(Qt.AlignCenter)
        self.tab_import.layout().addWidget(self.buttonBox)
        self.tab_import.layout().setAlignment(self.buttonBox, Qt.AlignCenter)
        # self.tab_import.layout().addItem(QSpacerItem(1, 1, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.right_widget = QWidget()
        self.right_widget.setLayout(QVBoxLayout())
        # self.right_widget.layout().setContentsMargins(2,2,2,2)

        self.label_description = QLabel("Description")

        self.right_widget.layout().addWidget(self.label_description)

        self.textEdit_description = QTextEdit()
        self.right_widget.layout().addWidget(self.textEdit_description)

        tab.layout().addWidget(self.right_widget)

        label_keystore_label.setText("Label")
        self.label_fingerprint.setText("Fingerprint")
        label_key_origin.setText("xPub Origin")
        self.label_xpub.setText("xPub")
        self.label_seed.setText("Seed")
        self.textEdit_description.setPlaceholderText(
            "Name of signing device: ......\nLocation of signing device: .....",
        )

        self.edit_key_origin.input_field.textChanged.connect(self.format_all_fields)
        self.edit_label.textChanged.connect(self.on_label_change)
        return tab

    def on_hwi_click(self):
        address_type = self.get_address_type()
        usb = USBGui(self.network)
        key_origin = address_type.key_origin(self.network)
        result = usb.get_fingerprint_and_xpub(key_origin=key_origin)
        if not result:
            return

        fingerprint, xpub = result
        self.set_using_signer_info(
            bitcoin_qr.SignerInfo(fingerprint=fingerprint, key_origin=key_origin, xpub=xpub)
        )

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
            key_origin = self.edit_key_origin.text()

            # try to validate
            # if this works, then these are valid values
            if not KeyStore.is_xpub_valid(xpub, self.network):
                raise ValueError(f"{xpub} is not a valid publix xpub")

        return KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            label=self.edit_label.text(),
            mnemonic=mnemonic if mnemonic else None,
            description=self.textEdit_description.toPlainText(),
            network=self.network,
        )

    def set_ui_from_keystore(self, keystore: KeyStore):
        with BlockChangesSignals([self.tab]):
            logger.debug(f"{self.__class__.__name__} set_ui_from_keystore")
            self.edit_xpub.setText(keystore.xpub if keystore.xpub else "")
            self.edit_fingerprint.setText(keystore.fingerprint if keystore.fingerprint else "")
            self.edit_key_origin.setText(keystore.key_origin if keystore.key_origin else "")
            self.edit_label.setText(self.label)
            self.textEdit_description.setPlainText(keystore.description)
            self.edit_seed.setText(keystore.mnemonic if keystore.mnemonic else "")


class SignedUI(QObject):
    def __init__(
        self,
        text: str,
        psbt: bdk.PartiallySignedTransaction,
        tabs: QTabWidget,
        network: bdk.Network,
        key_label: str,
    ) -> None:
        super().__init__()
        self.text = text
        self.psbt = psbt
        self.tabs = tabs
        self.network = network
        self.key_label = key_label

        self.ui_signer_tab = self.create()

        add_tab_to_tabs(
            self.tabs,
            self.ui_signer_tab,
            read_QIcon("confirmed.png"),
            key_label,
            f"Signed with {key_label}",
            focus=True,
        )

    def create(self):
        tab = QWidget()
        self.layout_keystore_buttons = QHBoxLayout(tab)

        self.edit_signature = QTextEdit()
        self.edit_signature.setMinimumHeight(30)
        self.edit_signature.setReadOnly(True)
        self.edit_signature.setText(str(self.text))
        self.layout_keystore_buttons.addWidget(self.edit_signature)

        return tab

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.ui_signer_tab))


class SignerUI(QObject):
    signal_signature_added = Signal(bdk.PartiallySignedTransaction)

    def __init__(
        self,
        signers: List[AbstractSigner],
        psbt: bdk.PartiallySignedTransaction,
        tabs: QTabWidget,
        network: bdk.Network,
        key_label: str,
        wallet_id: Optional[str],
    ) -> None:
        super().__init__()
        self.signers = signers
        self.psbt = psbt
        self.tabs = tabs
        self.network = network
        self.key_label = key_label
        self.wallet_id = wallet_id

        self.ui_signer_tab = self.create()

        add_tab_to_tabs(
            self.tabs,
            self.ui_signer_tab,
            icon_for_label(key_label),
            key_label,
            f"{key_label} contained in wallet {wallet_id}" if wallet_id else f"Unknown wallet",
            focus=True,
        )

    def create(self):
        tab = QWidget()

        self.layout_keystore_buttons = QVBoxLayout(tab)

        for signer in self.signers:

            def callback_generator(signer):
                def f():
                    signer.sign(self.psbt)

                return f

            button = QPushButton(signer.label)
            button.setMinimumHeight(30)
            button.setIcon(QIcon(icon_path(signer.keystore_type.icon_filename)))
            button.clicked.connect(callback_generator(signer))
            self.layout_keystore_buttons.addWidget(button)

            # forward the signal_signature_added from each signer to self.signal_signature_added
            signer.signal_signature_added.connect(self.signal_signature_added.emit)

        return tab

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.ui_signer_tab))
