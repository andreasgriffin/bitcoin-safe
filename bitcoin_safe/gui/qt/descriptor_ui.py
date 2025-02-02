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
from typing import Optional, Tuple

from bitcoin_qr_tools.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)
from bitcoin_usb.address_types import get_address_types
from PyQt6.QtCore import QMargins, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.descriptor_edit import DescriptorEdit
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.keystore_uis import KeyStoreUIs
from bitcoin_safe.gui.qt.util import Message, MessageType
from bitcoin_safe.i18n import translate
from bitcoin_safe.signal_tracker import SignalTools, SignalTracker
from bitcoin_safe.threading_manager import ThreadingManager

from ...descriptors import AddressType, get_default_address_type
from ...signals import SignalsMin, TypedPyQtSignalNo
from ...wallet import ProtoWallet, Wallet
from .block_change_signals import BlockChangesSignals

logger = logging.getLogger(__name__)


class DescriptorUI(QWidget):
    signal_qtwallet_apply_setting_changes: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_qtwallet_cancel_setting_changes: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_qtwallet_cancel_wallet_creation: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(
        self,
        protowallet: ProtoWallet,
        signals_min: SignalsMin,
        wallet: Optional[Wallet] = None,
        threading_parent: ThreadingManager | None = None,
    ) -> None:
        super().__init__()
        self.signal_tracker = SignalTracker()
        self._layout = QVBoxLayout(self)
        # if we are in the wallet setp process, then wallet = None
        self.protowallet = protowallet
        self.wallet = wallet
        self.signals_min = signals_min

        self.no_edit_mode = (self.protowallet.threshold, len(self.protowallet.keystores)) in [(1, 1), (2, 3)]

        self.create_wallet_type_and_descriptor(threading_parent=threading_parent)

        self.repopulate_comboBox_address_type(self.protowallet.is_multisig())

        self.edit_descriptor.signal_descriptor_change.connect(self.on_descriptor_change)

        self.keystore_uis = KeyStoreUIs(
            get_editable_protowallet=self.get_editable_protowallet,
            get_address_type=self.get_address_type_from_ui,
            signals_min=signals_min,
            slow_hwi_listing=True,
        )
        self._layout.addWidget(self.keystore_uis)

        self.keystore_uis.setCurrentIndex(0)

        self.set_all_ui_from_protowallet()
        # diasbeling fields MUST be done after the ui is filled
        self.disable_fields()

        self.box_button_bar = self.create_button_bar()
        self.updateUi()
        signals_min.language_switch.connect(self.updateUi)

    def get_editable_protowallet(self):
        return self.protowallet

    def updateUi(self) -> None:
        self.label_signers.setText(self.tr("Required Signers"))
        self.label_gap.setText(self.tr("Scan Addresses ahead"))
        self.edit_descriptor.input_field.setPlaceholderText(
            self.tr("Paste or scan your descriptor, if you restore a wallet.")
        )

        self.edit_descriptor.setToolTip(
            self.tr(
                'This "descriptor" contains all information to reconstruct the wallet. \nPlease back up this descriptor to be able to recover the funds!'
            )
        )
        self.box_wallet_type.setTitle(translate("descriptor", "Wallet Properties"))
        self.label_address_type.setText(translate("descriptor", "Address Type"))
        self.groupBox_wallet_descriptor.setTitle(translate("descriptor", "Wallet Descriptor"))

    def set_protowallet(self, protowallet: ProtoWallet) -> None:
        self.protowallet = protowallet
        self.set_all_ui_from_protowallet()

    def on_wallet_ui_changes(self) -> None:
        logger.debug("on_wallet_ui_changes")
        try:
            self.set_protowallet_from_ui()

            self.set_ui_descriptor()
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_wallet_ui_from_protowallet()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            logger.warning("on_wallet_ui_changes: Invalid input")
            self._set_keystore_tabs()

    def on_descriptor_change(self, new_value: str) -> None:
        if not BitcoinQRMultipathDescriptor.is_valid(new_value, network=self.protowallet.network):
            logger.debug("Descriptor invalid")
            return

        old_descriptor = self.protowallet.to_multipath_descriptor()

        if old_descriptor and (new_value == old_descriptor.as_string()):
            logger.info(self.tr("Descriptor unchanged"))
            return
        else:
            logger.info(f"Descriptor changed: {old_descriptor}  -->  {new_value}")
            if not question_dialog(
                text=self.tr(
                    f"Fill signer information based on the new descriptor?",
                ),
                title=self.tr("New descriptor entered"),
                buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
            ):
                return

        try:
            self.set_protowallet_from_descriptor_str(new_value)
            logger.info(f"Successfully set protwallet from descriptor {new_value}")

            self.set_wallet_ui_from_protowallet()
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.disable_fields()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), title="Error", type=MessageType.Error)
            return

    def on_spin_threshold_changed(self, new_value: int) -> None:
        self.on_wallet_ui_changes()

    def on_spin_signer_changed(self, new_value: int) -> None:
        self.repopulate_comboBox_address_type(new_value > 1)

        self.on_wallet_ui_changes()

    def set_protowallet_from_descriptor_str(self, descriptor: str) -> None:
        self.protowallet = ProtoWallet.from_descriptor(
            self.protowallet.id,
            descriptor,
            self.protowallet.network,
        )

    def _set_keystore_tabs(self) -> None:
        self.keystore_uis._set_keystore_tabs()

        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(self.spin_signers.value())
        self.spin_signers.setMinimum(self.spin_req.value())
        self.spin_signers.setMaximum(10)

    def set_wallet_ui_from_protowallet(self) -> None:
        with BlockChangesSignals([self]):
            logger.debug(f"{self.__class__.__name__} set_wallet_ui_from_protowallet")
            self.repopulate_comboBox_address_type(self.protowallet.is_multisig())
            self.comboBox_address_type.setCurrentText(self.protowallet.address_type.name)
            self.spin_req.setMinimum(1)
            self.spin_req.setMaximum(len(self.protowallet.keystores))
            self.spin_req.setValue(self.protowallet.threshold)

            self.spin_signers.setMinimum(self.protowallet.threshold)
            self.spin_signers.setMaximum(10)
            self.spin_signers.setValue(len(self.protowallet.keystores))

            if self.spin_req.value() < self.spin_signers.value():

                labels_of_recovery_signers = [
                    f'"{keystore_ui.label}"' for keystore_ui in self.keystore_uis.getAllTabData().values()
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

    def set_all_ui_from_protowallet(self) -> None:
        """Updates the 3 parts.

        - wallet ui (e.g. gap)
        - Keystore UI  (e.g. xpubs)
        - descriptor ui
        """
        with BlockChangesSignals([self]):
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.set_wallet_ui_from_protowallet()
            self.set_ui_descriptor()

    def set_protowallet_from_ui(self) -> None:
        logger.debug("set_protowallet_from_keystore_ui")

        # these wallet settings must come first
        m, n = self.get_m_of_n_from_ui()
        self.protowallet.set_number_of_keystores(n)
        self.protowallet.set_threshold(m)
        self.protowallet.set_address_type(self.get_address_type_from_ui())
        self.protowallet.set_gap(self.get_gap_from_ui())

        self.keystore_uis.set_protowallet_from_keystore_ui()

    def set_combo_box_address_type_default(self) -> None:
        address_types = get_address_types(self.protowallet.is_multisig())
        self.comboBox_address_type.setCurrentIndex(
            address_types.index(get_default_address_type(self.protowallet.is_multisig()))
        )

    def get_address_type_from_ui(self) -> AddressType:
        address_types = get_address_types(self.protowallet.is_multisig())

        # sanity check
        assert (
            self.comboBox_address_type.currentText()
            == address_types[self.comboBox_address_type.currentIndex()].name
        )
        assert (
            self.comboBox_address_type.currentData()
            == address_types[self.comboBox_address_type.currentIndex()]
        )

        return self.comboBox_address_type.currentData()

    def get_m_of_n_from_ui(self) -> Tuple[int, int]:
        return (self.spin_req.value(), self.spin_signers.value())

    def get_gap_from_ui(self) -> int:
        return self.spin_gap.value()

    def set_ui_descriptor(self) -> None:
        logger.debug(f"{self.__class__.__name__} set_ui_descriptor")
        # check if the descriptor actually CAN be calculated to a reasonable degree
        try:
            multipath_descriptor = self.protowallet.to_multipath_descriptor()
            if multipath_descriptor:
                self.edit_descriptor.setText(multipath_descriptor.as_string_private())
            else:
                self.edit_descriptor.setText("")
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            self.edit_descriptor.setText("")
        self.edit_descriptor.format_and_apply_validator()

    def disable_fields(self) -> None:
        self.comboBox_address_type.setHidden(self.no_edit_mode)
        self.label_address_type.setHidden(self.no_edit_mode)
        self.spin_signers.setHidden(self.no_edit_mode)
        self.spin_req.setHidden(self.no_edit_mode)
        self.label_signers.setHidden(self.no_edit_mode)
        self.label_of.setHidden(self.no_edit_mode)

        with BlockChangesSignals([self]):
            self.set_combo_box_address_type_default()
            self.spin_signers.setValue(len(self.protowallet.keystores))

        if self.protowallet.is_multisig():
            self.label_of.setEnabled(True)
            self.spin_signers.setEnabled(True)
        else:
            self.label_of.setDisabled(True)
            self.spin_signers.setDisabled(True)

    def repopulate_comboBox_address_type(self, is_multisig: bool) -> None:
        with BlockChangesSignals([self]):
            # Fetch the new address types
            address_types = get_address_types(is_multisig)
            address_type_names = [a.name for a in address_types]

            # Get the current items in the combo box
            current_names = [
                self.comboBox_address_type.itemText(i) for i in range(self.comboBox_address_type.count())
            ]

            # Check if the new list is different from the current items
            if address_type_names != current_names:

                # Clear and update the combo box
                self.comboBox_address_type.clear()
                for address_type in address_types:
                    self.comboBox_address_type.addItem(address_type.name, userData=address_type)

                default_address_type = get_default_address_type(is_multisig).name
                if default_address_type in address_type_names:
                    self.comboBox_address_type.setCurrentIndex(address_type_names.index(default_address_type))

    def create_wallet_type_and_descriptor(self, threading_parent: ThreadingManager | None = None) -> None:
        box_wallet_type_and_descriptor = QWidget(self)
        box_wallet_type_and_descriptor_layout = QHBoxLayout(box_wallet_type_and_descriptor)

        current_margins = box_wallet_type_and_descriptor_layout.contentsMargins()
        box_wallet_type_and_descriptor_layout.setContentsMargins(
            QMargins(0, 0, 0, current_margins.bottom())
        )  # Smaller margins (left, top, right, bottom)

        # Removed the unnecessary parent widgets. Using QGroupBox directly as the container.
        self.box_wallet_type = QGroupBox()

        # Create a QFormLayout
        form_wallet_type = QGridLayout(self.box_wallet_type)

        # box_signers_with_slider
        self.label_signers = QLabel()

        self.spin_req = QSpinBox()
        self.spin_req.setObjectName("spin_req")
        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(10)

        self.label_of = QLabel()
        self.label_of.setText("of")
        self.label_of.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spin_signers = QSpinBox()
        self.spin_signers.setObjectName("spin_signers")
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
        self.label_gap = QLabel()
        self.label_gap.setWordWrap(True)

        self.spin_gap = QSpinBox()
        self.spin_gap.setMinimum(20)
        self.spin_gap.setMaximum(int(1e6))

        # Add widgets to the layout
        form_wallet_type.addWidget(self.label_gap, 3, 0)
        form_wallet_type.addWidget(self.spin_gap, 3, 1, 1, 3)

        self.box_wallet_type.setLayout(form_wallet_type)
        box_wallet_type_and_descriptor_layout.addWidget(self.box_wallet_type)

        # now the descriptor
        self.groupBox_wallet_descriptor = QGroupBox()
        self.groupBox_wallet_descriptor.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
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
        self.horizontalLayout_4 = QHBoxLayout(self.groupBox_wallet_descriptor)
        self.edit_descriptor = DescriptorEdit(
            network=self.protowallet.network,
            signals_min=self.signals_min,
            wallet=self.wallet,
            signal_update=self.signals_min.language_switch,
            threading_parent=threading_parent,
        )
        self.edit_descriptor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_4.addWidget(self.edit_descriptor)

        box_wallet_type_and_descriptor_layout.addWidget(self.groupBox_wallet_descriptor)

        self._layout.addWidget(box_wallet_type_and_descriptor)

        self.spin_signers.valueChanged.connect(self.on_spin_signer_changed)
        self.spin_req.valueChanged.connect(self.on_spin_threshold_changed)

    def create_button_bar(self) -> QDialogButtonBox:

        # Create buttons and layout
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Discard
        )
        if _button := self.button_box.button(QDialogButtonBox.StandardButton.Apply):
            _button.clicked.connect(self.signal_qtwallet_apply_setting_changes.emit)
        if _button := self.button_box.button(QDialogButtonBox.StandardButton.Discard):
            _button.clicked.connect(self.signal_qtwallet_cancel_setting_changes.emit)
        if _button := self.button_box.button(QDialogButtonBox.StandardButton.Discard):
            _button.clicked.connect(self.signal_qtwallet_cancel_wallet_creation.emit)

        self._layout.addWidget(self.button_box, 0, Qt.AlignmentFlag.AlignRight)
        return self.button_box

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.edit_descriptor.close()
        self.setParent(None)
        super().close()
