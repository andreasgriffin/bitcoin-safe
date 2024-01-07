import logging

logger = logging.getLogger(__name__)

from PySide2.QtCore import QObject
from PySide2.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QDialogButtonBox,
)


from ...keystore import KeyStoreTypes
from .util import (
    add_to_buttonbox,
)


class KeyStoreUITypeChooser(QObject):
    def __init__(self, network) -> None:
        super().__init__()
        self.network = network
        self.widget = self.create()

    def create(self):
        tab = QWidget()
        tab.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.layout_keystore_buttons = QHBoxLayout(tab)

        # Create the QDialogButtonBox
        self.buttonBox = QDialogButtonBox(tab)

        # Create custom buttons
        self.button_hwi = add_to_buttonbox(self.buttonBox, "Connect USB", KeyStoreTypes.hwi.icon_filename)
        self.button_file = add_to_buttonbox(self.buttonBox, "Import file", KeyStoreTypes.file.icon_filename)
        self.button_qr = add_to_buttonbox(self.buttonBox, "Scan", KeyStoreTypes.qr.icon_filename)

        self.layout_keystore_buttons.addWidget(self.buttonBox)

        return tab
