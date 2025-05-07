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
import typing

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType, SignMessageRequest
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QLineEdit, QWidget

from bitcoin_safe.gui.qt.dialogs import show_textedit_message
from bitcoin_safe.gui.qt.export_data import QrToolButton
from bitcoin_safe.gui.qt.simple_qr_scanner import SimpleQrScanner
from bitcoin_safe.gui.qt.spinning_button import SpinningButton
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.keystore import KeyStoreImporterTypes
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.typestubs import TypedPyQtSignalNo

from ...signals import SignalsMin, TypedPyQtSignal
from .util import Message, do_copy

logger = logging.getLogger(__name__)


class SignMessage(QWidget):
    signal_signed_message: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore

    def __init__(
        self,
        bip32_path: str,
        network: bdk.Network,
        signals_min: SignalsMin,
        close_all_video_widgets: TypedPyQtSignalNo,
        threading_parent: ThreadingManager | None,
        parent: typing.Optional["QWidget"],
        grid_layout: QGridLayout | None = None,
    ) -> None:
        super().__init__(parent)
        self.network = network
        self.close_all_video_widgets = close_all_video_widgets
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self.grid_layout = grid_layout if grid_layout else QGridLayout(self)

        # sign message row
        self.bip32_path = bip32_path
        self.usb_gui = USBGui(network, allow_emulators_only_for_testnet_works=True)
        self.sign_edit = QLineEdit()
        self.sign_edit.setPlaceholderText(
            self.tr("Enter message to be signed at {bip32_path}").format(bip32_path=self.bip32_path)
        )

        self.sign_label = QLabel(self.tr("Sign message"))

        signal_end_hwi_blocker: TypedPyQtSignalNo = self.usb_gui.signal_end_hwi_blocker  # type: ignore
        self.sign_usb_button = SpinningButton(
            self.tr("Sign"),
            enable_signal=signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self,
        )
        self.sign_usb_button.setIcon(svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename))
        self.sign_usb_button.clicked.connect(self.on_sign_usb_message_button)

        # qr
        self.sign_qr_button = QrToolButton(
            data=self.get_data(),
            signals_min=signals_min,
            network=network,
            threading_parent=threading_parent,
            parent=self,
        )
        self.sign_qr_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sign_qr_button.setText(self.tr("Sign"))
        self.sign_qr_button.export_qr_widget.signal_close.connect(self.dialog_open_qr_scanner)
        self.sign_qr_button.export_qr_widget.signal_show.connect(self.on_show_export_widget)

        self.grid_layout.addWidget(self.sign_label, 1, 0)
        self.grid_layout.addWidget(self.sign_edit, 1, 1)
        self.grid_layout.addWidget(self.sign_usb_button, 1, 2)
        self.grid_layout.addWidget(self.sign_qr_button, 1, 3)

    def get_data(self) -> Data:
        return Data(
            SignMessageRequest(msg=self.sign_edit.text(), subpath=self.bip32_path, addr_fmt=""),
            data_type=DataType.SignMessageRequest,
            network=self.network,
        )

    def dialog_open_qr_scanner(self) -> None:
        self._qr_scanner = SimpleQrScanner(
            network=self.network,
            close_all_video_widgets=self.close_all_video_widgets,
            title=self.tr("Signed Message"),
        )

    def on_show_export_widget(self):
        self.sign_qr_button.set_data(self.get_data())

    def on_sign_usb_message_button(self):
        msg = self.sign_edit.text()
        if len(msg) < 2:
            Message(self.tr("Message too short."))
            self.usb_gui.signal_end_hwi_blocker.emit()
            return

        signed_message = self.usb_gui.sign_message(
            message=msg, bip32_path=self.bip32_path, slow_hwi_listing=True
        )

        if signed_message:
            title = self.tr("Signed Message")
            self.signal_signed_message.emit(signed_message)
            do_copy(signed_message, title=title)
            show_textedit_message(text=signed_message, label_description="", title=title)
