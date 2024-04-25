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

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit

from ...pythonbdk_types import Recipient
from .invisible_scroll_area import InvisibleScrollArea

logger = logging.getLogger(__name__)

from typing import List, Optional

import bdkpython as bdk
from bitcoin_qrreader import bitcoin_qr
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTabWidget,
    QWidget,
)

from ...i18n import translate
from ...signals import Signals
from ...util import unit_str
from ...wallet import Wallet, get_wallets
from .dialogs import question_dialog
from .spinbox import BTCSpinBox
from .util import ColorScheme


def dialog_replace_with_new_receiving_address(address: str):
    return question_dialog(
        text=translate(
            "recipients",
            f"Address {address} was used already. Would you like to get a fresh receiving address?",
        ),
        title=translate("recipients", "Address Already Used"),
        buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
    )


class CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(16, 16))  # Adjust the size as needed

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionButton()
        option.initFrom(self)
        option.features = QStyleOptionButton.ButtonFeature.None_
        option.icon = self.style().standardIcon(QStyle.StandardPixmap.SP_TabCloseButton)
        option.iconSize = QSize(14, 14)  # Adjust icon size as needed
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)


class RecipientGroupBox(QTabWidget):
    signal_close = QtCore.pyqtSignal(QTabWidget)

    def __init__(self, signals: Signals, network: bdk.Network, allow_edit=True, title=""):
        super().__init__()
        self.setTabsClosable(allow_edit)
        self.title = title
        self.tab = QWidget()
        self.addTab(self.tab, title)

        self.signals = signals
        self.allow_edit = allow_edit

        self.tabCloseRequested.connect(lambda: self.signal_close.emit(self))

        form_layout = QtWidgets.QFormLayout()
        self.tab.setLayout(form_layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def on_handle_input(data: bitcoin_qr.Data, parent: QWidget):
            if data.data_type == bitcoin_qr.DataType.Bip21:
                if data.data.get("address"):
                    self.address_line_edit.setText(data.data.get("address"))
                if data.data.get("amount"):
                    self.amount_spin_box.setValue(data.data.get("amount"))
                if data.data.get("label"):
                    self.label_line_edit.setText(data.data.get("label"))

        self.address_line_edit = ButtonEdit(signal_update=self.signals.language_switch)
        if allow_edit:
            self.address_line_edit.add_qr_input_from_camera_button(
                network=network,
                custom_handle_input=on_handle_input,
            )
        else:
            self.address_line_edit.add_copy_button()
            self.address_line_edit.setReadOnly(True)

        def is_valid():
            if not self.address_line_edit.text():
                # if it is empty, show no error
                return True
            try:
                bdk_address = bdk.Address(self.address_line_edit.text().strip(), network=network)
                if self.signals.get_network.emit() == bdk.Network.SIGNET:
                    # bdk treats signet AND testnet as testnet
                    assert bdk_address.network() in [bdk.Network.SIGNET, bdk.Network.TESTNET]
                else:
                    assert bdk_address.network() == self.signals.get_network.emit()
                return True
            except:
                return False

        self.address_line_edit.set_validator(is_valid)
        self.label_line_edit = QtWidgets.QLineEdit()

        self.amount_layout = QtWidgets.QHBoxLayout()
        self.amount_spin_box = BTCSpinBox(self.signals.get_network())
        self.label_unit = QtWidgets.QLabel(unit_str(self.signals.get_network()))
        self.send_max_button = QtWidgets.QPushButton()
        self.send_max_button.setCheckable(True)
        self.send_max_button.setMaximumWidth(80)
        self.send_max_button.clicked.connect(self.on_send_max_button_click)
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.label_unit)
        if allow_edit:
            self.amount_layout.addWidget(self.send_max_button)

        self.address_label = QLabel()
        self.label_txlabel = QLabel()
        self.amount_label = QLabel()

        form_layout.addRow(self.address_label, self.address_line_edit)
        form_layout.addRow(self.label_txlabel, self.label_line_edit)
        form_layout.addRow(self.amount_label, self.amount_layout)

        if not allow_edit:
            self.address_line_edit.setReadOnly(True)
            self.label_line_edit.setReadOnly(True)
            self.amount_spin_box.setReadOnly(True)

        self.address_line_edit.input_field.textChanged.connect(self.format_address_field)
        self.address_line_edit.input_field.textChanged.connect(self.set_label_placeholder_text)
        self.address_line_edit.input_field.textChanged.connect(self.check_if_used)

        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self):

        self.address_label.setText(self.tr("Address"))
        self.label_txlabel.setText(self.tr("Label"))
        self.amount_label.setText(self.tr("Amount"))

        self.label_line_edit.setPlaceholderText(self.tr("Enter label here"))
        self.send_max_button.setText(self.tr("Send max"))
        self.address_line_edit.setPlaceholderText(self.tr("Enter address here"))

        self.format_address_field()
        self.set_label_placeholder_text()

    def showEvent(self, event):
        # this is necessary, otherwise the background color of the
        # address_line_edit.input_field is not updated properly when setting the adddress
        self.updateUi()

    def on_send_max_button_click(self):
        # self.amount_spin_box.setValue(0)
        # self.amount_spin_box.setEnabled(not self.send_max_button.isChecked())
        self.amount_spin_box.set_max(self.send_max_button.isChecked())

    @property
    def address(self) -> str:
        return self.address_line_edit.text().strip()

    @address.setter
    def address(self, value: str):
        self.address_line_edit.setText(value)

    @property
    def label(self) -> str:
        return self.label_line_edit.text().strip()

    @label.setter
    def label(self, value: str):
        self.label_line_edit.setText(value)

    @property
    def amount(self) -> int:
        return self.amount_spin_box.value()

    @amount.setter
    def amount(self, value: int):
        self.amount_spin_box.setValue(value)

    @property
    def enabled(self) -> bool:
        return not self.address_line_edit.isReadOnly()

    @enabled.setter
    def enabled(self, state: bool):
        self.address_line_edit.setReadOnly(not state)
        self.label_line_edit.setReadOnly(not state)
        self.amount_spin_box.setReadOnly(not state)
        self.send_max_button.setEnabled(state)

    def set_label_placeholder_text(self):
        wallets = get_wallets(self.signals)

        wallet_id = None
        label = ""
        for wallet in wallets:
            if self.address in wallet.get_addresses():
                wallet_id = wallet.id
                label = wallet.get_label_for_address(self.address)
                if label:
                    break

        if wallet_id:
            self.label_line_edit.setPlaceholderText(label)
            if not self.allow_edit:
                self.label_line_edit.setText(label)
        else:
            self.label_line_edit.setPlaceholderText(self.tr("Enter label for recipient address"))

    def get_wallet_of_address(self, address: str) -> Optional[Wallet]:
        for wallet in get_wallets(self.signals):
            if wallet.is_my_address(address):
                return wallet
        return None

    def check_if_used(self, *args):
        wallet_of_address = self.get_wallet_of_address(self.address)
        if self.allow_edit and wallet_of_address and wallet_of_address.address_is_used(self.address):
            if dialog_replace_with_new_receiving_address(self.address):
                # find an address that is not used yet
                self.address = wallet_of_address.get_address().address.as_string()

    def format_address_field(self, *args):
        palette = QtGui.QPalette()
        background_color = None

        wallet_of_address = self.get_wallet_of_address(self.address)
        if wallet_of_address and wallet_of_address.is_my_address(self.address):
            self.setTabText(self.indexOf(self.tab), self.tr('Wallet "{id}"').format(id=wallet_of_address.id))

            if wallet_of_address.is_change(self.address):
                background_color = ColorScheme.YELLOW.as_color(background=True)
                palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
            else:
                background_color = ColorScheme.GREEN.as_color(background=True)
                palette.setColor(QtGui.QPalette.ColorRole.Base, background_color)
        else:
            palette = self.address_line_edit.input_field.style().standardPalette()
            self.setTabText(self.indexOf(self.tab), self.title)

        self.address_line_edit.input_field.setPalette(palette)
        self.address_line_edit.input_field.update()
        self.address_line_edit.update()
        logger.debug(
            f"{self.__class__.__name__} format_address_field for self.address {self.address}, background_color = {background_color.name() if background_color else None}"
        )
        self.setTabBarAutoHide(not self.tabText(self.indexOf(self.tab)) and not self.allow_edit)


class Recipients(QtWidgets.QWidget):
    signal_added_recipient = QtCore.pyqtSignal(RecipientGroupBox)
    signal_removed_recipient = QtCore.pyqtSignal(RecipientGroupBox)
    signal_clicked_send_max_button = QtCore.pyqtSignal(RecipientGroupBox)
    signal_amount_changed = QtCore.pyqtSignal(RecipientGroupBox)

    def __init__(self, signals: Signals, network: bdk.Network, allow_edit=True):
        super().__init__()
        self.signals = signals
        self.allow_edit = allow_edit
        self.network = network

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.recipient_list = InvisibleScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list.content_widget.setLayout(QtWidgets.QVBoxLayout())

        self.recipient_list.content_widget.layout().setContentsMargins(0, 0, 0, 0)  # Set all margins to zero
        self.recipient_list.content_widget.layout().setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QtWidgets.QPushButton("")
        self.add_recipient_button.setMaximumWidth(150)
        # self.add_recipient_button.setStyleSheet("background-color: green")
        self.add_recipient_button.clicked.connect(lambda: self.add_recipient())
        if allow_edit:
            self.recipient_list.content_widget.layout().addWidget(self.add_recipient_button)
            # self.main_layout.addWidget(self.add_recipient_button)
        self.updateUi()
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self):
        self.recipient_list.setToolTip(self.tr("Recipients"))
        self.add_recipient_button.setText(self.tr("+ Add Recipient"))

    def add_recipient(self, recipient: Recipient = None):
        if recipient is None:
            recipient = Recipient("", 0)
        recipient_box = RecipientGroupBox(
            self.signals,
            network=self.network,
            allow_edit=self.allow_edit,
            title="Recipient" if self.allow_edit else "",
        )
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        if recipient.checked_max_amount:
            recipient_box.send_max_button.click()
        if recipient.label:
            recipient_box.label = recipient.label
        recipient_box.signal_close.connect(self.remove_recipient_widget)
        recipient_box.amount_spin_box.valueChanged.connect(
            lambda *args: self.signal_amount_changed.emit(recipient_box)
        )

        # insert before the button position
        def insert_before_button(new_widget: QWidget):
            index = self.recipient_list.content_widget.layout().indexOf(self.add_recipient_button)
            if index >= 0:
                self.recipient_list.content_widget.layout().insertWidget(index, new_widget)
            else:
                self.recipient_list.content_widget.layout().addWidget(new_widget)

        insert_before_button(recipient_box)

        recipient_box.send_max_button.clicked.connect(
            lambda: self.signal_clicked_send_max_button.emit(recipient_box)
        )
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def remove_recipient_widget(self, recipient_box: RecipientGroupBox):
        recipient_box.close()
        recipient_box.setParent(None)
        self.recipient_list.content_widget.layout().removeWidget(recipient_box)
        self.signal_removed_recipient.emit(recipient_box)
        recipient_box.deleteLater()

    @property
    def recipients(self) -> List[Recipient]:
        return [
            Recipient(
                recipient_box.address,
                recipient_box.amount,
                recipient_box.label if recipient_box.label else None,
                checked_max_amount=recipient_box.send_max_button.isChecked(),
            )
            for recipient_box in self.get_recipient_group_boxes()
        ]

    @recipients.setter
    def recipients(self, recipient_list: List[Recipient]):
        # remove all old ones
        for recipient_box in self.get_recipient_group_boxes():
            self.remove_recipient_widget(recipient_box)

        for recipient in recipient_list:
            self.add_recipient(recipient)

    def get_recipient_group_boxes(self) -> List[RecipientGroupBox]:
        return self.recipient_list.findChildren(RecipientGroupBox)
