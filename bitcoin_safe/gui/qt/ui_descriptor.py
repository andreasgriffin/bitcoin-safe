import logging

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from ...wallet import Wallet, ProtoWallet
from ...descriptors import (
    get_default_address_type,
    AddressType,
    get_address_types,
)
from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from ...signals import Signals, Signal
from .keystore_ui import KeyStoreUI
from typing import List, Tuple
from .block_change_signals import BlockChangesSignals
from .custom_edits import DescriptorEdit
from ...descriptors import combined_wallet_descriptor


class WalletDescriptorUI(QObject):
    signal_descriptor_pasted = Signal(str)
    signal_descriptor_change_apply = Signal(str)
    signal_qtwallet_apply_setting_changes = Signal()
    signal_qtwallet_cancel_setting_changes = Signal()
    signal_qtwallet_cancel_wallet_creation = Signal()

    def __init__(self, protowallet: ProtoWallet = None, wallet: Wallet = None) -> None:
        super().__init__()
        # if we are in the wallet setp process, then wallet = None
        self.wallet: Wallet = wallet

        self.protowallet: ProtoWallet = (
            self.wallet.as_protowallet() if self.wallet else protowallet
        )

        self.tab = QWidget()
        self.verticalLayout_2 = QVBoxLayout(self.tab)

        self.keystore_uis: List[KeyStoreUI] = []

        self.create_wallet_type_and_descriptor()
        self.tabs_widget_signers = QTabWidget(self.tab)
        self.verticalLayout_2.addWidget(self.tabs_widget_signers)

        self.signal_descriptor_pasted.connect(self.on_descriptor_pasted)
        self.signal_descriptor_change_apply.connect(self.on_descriptor_change)

        for keystore in self.protowallet.keystores:
            keystore_ui = KeyStoreUI(
                keystore,
                self.tabs_widget_signers,
                self.protowallet.network,
            )
            self.keystore_uis.append(keystore_ui)

        self.block_change_signals = BlockChangesSignals(
            own_widgets=[
                self.spin_gap,
                self.spin_req,
                self.spin_signers,
                self.edit_descriptor,
            ],
        )

        for signal in (
            [ui.keystore_ui_default.signal_xpub_changed for ui in self.keystore_uis]
            + [
                ui.keystore_ui_default.signal_fingerprint_changed
                for ui in self.keystore_uis
            ]
            + [
                ui.keystore_ui_default.signal_derivation_path_changed
                for ui in self.keystore_uis
            ]
        ):
            signal.connect(self.ui_keystore_ui_change)
        for ui in self.keystore_uis:
            ui.keystore_ui_default.signal_seed_changed.connect(self.ui_seed_ui_change)
        self.set_all_ui_from_protowallet()
        # diasbeling fields MUST be done after the ui is filled
        self.disable_fields()

        self.box_button_bar = self.create_button_bar()

    def ui_seed_ui_change(self, *args):
        self.ui_keystore_ui_change()

    def ui_keystore_ui_change(self, *args):
        self.set_protowallet_from_keystore_ui()
        self.set_ui_descriptor()

    def on_wallet_ui_changes(self):
        self.set_protowallet_from_keystore_ui()

        self.set_ui_descriptor()
        self.set_keystore_ui_from_protowallet()
        self.set_wallet_ui_from_protowallet()

    def get_ui_values_as_keystores(self):
        return [
            keystore_ui.keystore_ui_default.get_ui_values_as_keystore()
            for keystore_ui in self.keystore_uis
        ]

    def on_descriptor_pasted(self, new_value):
        self.on_descriptor_change(new_value)
        self.set_ui_descriptor()

    def on_descriptor_change(self, new_value):
        # self.set_protowallet_from_keystore_ui(cloned_protowallet)
        if (
            hasattr(self, "_edit_descriptor_cache")
            and self._edit_descriptor_cache == new_value
        ):
            # no change
            return
        self._edit_descriptor_cache = new_value

        self.set_wallet_ui_from_protowallet()
        self.set_keystore_ui_from_protowallet()
        self.disable_fields()

    def on_spin_threshold_changed(self, new_value):
        self.on_wallet_ui_changes()

    def on_spin_signer_changed(self, new_value):
        self.on_wallet_ui_changes()

    def _set_keystore_tabs(self):
        # add keystore_ui if necessary
        if len(self.keystore_uis) < len(self.protowallet.keystores):
            for i in range(len(self.keystore_uis), len(self.protowallet.keystores)):
                self.keystore_uis.append(
                    KeyStoreUI(
                        self.protowallet.keystores[i],
                        self.tabs_widget_signers,
                        self.protowallet.network,
                    )
                )
        # remove keystore_ui if necessary
        elif len(self.keystore_uis) > len(self.protowallet.keystores):
            for i in range(len(self.protowallet.keystores), len(self.keystore_uis)):
                self.keystore_uis[-1].remove_tab()
                self.keystore_uis.pop()

        # now make a second pass and connect point the keystore_ui.keystore correctly
        for keystore, keystore_ui in zip(self.protowallet.keystores, self.keystore_uis):
            keystore_ui.keystore.from_other_keystore(keystore)

    def set_keystore_ui_from_protowallet(self):
        self._set_keystore_tabs()
        for keystore, keystore_ui in zip(self.protowallet.keystores, self.keystore_uis):
            keystore_ui.set_ui_from_keystore(keystore)

    def set_wallet_ui_from_protowallet(self):
        with self.block_change_signals:
            self.spin_req.setMinimum(1)
            self.spin_req.setMaximum(len(self.protowallet.keystores))
            self.spin_req.setValue(self.protowallet.threshold)

            self.spin_signers.setMinimum(self.protowallet.threshold)
            self.spin_signers.setMaximum(10)
            self.spin_signers.setValue(len(self.protowallet.keystores))

            if self.spin_req.value() < self.spin_signers.value():
                labels_of_recovery_signers = [
                    f'"{keystore.label}"' for keystore in self.protowallet.keystores
                ][self.spin_req.value() :]
                self.spin_req.setToolTip(
                    f"In the chosen multisig setup, you need {self.spin_req.value()} devices (signers) to sign every outgoing transaction.\n"
                    f'In case of loss of 1 of the devices, you can recover your funds using\n {" or ".join(labels_of_recovery_signers)} and send the funds to a new wallet.'
                )
            if self.spin_req.value() == self.spin_signers.value() != 1:
                self.spin_req.setToolTip(
                    f"Warning!  Choosing a multisig setup where ALL signers need to sign every transaction\n is very RISKY and does not offer ynay benefits of multisig. Recommended multisig setups are 2-of-3 or 3-of-5"
                )
            if self.spin_req.value() == self.spin_signers.value() == 1:
                self.spin_req.setToolTip(
                    f"A single signing device can sign outgoing transactions."
                )

            self.spin_gap.setValue(self.protowallet.gap)

    def set_all_ui_from_protowallet(self):
        """
        Updates the 3 parts
        - wallet ui (e.g. gap)
        - Keystore UI  (e.g. xpubs)
        - descriptor ui
        """
        with self.block_change_signals:
            self.set_wallet_ui_from_protowallet()
            self.set_keystore_ui_from_protowallet()
            self.set_ui_descriptor()

    def set_protowallet_from_keystore_ui(self):
        for keystore, keystore_ui in zip(self.protowallet.keystores, self.keystore_uis):
            keystore_ui.set_keystore_from_ui_values(keystore)
        self.protowallet.set_address_type(self.get_address_type_from_ui())
        self.protowallet.set_gap(self.get_gap_from_ui())

        m, n = self.get_m_of_n_from_ui()
        self.protowallet.set_threshold(m)

        assert len(self.protowallet.keystores) == len(self.keystore_uis)
        # if len(wallet.keystores) != len(self.keystore_uis):
        #         print(wallet.keystores, self.keystore_uis)

        self.protowallet.set_number_of_keystores(n)

        for i, keystore in enumerate(self.protowallet.keystores):
            keystore.label = self.protowallet.signer_names(
                self.protowallet.threshold, i
            )

    def set_combo_box_address_type_default(self):
        address_types = get_address_types(self.protowallet.is_multisig())
        self.comboBox_address_type.setCurrentIndex(
            address_types.index(
                get_default_address_type(self.protowallet.is_multisig())
            )
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
        # check if the descriptor actually CAN be calculated to a reasonable degree

        try:
            self.edit_descriptor.setText(
                combined_wallet_descriptor(self.protowallet.bdk_descriptors())
            )
        except:
            self.edit_descriptor.setText("Could not be derived from seed")

    def disable_fields(self):
        with self.block_change_signals:
            self.set_combo_box_address_type_default()
            self.spin_signers.setValue(len(self.protowallet.keystores))

        if self.protowallet.is_multisig():
            self.label_of.setEnabled(True)
            self.spin_signers.setEnabled(True)
        else:
            self.label_of.setDisabled(True)
            self.spin_signers.setDisabled(True)

    def create_wallet_type_and_descriptor(self):
        box_wallet_type_and_descriptor = QWidget(self.tab)
        box_wallet_type_and_descriptor.setMaximumHeight(200)

        h_wallet_type_and_descriptor = QHBoxLayout(box_wallet_type_and_descriptor)
        box_wallet_type = QGroupBox(box_wallet_type_and_descriptor)
        v_wallet_type = QVBoxLayout(box_wallet_type)

        # box_signers_with_slider
        box_signers_with_slider = QWidget(box_wallet_type)
        h_signers_with_slider = QHBoxLayout(box_signers_with_slider)
        label_signers = QLabel(box_signers_with_slider)
        label_signers.setText(QCoreApplication.translate("tab", "Signers", None))
        h_signers_with_slider.addWidget(label_signers)
        self.spin_req = QSpinBox(box_signers_with_slider)
        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(10)
        h_signers_with_slider.addWidget(self.spin_req)
        self.label_of = QLabel(box_signers_with_slider)
        self.label_of.setText(QCoreApplication.translate("tab", "of", None))
        self.label_of.setAlignment(Qt.AlignVCenter)
        h_signers_with_slider.addWidget(self.label_of)
        self.spin_signers = QSpinBox(box_signers_with_slider)
        self.spin_signers.setMinimum(1)
        self.spin_signers.setMaximum(10)
        h_signers_with_slider.addWidget(self.spin_signers)
        v_wallet_type.addWidget(box_signers_with_slider)

        box_address_type = QWidget(box_wallet_type)
        h_address_type = QHBoxLayout(box_address_type)
        label_address_type = QLabel(box_address_type)

        h_address_type.addWidget(label_address_type)

        self.comboBox_address_type = QComboBox(box_address_type)
        address_types = get_address_types(self.protowallet.is_multisig())
        addres_type_names = [a.name for a in address_types]
        self.comboBox_address_type.addItems(addres_type_names)
        h_address_type.addWidget(self.comboBox_address_type)

        v_wallet_type.addWidget(box_address_type)

        box_gap = QWidget(box_wallet_type)
        h_gap = QHBoxLayout(box_gap)
        label_gap = QLabel(box_gap)
        label_gap.setWordWrap(True)
        label_gap.setText("Pregenerate ")
        self.spin_gap = QSpinBox(box_gap)
        self.spin_gap.setMinimum(20)
        self.spin_gap.setMaximum(int(1e6))
        label_gap2 = QLabel(box_gap)
        label_gap2.setText(" unused Addresses")
        # self.label_gap2.setTextAlignment(Qt.AlignVCenter)
        h_gap.addWidget(label_gap)
        h_gap.addWidget(self.spin_gap)
        h_gap.addWidget(label_gap2)

        v_wallet_type.addWidget(box_gap)

        h_wallet_type_and_descriptor.addWidget(box_wallet_type)

        # now the descriptor
        groupBox_wallet_descriptor = QGroupBox(box_wallet_type_and_descriptor)
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
        self.edit_descriptor = DescriptorEdit(get_wallet=lambda: self.wallet)
        self.edit_descriptor.setToolTip(
            f'This "descriptor" contains all information to reconstruct the wallet. \nPlease back up this descriptor to be able to recover the funds!'
        )
        self.edit_descriptor.signal_key_press.connect(
            self.signal_descriptor_change_apply
        )
        self.edit_descriptor.signal_pasted_text.connect(self.signal_descriptor_pasted)

        self.horizontalLayout_4.addWidget(self.edit_descriptor)

        h_wallet_type_and_descriptor.addWidget(groupBox_wallet_descriptor)

        self.verticalLayout_2.addWidget(box_wallet_type_and_descriptor)

        box_wallet_type.setTitle(QCoreApplication.translate("tab", "Wallet Type", None))
        label_address_type.setText(
            QCoreApplication.translate("tab", "Address Type", None)
        )
        groupBox_wallet_descriptor.setTitle(
            QCoreApplication.translate("tab", "Wallet Descriptor", None)
        )

        # self.edit_descriptor.textChanged.connect(self.signal_descriptor_change_apply)
        self.spin_signers.valueChanged.connect(self.on_spin_signer_changed)
        self.spin_req.valueChanged.connect(self.on_spin_threshold_changed)
        self.comboBox_address_type.currentIndexChanged.connect(
            lambda x: self.on_wallet_ui_changes()
        )

    def create_button_bar(self):
        box_button_bar = QWidget(self.tab)
        layout_buttonbar = QHBoxLayout(box_button_bar)
        layout_buttonbar.setContentsMargins(0, 0, 0, 0)

        self.button_cancel = QPushButton(box_button_bar)
        self.button_cancel.setText("Cancel changes")
        self.button_cancel.setMinimumSize(QSize(150, 0))
        self.button_cancel.clicked.connect(
            self.signal_qtwallet_cancel_setting_changes.emit
        )
        layout_buttonbar.addWidget(self.button_cancel)

        self.button_apply = QPushButton(box_button_bar)
        self.button_apply.setText("Apply changes")
        self.button_apply.setMinimumSize(QSize(150, 0))
        self.button_apply.clicked.connect(
            self.signal_qtwallet_apply_setting_changes.emit
        )
        layout_buttonbar.addWidget(self.button_apply)
        self.verticalLayout_2.addWidget(box_button_bar, 0, Qt.AlignRight)
