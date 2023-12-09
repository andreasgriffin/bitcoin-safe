import logging

from bitcoin_safe import descriptors, keystore, util
from bitcoin_safe.gui.qt.custom_edits import DescriptorEdit

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
from .util import MnemonicLineEdit, CameraInputLineEdit, CameraInputTextEdit
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
