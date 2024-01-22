import logging

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit

from ...invisible_scroll_area import InvisibleScrollArea
from ...pythonbdk_types import Recipient

logger = logging.getLogger(__name__)

from typing import List, Optional

import bdkpython as bdk
from bitcoin_qrreader import bitcoin_qr
from PySide2 import QtCore, QtGui, QtWidgets
from PySide2.QtWidgets import QMessageBox

from ...signals import Signals
from ...util import unit_str
from ...wallet import Wallet, get_wallets
from .dialogs import question_dialog
from .spinbox import BTCSpinBox
from .util import ColorScheme


def dialog_replace_with_new_receiving_address(address):
    return question_dialog(
        text=f"Address {address} was used already. Would you like to get a fresh receiving address?",
        title="Address Already Used",
        buttons=QMessageBox.No | QMessageBox.Yes,
    )


class CloseButton(QtWidgets.QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            """
            background-color: red;
            """
        )
        self.setText("X")
        self.setFixedSize(15, 15)  # adjust size as needed


class RecipientGroupBox(QtWidgets.QGroupBox):
    signal_close = QtCore.Signal(QtWidgets.QGroupBox)
    signal_set_max_amount = QtCore.Signal(BTCSpinBox)

    def __init__(self, signals: Signals, allow_edit=True):
        super().__init__()

        self.signals = signals
        self.allow_edit = allow_edit

        self.close_button = CloseButton(self)
        self.close_button.setHidden(not allow_edit)
        self.close_button.clicked.connect(lambda: self.signal_close.emit(self))

        layout = QtWidgets.QHBoxLayout(self)
        current_margins = self.layout().contentsMargins()

        layout.setContentsMargins(
            current_margins.left(),
            current_margins.top() * 2,
            current_margins.right(),
            current_margins.bottom(),
        )  # Left, Top, Right, Bottom margins

        form_layout = QtWidgets.QFormLayout()

        def on_handle_input(data: bitcoin_qr.Data, parent: QtWidgets.QWidget):
            if data.data_type == bitcoin_qr.DataType.Bip21:
                if data.data.get("address"):
                    self.address_line_edit.setText(data.data.get("address"))
                if data.data.get("amount"):
                    self.amount_spin_box.setValue(data.data.get("amount"))
                if data.data.get("label"):
                    self.label_line_edit.setText(data.data.get("label"))

        self.address_line_edit = ButtonEdit()
        if allow_edit:
            self.address_line_edit.add_qr_input_from_camera_button(custom_handle_input=on_handle_input)
        else:
            self.address_line_edit.add_copy_button()
            self.address_line_edit.setReadOnly(True)

        self.address_line_edit.setPlaceholderText("Enter address here")

        def is_valid():
            if not self.address_line_edit.text():
                # if it is empty, show no error
                return True
            try:
                bdk_address = bdk.Address(self.address_line_edit.text().strip())
                assert bdk_address.network() == self.signals.get_network.emit()
                return True
            except:
                return False

        self.address_line_edit.set_validator(is_valid)
        self.label_line_edit = QtWidgets.QLineEdit()
        self.label_line_edit.setPlaceholderText("Enter label here")

        self.amount_layout = QtWidgets.QHBoxLayout()
        self.amount_spin_box = BTCSpinBox(self.signals.get_network())
        self.label_unit = QtWidgets.QLabel(unit_str(self.signals.get_network()))
        self.send_max_button = QtWidgets.QPushButton("Send max")
        self.send_max_button.setCheckable(True)
        self.send_max_button.setMaximumWidth(80)
        self.send_max_button.clicked.connect(self.on_send_max_button_click)
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.label_unit)
        if allow_edit:
            self.amount_layout.addWidget(self.send_max_button)

        form_layout.addRow("Address", self.address_line_edit)
        form_layout.addRow("Label", self.label_line_edit)
        form_layout.addRow("Amount", self.amount_layout)

        if not allow_edit:
            self.address_line_edit.setReadOnly(True)
            self.label_line_edit.setReadOnly(True)
            self.amount_spin_box.setReadOnly(True)

        layout.addLayout(form_layout)

        self.setFixedHeight(120)  # Set fixed height as required

        self.address_line_edit.input_field.textChanged.connect(self.format_address_field)
        self.address_line_edit.input_field.textChanged.connect(self.set_label_placeholder_text)
        self.address_line_edit.input_field.textChanged.connect(self.check_if_used)

        self.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid rgba(128, 128, 128, 0.7); /* Border styling */
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px; /* Horizontal position of the title */
                top: 3px; /* Move the title a few pixels down */
                background-color: transparent; /* Make the title background transparent */
            }            
        """
        )

    def on_send_max_button_click(self):
        # self.amount_spin_box.setValue(0)
        self.amount_spin_box.setEnabled(not self.send_max_button.isChecked())
        self.signal_set_max_amount.emit(self.amount_spin_box)

    def resizeEvent(self, event):
        if self.close_button:
            self.close_button.move(self.width() - self.close_button.width(), 0)

    @property
    def address(self):
        return self.address_line_edit.text().strip()

    @address.setter
    def address(self, value):
        self.address_line_edit.setText(value)

    @property
    def label(self):
        return self.label_line_edit.text().strip()

    @label.setter
    def label(self, value):
        self.label_line_edit.setText(value)

    @property
    def amount(self):
        return self.amount_spin_box.value()

    @amount.setter
    def amount(self, value):
        self.amount_spin_box.setValue(value)

    @property
    def enabled(self):
        return not self.address_line_edit.isReadOnly()

    @enabled.setter
    def enabled(self, state):
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
            self.label_line_edit.setPlaceholderText("Enter label for recipient address")

    def get_wallet_of_address(self, address) -> Optional[Wallet]:
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

        wallet_of_address = self.get_wallet_of_address(self.address)
        if wallet_of_address and wallet_of_address.is_my_address(self.address):
            self.setTitle(f'Recipient is wallet "{wallet_of_address.id}"')

            if wallet_of_address.is_change(self.address):
                background_color = ColorScheme.YELLOW.as_color(background=True)
                palette.setColor(QtGui.QPalette.Base, background_color)
            else:
                background_color = ColorScheme.GREEN.as_color(background=True)
                palette.setColor(QtGui.QPalette.Base, background_color)
        else:
            palette = self.address_line_edit.input_field.style().standardPalette()
            self.setTitle("")

        self.address_line_edit.input_field.setPalette(palette)
        self.update()


class Recipients(QtWidgets.QWidget):
    signal_added_recipient = QtCore.Signal(RecipientGroupBox)
    signal_clicked_send_max_button = QtCore.Signal(RecipientGroupBox)

    def __init__(self, signals: Signals, allow_edit=True):
        super().__init__()
        self.signals = signals
        self.allow_edit = allow_edit

        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignTop)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.recipient_list = InvisibleScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list.setToolTip("Recipients")
        self.recipient_list_content_layout = QtWidgets.QVBoxLayout(self.recipient_list.content_widget)

        self.recipient_list_content_layout.setContentsMargins(0, 0, 0, 0)  # Set all margins to zero
        self.recipient_list_content_layout.setAlignment(QtCore.Qt.AlignTop)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QtWidgets.QPushButton("+ Add Recipient")
        self.add_recipient_button.setStyleSheet("background-color: green")
        self.add_recipient_button.clicked.connect(lambda: self.add_recipient())
        if allow_edit:
            self.recipient_list_content_layout.addWidget(self.add_recipient_button)
            # self.main_layout.addWidget(self.add_recipient_button)

    def add_recipient(self, recipient: Recipient = None):

        if recipient is None:
            recipient = Recipient("", 0)
        recipient_box = RecipientGroupBox(self.signals, allow_edit=self.allow_edit)
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        if recipient.checked_max_amount:
            recipient_box.send_max_button.click()
        if recipient.label:
            recipient_box.label = recipient.label
        recipient_box.signal_close.connect(self.remove_recipient_widget)

        # insert before the button position
        def insert_before_button(new_widget):
            index = self.recipient_list_content_layout.indexOf(self.add_recipient_button)
            if index >= 0:
                self.recipient_list_content_layout.insertWidget(index, new_widget)
            else:
                self.recipient_list_content_layout.addWidget(new_widget)

        insert_before_button(recipient_box)

        recipient_box.send_max_button.clicked.connect(
            lambda: self.signal_clicked_send_max_button.emit(recipient_box)
        )
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def remove_recipient_widget(self, recipient_box):
        recipient_box.close()
        recipient_box.setParent(None)
        self.recipient_list_content_layout.removeWidget(recipient_box)
        recipient_box.deleteLater()

    @property
    def recipients(self) -> List[Recipient]:
        l = []
        for i in range(self.recipient_list_content_layout.count()):
            layout_item = self.recipient_list_content_layout.itemAt(i)
            if not isinstance(layout_item.wid, RecipientGroupBox):
                continue
            recipient_box: RecipientGroupBox = layout_item.wid
            l.append(
                Recipient(
                    recipient_box.address,
                    recipient_box.amount,
                    recipient_box.label if recipient_box.label else None,
                    checked_max_amount=recipient_box.send_max_button.isChecked(),
                )
            )
        return l

    @recipients.setter
    def recipients(self, recipient_list: List[Recipient]):
        # remove all old ones
        for i in reversed(range(self.recipient_list_content_layout.count())):
            layout_item = self.recipient_list_content_layout.itemAt(i)
            recipient_box: RecipientGroupBox = layout_item.wid
            if not isinstance(layout_item.wid, RecipientGroupBox):
                continue
            self.remove_recipient_widget(recipient_box)

        for i, recipient in enumerate(recipient_list):
            self.add_recipient(recipient)
