import logging

from bitcoin_safe.gui.qt.keystore_uis import KeyStoreUIs

logger = logging.getLogger(__name__)

from typing import Callable, Optional, Tuple

from bitcoin_usb.address_types import get_address_types
from PyQt6.QtCore import QCoreApplication, QMargins, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...descriptors import AddressType, get_default_address_type
from ...signals import pyqtSignal
from ...wallet import ProtoWallet, Wallet
from .block_change_signals import BlockChangesSignals
from .custom_edits import DescriptorEdit


class DescriptorUI(QObject):
    signal_qtwallet_apply_setting_changes = pyqtSignal()
    signal_qtwallet_cancel_setting_changes = pyqtSignal()
    signal_qtwallet_cancel_wallet_creation = pyqtSignal()

    def __init__(self, protowallet: ProtoWallet, get_wallet: Optional[Callable[[], Wallet]] = None) -> None:
        super().__init__()
        # if we are in the wallet setp process, then wallet = None
        self.protowallet = protowallet
        self.get_wallet = get_wallet

        self.no_edit_mode = (self.protowallet.threshold, len(self.protowallet.keystores)) in [(1, 1), (2, 3)]

        self.tab = QWidget()
        self.tab.setLayout(QVBoxLayout())

        self.create_wallet_type_and_descriptor()

        with BlockChangesSignals([self.tab]):
            self.repopulate_comboBox_address_type(self.protowallet.is_multisig())

        self.edit_descriptor.signal_change.connect(self.on_descriptor_change)

        self.keystore_uis = KeyStoreUIs(
            get_editable_protowallet=lambda: self.protowallet,
            get_address_type=self.get_address_type_from_ui,
        )
        self.tab.layout().addWidget(self.keystore_uis)

        self.keystore_uis.setCurrentIndex(0)

        self.set_all_ui_from_protowallet()
        # diasbeling fields MUST be done after the ui is filled
        self.disable_fields()

        self.box_button_bar = self.create_button_bar()

    def set_protowallet(self, protowallet: ProtoWallet):
        self.protowallet = protowallet
        self.set_all_ui_from_protowallet()

    def on_wallet_ui_changes(self):
        logger.debug("on_wallet_ui_changes")
        try:
            self.set_protowallet_from_ui()

            self.set_ui_descriptor()
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_wallet_ui_from_protowallet()
        except:
            logger.warning("on_wallet_ui_changes: Invalid input")
            self._set_keystore_tabs()

    def on_descriptor_change(self, new_value: str):
        new_value = new_value.strip().replace("\n", "")

        # self.set_protowallet_from_keystore_ui(cloned_protowallet)
        if hasattr(self, "_edit_descriptor_cache") and self._edit_descriptor_cache == new_value:
            # no change
            return
        self._edit_descriptor_cache: str = new_value

        try:
            self.set_protowallet_from_descriptor_str(new_value)
            logger.info(f"Successfully set protwallet from descriptor {new_value}")

            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_wallet_ui_from_protowallet()
            self.disable_fields()
        except:
            logger.info(f"Invalid descriptor {new_value}")
            return

    def on_spin_threshold_changed(self, new_value: int):
        self.on_wallet_ui_changes()

    def on_spin_signer_changed(self, new_value: int):
        self.repopulate_comboBox_address_type(new_value > 1)

        self.on_wallet_ui_changes()

    def set_protowallet_from_descriptor_str(self, descriptor: str):
        self.protowallet = ProtoWallet.from_descriptor(
            self.protowallet.id, descriptor, self.protowallet.network
        )

    def _set_keystore_tabs(self):
        self.keystore_uis._set_keystore_tabs()

        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(self.spin_signers.value())
        self.spin_signers.setMinimum(self.spin_req.value())
        self.spin_signers.setMaximum(10)

    def set_wallet_ui_from_protowallet(self):
        with BlockChangesSignals([self.tab]):
            logger.debug(f"{self.__class__.__name__} set_wallet_ui_from_protowallet")
            self.comboBox_address_type.setCurrentText(self.protowallet.address_type.name)
            self.spin_req.setMinimum(1)
            self.spin_req.setMaximum(len(self.protowallet.keystores))
            self.spin_req.setValue(self.protowallet.threshold)

            self.spin_signers.setMinimum(self.protowallet.threshold)
            self.spin_signers.setMaximum(10)
            self.spin_signers.setValue(len(self.protowallet.keystores))

            if self.spin_req.value() < self.spin_signers.value():

                labels_of_recovery_signers = [
                    f'"{keystore_ui.label}"' for keystore_ui in self.keystore_uis.keystore_uis
                ][self.spin_req.value() :]
                self.spin_req.setToolTip(
                    f"In the chosen multisig setup, you need {self.spin_req.value()} devices (signers) to sign every outgoing transaction.\n"
                    f'In case of loss of 1 of the devices, you can recover your funds using\n {" or ".join(labels_of_recovery_signers)} and send the funds to a new wallet.'
                )
            if self.spin_req.value() == self.spin_signers.value() != 1:
                self.spin_req.setToolTip(
                    f"Warning!  Choosing a multisig setup where ALL signers need to sign every transaction\n is very RISKY and does not offer any benefits of multisig. Recommended multisig setups are 2-of-3 or 3-of-5"
                )
            if self.spin_req.value() == self.spin_signers.value() == 1:
                self.spin_req.setToolTip(f"A single signing device can sign outgoing transactions.")

            self.spin_gap.setValue(self.protowallet.gap)
        assert len(self.protowallet.keystores) == len(self.keystore_uis)

    def set_all_ui_from_protowallet(self):
        """Updates the 3 parts.

        - wallet ui (e.g. gap)
        - Keystore UI  (e.g. xpubs)
        - descriptor ui
        """
        with BlockChangesSignals([self.tab]):
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_wallet_ui_from_protowallet()
            self.set_ui_descriptor()

    def set_protowallet_from_ui(self):
        logger.debug("set_protowallet_from_keystore_ui")

        # these wallet settings must come first
        m, n = self.get_m_of_n_from_ui()
        self.protowallet.set_number_of_keystores(n)
        self.protowallet.set_threshold(m)
        self.protowallet.set_address_type(self.get_address_type_from_ui())
        self.protowallet.set_gap(self.get_gap_from_ui())

        self.keystore_uis.set_protowallet_from_keystore_ui()

    def set_combo_box_address_type_default(self):
        address_types = get_address_types(self.protowallet.is_multisig())
        self.comboBox_address_type.setCurrentIndex(
            address_types.index(get_default_address_type(self.protowallet.is_multisig()))
        )

    def get_address_type_from_ui(self) -> AddressType:
        address_types = get_address_types(self.protowallet.is_multisig())

        address_type = address_types[self.comboBox_address_type.currentIndex()]

        assert address_type.name == self.comboBox_address_type.currentText()
        return address_type

    def get_m_of_n_from_ui(self) -> Tuple[int, int]:
        return (self.spin_req.value(), self.spin_signers.value())

    def get_gap_from_ui(self) -> int:
        return self.spin_gap.value()

    def set_ui_descriptor(self):
        logger.debug(f"{self.__class__.__name__} set_ui_descriptor")
        # check if the descriptor actually CAN be calculated to a reasonable degree
        try:
            multipath_descriptor = self.protowallet.to_multipath_descriptor()
            if multipath_descriptor:
                self.edit_descriptor.setText(multipath_descriptor.as_string_private())
            else:
                self.edit_descriptor.setText("")
        except:
            self.edit_descriptor.setText("")

    def disable_fields(self):
        self.comboBox_address_type.setHidden(self.no_edit_mode)
        self.label_address_type.setHidden(self.no_edit_mode)
        self.spin_signers.setHidden(self.no_edit_mode)
        self.spin_req.setHidden(self.no_edit_mode)
        self.label_signers.setHidden(self.no_edit_mode)
        self.label_of.setHidden(self.no_edit_mode)

        with BlockChangesSignals([self.tab]):
            self.set_combo_box_address_type_default()
            self.spin_signers.setValue(len(self.protowallet.keystores))

        if self.protowallet.is_multisig():
            self.label_of.setEnabled(True)
            self.spin_signers.setEnabled(True)
        else:
            self.label_of.setDisabled(True)
            self.spin_signers.setDisabled(True)

    def repopulate_comboBox_address_type(self, is_multisig: bool):
        with BlockChangesSignals([self.tab]):
            # Fetch the new address types
            address_types = get_address_types(is_multisig)
            address_type_names = [a.name for a in address_types]

            # Get the current items in the combo box
            current_items = [
                self.comboBox_address_type.itemText(i) for i in range(self.comboBox_address_type.count())
            ]

            # Check if the new list is different from the current items
            if address_type_names != current_items:

                # Clear and update the combo box
                self.comboBox_address_type.clear()
                self.comboBox_address_type.addItems(address_type_names)
                default_address_type = get_default_address_type(is_multisig).name
                if default_address_type in address_type_names:
                    self.comboBox_address_type.setCurrentIndex(address_type_names.index(default_address_type))

    def create_wallet_type_and_descriptor(self):
        box_wallet_type_and_descriptor = QWidget(self.tab)
        box_wallet_type_and_descriptor.setLayout(QHBoxLayout(box_wallet_type_and_descriptor))

        current_margins = box_wallet_type_and_descriptor.layout().contentsMargins()
        box_wallet_type_and_descriptor.layout().setContentsMargins(
            QMargins(0, 0, 0, current_margins.bottom())
        )  # Smaller margins (left, top, right, bottom)

        # Removed the unnecessary parent widgets. Using QGroupBox directly as the container.
        box_wallet_type = QGroupBox()

        # Create a QFormLayout
        form_wallet_type = QGridLayout(box_wallet_type)

        # box_signers_with_slider
        self.label_signers = QLabel()
        self.label_signers.setText("Required Signers")

        self.spin_req = QSpinBox()
        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(10)

        self.label_of = QLabel()
        self.label_of.setText("of")
        self.label_of.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spin_signers = QSpinBox()
        self.spin_signers.setMinimum(1)
        self.spin_signers.setMaximum(10)

        # Add widgets to the layout
        form_wallet_type.addWidget(self.label_signers, 0, 0)
        form_wallet_type.addWidget(self.spin_req, 0, 1)
        form_wallet_type.addWidget(self.label_of, 0, 2)
        form_wallet_type.addWidget(self.spin_signers, 0, 3)

        # box_address_type
        self.label_address_type = QLabel()
        self.label_address_type.setObjectName("this label")

        self.comboBox_address_type = QComboBox()
        self.comboBox_address_type.setObjectName("this QComboBox")
        self.comboBox_address_type.currentIndexChanged.connect(self.on_wallet_ui_changes)
        form_wallet_type.addWidget(self.label_address_type, 2, 0)
        form_wallet_type.setObjectName("this form_wallet_type")
        form_wallet_type.addWidget(self.comboBox_address_type, 2, 1, 1, 3)

        # box_gap
        label_gap = QLabel()
        label_gap.setWordWrap(True)
        label_gap.setText("Scan Address Limit")

        self.spin_gap = QSpinBox()
        self.spin_gap.setMinimum(20)
        self.spin_gap.setMaximum(int(1e6))

        # Add widgets to the layout
        form_wallet_type.addWidget(label_gap, 3, 0)
        form_wallet_type.addWidget(self.spin_gap, 3, 1, 1, 3)

        box_wallet_type.setLayout(form_wallet_type)
        box_wallet_type_and_descriptor.layout().addWidget(box_wallet_type)

        # now the descriptor
        groupBox_wallet_descriptor = QGroupBox()
        groupBox_wallet_descriptor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        # below is an example how to highlight the box
        # groupBox_wallet_descriptor.setStyleSheet("""
        # QGroupBox {
        #         font-weight: bold;
        #         border: 2px solid red;
        #         border-radius: 5px;
        #         margin-top: 12px;
        # }
        # QGroupBox::title {
        #         color: red;
        #         subcontrol-origin: margin;
        #         left: 10px;
        #         padding: 0 5px 0 5px;
        # }
        # """)
        self.horizontalLayout_4 = QHBoxLayout(groupBox_wallet_descriptor)
        self.edit_descriptor = (DescriptorEdit)(
            network=self.protowallet.network,
            get_wallet=self.get_wallet,
        )
        self.edit_descriptor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.edit_descriptor.input_field.setPlaceholderText(
            "Paste or scan your descriptor, if you restore a wallet."
        )

        self.edit_descriptor.setToolTip(
            f'This "descriptor" contains all information to reconstruct the wallet. \nPlease back up this descriptor to be able to recover the funds!'
        )

        self.horizontalLayout_4.addWidget(self.edit_descriptor)

        # if self.wallet:
        #     button = create_button(
        #         "Print the \ndescriptor",
        #         icon_path("pdf-file.svg"),
        #         box_wallet_type_and_descriptor,
        #         self.horizontalLayout_4,
        #         max_sizes=[(30, 50)],
        #     )
        #     button.setMaximumWidth(100)
        #     button.clicked.connect(lambda: make_and_open_pdf(self.wallet))

        box_wallet_type_and_descriptor.layout().addWidget(groupBox_wallet_descriptor)

        self.tab.layout().addWidget(box_wallet_type_and_descriptor)

        box_wallet_type.setTitle(QCoreApplication.translate("tab", "Wallet Type", None))
        self.label_address_type.setText(QCoreApplication.translate("tab", "Address Type", None))
        groupBox_wallet_descriptor.setTitle(QCoreApplication.translate("tab", "Wallet Descriptor", None))

        self.spin_signers.valueChanged.connect(self.on_spin_signer_changed)
        self.spin_req.valueChanged.connect(self.on_spin_threshold_changed)

    def create_button_bar(self):

        # Create buttons and layout
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Discard
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self.signal_qtwallet_apply_setting_changes.emit
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Discard).clicked.connect(
            self.signal_qtwallet_cancel_setting_changes.emit
        )

        self.tab.layout().addWidget(self.button_box, 0, Qt.AlignmentFlag.AlignRight)
