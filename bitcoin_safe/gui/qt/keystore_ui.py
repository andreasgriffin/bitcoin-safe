import logging

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from PySide2.QtSvg import QSvgWidget
from .util import (
    icon_path,
    center_in_widget,
    qresize,
    add_tab_to_tabs,
    read_QIcon,
    create_button,
)

from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from ...signals import Signals, Signal
from ...util import compare_dictionaries, psbt_to_hex
from typing import List
from .keystore_ui_tabs import KeyStoreUIDefault, KeyStoreUITypeChooser
from .block_change_signals import BlockChangesSignals
import bdkpython as bdk
from ...signer import AbstractSigner


def icon_for_label(label):
    return (
        read_QIcon("key-gray.png")
        if label.startswith("Recovery")
        else read_QIcon("key.png")
    )


class KeyStoreUI:
    def __init__(
        self, keystore: KeyStore, tabs: QTabWidget, network: bdk.Network
    ) -> None:
        self.keystore = keystore
        self.tabs = tabs

        self.keystore_ui_default = KeyStoreUIDefault(tabs, network)
        self.block_change_signals = BlockChangesSignals(
            sub_instances=[self.keystore_ui_default.block_change_signals]
        )

        add_tab_to_tabs(
            self.tabs,
            self.keystore_ui_default.tab,
            icon_for_label(keystore.label),
            keystore.label,
            keystore.label,
            focus=True,
        )

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.keystore_ui_default.tab))

    def set_keystore_from_ui_values(self, keystore: KeyStore):
        ui_keystore = self.keystore_ui_default.get_ui_values_as_keystore()
        if not keystore:
            keystore = self.keystore
        keystore.from_other_keystore(ui_keystore)

    def changed_ui_values(self) -> KeyStore:
        return compare_dictionaries(
            self.keystore, self.keystore_ui_default.get_ui_values_as_keystore()
        )

    def set_ui_from_keystore(self, keystore: KeyStore):
        index = self.tabs.indexOf(self.keystore_ui_default.tab)
        if index >= 0:
            self.tabs.setTabText(index, keystore.label)
            self.tabs.setTabIcon(index, icon_for_label(keystore.label))

        self.keystore_ui_default.set_ui_from_keystore(keystore)


class SignerUI(QObject):
    signal_signature_added = Signal(bdk.PartiallySignedTransaction)

    def __init__(
        self,
        signers: List[AbstractSigner],
        psbt: bdk.PartiallySignedTransaction,
        tabs: QTabWidget,
        network: bdk.Network,
        wallet_id: str,
    ) -> None:
        super().__init__()
        self.signers = signers
        self.psbt = psbt
        self.tabs = tabs
        self.network = network

        self.ui_signer_tab = self.create()

        add_tab_to_tabs(
            self.tabs,
            self.ui_signer_tab,
            icon_for_label(wallet_id),
            wallet_id,
            wallet_id,
            focus=True,
        )

    def create(self):
        tab = QWidget()

        self.layout_keystore_buttons = QHBoxLayout(tab)

        for signer in self.signers:
            button = create_button(
                "Import signature with",  # signer.keystore_type.description,
                (signer.keystore_type.icon_filename),
                parent=tab,
                outer_layout=self.layout_keystore_buttons,
            )

            # with lambda function it works. But not without. No idea why
            button.clicked.connect(lambda: signer.sign(self.psbt))
            signer.signal_signature_added.connect(self.signal_signature_added.emit)

        return tab

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.ui_signer_tab))
