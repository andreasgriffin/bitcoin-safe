import logging

from bitcoin_safe import descriptors, keystore, util

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from .util import (
    icon_path,
    center_in_widget,
    qresize,
    add_tab_to_tabs,
    read_QIcon,
    create_button,
)
from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from typing import List
from .block_change_signals import BlockChangesSignals
import bdkpython as bdk
from ...signer import AbstractSigner, SignerWallet
from .util import MnemonicLineEdit, CameraInputLineEdit
from bitcoin_qrreader import bitcoin_qr


class KeyStoreUITypeChooser(QObject):
    def __init__(self, network) -> None:
        super().__init__()
        self.network = network
        self.widget = self.create()

    def create(self):
        tab = QWidget()
        tab.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.layout_keystore_buttons = QHBoxLayout(tab)

        self.button_hwi = create_button(
            "",  # KeyStoreTypes.hwi.description,
            (KeyStoreTypes.hwi.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
            max_sizes=[(40, 40)],
        )
        self.button_file = create_button(
            "",  # KeyStoreTypes.file.description,
            (KeyStoreTypes.file.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
            max_sizes=[(40, 40)],
        )
        self.button_qr = create_button(
            "",  # KeyStoreTypes.qr.description,
            (KeyStoreTypes.qr.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
            max_sizes=[(40, 40)],
        )
        return tab


class KeyStoreUIDefault(QObject):
    signal_xpub_changed = Signal()
    signal_seed_changed = Signal()
    signal_fingerprint_changed = Signal()
    signal_derivation_path_changed = Signal()

    def __init__(self, tabs: QTabWidget, network: bdk.Network) -> None:
        super().__init__()
        self.tabs = tabs
        self.network = network

        self.tab = self.create()
        self.block_change_signals = BlockChangesSignals(
            [
                self.edit_derivation_path,
                self.edit_fingerprint,
                self.edit_label,
                self.edit_xpub,
                self.textEdit_description,
            ]
        )

    def seed_visibility(self, visible=False):

        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

        # self.edit_xpub.setHidden(visible)
        # self.edit_fingerprint.setHidden(visible)
        # self.label_xpub.setHidden(visible)
        # self.label_fingerprint.setHidden(visible)

    def on_label_change(self):
        self.tabs.setTabText(self.tabs.indexOf(self.tab), self.edit_label.text())

    def create(self):
        tab = QWidget()
        self.tabs.setTabText(
            self.tabs.indexOf(tab),
            QCoreApplication.translate("tab", "Signer settings", None),
        )

        self.horizontalLayout_6 = QHBoxLayout(tab)
        self.horizontalLayout_6.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins

        self.box_left = QWidget(tab)
        self.box_left_layout = QVBoxLayout(self.box_left)
        self.box_left_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins
        self.box_form = QWidget(self.box_left)
        self.box_left_layout.addWidget(self.box_form)

        def on_handle_input(data: bitcoin_qr.Data, parent: QWidget):
            if data.data_type == bitcoin_qr.DataType.KeyStoreInfo:
                # {
                #         "fingerprint": groups[0],
                #         "derivation_path": "m/" + groups[1].replace("h", "'"),
                #         "xpub": groups[2],
                #         "further_derivation_path": groups[3],
                #     }
                if data.data.get("xpub"):
                    self.edit_xpub.setText(data.data.get("xpub"))
                if data.data.get("derivation_path"):
                    self.edit_derivation_path.setText(data.data.get("derivation_path"))
                if data.data.get("fingerprint"):
                    self.edit_fingerprint.setText(data.data.get("fingerprint"))
            elif isinstance(data.data, str):
                parent.setText(data.data)
            else:
                Exception("Could not recognize the QR Code")

        label_keystore_label = QLabel(self.box_form)
        self.edit_label = QLineEdit(self.box_form)
        self.label_fingerprint = QLabel(self.box_form)
        self.edit_fingerprint = CameraInputLineEdit(custom_handle_input=on_handle_input)
        label_derivation_path = QLabel(self.box_form)
        self.edit_derivation_path = CameraInputLineEdit(
            custom_handle_input=on_handle_input
        )
        self.label_xpub = QLabel(self.box_form)
        self.edit_xpub = CameraInputLineEdit(custom_handle_input=on_handle_input)
        self.label_seed = QLabel()
        self.edit_seed = MnemonicLineEdit()

        # put them on the formLayout
        self.formLayout = QFormLayout(self.box_form)
        self.formLayout.setWidget(1, QFormLayout.LabelRole, label_keystore_label)
        self.formLayout.setWidget(1, QFormLayout.FieldRole, self.edit_label)
        self.formLayout.setWidget(2, QFormLayout.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(3, QFormLayout.LabelRole, label_derivation_path)
        self.formLayout.setWidget(3, QFormLayout.FieldRole, self.edit_derivation_path)
        self.formLayout.setWidget(4, QFormLayout.LabelRole, self.label_xpub)
        self.formLayout.setWidget(4, QFormLayout.FieldRole, self.edit_xpub)
        self.formLayout.setWidget(5, QFormLayout.LabelRole, self.label_seed)
        self.formLayout.setWidget(5, QFormLayout.FieldRole, self.edit_seed)
        self.seed_visibility(self.network in KeyStoreTypes.seed.networks)

        # add the buttons
        self.button_chooser = KeyStoreUITypeChooser(self.network)
        self.button_chooser.button_qr.clicked.connect(
            lambda: self.edit_fingerprint.camera_button.click()
        )
        self.box_left_layout.addWidget(self.button_chooser.widget)

        self.horizontalLayout_6.addWidget(self.box_left)

        self.widget_8 = QWidget(tab)
        self.verticalLayout_3 = QVBoxLayout(self.widget_8)
        self.widget_6 = QWidget(self.widget_8)
        self.verticalLayout_5 = QVBoxLayout(self.widget_6)
        self.label_4 = QLabel(self.widget_6)

        self.verticalLayout_5.addWidget(self.label_4)

        self.textEdit_description = QTextEdit(self.widget_6)
        self.verticalLayout_5.addWidget(self.textEdit_description)

        self.verticalLayout_3.addWidget(self.widget_6)

        self.horizontalLayout_6.addWidget(self.widget_8)

        label_keystore_label.setText(QCoreApplication.translate("tab", "Label", None))
        self.label_fingerprint.setText(
            QCoreApplication.translate("tab", "Fingerprint", None)
        )
        label_derivation_path.setText(
            QCoreApplication.translate("tab", "Derivation Path", None)
        )
        self.label_xpub.setText(QCoreApplication.translate("tab", "xPub", None))
        self.label_seed.setText(QCoreApplication.translate("tab", "Seed", None))
        self.label_4.setText(QCoreApplication.translate("tab", "Description", None))
        self.textEdit_description.setPlaceholderText(
            QCoreApplication.translate("tab", "Useful information about signer", None)
        )

        self.edit_xpub.textChanged.connect(self.signal_xpub_changed)
        self.edit_seed.textChanged.connect(self.signal_seed_changed)
        self.edit_fingerprint.textChanged.connect(self.on_edit_fingerprint)
        self.edit_derivation_path.textChanged.connect(
            self.signal_derivation_path_changed
        )
        self.edit_label.textChanged.connect(self.on_label_change)

        return tab

    def set_formatting(self):
        # disable this for now.
        return
        if self.edit_fingerprint.isEnabled() and len(self.edit_fingerprint.text()) != 8:
            self.edit_fingerprint.setStyleSheet(
                "QLineEdit { background-color: #ff6c54; }"
            )
        else:
            self.edit_fingerprint.setStyleSheet(
                "QLineEdit { background-color: white; }"
            )

    def on_edit_fingerprint(self, new_value):
        self.set_formatting()
        self.signal_fingerprint_changed.emit()

    def get_ui_values_as_keystore(self) -> KeyStore:
        seed_str = self.edit_seed.text().strip()

        if seed_str:
            mnemonic = bdk.Mnemonic.from_string(seed_str)
            fingerprint = None
            xpub = None
        else:
            mnemonic = None
            fingerprint = (
                self.edit_fingerprint.text()
                if len(self.edit_fingerprint.text()) == 8
                else None
            )
            xpub = self.edit_xpub.text()

        return KeyStore(
            xpub,
            fingerprint,
            self.edit_derivation_path.text(),
            self.edit_label.text(),
            mnemonic,
            self.textEdit_description.toPlainText(),
        )

    def set_ui_from_keystore(self, keystore: KeyStore):
        with self.block_change_signals:
            self.edit_xpub.setText(keystore.xpub if keystore.xpub else "")
            self.edit_fingerprint.setText(
                keystore.fingerprint if keystore.fingerprint else ""
            )
            self.edit_derivation_path.setText(
                keystore.derivation_path if keystore.derivation_path else ""
            )
            self.edit_label.setText(keystore.label)
            self.textEdit_description.setPlainText(keystore.description)

            self.set_formatting()

            if keystore.mnemonic:
                self.edit_seed.setText(keystore.mnemonic.as_string())
