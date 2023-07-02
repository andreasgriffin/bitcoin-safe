import logging

from bitcoin_safe import keystore

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
from ...wallet import (
    AddressTypes,
    get_default_address_type,
    Wallet,
    generate_bdk_descriptors,
)
from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from ...signals import Signal
from typing import List
from .block_change_signals import BlockChangesSignals
import bdkpython as bdk
from ...signer import AbstractSigner, SignerWallet
from .util import MnemonicLineEdit


class KeyStoreUITypeChooser(QObject):
    signal_click_watch_only = Signal()
    signal_click_seed = Signal()

    def __init__(self, network) -> None:
        super().__init__()
        self.network = network
        self.tab = self.create()

    def create(self):
        tab = QWidget()

        self.layout_keystore_buttons = QHBoxLayout(tab)

        button = create_button(
            KeyStoreTypes.hwi.description,
            (KeyStoreTypes.hwi.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
        )
        button = create_button(
            KeyStoreTypes.psbt.description,
            (KeyStoreTypes.psbt.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
        )
        self.button_xpub = create_button(
            KeyStoreTypes.watch_only.description,
            (KeyStoreTypes.watch_only.icon_filename),
            parent=tab,
            outer_layout=self.layout_keystore_buttons,
        )
        self.button_xpub.clicked.connect(self.signal_click_watch_only)
        if self.network in KeyStoreTypes.seed.networks:
            self.button_seed = create_button(
                KeyStoreTypes.seed.description,
                (KeyStoreTypes.seed.icon_filename),
                parent=tab,
                outer_layout=self.layout_keystore_buttons,
            )
            self.button_seed.clicked.connect(self.signal_click_seed)

        return tab


class KeyStoreUISigner(QObject):
    def __init__(self, signer: AbstractSigner, network) -> None:
        super().__init__()
        self.signer = signer

        self.network = network
        self.tab = self.create()

    def create(self):
        tab = QWidget()

        self.layout_keystore_buttons = QHBoxLayout(tab)

        # button = create_button(KeyStoreTypes.hwi.description, (KeyStoreTypes.hwi.icon_filename), parent=tab , outer_layout= self.layout_keystore_buttons)

        if (
            self.network in KeyStoreTypes.seed.networks
            and type(self.signer) == SignerWallet
        ):
            self.button_seed = create_button(
                KeyStoreTypes.seed.description,
                (KeyStoreTypes.seed.icon_filename),
                parent=tab,
                outer_layout=self.layout_keystore_buttons,
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
                self.comboBox_keystore_type,
            ]
        )

    def seed_visibility(self, visible=False):
        def is_widget_in_layout(widget, layout):
            return widget.parent() is layout

        if visible and not is_widget_in_layout(self.label_seed, self.formLayout):
            self.formLayout.setWidget(5, QFormLayout.LabelRole, self.label_seed)
        if visible and not is_widget_in_layout(self.edit_seed, self.formLayout):
            self.formLayout.setWidget(5, QFormLayout.FieldRole, self.edit_seed)

        if not visible and is_widget_in_layout(self.label_seed, self.formLayout):
            self.formLayout.removeWidget(self.label_seed)
        if not visible and is_widget_in_layout(self.edit_seed, self.formLayout):
            self.formLayout.removeWidget(self.edit_seed)

        self.edit_xpub.setHidden(visible)
        self.edit_fingerprint.setHidden(visible)
        self.label_xpub.setHidden(visible)
        self.label_fingerprint.setHidden(visible)

    def on_label_change(self):
        self.tabs.setTabText(self.tabs.indexOf(self.tab), self.edit_label.text())

    def create(self):
        tab = QWidget()
        self.tabs.setTabText(
            self.tabs.indexOf(tab),
            QCoreApplication.translate("tab", "Signer settings", None),
        )

        self.horizontalLayout_6 = QHBoxLayout(tab)
        self.box_left = QWidget(tab)
        label_keystore_type = QLabel(self.box_left)

        self.comboBox_keystore_type = QComboBox(self.box_left)
        self.comboBox_keystore_type.addItems(KeyStoreTypes.list_names(self.network))
        label_keystore_label = QLabel(self.box_left)
        self.edit_label = QLineEdit(self.box_left)
        self.label_fingerprint = QLabel(self.box_left)
        self.edit_fingerprint = QLineEdit(self.box_left)
        label_derivation_path = QLabel(self.box_left)
        self.edit_derivation_path = QLineEdit(self.box_left)
        self.label_xpub = QLabel(self.box_left)
        self.edit_xpub = QLineEdit(self.box_left)
        self.label_seed = QLabel()
        self.edit_seed = MnemonicLineEdit()

        # put them on the formLayout
        self.formLayout = QFormLayout(self.box_left)
        self.formLayout.setWidget(0, QFormLayout.LabelRole, label_keystore_type)
        self.formLayout.setWidget(0, QFormLayout.FieldRole, self.comboBox_keystore_type)
        self.formLayout.setWidget(1, QFormLayout.LabelRole, label_keystore_label)
        self.formLayout.setWidget(1, QFormLayout.FieldRole, self.edit_label)
        self.formLayout.setWidget(2, QFormLayout.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(3, QFormLayout.LabelRole, label_derivation_path)
        self.formLayout.setWidget(3, QFormLayout.FieldRole, self.edit_derivation_path)
        self.formLayout.setWidget(4, QFormLayout.LabelRole, self.label_xpub)
        self.formLayout.setWidget(4, QFormLayout.FieldRole, self.edit_xpub)

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

        label_keystore_type.setText(QCoreApplication.translate("tab", "Type", None))
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

    def set_comboBox_keystore_type(self, keystore_type: KeyStoreType):
        keys = KeyStoreTypes.list_names(self.network)
        if keystore_type:
            self.comboBox_keystore_type.setCurrentIndex(keys.index(keystore_type.name))

    def get_comboBox_keystore_type(self) -> KeyStoreType:
        keystore_types = KeyStoreTypes.list_types(self.network)
        return keystore_types[self.comboBox_keystore_type.currentIndex()]

    def get_ui_values_as_keystore(self) -> KeyStore:
        seed_str = self.edit_seed.text()

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
            self.get_comboBox_keystore_type(),
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
            self.set_comboBox_keystore_type(keystore.type)
            self.textEdit_description.setPlainText(keystore.description)

            self.set_formatting()

            if keystore.type:
                self.seed_visibility(keystore.type.id == KeyStoreTypes.seed.id)
            if keystore.mnemonic:
                self.edit_seed.setText(keystore.mnemonic.as_string())
