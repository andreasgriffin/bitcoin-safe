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

from __future__ import annotations

import logging
from typing import cast

from bitcoin_qr_tools.data import Data
from bitcoin_qr_tools.multipath_descriptor import is_valid_descriptor
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_usb.address_types import get_address_types
from PyQt6.QtCore import Qt, pyqtSignal
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
from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.keystore_uis import KeyStoreUIs
from bitcoin_safe.gui.qt.util import Message, MessageType, set_margins
from bitcoin_safe.signals import WalletFunctions

from ...descriptors import AddressType, get_default_address_type
from ...wallet import ProtoWallet, Wallet
from .block_change_signals import BlockChangesSignals

logger = logging.getLogger(__name__)


class DescriptorUI(QWidget):
    signal_qtwallet_apply_setting_changes = cast(SignalProtocol[[]], pyqtSignal())
    signal_qtwallet_cancel_setting_changes = cast(SignalProtocol[[]], pyqtSignal())
    signal_qtwallet_cancel_wallet_creation = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        protowallet: ProtoWallet,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
        wallet: Wallet | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signal_tracker = SignalTracker()
        self._layout = QVBoxLayout(self)
        # if we are in the wallet setp process, then wallet = None
        self.protowallet = protowallet
        self.wallet = wallet
        self.wallet_functions = wallet_functions
        self.loop_in_thread = loop_in_thread

        self.no_edit_mode = (self.protowallet.threshold, len(self.protowallet.keystores)) in [(1, 1), (2, 3)]

        self.create_wallet_type_and_descriptor(loop_in_thread=loop_in_thread)

        self.repopulate_comboBox_address_type(self.protowallet.is_multisig())

        self.edit_descriptor.signal_descriptor_change.connect(self.on_descriptor_change)

        self.keystore_uis = KeyStoreUIs(
            get_editable_protowallet=self.get_editable_protowallet,
            get_address_type=self.get_address_type_from_ui,
            signals_min=wallet_functions.signals,
            slow_hwi_listing=True,
            loop_in_thread=self.loop_in_thread,
        )
        self._layout.addWidget(self.keystore_uis)

        self.keystore_uis.setCurrentIndex(0)

        self.set_all_ui_from_protowallet()
        # diasbeling fields MUST be done after the ui is filled
        self.disable_fields()

        self.box_button_bar = self.create_button_bar()
        self.updateUi()
        wallet_functions.signals.language_switch.connect(self.updateUi)

    def get_editable_protowallet(self):
        """Get editable protowallet."""
        return self.protowallet

    def updateUi(self) -> None:
        """UpdateUi."""
        self.label_signers.setText(self.tr("Required Signers"))
        self.label_gap.textLabel.setText(self.tr("Scan Addresses ahead"))
        self.label_gap.set_icon_as_help(
            tooltip=self.tr(
                "While scanning the blockchain the wallet will create additional addresses to discover transactions\nDefault 20"
            )
        )
        self.box_wallet_type.setTitle(self.tr("Wallet Properties"))
        self.label_address_type.setText(self.tr("Address Type"))
        self.groupBox_wallet_descriptor.setTitle(self.tr("Wallet Descriptor"))
        self.edit_descriptor.updateUi()

    def set_protowallet(self, protowallet: ProtoWallet) -> None:
        """Set protowallet."""
        self.protowallet = protowallet
        self.set_all_ui_from_protowallet()

    def on_wallet_ui_changes(self) -> None:
        """On wallet ui changes."""
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

    def on_spin_threshold_changed(self, new_value: int) -> None:
        """On spin threshold changed."""
        self.on_wallet_ui_changes()

    def on_spin_signer_changed(self, new_value: int) -> None:
        """On spin signer changed."""
        self.repopulate_comboBox_address_type(new_value > 1)

        self.on_wallet_ui_changes()

    def set_protowallet_from_descriptor_str(self, descriptor: str) -> None:
        """Set protowallet from descriptor str."""
        self.protowallet = ProtoWallet.from_descriptor(
            self.protowallet.id,
            descriptor,
            self.protowallet.network,
        )

    def _set_keystore_tabs(self) -> None:
        """Set keystore tabs."""
        self.keystore_uis._set_keystore_tabs()

        self.spin_req.setMinimum(1)
        self.spin_req.setMaximum(self.spin_signers.value())
        self.spin_signers.setMinimum(self.spin_req.value())
        self.spin_signers.setMaximum(10)

    def set_wallet_ui_from_protowallet(self) -> None:
        """Set wallet ui from protowallet."""
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
                    f"In case of loss of 1 of the devices, you can recover your funds using\n {' or '.join(labels_of_recovery_signers)} and send the funds to a new wallet."
                )
            if self.spin_req.value() == self.spin_signers.value() != 1:
                self.spin_req.setToolTip(
                    "Warning!  Choosing a multisig setup where ALL signers need to sign every transaction\n is very RISKY and does not offer any benefits of multisig. Recommended multisig setups are 2-of-3 or 3-of-5"
                )
            if self.spin_req.value() == self.spin_signers.value() == 1:
                self.spin_req.setToolTip("A single signing device can sign outgoing transactions.")

            self.spin_gap.setValue(self.protowallet.gap)

    def set_all_ui_from_protowallet(self) -> None:
        """Updates the 3 parts.

        - wallet ui (e.g. gap)
        - Keystore UI  (e.g. xpubs)
        - descriptor ui
        """
        # do not do BlockChangesSignals here
        # otherwise the tab count wont update
        self.set_wallet_ui_from_protowallet()
        self.set_ui_descriptor()
        self.keystore_uis.set_keystore_ui_from_protowallet()

    def set_protowallet_from_ui(self) -> None:
        """Set protowallet from ui."""
        logger.debug("set_protowallet_from_keystore_ui")

        # these wallet settings must come first
        m, n = self.get_m_of_n_from_ui()
        self.protowallet.set_number_of_keystores(n)
        self.protowallet.set_threshold(m)
        self.protowallet.set_address_type(self.get_address_type_from_ui())
        self.protowallet.set_gap(self.get_gap_from_ui())

        self.keystore_uis.set_protowallet_from_keystore_ui()

    def set_combo_box_address_type_from_protowallet(self) -> None:
        """Set combo box address type from protowallet."""
        address_types = get_address_types(self.protowallet.is_multisig())
        self.comboBox_address_type.setCurrentIndex(address_types.index(self.protowallet.address_type))

    def get_address_type_from_ui(self) -> AddressType:
        """Get address type from ui."""
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

    def get_m_of_n_from_ui(self) -> tuple[int, int]:
        """Get m of n from ui."""
        return (self.spin_req.value(), self.spin_signers.value())

    def get_gap_from_ui(self) -> int:
        """Get gap from ui."""
        return self.spin_gap.value()

    def set_ui_descriptor(self) -> None:
        """Set ui descriptor."""
        logger.debug(f"{self.__class__.__name__} set_ui_descriptor")
        # check if the descriptor actually CAN be calculated to a reasonable degree
        try:
            multipath_descriptor = self.protowallet.to_multipath_descriptor()
            if multipath_descriptor:
                self.edit_descriptor.edit.setText(multipath_descriptor.to_string_with_secret())
            else:
                self.edit_descriptor.edit.setText("")
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            self.edit_descriptor.edit.setText("")
        self.edit_descriptor.edit.format_and_apply_validator()

    def disable_fields(self) -> None:
        """Disable fields."""
        self.comboBox_address_type.setEnabled(not self.no_edit_mode)
        self.label_address_type.setHidden(False)
        self.spin_signers.setHidden(self.no_edit_mode)
        self.spin_req.setHidden(self.no_edit_mode)
        self.label_signers.setHidden(self.no_edit_mode)
        self.label_of.setHidden(self.no_edit_mode)

        with BlockChangesSignals([self]):
            self.set_combo_box_address_type_from_protowallet()
            self.spin_signers.setValue(len(self.protowallet.keystores))

        if self.protowallet.is_multisig():
            self.label_of.setEnabled(True)
            self.spin_signers.setEnabled(True)
        else:
            self.label_of.setDisabled(True)
            self.spin_signers.setDisabled(True)

    def repopulate_comboBox_address_type(self, is_multisig: bool) -> None:
        """Repopulate comboBox address type."""
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

    def create_wallet_type_and_descriptor(self, loop_in_thread: LoopInThread) -> None:
        """Create wallet type and descriptor."""
        box_wallet_type_and_descriptor = QWidget(self)
        box_wallet_type_and_descriptor_layout = QHBoxLayout(box_wallet_type_and_descriptor)

        set_margins(
            box_wallet_type_and_descriptor_layout,
            {
                Qt.Edge.LeftEdge: 0,
                Qt.Edge.TopEdge: 0,
                Qt.Edge.RightEdge: 0,
            },
        )

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
        self.label_gap = IconLabel()
        self.label_gap.textLabel.setWordWrap(True)

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
        self.horizontalLayout_4 = QVBoxLayout(self.groupBox_wallet_descriptor)
        self.edit_descriptor = DescriptorEdit(
            network=self.protowallet.network,
            wallet_functions=self.wallet_functions,
            wallet=self.wallet,
            signal_update=self.wallet_functions.signals.language_switch,
            loop_in_thread=loop_in_thread,
        )
        self.edit_descriptor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.horizontalLayout_4.addWidget(self.edit_descriptor)

        box_wallet_type_and_descriptor_layout.addWidget(self.groupBox_wallet_descriptor)

        self._layout.addWidget(box_wallet_type_and_descriptor)

        self.spin_signers.valueChanged.connect(self.on_spin_signer_changed)
        self.spin_req.valueChanged.connect(self.on_spin_threshold_changed)

    def on_descriptor_change(self, user_input: str) -> None:
        # try converting it to a descriptor
        """On descriptor change."""
        data = self._input_to_data(s=user_input)
        if not data:
            logger.debug(f"{user_input} could not be decoded into data")
            return
        corrected_descriptor = self.edit_descriptor._data_to_descriptor(data)
        if not corrected_descriptor:
            logger.debug("data could not be decoded into a descriptor")
            return

        if corrected_descriptor != user_input:
            if not question_dialog(
                text=self.tr(
                    f"The input was non-standard, and was auto-corrected to\n{corrected_descriptor}\n Do you want to proceed?",
                ).format(autocorrected_descriptor=corrected_descriptor),
                title=self.tr("Input corrected"),
                true_button=QMessageBox.StandardButton.Ok,
                false_button=QMessageBox.StandardButton.Cancel,
            ):
                self.edit_descriptor.edit.input_field.clear()
                self.edit_descriptor.edit.reset_formatting()
                return
            else:
                self.edit_descriptor.edit.input_field.setText(corrected_descriptor)
                self.edit_descriptor.edit.reset_formatting()
                logger.debug(
                    f"autocorrection {str(user_input)[:10]=} --> {str(corrected_descriptor)[:10]=} denied"
                )
                return

        if not is_valid_descriptor(user_input, network=self.protowallet.network):
            logger.debug("Descriptor invalid")
            return

        old_descriptor = self.protowallet.to_multipath_descriptor()

        if old_descriptor and (user_input == str(old_descriptor)):
            logger.info(self.tr("Descriptor unchanged"))
            return
        else:
            logger.info(f"Descriptor changed: {str(old_descriptor)[:10]=}  -->  {str(user_input)[:10]=}")
            if not question_dialog(
                text=self.tr(
                    "Fill signer information based on the new descriptor?",
                ),
                title=self.tr("New descriptor entered"),
                true_button=QMessageBox.StandardButton.Ok,
                false_button=QMessageBox.StandardButton.No,
            ):
                return

        try:
            self.set_protowallet_from_descriptor_str(user_input)
            logger.info(f"Successfully set protwallet from descriptor {str(user_input)[:10]=}")

            self.set_wallet_ui_from_protowallet()
            self.keystore_uis.set_keystore_ui_from_protowallet()
            self.disable_fields()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), title="Error", type=MessageType.Error, parent=self)
            return

    def _input_to_data(self, s: str) -> Data | None:
        """Input to data."""
        s = s.strip(" \n")
        try:
            return Data.from_str(s, network=self.protowallet.network)
        except Exception as e:
            logger.debug(f"{e}")

        # perhaps the \n are \\n, then try
        if "\\n" in s:
            try:
                return Data.from_str(s.replace("\\n", "\n"), network=self.protowallet.network)
            except Exception as e:
                logger.debug(f"{e}")
        return None

    def create_button_bar(self) -> QDialogButtonBox:
        # Create buttons and layout
        """Create button bar."""
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
        """Close."""
        self.edit_descriptor.close()
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()
