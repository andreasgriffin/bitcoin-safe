import sys
from PySide2 import QtWidgets, QtCore, QtGui
from ...wallet import Wallet
from .util import ColorScheme


class CloseButton(QtWidgets.QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            background-color: red;
            """)
        self.setText("X")
        self.setFixedSize(15, 15)  # adjust size as needed
        self.clicked.connect(self.close_groupbox)

    def close_groupbox(self):
        if self.parent():
            self.parent().close_signal.emit(self)


class RecipientGroupBox(QtWidgets.QGroupBox):
    close_signal = QtCore.Signal(QtWidgets.QGroupBox)

    def __init__(self, get_receiving_addresses, get_change_addresses):
        super().__init__()
        self.get_receiving_addresses = get_receiving_addresses
        self.get_change_addresses = get_change_addresses
        
        
        self.close_button = CloseButton(self)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 10)  # Left, Top, Right, Bottom margins

        form_layout = QtWidgets.QFormLayout()
        self.address_line_edit = QtWidgets.QLineEdit()
        self.address_line_edit.setPlaceholderText("Enter address here")
        self.label_line_edit = QtWidgets.QLineEdit()
        self.label_line_edit.setPlaceholderText("Enter label here")

        self.amount_layout = QtWidgets.QHBoxLayout()
        self.amount_spin_box = QtWidgets.QSpinBox()
        self.amount_spin_box.setRange(0, 999999999) # Define range as required
        self.send_max_button = QtWidgets.QPushButton("Send max")
        self.send_max_button.setMaximumWidth(80)
        self.amount_layout.addWidget(self.amount_spin_box)
        self.amount_layout.addWidget(self.send_max_button)

        form_layout.addRow("address:", self.address_line_edit)
        form_layout.addRow("label:", self.label_line_edit)
        form_layout.addRow("amount:", self.amount_layout)
        layout.addLayout(form_layout)

        self.setFixedHeight(120) # Set fixed height as required

        self.address_line_edit.textChanged.connect(self.format_address_field)
        self.close_signal.connect(self.close)

    def resizeEvent(self, event):
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

    def format_address_field(self, *args):
        palette = QtGui.QPalette() 
        if self.address in self.get_receiving_addresses():
            background_color = ColorScheme.GREEN.as_color(background=True)  
            palette.setColor(QtGui.QPalette.Base, background_color) 
        elif self.address in self.get_change_addresses():
            background_color = ColorScheme.YELLOW.as_color(background=True)  
            palette.setColor(QtGui.QPalette.Base, background_color) 
        else:
            palette = self.address_line_edit.style().standardPalette()
            
        self.address_line_edit.setPalette(palette)


class Recipients(QtWidgets.QWidget):
    def __init__(self, get_receiving_addresses, get_change_addresses):
        super().__init__()
        self.get_receiving_addresses = get_receiving_addresses
        self.get_change_addresses = get_change_addresses
        
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setAlignment(QtCore.Qt.AlignTop)

        self.recipient_list = QtWidgets.QScrollArea()
        self.recipient_list.setWidgetResizable(True)

        self.recipient_list_content = QtWidgets.QWidget()
        self.recipient_list_content_layout = QtWidgets.QVBoxLayout(self.recipient_list_content)
        self.recipient_list_content_layout.setAlignment(QtCore.Qt.AlignTop)
        self.recipient_list.setWidget(self.recipient_list_content)

        self.main_layout.addWidget(self.recipient_list)

        self.add_recipient_button = QtWidgets.QPushButton("+ Add Recipient")
        self.add_recipient_button.setStyleSheet("background-color: green")
        self.add_recipient_button.clicked.connect(self.add_recipient)
        self.main_layout.addWidget(self.add_recipient_button)

    def add_recipient(self):
        recipient = RecipientGroupBox(self.get_receiving_addresses, self.get_change_addresses)
        recipient.close_signal.connect(lambda: self.remove_recipient(recipient))
        self.recipient_list_content_layout.addWidget(recipient)


    def remove_recipient(self, recipient):
        recipient.setParent(None)
        self.recipient_list_content_layout.removeWidget(recipient)
        recipient.deleteLater()

    @property
    def recipients(self):
        l = []
        for i in range(self.recipient_list_content_layout.count()):
            layout_item = self.recipient_list_content_layout.itemAt(i)
            recipient:RecipientGroupBox = layout_item.wid
            l.append({'address':recipient.address, 'label':recipient.label, 'amount':recipient.amount})
        return l


if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    widget = Recipients()
    widget.show()

    sys.exit(app.exec_())
