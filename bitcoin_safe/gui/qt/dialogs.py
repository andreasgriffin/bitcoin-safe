import logging
import os

from .util import create_button_box

logger = logging.getLogger(__name__)
from PySide2.QtGui import QFont, QIcon
from PySide2.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...wallet import filename_clean


def question_dialog(text="", title="", buttons=QMessageBox.Cancel | QMessageBox.Yes):
    msg_box = QMessageBox()
    msg_box.setWindowTitle(title)
    msg_box.setText(text)
    msg_box.setIcon(QMessageBox.Question)

    # Set the QDialogButtonBox as the standard button in the message box
    msg_box.setStandardButtons(buttons)

    # Execute the message box
    ret = msg_box.exec_()

    # Check which button was clicked
    if ret == QMessageBox.Yes:
        return True
    elif ret == QMessageBox.No:
        return False


class PasswordQuestion(QDialog):
    def __init__(self, parent=None):
        super(PasswordQuestion, self).__init__(parent)

        self.setWindowTitle("Password Input")

        self.layout = QVBoxLayout(self)

        self.label = QLabel("Please enter your password:")
        self.layout.addWidget(self.label)

        self.password_input = QLineEdit(self)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password_input)

        self.submit_button = QPushButton("Submit", self)
        self.submit_button.clicked.connect(self.accept)
        self.layout.addWidget(self.submit_button)

    def ask_for_password(self):
        if self.exec_() == QDialog.Accepted:
            return self.password_input.text()
        else:
            return None


from PySide2.QtCore import Qt
from PySide2.QtGui import QFont, QIcon, QPainter, QPixmap


def create_icon_from_unicode(unicode_char, font_name="Arial", size=18):
    # Create a QPixmap object and set its size
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)

    # Create a QPainter object and draw text on the pixmap
    painter = QPainter(pixmap)
    painter.setFont(QFont(font_name, size))
    painter.drawText(0, 0, 32, 32, Qt.AlignCenter, unicode_char)
    painter.end()

    # Create a QIcon object from the QPixmap
    return QIcon(pixmap)


class PasswordCreation(QDialog):
    def __init__(self, parent=None):
        super(PasswordCreation, self).__init__(parent)

        self.setWindowTitle("Create Password")

        self.layout = QVBoxLayout(self)

        # First password input
        self.label1 = QLabel("Enter your password:")
        self.layout.addWidget(self.label1)

        self.password_input1 = QLineEdit(self)
        self.password_input1.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password_input1)

        self.icon_show = create_icon_from_unicode("👁", size=18)
        self.icon_hide = create_icon_from_unicode("🙈", size=18)

        # Show password action for the first input
        self.show_password_action1 = QAction(create_icon_from_unicode("👁", size=18), "Show Password")
        self.show_password_action1.setFont(
            QFont("Arial", 12)
        )  # Set the font to Arial to ensure Unicode support
        self.show_password_action1.triggered.connect(lambda: self.toggle_password_visibility())
        self.password_input1.addAction(self.show_password_action1, QLineEdit.TrailingPosition)

        # Second password input
        self.label2 = QLabel("Re-enter your password:")
        self.layout.addWidget(self.label2)

        self.password_input2 = QLineEdit(self)
        self.password_input2.setEchoMode(QLineEdit.Password)
        self.layout.addWidget(self.password_input2)

        # Show password action for the second input
        # self.show_password_action2 = QAction(self.icon_show, "Show Password")
        # self.show_password_action2.triggered.connect(
        #     lambda: self.toggle_password_visibility(
        #         self.password_input2, self.show_password_action2
        #     )
        # )
        # self.password_input2.addAction(
        #     self.show_password_action2, QLineEdit.TrailingPosition
        # )

        # Submit button
        self.submit_button = QPushButton("Submit", self)
        self.submit_button.clicked.connect(self.verify_password)
        self.layout.addWidget(self.submit_button)

    def toggle_password_visibility(self):
        new_visibility = self.password_input1.echoMode() == QLineEdit.Password

        self._set_password_visibility(self.password_input1, self.show_password_action1, new_visibility)
        self._set_password_visibility(self.password_input2, self.show_password_action1, new_visibility)

    def _set_password_visibility(self, password_input, show_password_action, visibility):
        if visibility:
            password_input.setEchoMode(QLineEdit.Normal)
            show_password_action.setIcon(self.icon_hide)
            show_password_action.setToolTip("Hide Password")  # Set tooltip to "Hide Password"
        else:
            password_input.setEchoMode(QLineEdit.Password)
            show_password_action.setIcon(self.icon_show)
            show_password_action.setToolTip("Show Password")  # Set tooltip to "Show Password"

    def verify_password(self):
        # Check if passwords are identical
        password1 = self.password_input1.text()
        password2 = self.password_input2.text()

        if password1 == password2:
            self.accept()
        else:
            # Show a message box if passwords don't match
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setText("Passwords do not match!")
            msg_box.setWindowTitle("Error")
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec_()

    def get_password(self):
        if self.exec_() == QDialog.Accepted:
            return self.password_input1.text()
        else:
            return None


class WalletIdDialog(QDialog):
    def __init__(self, wallet_dir, parent=None):
        super().__init__(parent)
        self.wallet_dir = wallet_dir
        self.setWindowTitle("Create Wallet")

        # Create layout
        layout = QVBoxLayout()

        # Add name label and input field
        self.name_label = QLabel("Wallet Name:")
        self.name_input = QLineEdit()
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_input)

        # Add buttons
        layout.addWidget(create_button_box(self.check_wallet_existence, self.reject))

        # Set the layout
        self.setLayout(layout)

    def check_wallet_existence(self):
        chosen_wallet_id = self.name_input.text()

        wallet_file = os.path.join(self.wallet_dir, filename_clean(chosen_wallet_id))
        if os.path.exists(wallet_file):
            QMessageBox.warning(self, "Error", "A wallet with the same name already exists.")
        else:
            self.accept()  # Accept the dialog if wallet does not exist


if __name__ == "__main__":
    import sys

    from PySide2.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = PasswordCreation()
    password = dialog.get_password()
    if password:
        print(f"Password created: {password}")
    sys.exit(app.exec_())
    quit()
