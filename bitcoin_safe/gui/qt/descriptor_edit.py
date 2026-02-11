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

import bdkpython as bdk
from bitcoin_qr_tools.data import ConverterMultisigWalletExport, Data, DataType
from bitcoin_qr_tools.gui.bitcoin_video_widget import (
    BitcoinVideoWidget,
    DecodingException,
)
from bitcoin_qr_tools.multipath_descriptor import (
    convert_to_multipath_descriptor,
    is_valid_descriptor,
)
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import QLocale, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QShowEvent
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.descriptors import from_multisig_wallet_export
from bitcoin_safe.execute_config import DEFAULT_LANG_CODE
from bitcoin_safe.gui.qt.analyzers import DescriptorAnalyzer
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit
from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.gui.qt.register_multisig import RegisterMultisigInteractionWidget
from bitcoin_safe.gui.qt.util import Message, MessageType, center_on_screen, do_copy, svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.signals import SignalsMin, WalletFunctions
from bitcoin_safe.wallet import Wallet

from ...pdfrecovery import make_and_open_pdf
from .util import set_no_margins

logger = logging.getLogger(__name__)


class DescriptorExport(QDialog):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        descriptor: bdk.Descriptor,
        signals_min: SignalsMin,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
        parent=None,
        wallet_id: str = "MultiSig",
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export Descriptor"))

        self.descriptor = descriptor
        self.data = Data.from_descriptor(descriptor, network=network)

        self.export_widget = ExportDataSimple(
            data=self.data,
            signals_min=signals_min,
            enable_clipboard=False,
            enable_usb=False,
            network=network,
            loop_in_thread=loop_in_thread,
            wallet_name=wallet_id,
        )
        self.export_widget.set_minimum_size_as_floating_window()

        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.export_widget)

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)


class DescriptorInputField(AnalyzerTextEdit):
    def sizeHint(self) -> QSize:
        """SizeHint."""
        size = super().sizeHint()
        size.setHeight(30)
        return size


class DescriptorEdit(QWidget):
    signal_descriptor_change = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread | None,
        wallet: Wallet | None = None,
        signal_update: SignalProtocol[[]] | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.edit = ButtonEdit(
            input_field=DescriptorInputField(),
            button_vertical_align=Qt.AlignmentFlag.AlignBottom,
            signal_update=signal_update,
            signals_min=wallet_functions,
            close_all_video_widgets=wallet_functions.signals.close_all_video_widgets,
            parent=self,
        )
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None
        self._dialog: QWidget | None = None
        self._temp_bitcoin_video_widget: BitcoinVideoWidget | None = None

        self._hardware_signer_interaction: RegisterMultisigInteractionWidget | None = None
        self._layout = QVBoxLayout(self)
        set_no_margins(self._layout)
        self._layout.addWidget(self.edit)
        self.signal_tracker = SignalTracker()

        self.wallet_functions = wallet_functions
        self.network = network
        self.wallet = wallet

        self.edit.input_field.setAnalyzer(DescriptorAnalyzer(self.network, parent=self))

        # import button
        self.import_export_widget_layout = QHBoxLayout()
        self._layout.addLayout(self.import_export_widget_layout)
        self.import_button = QToolButton()
        self.import_button.setIcon(svg_tools.get_QIcon("bi--upload.svg"))
        self.import_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.import_button_menu = Menu(self)
        self.import_button.setMenu(self.import_button_menu)
        self.import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # self.import_button.setIcon((self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.import_export_widget_layout.addWidget(self.import_button)
        self.action_import_qr = self.import_button_menu.add_action(
            text="", slot=self.on_action_import_qr, icon=svg_tools.get_QIcon("camera.svg")
        )
        self.action_import_clipbard = self.import_button_menu.add_action(
            text="", slot=self.on_action_import_from_clipboard, icon=svg_tools.get_QIcon("clip.svg")
        )

        # export button
        self.export_button = QToolButton()
        self.export_button.setIcon(svg_tools.get_QIcon("bi--download.svg"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button_menu = Menu(self)
        self.export_button.setMenu(self.export_button_menu)
        self.export_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # self.export_button.setIcon((self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.import_export_widget_layout.addWidget(self.export_button)
        self.action_copy = self.export_button_menu.add_action(
            text="", slot=self._on_copy_descriptor, icon=svg_tools.get_QIcon("bi--copy.svg")
        )
        self.action_export_hardware_signers = self.export_button_menu.add_action(
            text="",
            slot=self.show_export_widget,
        )

        # pdf button
        self.pdf_button = QPushButton()
        self.pdf_button.setIcon(svg_tools.get_QIcon("bi--filetype-pdf.svg"))
        self.pdf_button.clicked.connect(self._do_pdf)
        if wallet is not None:
            self.import_export_widget_layout.addWidget(self.pdf_button)

        # pdf button
        self.register_button = QPushButton()
        self.register_button.setIcon(svg_tools.get_QIcon("bi--download.svg"))
        self.register_button.clicked.connect(self.show_register_multisig)
        if wallet is not None and wallet.is_multisig():
            self.import_export_widget_layout.addWidget(self.register_button)

        self.import_export_widget_layout.addStretch()

        # signals
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.edit.input_field.textChanged), self.on_input_field_textChanged
        )

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        center_on_screen(self)

    def updateUi(self):
        """UpdateUi."""
        self.import_button.setText(self.tr("Import"))
        self.action_import_qr.setText(self.tr("Read QR Code"))
        self.action_import_clipbard.setText(self.tr("Import from Clipboard"))
        self.export_button.setText(self.tr("Export"))
        self.action_export_hardware_signers.setText(self.tr("Export for hardware signers"))
        self.action_copy.setText(self.tr("Copy to clipboard"))
        self.edit.input_field.setPlaceholderText(
            self.tr("Paste or scan your descriptor, if you restore a wallet.")
        )

        self.edit.setToolTip(
            self.tr(
                'This "descriptor" contains all information to reconstruct the wallet. \nPlease back up this descriptor to be able to recover the funds!'
            )
        )
        self.pdf_button.setText(self.tr("Recovery Sheet"))
        self.register_button.setText(self.tr("Register with hardware signers"))

    def _do_pdf(self) -> None:
        """Do pdf."""
        if not self.wallet:
            Message(
                self.tr("Wallet setup not finished. Please finish before creating a Backup pdf."),
                type=MessageType.Error,
                parent=self,
            )
            return

        lang_code = QLocale().name() or DEFAULT_LANG_CODE
        make_and_open_pdf(self.wallet, lang_code=lang_code)

    def on_input_field_textChanged(self):
        """On input field textChanged."""
        self.signal_descriptor_change.emit(self.edit.text())

    def _check_if_valid(self) -> bool:
        """Check if valid."""
        if not self.edit.text():
            return True

        return is_valid_descriptor(self.edit.text(), network=self.network)

    def _data_to_descriptor(self, data: Data) -> str | None:
        """Data to descriptor."""
        if data.data_type in [DataType.Descriptor]:
            return str(
                convert_to_multipath_descriptor(descriptor_str=data.data_as_string(), network=self.network)
            )
        if data.data_type in [DataType.MultiPathDescriptor]:
            return data.data_as_string()
        if data.data_type in [DataType.MultisigWalletExport] and isinstance(
            data.data, ConverterMultisigWalletExport
        ):
            return from_multisig_wallet_export(data.data, network=self.network).to_string_with_secret()

        return None

    def _on_signal_data(self, data: Data):
        """On signal data."""
        text = self._data_to_descriptor(data)
        if text:
            self.edit.input_field.setText(text)

    def _exception_callback(self, e: Exception) -> None:
        """Exception callback."""
        if isinstance(e, DecodingException):
            if question_dialog(
                self.tr("Could not recognize the input. Do you want to scan again?"),
                true_button=self.tr("Scan again"),
            ):
                self.on_action_import_qr()
            else:
                return
        else:
            Message(f"{type(e).__name__}\n{e}", type=MessageType.Error, parent=self)

    def on_action_import_from_clipboard(self):
        """On action import from clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard:
            self.edit.input_field.setText(clipboard.text())

    def on_action_import_qr(self):
        """On action import qr."""
        self._temp_bitcoin_video_widget = BitcoinVideoWidget(network=self.network, close_on_result=True)
        self._temp_bitcoin_video_widget.signal_data.connect(self._on_signal_data)
        self._temp_bitcoin_video_widget.signal_recognize_exception.connect(self._exception_callback)
        self._temp_bitcoin_video_widget.show()

    def _on_copy_descriptor(self):
        """On copy descriptor."""
        do_copy(self.edit.text().strip())

    def show_export_widget(self):
        """Show export widget."""
        if not self._check_if_valid():
            Message(self.tr("Descriptor not valid"), parent=self)
            return

        try:
            self._dialog = DescriptorExport(
                descriptor=convert_to_multipath_descriptor(self.edit.text().strip(), self.network),
                signals_min=self.wallet_functions.signals,
                parent=self,
                network=self.network,
                loop_in_thread=self.loop_in_thread,
                wallet_id=self.wallet.id if self.wallet is not None else "Multisig",
            )
            self._dialog.show()
            self._dialog.raise_()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            logger.error(f"Could not create a DescriptorExport for {self.__class__.__name__}: {e}")
            return

    def close(self):
        """Close."""
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()
        self.edit.close()
        self.signal_tracker.disconnect_all()
        if self._temp_bitcoin_video_widget:
            self._temp_bitcoin_video_widget.close()
        if self._dialog:
            self._dialog.close()
        if self._hardware_signer_interaction:
            self._hardware_signer_interaction.close()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()

    def show_register_multisig(self) -> None:
        """Show register multisig."""
        if not self.wallet:
            return
        if not self.wallet.is_multisig():
            Message(
                self.tr("Please select a Multisignature wallet first"), type=MessageType.Warning, parent=self
            )
            return

        if self._hardware_signer_interaction:
            self._hardware_signer_interaction.close()

        self._hardware_signer_interaction = RegisterMultisigInteractionWidget(
            wallet=self.wallet,
            loop_in_thread=self.loop_in_thread,
            wallet_name=self.wallet.id,
            wallet_functions=self.wallet_functions,
        )
        self._hardware_signer_interaction.set_minimum_size_as_floating_window()
        self._hardware_signer_interaction.show()
        self._hardware_signer_interaction.raise_()
