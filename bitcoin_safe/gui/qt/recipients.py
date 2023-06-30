import logging

from bitcoin_safe.pythonbdk_types import Recipient

logger = logging.getLogger(__name__)

from typing import List, Dict
import sys
from PySide2 import QtWidgets, QtCore, QtGui
from .util import ColorScheme
from ...signals import Signals, SignalFunction
from .spinbox import CustomDoubleSpinBox
from ...wallet import Wallet

from PySide2.QtWidgets import QMessageBox, QApplication
import sys
from .util import ShowCopyLineEdit


def dialog_replace_with_new_receiving_address(address):
    msg_box = QMessageBox()
    msg_box.setWindowTitle("Address Already Used")
    msg_box.setText(
        f"Address {address} was used already. Would you like to get a fresh receiving address?"
    )
    msg_box.setIcon(QMessageBox.Question)
    keep_button = msg_box.addButton("Keep address", QMessageBox.NoRole)
    ok_button = msg_box.addButton("OK", QMessageBox.YesRole)
    msg_box.exec_()

    if msg_box.clickedButton() == ok_button:
        return True
    elif msg_box.clickedButton() == keep_button:
        return False


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
        self.clicked.connect(self.close_groupbox)

    def close_groupbox(self):
        if self.parent():
            self.parent().signal_close.emit(self)


class RecipientGroupBox(QtWidgets.QGroupBox):
    signal_close = QtCore.Signal(QtWidgets.QGroupBox)
    signal_set_max_amount = QtCore.Signal(CustomDoubleSpinBox)

    def __init__(self, signals: Signals, allow_edit=True):
        super().__init__()
        self.signals = signals
        self.allow_edit = allow_edit

        self.close_button = CloseButton(self) if allow_edit else None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 10)  # Left, Top, Right, Bottom margins

        form_layout = QtWidgets.QFormLayout()
        self.address_line_edit = (
            QtWidgets.QLineEdit() if allow_edit else ShowCopyLineEdit()
        )
        self.address_line_edit.setPlaceholderText("Enter address here")
        self.label_line_edit = QtWidgets.QLineEdit()
        self.label_line_edit.setPlaceholderText("Enter label here")

        self.amount_layout = QtWidgets.QHBoxLayout()
        self.amount_spin_box = CustomDoubleSpinBox()
        self.send_max_button = QtWidgets.QPushButton("Send max")
        self.send_max_button.setCheckable(True)
        self.send_max_button.setMaximumWidth(80)
        self.send_max_button.clicked.connect(self.on_send_max_button_click)
        self.amount_layout.addWidget(self.amount_spin_box)
        if allow_edit:
            self.amount_layout.addWidget(self.send_max_button)

        form_layout.addRow("address:", self.address_line_edit)
        form_layout.addRow("label:", self.label_line_edit)
        form_layout.addRow("amount:", self.amount_layout)

        if not allow_edit:
            self.address_line_edit.setReadOnly(True)
            self.label_line_edit.setReadOnly(True)
            self.amount_spin_box.setReadOnly(True)

        layout.addLayout(form_layout)

        self.setFixedHeight(120)  # Set fixed height as required

        self.address_line_edit.textChanged.connect(self.format_address_field)
        self.address_line_edit.textChanged.connect(self.set_label_placeholder_text)
        self.signal_close.connect(self.close)

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
        wallets: List[Wallet] = self.signals.get_wallets().values()

        wallet_id = None
        label = ""
        for wallet in wallets:
            if self.address in wallet.get_addresses():
                wallet_id = wallet.id
                label = wallet.get_label_for_address(self.address)

        if wallet_id:
            self.label_line_edit.setPlaceholderText(label)
            if not self.allow_edit:
                self.label_line_edit.setText(label)
        else:
            self.label_line_edit.setPlaceholderText("Enter label for recipient address")

    def format_address_field(self, *args):
        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()

        def get_wallet_of_address(address) -> Wallet:
            for wallet in wallets_dict.values():
                if address in wallet.get_addresses():
                    return wallet

        palette = QtGui.QPalette()

        wallet_of_address = get_wallet_of_address(self.address)
        if wallet_of_address:
            if self.allow_edit and wallet_of_address.address_is_used(self.address):
                if dialog_replace_with_new_receiving_address(self.address):
                    # find an address that is not used yet

                    address_info = wallet_of_address.get_address()
                    self.address = address_info.address.as_string()

            if wallet_of_address.is_change(self.address):
                background_color = ColorScheme.YELLOW.as_color(background=True)
                palette.setColor(QtGui.QPalette.Base, background_color)
                self.setTitle(f'Recipient is wallet "{wallet_of_address.id}"')
            else:
                background_color = ColorScheme.GREEN.as_color(background=True)
                palette.setColor(QtGui.QPalette.Base, background_color)
                self.setTitle(f'Recipient is wallet "{wallet_of_address.id}"')
        else:
            palette = self.address_line_edit.style().standardPalette()
            self.setTitle("")

        self.address_line_edit.setPalette(palette)


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

        self.recipient_list = QtWidgets.QScrollArea()
        self.recipient_list.setWidgetResizable(True)
        self.recipient_list.setToolTip("Recipients")

        self.recipient_list_content = QtWidgets.QWidget()
        self.recipient_list_content_layout = QtWidgets.QVBoxLayout(
            self.recipient_list_content
        )
        self.recipient_list_content_layout.setAlignment(QtCore.Qt.AlignTop)
        self.recipient_list.setWidget(self.recipient_list_content)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QtWidgets.QPushButton("+ Add Recipient")
        self.add_recipient_button.setStyleSheet("background-color: green")
        self.add_recipient_button.clicked.connect(lambda: self.add_recipient())
        if allow_edit:
            self.main_layout.addWidget(self.add_recipient_button)

    def add_recipient(self, recipient: Recipient = None):
        if recipient is None:
            recipient = Recipient("", 0)
        recipient_box = RecipientGroupBox(self.signals, allow_edit=self.allow_edit)
        recipient_box.address = recipient.address
        recipient_box.amount = recipient.amount
        if recipient.label:
            recipient_box.label = recipient.label
        recipient_box.signal_close.connect(
            lambda: self.remove_recipient_widget(recipient)
        )
        self.recipient_list_content_layout.addWidget(recipient_box)

        recipient_box.send_max_button.clicked.connect(
            lambda: self.signal_clicked_send_max_button.emit(recipient_box)
        )
        self.signal_added_recipient.emit(recipient_box)
        return recipient_box

    def remove_recipient_widget(self, recipient):
        recipient.setParent(None)
        self.recipient_list_content_layout.removeWidget(recipient)
        recipient.deleteLater()

    @property
    def recipients(self) -> List[Recipient]:
        l = []
        for i in range(self.recipient_list_content_layout.count()):
            layout_item = self.recipient_list_content_layout.itemAt(i)
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
    def recipients(self, recipient_list: List[Dict[str, object]]):
        # remove all old ones
        for i in reversed(range(self.recipient_list_content_layout.count())):
            layout_item = self.recipient_list_content_layout.itemAt(i)
            recipient_box: RecipientGroupBox = layout_item.wid
            self.remove_recipient_widget(recipient_box)

        for i, recipient in enumerate(recipient_list):
            self.add_recipient(recipient)


if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    widget = Recipients()
    widget.show()

    sys.exit(app.exec_())
