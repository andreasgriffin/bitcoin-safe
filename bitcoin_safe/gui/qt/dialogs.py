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
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QAction,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.util import filename_clean

from .util import create_button_box

logger = logging.getLogger(__name__)


class PasswordQuestion(QDialog):
    def __init__(self, parent=None, label_text=None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        self.setWindowTitle(self.tr("Password Input"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self._layout = QVBoxLayout(self)

        label_text = label_text if label_text else self.tr("Please enter your password:")
        self.label = QLabel(label_text)
        self._layout.addWidget(self.label)

        self.password_input = QLineEdit(self)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._layout.addWidget(self.password_input)

        # Create show/hide icons
        self.icon_show = create_icon_from_unicode("👁", size=18)
        self.icon_hide = create_icon_from_unicode("🙈", size=18)

        # Toggle password visibility action
        self.toggle_action = QAction(self.icon_show, self.tr("Show Password"), self)
        self.toggle_action.setFont(QFont("Arial", 12))  # Ensure Unicode support
        self.toggle_action.triggered.connect(self.toggle_password_visibility)
        self.password_input.addAction(self.toggle_action, QLineEdit.ActionPosition.TrailingPosition)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self._layout.addWidget(self.button_box)

    def toggle_password_visibility(self):
        """Toggle password visibility."""
        if self.password_input.echoMode() == QLineEdit.EchoMode.Password:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.toggle_action.setIcon(self.icon_hide)
            self.toggle_action.setText(self.tr("Hide Password"))
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.toggle_action.setIcon(self.icon_show)
            self.toggle_action.setText(self.tr("Show Password"))

    def ask_for_password(self) -> str | None:
        """Ask for password."""
        self.password_input.clear()
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.password_input.text()
        return None


def create_icon_from_unicode(unicode_char, font_name="Arial", size=18) -> QIcon:
    # Create a QPixmap object and set its size
    """Create icon from unicode."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)

    # Create a QPainter object and draw text on the pixmap
    painter = QPainter(pixmap)
    painter.setFont(QFont(font_name, size))
    painter.drawText(0, 0, 32, 32, Qt.AlignmentFlag.AlignCenter, unicode_char)
    painter.end()

    # Create a QIcon object from the QPixmap
    return QIcon(pixmap)


class PasswordCreation(QDialog):
    def __init__(self, parent=None, window_title=None, label_text=None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        window_title = window_title if window_title else self.tr("Create Password")
        self.setWindowTitle(window_title)

        self._layout = QVBoxLayout(self)

        # First password input
        label_text = label_text if label_text else self.tr("Enter your password:")
        self.label1 = QLabel(label_text)
        self._layout.addWidget(self.label1)

        self.password_input1 = QLineEdit(self)
        self.password_input1.setEchoMode(QLineEdit.EchoMode.Password)
        self._layout.addWidget(self.password_input1)

        self.icon_show = create_icon_from_unicode("👁", size=18)
        self.icon_hide = create_icon_from_unicode("🙈", size=18)

        # Show password action for the first input
        self.show_password_action1 = QAction(create_icon_from_unicode("👁", size=18), self.tr("Show Password"))
        self.show_password_action1.setFont(
            QFont("Arial", 12)
        )  # Set the font to Arial to ensure Unicode support
        self.show_password_action1.triggered.connect(self.toggle_password_visibility)
        self.password_input1.addAction(self.show_password_action1, QLineEdit.ActionPosition.TrailingPosition)

        # Second password input
        self.label2 = QLabel(self.tr("Re-enter your password:"))
        self._layout.addWidget(self.label2)

        self.password_input2 = QLineEdit(self)
        self.password_input2.setEchoMode(QLineEdit.EchoMode.Password)
        self._layout.addWidget(self.password_input2)

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
        self.submit_button = QPushButton(self.tr("Submit"), self)
        self.submit_button.clicked.connect(self.verify_password)
        self._layout.addWidget(self.submit_button)

    def toggle_password_visibility(self) -> None:
        """Toggle password visibility."""
        new_visibility = self.password_input1.echoMode() == QLineEdit.EchoMode.Password

        self._set_password_visibility(self.password_input1, self.show_password_action1, new_visibility)
        self._set_password_visibility(self.password_input2, self.show_password_action1, new_visibility)

    def _set_password_visibility(self, password_input, show_password_action, visibility) -> None:
        """Set password visibility."""
        if visibility:
            password_input.setEchoMode(QLineEdit.EchoMode.Normal)
            show_password_action.setIcon(self.icon_hide)
            show_password_action.setToolTip(self.tr("Hide Password"))  # Set tooltip to "Hide Password"
        else:
            password_input.setEchoMode(QLineEdit.EchoMode.Password)
            show_password_action.setIcon(self.icon_show)
            show_password_action.setToolTip(self.tr("Show Password"))  # Set tooltip to "Show Password"

    def verify_password(self) -> None:
        # Check if passwords are identical
        """Verify password."""
        password1 = self.password_input1.text()
        password2 = self.password_input2.text()

        if password1 == password2:
            self.accept()
        else:
            # Show a message box if passwords don't match
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setText(self.tr("Passwords do not match!"))
            msg_box.setWindowTitle(self.tr("Error"))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()

    def get_password(self) -> str | None:
        """Get password."""
        if self.exec() == QDialog.DialogCode.Accepted:
            return self.password_input1.text()
        else:
            return None


class WalletIdDialog(QDialog):
    def __init__(
        self, wallet_dir: Path, parent=None, window_title=None, label_text=None, prefilled=None
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.wallet_dir = wallet_dir
        window_title = window_title if window_title else self.tr("Choose wallet name")
        self.setWindowTitle(window_title)

        # Create layout
        layout = QVBoxLayout(self)

        # Add name label and input field
        label_text = label_text if label_text else self.tr("Wallet name:")
        self.name_label = QLabel(label_text)
        self.name_input = QLineEdit(prefilled if prefilled else "")
        self.name_input.setPlaceholderText(self.tr("Type wallet name"))
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_input)

        # Add buttons
        self.buttonbox, self.buttons = create_button_box(self.check_wallet_existence, self.reject)
        layout.addWidget(self.buttonbox)

        # Set the layout
        self.name_input.setFocus()

    def check_wallet_existence(self) -> None:
        """Check wallet existence."""
        wallet_file = self.wallet_dir / self.filename
        if wallet_file.exists():
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("The wallet {filename} exists already.").format(filename=wallet_file),
            )
        elif not self.wallet_id:
            QMessageBox.warning(
                self,
                self.tr("Error"),
                self.tr("Please choose a wallet name"),
            )
        else:
            self.accept()  # Accept the dialog if wallet does not exist

    @property
    def wallet_id(self) -> str:
        """Wallet id."""
        return self.name_input.text()

    @property
    def filename(self) -> str:
        """Filename."""
        return filename_clean(self.wallet_id.lower())


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = PasswordCreation()
    password = dialog.get_password()
    if password:
        print("Password created successfully.")
    sys.exit(app.exec())
    quit()


def show_textedit_message(text: str, label_description: str, title: str):
    # Create a modal dialog
    """Show textedit message."""
    dialog = QDialog()
    dialog.setWindowTitle(title)

    # Set up the layout
    layout = QVBoxLayout(dialog)

    # Add a descriptive label
    label = QLabel(label_description)
    layout.addWidget(label)

    # Add a read-only text edit and populate it with text
    text_edit = QTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlainText(text)
    layout.addWidget(text_edit)

    # Create a button bar with an OK button
    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
    if ok_button:
        ok_button.setDefault(True)  # Preselect the OK button

    # Connect the OK button to close the dialog
    button_box.accepted.connect(dialog.accept)
    layout.addWidget(button_box)

    # Add a shortcut for the ESC key to close the dialog
    shortcut_close = QShortcut(QKeySequence("ESC"), dialog)
    shortcut_close.activated.connect(dialog.close)

    # Execute the dialog modally
    dialog.exec()
