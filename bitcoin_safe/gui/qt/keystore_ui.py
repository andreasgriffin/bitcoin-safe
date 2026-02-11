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
from collections.abc import Callable, Iterable
from functools import partial
from typing import cast

import bdkpython as bdk
from bitcoin_qr_tools.data import ConverterXpub, Data, DataType, SignerInfo
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_usb.address_types import AddressType, SimplePubKeyProvider
from bitcoin_usb.seed_tools import derive
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.analyzer_indicator import AnalyzerIndicator
from bitcoin_safe.gui.qt.analyzers import (
    FingerprintAnalyzer,
    KeyOriginAnalyzer,
    SeedAnalyzer,
    XpubAnalyzer,
)
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerState,
    AnalyzerTextEdit,
    QCompleterLineEdit,
)
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsExportXpub
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate

from ...keystore import KeyStore, KeyStoreImporterTypes
from ...signals import SignalsMin
from ...signer import AbstractSignatureImporter, SignatureImporterUSB
from .block_change_signals import BlockChangesSignals
from .dialog_import import ImportDialog
from .util import (
    Message,
    MessageType,
    add_to_buttonbox,
    create_tool_button,
    generate_help_button,
    set_no_margins,
)

logger = logging.getLogger(__name__)


def icon_for_label(label: str) -> QIcon:
    """Icon for label."""
    return (
        svg_tools.get_QIcon("bi--key.svg")
        if label.startswith(translate("d", "Recovery"))
        else svg_tools.get_QIcon("bi--key.svg")
    )


class BaseHardwareSignerInteractionWidget(QWidget):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self._layout = QVBoxLayout(self)
        set_no_margins(self._layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # add the buttons
        self.buttonBox = QDialogButtonBox()
        self.help_button: QPushButton | None = None

        self._layout.addWidget(self.buttonBox)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.setAlignment(self.buttonBox, Qt.AlignmentFlag.AlignCenter)

    def add_button(self, button: QPushButton | QToolButton):
        """Add button."""
        self.buttonBox.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)

    def add_help_button(self, help_widget: QWidget) -> QPushButton:
        """Add help button."""
        self.buttonBoxHelp = QDialogButtonBox()
        help_button = generate_help_button(help_widget)

        self.buttonBoxHelp.addButton(help_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._layout.addWidget(self.buttonBoxHelp)
        self._layout.setAlignment(self.buttonBoxHelp, Qt.AlignmentFlag.AlignCenter)

        self.help_button = help_button
        return help_button

    def updateUi(self) -> None:
        """UpdateUi."""
        if self.help_button:
            self.help_button.setText(self.tr("Device instructions"))

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)


class HardwareSignerInteractionWidget(BaseHardwareSignerInteractionWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        # add the buttons
        self.button_import_file: QPushButton | None = None
        self.button_import_qr: QPushButton | None = None
        self.button_export_qr: QToolButton | None = None
        self.button_hwi: QPushButton | None = None
        self.button_export_file: QToolButton | None = None

        self._layout.addWidget(self.buttonBox)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.setAlignment(self.buttonBox, Qt.AlignmentFlag.AlignCenter)

    def add_import_file_button(self) -> QPushButton:
        # Create custom buttons
        """Add import file button."""
        self.button_import_file = button_import_file = add_to_buttonbox(
            self.buttonBox, self.tr(""), KeyStoreImporterTypes.file.icon_filename
        )
        return button_import_file

    def add_copy_button(self) -> tuple[QToolButton, Menu]:
        """Add copy button."""
        button, menu = create_tool_button(parent=self)

        button.setIcon(svg_tools.get_QIcon("bi--copy.svg"))

        # Add the button to the QDialogButtonBox
        self.buttonBox.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)

        self.button_export_file = button
        return self.button_export_file, menu

    def add_qr_import_buttonn(self) -> QPushButton:
        """Add qr import buttonn."""
        self.button_import_qr = button_import_qr = add_to_buttonbox(
            self.buttonBox, text="", icon_name=KeyStoreImporterTypes.qr.icon_filename
        )
        return button_import_qr

    def add_hwi_button(self, signal_end_hwi_blocker: SignalProtocol[[]]) -> QPushButton:
        """Add hwi button."""
        button_hwi = SpinningButton(
            text="",
            signal_stop_spinning=signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self,
        )
        self.buttonBox.addButton(button_hwi, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_hwi = button_hwi
        return button_hwi

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        if self.button_import_file:
            self.button_import_file.setText(self.tr("Import File or Text"))
        if self.button_export_file:
            self.button_export_file.setText(self.tr("Export File"))
        if self.button_import_qr:
            self.button_import_qr.setText(self.tr("QR Code"))
        if self.button_export_qr:
            self.button_export_qr.setText(self.tr("QR Code"))
        if self.button_hwi:
            self.button_hwi.setText(self.tr("USB"))


class KeyStoreUI(QWidget):
    signal_signer_infos = cast(SignalProtocol[[list[SignerInfo]]], pyqtSignal(list))

    def __init__(
        self,
        network: bdk.Network,
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        label: str = "",
        hardware_signer_label="",
        parent: QWidget | None = None,
        slow_hwi_listing=True,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.signals_min = signals_min

        self.label = label
        self.hardware_signer_label = hardware_signer_label
        self.network = network
        self.get_address_type = get_address_type
        self.slow_hwi_listing = slow_hwi_listing

        self.tab_layout = QHBoxLayout(self)

        self.tabs_import_type = QTabWidget(self)
        self.tab_layout.addWidget(self.tabs_import_type)

        self.tab_import = QWidget(self)
        self.tab_import_layout = QVBoxLayout(self.tab_import)
        self.tabs_import_type.addTab(self.tab_import, "")
        self.tab_manual = QWidget(self.tab_import)
        self.tabs_import_type.addTab(self.tab_manual, "")

        self.label_fingerprint = QLabel(self)
        self.edit_fingerprint = ButtonEdit(
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self,
        )
        self.edit_fingerprint.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_fingerprint.signal_data.connect(self._on_handle_input)

        self.edit_fingerprint.input_field.setAnalyzer(FingerprintAnalyzer(parent=self))
        # key_origin
        self.label_key_origin = QLabel(self)
        self.edit_key_origin_input = QCompleterLineEdit(self.network)
        self.edit_key_origin = ButtonEdit(
            input_field=self.edit_key_origin_input,
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self,
        )
        self.edit_key_origin.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_key_origin.signal_data.connect(self._on_handle_input)
        self.edit_key_origin_input.setAnalyzer(
            KeyOriginAnalyzer(
                get_expected_key_origin=self.get_expected_key_origin, network=self.network, parent=self
            )
        )

        # xpub
        self.label_xpub = QLabel(self)
        self.edit_xpub = ButtonEdit(
            input_field=AnalyzerTextEdit(),
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self,
        )
        self.edit_xpub.setFixedHeight(50)
        self.edit_xpub.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.edit_xpub.add_usb_buttton(on_click=self.on_xpub_usb_click)
        self.edit_xpub.signal_data.connect(self._on_handle_input)

        self.edit_xpub.input_field.setAnalyzer(XpubAnalyzer(self.network, parent=self))
        self.label_seed = QLabel(self)
        self.edit_seed = ButtonEdit(
            close_all_video_widgets=self.signals_min.close_all_video_widgets, parent=self
        )

        self.edit_seed.add_random_mnemonic_button(callback_seed=self.on_edit_seed_changed)
        self.edit_seed.input_field.setAnalyzer(SeedAnalyzer(parent=self))
        self.edit_seed.input_field.textChanged.connect(self.on_edit_seed_changed)

        # put them on the formLayout
        self.formLayout = QFormLayout(self.tab_manual)
        self.formLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.label_fingerprint)
        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.edit_fingerprint)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.label_key_origin)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.edit_key_origin)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.label_xpub)
        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.edit_xpub)
        self.formLayout.setWidget(4, QFormLayout.ItemRole.LabelRole, self.label_seed)
        self.formLayout.setWidget(5, QFormLayout.ItemRole.FieldRole, self.edit_seed)
        self.seed_visibility(self.network in KeyStoreImporterTypes.seed.networks)

        # tab_import

        self.hardware_signer_interaction = HardwareSignerInteractionWidget()
        self.button_qr = self.hardware_signer_interaction.add_qr_import_buttonn()
        self.hardware_signer_interaction.add_help_button(ScreenshotsExportXpub())

        self.button_qr.clicked.connect(self.edit_xpub.button_container.buttons[0].click)

        self.usb_gui = USBGui(
            self.network, initalization_label=self.hardware_signer_label, loop_in_thread=loop_in_thread
        )
        button_hwi = self.hardware_signer_interaction.add_hwi_button(
            signal_end_hwi_blocker=self.usb_gui.signal_end_hwi_blocker
        )
        button_hwi.clicked.connect(self.on_hwi_click)

        self.button_file = self.hardware_signer_interaction.add_import_file_button()
        self.button_file.clicked.connect(self._import_dialog)

        # self.tab_import_layout.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.tab_import_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.analyzer_indicator = AnalyzerIndicator(
            line_edits=[
                self.edit_fingerprint.input_field,
                self.edit_key_origin_input,
                self.edit_xpub.input_field,
            ],
            icon_OK=svg_tools.get_pixmap("checkmark.svg", size=(50, 50)),
            icon_warning=svg_tools.get_pixmap("warning.svg", size=(50, 50)),
            icon_error=svg_tools.get_pixmap("error.svg", size=(50, 50)),
            hide_if_all_empty=True,
        )
        self.analyzer_indicator.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.tab_import_layout.addWidget(self.analyzer_indicator)
        self.tab_import_layout.addWidget(self.hardware_signer_interaction)

        # self.tab_import_layout.addItem(QSpacerItem(1, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.right_widget = QWidget(self)
        self.right_widget_layout = QVBoxLayout(self.right_widget)
        # self.right_widget_layout.setContentsMargins(0,0,0,0)

        self.label_description = QLabel(self)

        self.right_widget_layout.addWidget(self.label_description)

        self.textEdit_description = AnalyzerTextEdit()
        self.right_widget_layout.addWidget(self.textEdit_description)

        self.tab_layout.addWidget(self.right_widget)

        self.updateUi()

        self.edit_key_origin_input.textChanged.connect(self.format_all_fields)
        self.signals_min.language_switch.connect(self.updateUi)

    def _process_input(self, s: str) -> None:
        """Process input."""
        try:
            res = Data.from_str(s, network=self.network)
            self._on_handle_input(res)
        except Exception as e:
            Message(str(e), type=MessageType.Error, parent=self)

    def _import_dialog(self):
        """Import dialog."""
        self._attached_import_dialog = ImportDialog(
            self.network,
            on_open=self._process_input,
            window_title=self.tr("Import fingerprint and xpub"),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr("Please paste the exported file (like sparrow-export.json):"),
            text_placeholder=self.tr("Please paste the exported file (like sparrow-export.json)"),
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
        )
        self._attached_import_dialog.show()

    def on_edit_seed_changed(self, text: str):
        """On edit seed changed."""
        try:
            keystore = self.get_ui_values_as_keystore()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), type=MessageType.Error, parent=self)
            return
        self.edit_fingerprint.setText(keystore.fingerprint)
        self.edit_xpub.setText(keystore.xpub)
        self.key_origin = keystore.key_origin

    def seed_visibility(self, visible=False) -> None:
        """Seed visibility."""
        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

        # self.edit_xpub.setHidden(visible)
        # self.edit_fingerprint.setHidden(visible)
        # self.label_xpub.setHidden(visible)
        # self.label_fingerprint.setHidden(visible)

    @property
    def key_origin(self) -> str:
        """Key origin."""
        try:
            standardized = SimplePubKeyProvider.format_key_origin(self.edit_key_origin.text().strip())
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            return ""

        return standardized

    @key_origin.setter
    def key_origin(self, value: str) -> None:
        """Key origin."""
        self.edit_key_origin.setText(value if value else "")

    def format_all_fields(self) -> None:
        """Format all fields."""
        self.edit_fingerprint.format_and_apply_validator()

        expected_key_origin = self.get_expected_key_origin()
        if expected_key_origin != self.key_origin:
            self.edit_key_origin.format_as_error(True)
            analyzer = self.edit_key_origin_input.analyzer()
            analyzer_message = analyzer.analyze(self.key_origin).msg + "\n" if analyzer else ""
            self.edit_key_origin.setToolTip(
                analyzer_message
                + self.tr(
                    "Standard for the selected address type {type} is {expected_key_origin}.  Please correct if you are not sure."
                ).format(expected_key_origin=expected_key_origin, type=self.get_address_type().name)
            )
            self.edit_xpub.format_as_error(True)
            self.edit_xpub.setToolTip(
                self.tr(
                    "The xPub origin {key_origin} and the xPub belong together. Please choose the correct xPub origin pair."
                ).format(key_origin=self.key_origin)
            )
        else:
            self.edit_xpub.format_and_apply_validator()
            self.edit_xpub.setToolTip("")
            self.edit_key_origin.format_and_apply_validator()
            self.edit_key_origin.setToolTip("")
        self.edit_key_origin.setPlaceholderText(expected_key_origin)
        self.edit_key_origin_input.reset_memory()
        self.edit_key_origin_input.add_to_memory(expected_key_origin)
        self.analyzer_indicator.updateUi()

    def get_expected_key_origin(self) -> str:
        """Get expected key origin."""
        return self.get_address_type().key_origin(self.network)

    def get_key_origin(self) -> str:
        """Get key origin."""
        key_origin = self.edit_key_origin.text().strip()
        return key_origin if key_origin else self.get_expected_key_origin()

    def set_using_signer_info(self, signer_info: SignerInfo) -> None:
        """Set using signer info."""
        key_origin_input_analyzer = self.edit_key_origin_input.analyzer()
        assert key_origin_input_analyzer
        analyzer_message = key_origin_input_analyzer.analyze(signer_info.key_origin)
        if analyzer_message.state == AnalyzerState.Invalid:
            Message(
                analyzer_message.msg,
                type=MessageType.Error,
                parent=self,
            )
            return
        elif analyzer_message.state == AnalyzerState.Warning:
            if not question_dialog(
                self.tr("{msg}\nDo you want to proceed anyway?").format(msg=analyzer_message.msg),
            ):
                return

        self.edit_xpub.setText(signer_info.xpub)
        self.key_origin = signer_info.key_origin
        self.edit_fingerprint.setText(signer_info.fingerprint)

    def _on_handle_input(self, data: Data, parent: QLineEdit | QTextEdit | None = None) -> None:
        """On handle input."""
        if data.data_type == DataType.SignerInfo:
            self.set_using_signer_info(data.data)
        elif data.data_type == DataType.SignerInfos and len(data.data) == 1:
            # this case is relevant if a single SignerInfo is contains an account>0
            self.set_using_signer_info(data.data[0])
        elif data.data_type == DataType.SignerInfos:
            key_origin = self.get_key_origin()

            matching_signer_infos = [
                signer_info
                for signer_info in data.data
                if isinstance(signer_info, SignerInfo) and (signer_info.key_origin == key_origin)
            ]

            if len(matching_signer_infos) == 1:
                self.set_using_signer_info(matching_signer_infos[0])
            elif len(matching_signer_infos) > 1:
                self.signal_signer_infos.emit(matching_signer_infos)
            else:
                # none found
                Message(
                    self.tr(
                        "No signer data for the expected Xpub origin {key_origin} found. If you want to import a non-default account number, specify the Xpub origin and scan again."
                    ).format(key_origin=key_origin),
                    parent=self,
                )

        elif data.data_type == DataType.Xpub:
            self.edit_xpub.setText(data.data)
        elif data.data_type == DataType.Fingerprint:
            self.edit_fingerprint.setText(data.data)
        elif data.data_type in [
            DataType.Descriptor,
            DataType.MultisigWalletExport,
        ]:
            Message(
                self.tr("Please paste descriptors into the descriptor field in the top right."),
                parent=self,
            )
        elif isinstance(data.data, str) and parent:
            parent.setText(data.data)
        elif isinstance(data, Data):
            Message(
                self.tr("{data_type} cannot be used here.").format(data_type=data.data_type),
                type=MessageType.Error,
                parent=self,
            )
        else:
            Exception("Could not recognize the QR Code")

    def xpub_validator(self) -> bool:
        """Xpub validator."""
        xpub = self.edit_xpub.text()
        # automatically convert slip132
        if ConverterXpub.is_slip132(xpub):
            Message(
                self.tr("The xpub is in SLIP132 format. Converting to standard format."),
                title="Converting format",
                parent=self,
            )
            try:
                self.edit_xpub.setText(ConverterXpub.convert_slip132_to_bip32(xpub))
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
                return False

        return KeyStore.is_xpub_valid(self.edit_xpub.text(), network=self.network)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.tabs_import_type.setTabText(self.tabs_import_type.indexOf(self.tab_import), self.tr("Import"))
        self.tabs_import_type.setTabText(self.tabs_import_type.indexOf(self.tab_manual), self.tr("Advanced"))
        self.label_description.setText(self.tr("Description"))

        self.label_fingerprint.setText(self.tr("Fingerprint"))
        self.edit_fingerprint.input_field.display_name = self.label_fingerprint.text()

        self.label_key_origin.setText(self.tr("xPub Origin"))
        self.edit_key_origin_input.display_name = self.label_key_origin.text()

        self.label_xpub.setText(self.tr("xPub"))
        self.edit_xpub.input_field.display_name = self.label_xpub.text()

        self.label_seed.setText(self.tr("Seed"))
        self.edit_seed.input_field.display_name = self.label_seed.text()

        self.textEdit_description.setPlaceholderText(
            self.tr(
                "Name of signing device: ......\nLocation of signing device: .....",
            )
        )
        self.analyzer_indicator.updateUi()
        self.hardware_signer_interaction.updateUi()

    def _on_hwi_click(self, key_origin: str) -> None:
        """On hwi click."""
        try:
            result = self.usb_gui.get_fingerprint_and_xpub(
                key_origin=key_origin, slow_hwi_listing=self.slow_hwi_listing
            )
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(
                str(e)
                + "\n\n"
                + self.tr("Please ensure that there are no other programs accessing the Hardware signer"),
                type=MessageType.Error,
                parent=self,
            )
            return
        if not result:
            return

        device, fingerprint, xpub = result
        self.set_using_signer_info(SignerInfo(fingerprint=fingerprint, key_origin=key_origin, xpub=xpub))
        if not self.textEdit_description.text():
            self.textEdit_description.setText(f"{device.get('type', '')} - {device.get('model', '')}")

    def on_hwi_click(self) -> None:
        """On hwi click."""
        address_type = self.get_address_type()
        key_origin = address_type.key_origin(self.network)
        self._on_hwi_click(key_origin=key_origin)

    def on_xpub_usb_click(self) -> None:
        """On xpub usb click."""
        key_origin = self.key_origin
        if not key_origin:
            Message(self.tr("Please enter a valid key origin."), parent=self)
            return
        self._on_hwi_click(key_origin=key_origin)

    def get_ui_values_as_keystore(self) -> KeyStore:
        """Get ui values as keystore."""
        seed_str = self.edit_seed.text().strip()

        if seed_str:
            mnemonic = str(bdk.Mnemonic.from_string(seed_str))
            key_origin = self.edit_key_origin.text().strip()
            # if key_origin is empty  fill it with the default
            key_origin = key_origin if key_origin else self.get_address_type().key_origin(self.network)
            xpub, fingerprint = derive(mnemonic=mnemonic, key_origin=key_origin, network=self.network)
        else:
            mnemonic = None
            fingerprint = self.edit_fingerprint.text()
            xpub = self.edit_xpub.text()
            key_origin = self.key_origin

            # try to validate
            # if this works, then these are valid values
            if not KeyStore.is_xpub_valid(xpub, self.network):
                if xpub:
                    raise ValueError(self.tr("{xpub} is not a valid public xpub").format(xpub=xpub))
                else:
                    raise ValueError(self.tr("Please import the information from all hardware signers first"))

        return KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            label=self.label,
            mnemonic=mnemonic if mnemonic else None,
            description=self.textEdit_description.toPlainText(),
            network=self.network,
        )

    def set_ui_from_keystore(self, keystore: KeyStore) -> None:
        """Set ui from keystore."""
        with BlockChangesSignals([self]):
            self.label = keystore.label

            logger.debug(f"{self.__class__.__name__} set_ui_from_keystore")
            xpub = keystore.xpub if keystore.xpub else ""
            if xpub != self.edit_xpub.text():
                self.edit_xpub.setText(xpub)

            fingerprint = keystore.fingerprint if keystore.fingerprint else ""
            if fingerprint != self.edit_fingerprint.text():
                self.edit_fingerprint.setText(fingerprint)

            if self.key_origin != keystore.key_origin:
                self.key_origin = keystore.key_origin

            if self.textEdit_description.toPlainText() != keystore.description:
                self.textEdit_description.setPlainText(keystore.description)

            mnemonic = keystore.mnemonic if keystore.mnemonic else ""
            if self.edit_seed.text() != mnemonic:
                self.edit_seed.setText(mnemonic)

    def close(self) -> bool:
        """Close."""
        SignalTools.disconnect_all_signals_from(self)
        self.edit_seed.close()
        self.edit_key_origin.close()
        self.edit_fingerprint.close()
        self.edit_key_origin_input.close()
        self.edit_xpub.close()
        return super().close()


class SignedUI(QWidget):
    def __init__(
        self,
        text: str,
        psbt: bdk.Psbt,
        network: bdk.Network,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.text = text
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QHBoxLayout(self)

        self.edit_signature = QTextEdit()
        self.edit_signature.setMinimumHeight(30)
        self.edit_signature.setReadOnly(True)
        self.edit_signature.setText(str(self.text))
        self.layout_keystore_buttons.addWidget(self.edit_signature)


class SignerUI(QWidget):
    signal_signature_added = cast(SignalProtocol[[bdk.Psbt]], pyqtSignal(bdk.Psbt))
    signal_tx_received = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))

    def __init__(
        self,
        signature_importers: Iterable[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
        button_prefix: str = "",
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        self.buttons: list[QPushButton] = []
        for signer in self.signature_importers:
            button: QPushButton
            if isinstance(signer, SignatureImporterUSB):
                signal_end_hwi_blocker = cast(SignalProtocol[[]], signer.usb_gui.signal_end_hwi_blocker)
                button = SpinningButton(
                    text=button_prefix + signer.label,
                    signal_stop_spinning=signal_end_hwi_blocker,
                    enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
                    timeout=60,
                    parent=self,
                    svg_tools=svg_tools,
                )
            else:
                button = QPushButton(button_prefix + signer.label, parent=self)
                button.setIcon(svg_tools.get_QIcon(signer.keystore_type.icon_filename))
            self.buttons.append(button)
            callback = partial(signer.sign, self.psbt)
            button.clicked.connect(callback)
            self.layout_keystore_buttons.addWidget(button)

            # forward the signal_signature_added from each signer to self.signal_signature_added
            signer.signal_signature_added.connect(self.signal_signature_added)
            signer.signal_final_tx_received.connect(self.signal_tx_received)


class SignerUIHorizontal(QWidget):
    signal_signature_added = cast(SignalProtocol[[bdk.Psbt]], pyqtSignal(bdk.Psbt))
    signal_tx_received = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))

    def __init__(
        self,
        signature_importers: list[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        for signer in self.signature_importers:
            button = QPushButton(signer.label)
            button.setIcon(svg_tools.get_QIcon(signer.keystore_type.icon_filename))
            action = partial(signer.sign, self.psbt)
            button.clicked.connect(action)
            self.layout_keystore_buttons.addWidget(button)

            # forward the signal_signature_added from each signer to self.signal_signature_added
            signer.signal_signature_added.connect(self.signal_signature_added)
            signer.signal_final_tx_received.connect(self.signal_tx_received)
