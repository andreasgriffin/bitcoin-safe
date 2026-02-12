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
from abc import abstractmethod
from typing import cast

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType, SignMessageRequest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.descriptors import get_address_bip32_path
from bitcoin_safe.gui.qt.address_edit import AddressEdit
from bitcoin_safe.gui.qt.dialogs import show_textedit_message
from bitcoin_safe.gui.qt.export_data import QrToolButton
from bitcoin_safe.gui.qt.simple_qr_scanner import SimpleQrScanner
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.i18n import translate
from bitcoin_safe.keystore import KeyStoreImporterTypes

from ...message_signature_verifyer import MessageSignatureVerifyer
from ...signals import SignalsMin, WalletFunctions
from .gpg_verify import verify_gpg_signed_message
from .util import Message, do_copy

logger = logging.getLogger(__name__)


def get_disclaimer_text():
    return translate(
        "pgp",
        'Security note: verification uses a built-in <a href="https://github.com/SecurityInnovation/PGPy">pgpy</a> '
        "library. It does not honor trust settings, revocations, or expiration times from your keyring. "
        'Please verify high value messages with <a href="https://gnupg.org/">GPG</a>.',
    )


class SignMessageBase(QWidget):
    signal_signed_message = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        network: bdk.Network,
        signals_min: SignalsMin,
        close_all_video_widgets: SignalProtocol[[]],
        loop_in_thread: LoopInThread,
        parent: QWidget | None,
        grid_layout: QGridLayout | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.network = network
        self.signals_min = signals_min
        self.close_all_video_widgets = close_all_video_widgets
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self.grid_layout = grid_layout if grid_layout else QGridLayout(self)

        self.usb_gui = USBGui(
            network, allow_emulators_only_for_testnet_works=True, loop_in_thread=loop_in_thread
        )

        self.sign_usb_button = SpinningButton(
            "",
            signal_stop_spinning=self.usb_gui.signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self,
            svg_tools=svg_tools,
        )
        self.sign_usb_button.setIcon(svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename))
        self.sign_usb_button.clicked.connect(self.on_sign_usb_message_button)

        # qr
        self.sign_qr_button = QrToolButton(
            data=self.get_data(),
            signals_min=signals_min,
            network=network,
            loop_in_thread=loop_in_thread,
            parent=self,
        )
        self.sign_qr_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sign_qr_button.setText("")
        self.sign_qr_button.export_qr_widget.signal_close.connect(self.dialog_open_qr_scanner)
        self.sign_qr_button.export_qr_widget.signal_show.connect(self.on_show_export_widget)

        self.signals_min.language_switch.connect(self.updateUI)
        self.updateUI()

    def get_data(self) -> Data:
        """Get data."""
        return Data(
            SignMessageRequest(msg=self.get_message(), subpath=self.get_bip32_path(), addr_fmt=""),
            data_type=DataType.SignMessageRequest,
            network=self.network,
        )

    @abstractmethod
    def get_message(self) -> str:
        """Return the message to be signed."""

    @abstractmethod
    def get_bip32_path(self) -> str:
        """Return the BIP32 path used for signing."""

    def dialog_open_qr_scanner(self) -> None:
        """Dialog open qr scanner."""
        self._qr_scanner = SimpleQrScanner(
            network=self.network,
            close_all_video_widgets=self.close_all_video_widgets,
            title=self.tr("Signed Message"),
            display_result=False,
        )
        self._qr_scanner.signal_raw_content.connect(self.on_raw_content)

    def on_raw_content(self, o: object):
        """On raw content."""
        self.signal_signed_message.emit(str(o))

    def on_show_export_widget(self):
        """On show export widget."""
        self.sign_qr_button.set_data(self.get_data())

    def on_sign_usb_message_button(self):
        """On sign usb message button."""
        msg = self.get_message()
        bip32_path = self.get_bip32_path()
        if len(msg) < 2:
            Message(self.tr("Message too short."), parent=self)
            self.usb_gui.signal_end_hwi_blocker.emit()
            return

        if not bip32_path:
            Message(
                self.tr("Could not determine the derivation path for the provided address."),
                parent=self,
            )
            self.usb_gui.signal_end_hwi_blocker.emit()
            return

        signed_message = self.usb_gui.sign_message(message=msg, bip32_path=bip32_path, slow_hwi_listing=True)

        if signed_message:
            self.signal_signed_message.emit(signed_message)

    def updateUI(self) -> None:
        """Update translatable strings."""

        self.sign_usb_button.setText(self.tr("Sign"))
        self.sign_qr_button.setText(self.tr("Sign"))


class SignMessage(SignMessageBase):
    def __init__(
        self,
        bip32_path: str,
        network: bdk.Network,
        signals_min: SignalsMin,
        close_all_video_widgets: SignalProtocol[[]],
        loop_in_thread: LoopInThread,
        parent: QWidget | None,
        grid_layout: QGridLayout | None = None,
    ) -> None:
        """Initialize instance."""

        self.bip32_path = bip32_path
        self.sign_edit = QLineEdit()
        self.sign_label = QLabel()

        self.sign_edit.setPlaceholderText("")
        super().__init__(
            network=network,
            signals_min=signals_min,
            close_all_video_widgets=close_all_video_widgets,
            loop_in_thread=loop_in_thread,
            parent=parent,
            grid_layout=grid_layout,
        )
        self.grid_layout.addWidget(self.sign_label, 1, 0)
        self.grid_layout.addWidget(self.sign_edit, 1, 1)
        self.grid_layout.addWidget(self.sign_usb_button, 1, 2)
        self.grid_layout.addWidget(self.sign_qr_button, 1, 3)

        self.updateUI()

    def get_bip32_path(self) -> str:
        """Return the fixed BIP32 path for this widget."""

        return self.bip32_path

    def get_message(self) -> str:
        """Return the message from the input field."""

        return self.sign_edit.text()

    def updateUI(self) -> None:
        """Update translatable strings."""

        super().updateUI()
        self.sign_label.setText(self.tr("Sign message"))
        self.sign_edit.setPlaceholderText(
            self.tr("Enter message to be signed at {bip32_path}").format(bip32_path=self.bip32_path)
        )


class _SignTab(SignMessageBase):
    def __init__(
        self,
        network: bdk.Network,
        signals_min: SignalsMin,
        close_all_video_widgets: SignalProtocol[[]],
        loop_in_thread: LoopInThread,
        wallet_functions: WalletFunctions,
        parent: QWidget | None = None,
    ) -> None:
        """Tab handling signing controls and QR/USB actions."""
        self.signals_min = signals_min
        self.sign_message_edit = QPlainTextEdit()
        self.message_label = QLabel()
        self.sign_button_box = QDialogButtonBox(Qt.Orientation.Horizontal)
        self.sign_address_edit = AddressEdit(
            network=network, wallet_functions=wallet_functions, ask_to_replace_if_was_used=False
        )
        self.wallet_functions = wallet_functions

        super().__init__(
            network=network,
            signals_min=signals_min,
            close_all_video_widgets=close_all_video_widgets,
            loop_in_thread=loop_in_thread,
            parent=parent,
        )
        self.sign_message_edit.setPlaceholderText("")

        self.grid_layout.addWidget(self.message_label, 0, 0)
        self.sign_message_edit.setPlaceholderText(self.tr("Enter message"))
        self.sign_address_edit.setPlaceholderText(self.tr("Address used to sign the message"))

        self.grid_layout.addWidget(QLabel(self.tr("Message")), 0, 0)
        self.grid_layout.addWidget(self.sign_message_edit, 0, 1, 1, 3)

        self.grid_layout.addWidget(QLabel(self.tr("Address")), 1, 0)
        self.grid_layout.addWidget(self.sign_address_edit, 1, 1, 1, 3)
        self.sign_button_box.addButton(self.sign_usb_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.sign_button_box.addButton(self.sign_qr_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.grid_layout.addWidget(self.sign_button_box, 2, 1, 1, 3)

        self.signals_min.language_switch.connect(self.updateUI)
        self.updateUI()

    def get_bip32_path(self) -> str:
        """Return the BIP32 path for the entered address if it is in an open wallet."""

        address = self.sign_address_edit.text().strip()
        if not address:
            return ""

        qt_wallets = self.wallet_functions.get_qt_wallets.emit()
        for qt_wallet in qt_wallets.values():
            if address_info := qt_wallet.wallet.get_address_info_min(address):
                return get_address_bip32_path(
                    descriptor_str=str(qt_wallet.wallet.multipath_descriptor),
                    kind=address_info.keychain,
                    index=address_info.index,
                )

        return ""

    def get_message(self) -> str:
        """Return the user-entered message."""

        return self.sign_message_edit.toPlainText()

    def updateUI(self) -> None:
        """Update translatable strings."""

        super().updateUI()
        self.message_label.setText(self.tr("Message"))
        self.sign_message_edit.setPlaceholderText(self.tr("Enter message"))


class VerifyGpgMessageTab(QWidget):
    signal_verify_gpg_message = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(self, signals_min: SignalsMin, parent: QWidget | None = None) -> None:
        """Tab handling verification of ASCII-armored PGP signed messages."""
        super().__init__(parent)
        self.signals_min = signals_min
        self.signed_message_edit = QPlainTextEdit()
        self.verify_button = QPushButton()
        self.disclaimer_label = QLabel()
        self.disclaimer_label.setWordWrap(True)
        self.disclaimer_label.setTextFormat(Qt.TextFormat.RichText)
        self.disclaimer_label.setOpenExternalLinks(True)

        layout = QGridLayout(self)
        layout.addWidget(QLabel(self.tr("Signed message")), 0, 0)
        layout.addWidget(self.signed_message_edit, 0, 1, 1, 3)
        button_box = QDialogButtonBox(Qt.Orientation.Horizontal)
        button_box.addButton(self.verify_button, QDialogButtonBox.ButtonRole.ActionRole)
        layout.addWidget(button_box, 1, 1, 1, 3)
        layout.addWidget(self.disclaimer_label, 2, 1, 1, 3)

        self.verify_button.clicked.connect(self._emit_verify_request)
        self.signals_min.language_switch.connect(self.updateUI)
        self.updateUI()

    def _emit_verify_request(self) -> None:
        """Emit the verify request to the parent widget."""
        self.signal_verify_gpg_message.emit(self.signed_message_edit.toPlainText())

    def updateUI(self) -> None:
        """Update translatable strings."""
        self.verify_button.setText(self.tr("Verify"))
        self.signed_message_edit.setPlaceholderText(
            """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA256

Example message
-----BEGIN PGP SIGNATURE-----
...
-----END PGP SIGNATURE-----"""
        )
        self.disclaimer_label.setText(get_disclaimer_text())


class SignAndVerifyMessage(QWidget):
    def __init__(
        self,
        network: bdk.Network,
        signals_min: SignalsMin,
        close_all_video_widgets: SignalProtocol[[]],
        loop_in_thread: LoopInThread,
        wallet_functions: WalletFunctions,
        parent: QWidget | None = None,
    ) -> None:
        """Widget that combines message signing and verification."""
        super().__init__(parent)
        self.signals_min = signals_min
        self.setWindowIcon(svg_tools.get_QIcon("material-symbols--signature.svg"))

        self.verify_message_edit = QPlainTextEdit()
        self.verify_address_edit = AddressEdit(
            network=network, wallet_functions=wallet_functions, ask_to_replace_if_was_used=False
        )
        self.verify_signature_edit = QLineEdit()
        self.armored_message_edit = QPlainTextEdit()
        self.result_label = QLabel()
        self.result_label.setTextFormat(Qt.TextFormat.RichText)
        self.result_label.setOpenExternalLinks(True)
        self.verify_button = QPushButton()
        self.verify_armored_button = QPushButton()
        self.verify_message_label = QLabel()
        self.verify_address_label = QLabel()
        self.verify_signature_label = QLabel()
        self.verify_button_box = QDialogButtonBox(Qt.Orientation.Horizontal)

        self.sign_tab = _SignTab(
            network=network,
            signals_min=signals_min,
            close_all_video_widgets=close_all_video_widgets,
            loop_in_thread=loop_in_thread,
            wallet_functions=wallet_functions,
            parent=self,
        )
        self.verify_gpg_tab = VerifyGpgMessageTab(signals_min=signals_min, parent=self)

        self.result_label.setWordWrap(True)
        self.verify_button.clicked.connect(self.on_verify_clicked)
        self.verify_armored_button.clicked.connect(self.on_verify_armored_clicked)
        self.verify_gpg_tab.signal_verify_gpg_message.connect(self.on_verify_gpg_clicked)
        self.sign_tab.signal_signed_message.connect(self.on_signed_message)

        self.verify_tab = QWidget()
        verify_layout = QGridLayout(self.verify_tab)
        verify_layout.addWidget(self.verify_message_label, 0, 0)
        verify_layout.addWidget(self.verify_message_edit, 0, 1, 1, 3)
        verify_layout.addWidget(self.verify_address_label, 1, 0)
        verify_layout.addWidget(self.verify_address_edit, 1, 1, 1, 3)
        verify_layout.addWidget(self.verify_signature_label, 2, 0)
        verify_layout.addWidget(self.verify_signature_edit, 2, 1, 1, 3)
        self.verify_button_box.addButton(self.verify_button, QDialogButtonBox.ButtonRole.ActionRole)
        verify_layout.addWidget(self.verify_button_box, 3, 1, 1, 3)

        self.verify_armored_tab = QWidget()
        verify_armored_layout = QVBoxLayout(self.verify_armored_tab)
        verify_armored_layout.addWidget(self.armored_message_edit)
        verify_armored_button_box = QDialogButtonBox(Qt.Orientation.Horizontal)
        verify_armored_button_box.addButton(
            self.verify_armored_button, QDialogButtonBox.ButtonRole.ActionRole
        )
        verify_armored_layout.addWidget(verify_armored_button_box)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.sign_tab, "")
        self.tabs.addTab(self.verify_tab, "")
        self.tabs.addTab(self.verify_armored_tab, "")
        self.tabs.addTab(self.verify_gpg_tab, "")

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)
        main_layout.addWidget(self.result_label)

        self.signals_min.language_switch.connect(self.updateUI)
        self.updateUI()

    def on_verify_clicked(self) -> None:
        """Verify the provided signature for the given address and message."""

        address = self.verify_address_edit.text().strip()
        signature = self.verify_signature_edit.text().strip()
        message = self.verify_message_edit.toPlainText()

        if not address or not signature or not message:
            self._set_result(
                self.tr("Address, message and signature are required for verification."),
                success=False,
            )
            return

        verifyer = MessageSignatureVerifyer()
        result = verifyer.verify_message(address, message, signature)

        if result.match:
            warning_text = "\n".join(result.warnings)
            body = self.tr("Signature matches the provided address.")
            if warning_text:
                body += f"\n{warning_text}"
            self._set_result(body, success=True)
            return

        error_message = result.error or self.tr("Verification failed.")
        warnings = "\n".join(result.warnings)
        if warnings:
            error_message += f"\n{warnings}"
        self._set_result(error_message, success=False)

    def on_signed_message(self, signed_message: str) -> None:
        """Populate the signature field instead of opening a dialog."""

        title = self.tr("Signed Message")
        do_copy(signed_message, title=title)
        show_textedit_message(text=signed_message, label_description="", title=title)

    def on_verify_armored_clicked(self) -> None:
        """Verify a BIP-0137 ASCII-armored message block."""

        armored_text = self.armored_message_edit.toPlainText()
        if not armored_text.strip():
            self._set_result(self.tr("ASCII armored message is required."), success=False)
            return

        verifyer = MessageSignatureVerifyer()
        result = verifyer.verify_message_asciguarded(armored_text)

        if result.match:
            warning_text = "\n".join(result.warnings)
            body = self.tr("Armored message is valid.")
            if warning_text:
                body += f"\n{warning_text}"
            self._set_result(body, success=True)
            return

        error_message = result.error or self.tr("Verification failed.")
        warnings = "\n".join(result.warnings)
        if warnings:
            error_message += f"\n{warnings}"
        self._set_result(error_message, success=False)

    def on_verify_gpg_clicked(self, signed_message: str) -> None:
        """Verify an ASCII-armored PGP signed message."""

        result = verify_gpg_signed_message(
            signed_message,
            parent=self,
        )
        self._set_result(result.message, success=result.success)

    def _set_result(self, message: str, *, success: bool) -> None:
        """Display the verification outcome."""

        self.result_label.setText(message)
        color = "green" if success else "red"
        self.result_label.setStyleSheet(f"color: {color};")

    def updateUI(self) -> None:
        """Update translatable strings."""

        self.verify_message_label.setText(self.tr("Message"))
        self.verify_address_label.setText(self.tr("Address"))
        self.verify_signature_label.setText(self.tr("Signature"))
        self.verify_message_edit.setPlaceholderText(self.tr("Enter message"))
        self.verify_address_edit.setPlaceholderText(self.tr("Address used to sign the message"))
        self.verify_signature_edit.setPlaceholderText(self.tr("Base64 signature"))
        self.armored_message_edit.setPlaceholderText(
            """-----BEGIN BITCOIN SIGNED MESSAGE-----
test
-----BEGIN BITCOIN SIGNATURE-----
bcrt1qznp9gqwteevnnyf8gsq5x7vjkd67ccmx0f9j55
KHtJPcAxgXox0oi6N9u+E3Bt1aWPo9DriQoCcnd/9c/0BxWozkTte2FQ+R20+ZTKQWUW17rGjNBww9qq8XX5usI=
-----END BITCOIN SIGNATURE-----
"""
        )
        self.verify_button.setText(self.tr("Verify"))
        self.verify_armored_button.setText(self.tr("Verify"))
        self.tabs.setTabText(0, self.tr("Sign"))
        self.tabs.setTabText(1, self.tr("Verify"))
        self.tabs.setTabText(2, self.tr("Verify ASCII Armour"))
        self.tabs.setTabText(3, self.tr("Verify PGP"))
        self.sign_tab.updateUI()
        self.verify_gpg_tab.updateUI()
