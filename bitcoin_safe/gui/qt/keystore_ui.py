#
# Bitcoin Safe
# Copyright (C) 2023-2026 Andreas Griffin
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
#

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
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
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.analyzers import (
    FingerprintAnalyzer,
    KeyOriginAnalyzer,
    SeedAnalyzer,
    XpubAnalyzer,
)
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.card_base import CardBase, CardExpansionMode
from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerLineEdit,
    AnalyzerMessage,
    AnalyzerState,
    AnalyzerTextEdit,
    BaseAnalyzer,
    FlexibleHeightTextedit,
    QCompleterLineEdit,
)
from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.tutorial_screenshots import ScreenshotsExportXpub
from bitcoin_safe.gui.qt.util import svg_tools, svg_tools_hardware_signer
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate

from ...execute_config import DEMO_MODE
from ...hardware_signers import (
    SUPPORTED_HARDWARE_SIGNERS_URL,
    FeatureLevel,
    HardwareSigner,
    HardwareSigners,
)
from ...keystore import KeyStore, KeyStoreImporterTypes
from ...signals import SignalsMin
from .block_change_signals import BlockChangesSignals
from .dialog_import import ImportDialog
from .util import Message, MessageType

logger = logging.getLogger(__name__)


def icon_for_label(label: str) -> QIcon:
    """Icon for label."""
    return (
        svg_tools.get_QIcon("bi--key.svg")
        if label.startswith(translate("d", "Recovery"))
        else svg_tools.get_QIcon("bi--key.svg")
    )


class KeyStoreUiState(enum.Enum):
    Add = enum.auto()
    Empty = enum.auto()
    Filled = enum.auto()
    ReadOnly = enum.auto()


class KeyStoreUI(CardBase):
    signal_signer_infos = cast(SignalProtocol[[list[SignerInfo]]], pyqtSignal(list))
    signal_ui_changed = cast(SignalProtocol[[]], pyqtSignal())
    request_show_register_multisig = cast(SignalProtocol[[HardwareSigner | None]], pyqtSignal(object))

    def __init__(
        self,
        network: bdk.Network,
        get_address_type: Callable[[], AddressType],
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        hardware_signer_label: str = "",
        parent: QWidget | None = None,
        read_only_mode: bool = False,
        show_register_button: bool = True,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, expansion_mode=CardExpansionMode.EXPANDABLE)
        self.signals_min = signals_min
        self._fallback_hardware_signer_label = hardware_signer_label
        self.hardware_signer_label = hardware_signer_label
        self.network = network
        self.get_address_type = get_address_type
        self.read_only_mode = read_only_mode
        self.show_register_button = show_register_button
        self.loop_in_thread = loop_in_thread
        self.counter_register_button_clicked = 0
        self._device_type_editing = False
        self._selected_hardware_signer: HardwareSigner | None = None
        self._device_help_widget: QWidget | None = None
        self._state = KeyStoreUiState.Add
        self._status_pixmaps = {
            AnalyzerState.Valid: svg_tools.get_pixmap("checkmark.svg", size=(22, 22)),
            AnalyzerState.Warning: svg_tools.get_pixmap("warning.svg", size=(22, 22)),
            AnalyzerState.Invalid: svg_tools.get_pixmap("error.svg", size=(22, 22)),
        }

        self.usb_gui = USBGui(
            self.network, initalization_label=self.hardware_signer_label, loop_in_thread=loop_in_thread
        )

        self._build_widgets()
        self._connect_signals()
        self.updateUi()
        self._apply_state()

    def set_hardware_signer_label(self, value: str) -> None:
        """Update the derived signer label used by the UI and USB workflows."""
        self.hardware_signer_label = value
        self.usb_gui.set_initalization_label(value)

    def set_fallback_hardware_signer_label(self, value: str) -> None:
        """Update the slot-based fallback label used before a concrete signer is known."""
        self._fallback_hardware_signer_label = value
        self._sync_hardware_signer_label()

    def _sync_hardware_signer_label(self) -> None:
        """Refresh the visible label from the selected signer or the slot fallback."""
        hardware_signer = self.selected_hardware_signer
        if hardware_signer and hardware_signer != HardwareSigners.generic:
            self.set_hardware_signer_label(hardware_signer.display_name)
            return
        self.set_hardware_signer_label(self._fallback_hardware_signer_label)

    def _build_widgets(self) -> None:
        self.card_frame = self
        self.card_layout = self.root_layout

        self.header_icon.setFixedSize(36, 36)
        self.header_text_layout.setSpacing(2)

        self.header_status_icon = QLabel(self.header_text_widget)
        self.header_status_icon.setFixedSize(22, 22)
        self.header_title_row.addWidget(self.header_status_icon)
        self.header_title_row.addStretch()
        self.register_header_click_target(self.header_status_icon)

        self.add_controls_widget = QWidget(self.header_widget)
        self.add_controls_layout = QHBoxLayout(self.add_controls_widget)
        self.add_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.add_controls_layout.setSpacing(8)
        self.header_right_layout.addWidget(self.add_controls_widget)

        self.device_type_help_label = IconLabel(parent=self.header_widget)
        self.device_type_help_label.textLabel.setWordWrap(True)
        self.device_type_help_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.add_controls_layout.addWidget(self.device_type_help_label, stretch=1)

        self.combo_brand = QComboBox(self.header_widget)
        self.combo_model = QComboBox(self.header_widget)
        self.button_confirm_signer = QPushButton(self.header_widget)
        self.button_confirm_signer.setEnabled(False)
        self.add_controls_layout.addWidget(self.combo_brand)
        self.add_controls_layout.addWidget(self.combo_model)
        self.add_controls_layout.addWidget(self.button_confirm_signer)

        self.header_actions_widget = QWidget(self.header_widget)
        self.header_actions_layout = QHBoxLayout(self.header_actions_widget)
        self.header_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.header_actions_layout.setSpacing(8)
        self.header_right_layout.addWidget(self.header_actions_widget)

        self.button_device_instructions = QPushButton(self.header_widget)
        self.button_device_instructions.setIcon(svg_tools.get_QIcon("bi--question-circle.svg"))
        self.header_actions_layout.addWidget(self.button_device_instructions)

        self.button_register = QPushButton(self.header_widget)
        self.header_actions_layout.addWidget(self.button_register)

        self.button_menu = QToolButton(self.header_widget)
        self.button_menu.setAutoRaise(True)
        self.button_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.button_menu.setIcon(svg_tools.get_QIcon("bi--gear.svg"))
        self.button_menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.menu_button_menu = Menu(self.button_menu)
        self.button_menu.setMenu(self.menu_button_menu)
        self.action_device_instructions = self.menu_button_menu.add_action(slot=self.show_device_instructions)
        self.action_reregister = self.menu_button_menu.add_action(slot=self._request_show_register_multisig)
        self.action_change_device_type = self.menu_button_menu.add_action(slot=self.start_device_type_change)
        self.header_actions_layout.addWidget(self.button_menu)

        self.content_body = QWidget(self.content_widget)
        self._content_layout.addWidget(self.content_body)
        self.content_layout = QHBoxLayout(self.content_body)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        self.left_widget = QWidget(self.content_body)
        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.addWidget(self.left_widget, stretch=7, alignment=Qt.AlignmentFlag.AlignTop)

        self.connect_layout = QHBoxLayout()
        self.left_layout.addLayout(self.connect_layout)

        self.connect_help_label = IconLabel(parent=self.left_widget)
        self.connect_layout.addWidget(self.connect_help_label)

        self.connect_layout.addStretch()

        self.button_connect_qr = QPushButton(self.left_widget)
        self.button_connect_qr.setIcon(svg_tools.get_QIcon(KeyStoreImporterTypes.qr.icon_filename))
        self.connect_layout.addWidget(self.button_connect_qr)

        self.button_connect_usb = SpinningButton(
            text="",
            signal_stop_spinning=self.usb_gui.signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self.left_widget,
        )
        self.connect_layout.addWidget(self.button_connect_usb)

        self.button_connect_import = QPushButton(self.left_widget)
        self.button_connect_import.setIcon(svg_tools.get_QIcon(KeyStoreImporterTypes.file.icon_filename))
        self.connect_layout.addWidget(self.button_connect_import)

        self.label_fingerprint = IconLabel(parent=self.left_widget)
        self.edit_fingerprint = ButtonEdit(
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self.left_widget,
        )
        self.edit_fingerprint.add_copy_button()
        self.edit_fingerprint.signal_data.connect(self._on_handle_input)
        self.edit_fingerprint.input_field.setAnalyzer(FingerprintAnalyzer(parent=self))

        self.label_key_origin = IconLabel(parent=self.left_widget)
        self.edit_key_origin_input = QCompleterLineEdit(self.network)
        self.edit_key_origin = ButtonEdit(
            input_field=self.edit_key_origin_input,
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self.left_widget,
        )
        self.edit_key_origin.add_copy_button()
        self.edit_key_origin.signal_data.connect(self._on_handle_input)
        self.edit_key_origin_input.setAnalyzer(
            KeyOriginAnalyzer(
                get_expected_key_origin=self.get_expected_key_origin, network=self.network, parent=self
            )
        )

        self.label_xpub = IconLabel(parent=self.left_widget)
        self.edit_xpub = ButtonEdit(
            input_field=AnalyzerTextEdit(),
            signal_update=self.signals_min.language_switch,
            close_all_video_widgets=self.signals_min.close_all_video_widgets,
            parent=self.left_widget,
        )
        self.edit_xpub.setFixedHeight(50)
        self.edit_xpub.add_copy_button()
        self.edit_xpub.signal_data.connect(self._on_handle_input)
        self.edit_xpub.input_field.setAnalyzer(XpubAnalyzer(self.network, parent=self))

        self.label_seed = IconLabel(parent=self.left_widget)
        self.edit_seed = ButtonEdit(
            close_all_video_widgets=self.signals_min.close_all_video_widgets, parent=self.left_widget
        )
        self.edit_seed.add_copy_button()
        self.edit_seed.add_random_mnemonic_button(callback_seed=self.on_edit_seed_changed)
        self.edit_seed.input_field.setAnalyzer(SeedAnalyzer(parent=self))
        self.edit_seed.input_field.textChanged.connect(self.on_edit_seed_changed)

        self.details_widget = QWidget(self.left_widget)
        self.details_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self.details_layout = QGridLayout(self.details_widget)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setColumnStretch(1, 1)
        self.details_layout.addWidget(self.label_fingerprint, 0, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.details_layout.addWidget(self.edit_fingerprint, 0, 1)
        self.details_layout.addWidget(self.label_key_origin, 1, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.details_layout.addWidget(self.edit_key_origin, 1, 1)
        self.details_layout.addWidget(self.label_xpub, 2, 0, alignment=Qt.AlignmentFlag.AlignTop)
        self.details_layout.addWidget(self.edit_xpub, 2, 1)
        self.details_layout.addWidget(self.label_seed, 3, 0, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.details_layout.addWidget(self.edit_seed, 3, 1)
        self.left_layout.addWidget(self.details_widget, alignment=Qt.AlignmentFlag.AlignTop)

        self.right_widget = QWidget(self.content_body)
        self.right_widget_layout = QVBoxLayout(self.right_widget)
        self.right_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addWidget(self.right_widget, stretch=3)

        self.label_description = QLabel(self.right_widget)
        self.right_widget_layout.addWidget(self.label_description)

        self.textEdit_description = FlexibleHeightTextedit()
        self.textEdit_description.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.right_widget_layout.addWidget(self.textEdit_description)

        self._populate_brand_combo()
        self._seed_supported = self.network in KeyStoreImporterTypes.seed.networks
        self.seed_visibility(self._seed_supported)

    def _connect_signals(self) -> None:
        for signal in (
            self.edit_fingerprint.input_field.textChanged,
            self.edit_key_origin.input_field.textChanged,
            self.edit_xpub.input_field.textChanged,
            self.edit_seed.input_field.textChanged,
            self.textEdit_description.textChanged,
        ):
            signal.connect(self.signal_ui_changed.emit)

        self.edit_key_origin_input.textChanged.connect(self.format_all_fields)
        self.edit_xpub.input_field.textChanged.connect(self._apply_state)
        self.edit_fingerprint.input_field.textChanged.connect(self._apply_state)
        self.edit_key_origin_input.textChanged.connect(self._apply_state)
        self.textEdit_description.textChanged.connect(self._update_header_subtitle)

        self.signals_min.language_switch.connect(self.updateUi)

        self.combo_brand.currentIndexChanged.connect(self._on_brand_changed)
        self.combo_model.currentIndexChanged.connect(self._update_confirm_button)
        self.combo_model.currentIndexChanged.connect(self._update_device_type_help)
        self.button_confirm_signer.clicked.connect(self.confirm_device_type_selection)
        self.button_connect_qr.clicked.connect(self.scan_signer_data_from_qr)
        self.button_connect_usb.clicked.connect(self.on_hwi_click)
        self.button_connect_import.clicked.connect(self._import_dialog)
        self.connect_help_label.icon_label.clicked.connect(self.show_device_instructions)
        self.button_device_instructions.clicked.connect(self.show_device_instructions)
        self.button_register.clicked.connect(self._request_show_register_multisig)

    @property
    def selected_hardware_signer(self) -> HardwareSigner | None:
        """Return the selected hardware signer."""
        return self._selected_hardware_signer

    @property
    def state(self) -> KeyStoreUiState:
        """Return the current UI state."""
        return self._state

    def _populate_brand_combo(self) -> None:
        self.combo_brand.blockSignals(True)
        self.combo_model.blockSignals(True)
        self.combo_brand.clear()
        self.combo_model.clear()
        self.combo_brand.addItem("")
        for brand_name in HardwareSigners.list_brands():
            self.combo_brand.addItem(brand_name)
        self.combo_model.addItem("", userData=None)
        self.combo_brand.blockSignals(False)
        self.combo_model.blockSignals(False)
        self._on_brand_changed()

    def _on_brand_changed(self) -> None:
        brand_name = self.combo_brand.currentText()
        selected_name = self.combo_model.currentData()
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        if not brand_name:
            self.combo_model.addItem("", userData=None)
        else:
            for hardware_signer in HardwareSigners.models_for_brand(brand_name):
                self.combo_model.addItem(hardware_signer.display_name, userData=hardware_signer.id)
            model_index = self.combo_model.findData(selected_name) if selected_name else -1
            self.combo_model.setCurrentIndex(model_index if model_index >= 0 else 0)
        self.combo_model.blockSignals(False)
        self._update_confirm_button()
        self._update_device_type_help()

    def _update_confirm_button(self) -> None:
        self.button_confirm_signer.setEnabled(self.combo_model.currentData() is not None)

    def _device_type_help_target(self) -> tuple[str, str]:
        """Return the link text and URL for the device-selection help label."""
        hardware_signer = HardwareSigners.from_id(self.combo_model.currentData())
        if hardware_signer and hardware_signer.info_url:
            return (
                self.tr('Learn more about <a href="{url}">{device}</a>.').format(
                    url=hardware_signer.info_url,
                    device=hardware_signer.display_name,
                ),
                hardware_signer.info_url,
            )
        return (
            self.tr('Learn more about <a href="{url}">supported hardware signers</a>.').format(
                url=SUPPORTED_HARDWARE_SIGNERS_URL
            ),
            SUPPORTED_HARDWARE_SIGNERS_URL,
        )

    def _update_device_type_help(self) -> None:
        """Refresh the contextual help text shown during device selection."""
        text, click_url = self._device_type_help_target()
        self.device_type_help_label.setText(text)
        self.device_type_help_label.set_icon_as_help(
            tooltip=self.tr("Open the signer guide"),
            click_url=click_url,
        )

    def _set_combo_selection(self, hardware_signer: HardwareSigner | None) -> None:
        if not hardware_signer:
            self.combo_brand.setCurrentIndex(0)
            self.combo_model.setCurrentIndex(0)
            return
        brand_index = self.combo_brand.findText(hardware_signer.brand_name)
        if brand_index >= 0:
            brand_changed = self.combo_brand.currentIndex() != brand_index
            self.combo_brand.setCurrentIndex(brand_index)
            if not brand_changed:
                self._on_brand_changed()
        model_index = self.combo_model.findData(hardware_signer.id)
        if model_index >= 0:
            self.combo_model.setCurrentIndex(model_index)
        self._update_confirm_button()

    def set_selected_hardware_signer(self, hardware_signer: HardwareSigner | None) -> None:
        """Set the selected hardware signer."""
        self._selected_hardware_signer = hardware_signer
        self._set_combo_selection(hardware_signer)
        self._sync_hardware_signer_label()
        self._update_header_icon()
        self._update_connect_buttons()
        self._update_help_visibility()
        self._update_header_subtitle()

    def start_device_type_change(self) -> None:
        """Return to the device selection flow."""
        self._device_type_editing = True
        self.counter_register_button_clicked = 0
        self._set_combo_selection(self.selected_hardware_signer)
        self._apply_state()

    def _analysis_fields(self) -> list[AnalyzerLineEdit | AnalyzerTextEdit]:
        """Return the fields contributing to signer validation state."""
        return [
            self.edit_fingerprint.input_field,
            self.edit_key_origin_input,
            self.edit_xpub.input_field,
        ]

    def get_analysis_list(self, min_state: AnalyzerState = AnalyzerState.Valid) -> list[AnalyzerMessage]:
        """Return analyzer messages for the visible signer detail fields."""
        analysis_list: list[AnalyzerMessage] = []
        for field in self._analysis_fields():
            analyzer = field.analyzer()
            if not analyzer:
                continue
            analysis = analyzer.analyze(field.text())
            if analysis.state >= min_state:
                analysis_list.append(analysis)
        return analysis_list

    def get_worst_analysis(self) -> AnalyzerMessage:
        """Return the most severe analyzer message across the signer details."""
        return BaseAnalyzer.worst_message(self.get_analysis_list())

    def confirm_device_type_selection(self) -> None:
        """Confirm the currently selected signer model."""
        hardware_signer = HardwareSigners.from_id(self.combo_model.currentData())
        if not hardware_signer:
            return
        self.select_hardware_signer(hardware_signer)

    def select_hardware_signer(self, hardware_signer: HardwareSigner) -> None:
        """Select a signer model and move the card into data entry mode."""
        self._device_type_editing = False
        super().set_expanded(True)
        self.counter_register_button_clicked = 0
        self.set_selected_hardware_signer(hardware_signer)
        self.signal_ui_changed.emit()
        self._apply_state()

    def _update_header_icon(self) -> None:
        if self.state == KeyStoreUiState.Add:
            self.header_icon.clear()
            self.header_icon.setStyleSheet("font-size: 28px; font-weight: 600;")
            self.header_icon.setText("+")
            return

        self.header_icon.setStyleSheet("")
        hardware_signer = self.selected_hardware_signer or HardwareSigners.generic
        pixmap = svg_tools_hardware_signer.get_QIcon(hardware_signer.icon_name).pixmap(34, 34)
        self.header_icon.setPixmap(pixmap)
        self.header_icon.setText("")

    def _update_header_subtitle(self) -> None:
        if self.state == KeyStoreUiState.Add:
            self.header_subtitle.setText("-")
            return

        parts = []
        if self.edit_fingerprint.text().strip():
            parts.append(self.edit_fingerprint.text().strip())
        description = self.textEdit_description.toPlainText().strip()
        if description:
            parts.append(description.splitlines()[0])
        self.header_subtitle.setText(" - ".join(parts) if parts else "-")

    def _update_help_visibility(self) -> None:
        visible = bool(
            self.selected_hardware_signer
            and self.selected_hardware_signer.id != HardwareSigners.generic.id
            and self.state != KeyStoreUiState.Add
        )
        self.button_device_instructions.setVisible(visible and self.state != KeyStoreUiState.ReadOnly)
        self.action_device_instructions.setVisible(visible)
        if self.state in (KeyStoreUiState.Empty, KeyStoreUiState.Filled):
            self.connect_help_label.setVisible(visible)

    def _update_connect_buttons(self, connect_visible: bool = True) -> None:
        hardware_signer = self.selected_hardware_signer or HardwareSigners.generic
        self.button_connect_qr.setVisible(connect_visible and hardware_signer.supports_qr)
        self.button_connect_usb.setVisible(
            connect_visible and hardware_signer.usb != FeatureLevel.not_capable
        )
        self.button_connect_import.setVisible(connect_visible)

    def _update_header_status_icon(self) -> None:
        if self.state in (KeyStoreUiState.Add, KeyStoreUiState.Empty):
            self.header_status_icon.setVisible(False)
            return
        analysis = self.get_worst_analysis()
        self.header_status_icon.setPixmap(self._status_pixmaps[analysis.state])
        self.header_status_icon.setToolTip(
            "\n".join(str(item) for item in self.get_analysis_list(min_state=AnalyzerState.Warning))
        )
        self.header_status_icon.setVisible(True)

    def _determine_state(self) -> KeyStoreUiState:
        if not self.selected_hardware_signer:
            return KeyStoreUiState.Add
        if self.read_only_mode:
            return KeyStoreUiState.ReadOnly
        if self._has_complete_signer_data():
            return KeyStoreUiState.Filled
        return KeyStoreUiState.Empty

    def _has_complete_signer_data(self) -> bool:
        return bool(
            self.edit_fingerprint.text().strip() and self.key_origin and self.edit_xpub.text().strip()
        )

    def expand(self) -> None:
        """Show the full signer card."""
        if self.is_expanded:
            return
        super().expand()
        self._apply_state()

    def collapse(self) -> None:
        """Show only the signer card header."""
        if not self.is_expanded:
            return
        super().collapse()
        self._apply_state()

    def _update_header_clickability(self) -> None:
        self._update_header_cursor()

    def _show_seed_input(self) -> bool:
        """Whether the seed row should be visible for the current state and network."""
        if DEMO_MODE:
            return False
        if not self._seed_supported:
            return False
        if self.state in (KeyStoreUiState.Filled, KeyStoreUiState.ReadOnly):
            return True
        return self.state == KeyStoreUiState.Empty and self.network != bdk.Network.BITCOIN

    def _apply_state(self) -> None:
        self._state = self._determine_state()
        is_add_state = self.state == KeyStoreUiState.Add
        show_device_selection = is_add_state or self._device_type_editing
        show_content = self.selected_hardware_signer is not None
        has_details = self.state in (KeyStoreUiState.Filled, KeyStoreUiState.ReadOnly)
        show_seed_input = self._show_seed_input()
        connect_visible = self.state in (KeyStoreUiState.Empty, KeyStoreUiState.Filled)
        show_expanded_content = self.is_expanded and show_content

        self.add_controls_layout.setEnabled(show_device_selection)
        self.combo_brand.setVisible(show_device_selection)
        self.combo_model.setVisible(show_device_selection)
        self.button_confirm_signer.setVisible(show_device_selection)

        self.header_actions_layout.setEnabled(not is_add_state)
        self.button_menu.setVisible(
            not is_add_state and not self._device_type_editing and self.selected_hardware_signer is not None
        )
        self.button_device_instructions.setVisible(
            not self._device_type_editing and self.button_device_instructions.isVisible()
        )
        self.button_register.setVisible(
            self.show_register_button
            and not self._device_type_editing
            and self.state == KeyStoreUiState.ReadOnly
            and self.counter_register_button_clicked == 0
        )
        self.device_type_help_label.setVisible(show_device_selection)
        self.add_controls_widget.setVisible(show_device_selection)
        self.header_actions_widget.setVisible(not is_add_state)

        self.set_body_content_visible(show_content)
        self.left_widget.setVisible(show_expanded_content)
        self.right_widget.setVisible(show_expanded_content)
        self.connect_help_label.setVisible(show_expanded_content and connect_visible)

        for widget in (
            self.label_fingerprint,
            self.edit_fingerprint,
            self.label_key_origin,
            self.edit_key_origin,
            self.label_xpub,
            self.edit_xpub,
            self.label_seed,
            self.edit_seed,
        ):
            widget.setVisible(has_details)

        self.label_seed.setVisible(show_seed_input)
        self.edit_seed.setVisible(show_seed_input)

        read_only_fields = self.state == KeyStoreUiState.ReadOnly
        for field in (self.edit_fingerprint, self.edit_key_origin, self.edit_xpub, self.edit_seed):
            field.setReadOnly(read_only_fields)

        for button in self.edit_seed.button_container.buttons:
            button.setVisible(not read_only_fields and show_seed_input)

        self.header_title.setText(
            self.tr("Add New Signer") if self.state == KeyStoreUiState.Add else self.hardware_signer_label
        )
        self._update_header_icon()
        self._update_connect_buttons(connect_visible=connect_visible)
        self._update_help_visibility()
        if self._device_type_editing:
            self.button_device_instructions.setVisible(False)
        self._update_header_subtitle()
        self.header_subtitle.setVisible(not (show_device_selection and self.header_subtitle.text() == "-"))
        self._update_device_type_help()
        self._update_header_status_icon()
        self._update_header_clickability()

    def _process_input(self, value: str) -> None:
        try:
            res = Data.from_str(value, network=self.network)
            self._on_handle_input(res)
        except Exception as exc:
            Message(str(exc), type=MessageType.Error, parent=self)

    def _import_dialog(self) -> None:
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

    def scan_signer_data_from_qr(self) -> None:
        """Scan signer data from a camera QR code."""
        self.edit_xpub.input_qr_from_camera(self.network, set_data_as_string=False)

    def show_device_instructions(self) -> None:
        """Show device instructions for the selected hardware signer."""
        hardware_signer = self.selected_hardware_signer
        if not hardware_signer or hardware_signer.id == HardwareSigners.generic.id:
            return
        if self._device_help_widget:
            self._device_help_widget.close()
        self._device_help_widget = ScreenshotsExportXpub(hardware_signers=[hardware_signer], parent=None)
        self._device_help_widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._device_help_widget.destroyed.connect(self._clear_device_help_widget)
        self._device_help_widget.setWindowTitle(
            self.tr("{device} instructions").format(device=hardware_signer.display_name)
        )
        self._device_help_widget.setWindowFlag(Qt.WindowType.Window, True)
        self._device_help_widget.show()
        self._device_help_widget.raise_()
        self._device_help_widget.activateWindow()

    def _clear_device_help_widget(self, destroyed_widget: QObject | None = None) -> None:
        """Clear the cached device instructions window after it closes."""
        _ = destroyed_widget
        self._device_help_widget = None

    def _request_show_register_multisig(self) -> None:
        """Request the multisig registration dialog from the owner."""
        self.counter_register_button_clicked += 1
        self._apply_state()
        self.request_show_register_multisig.emit(self.selected_hardware_signer)

    def on_edit_seed_changed(self, text: str) -> None:
        """On edit seed changed."""
        try:
            keystore = self.get_ui_values_as_keystore()
        except Exception as exc:
            logger.debug(f"{self.__class__.__name__}: {exc}")
            Message(str(exc), type=MessageType.Error, parent=self)
            return
        self.edit_fingerprint.setText(keystore.fingerprint)
        self.edit_xpub.setText(keystore.xpub)
        self.key_origin = keystore.key_origin

    def seed_visibility(self, visible: bool = False) -> None:
        """Seed visibility."""
        self.edit_seed.setHidden(not visible)
        self.label_seed.setHidden(not visible)

    @property
    def key_origin(self) -> str:
        """Key origin."""
        try:
            standardized = SimplePubKeyProvider.format_key_origin(self.edit_key_origin.text().strip())
        except Exception as exc:
            logger.debug(f"{self.__class__.__name__}: {exc}")
            return ""
        return standardized

    @key_origin.setter
    def key_origin(self, value: str) -> None:
        """Key origin."""
        self.edit_key_origin.setText(value if value else "")

    def _apply_field_analysis(
        self,
        edit: ButtonEdit,
        text: str,
        analysis: AnalyzerMessage,
        override_state: AnalyzerState | None = None,
        extra_tooltip: str = "",
    ) -> None:
        """Apply analyzer styling and tooltip to a button edit."""
        state = edit.input_field.state_for_text(text=text, analysis=analysis, override_state=override_state)
        edit.format_edit(state)

        tooltip_parts: list[str] = []
        if analysis.msg and analysis.state != AnalyzerState.Valid:
            tooltip_parts.append(analysis.msg)
        if extra_tooltip:
            tooltip_parts.append(extra_tooltip)
        edit.setToolTip("\n".join(tooltip_parts))

    def format_all_fields(self) -> None:
        """Format all fields."""
        self.edit_fingerprint.format_and_apply_validator()
        self.edit_xpub.input_field.normalize()

        expected_key_origin = self.get_expected_key_origin()
        key_origin_value = self.key_origin
        key_origin_analysis = self.edit_key_origin_input.analyze_text(key_origin_value)
        xpub_analysis = self.edit_xpub.input_field.analyze_text(self.edit_xpub.text())

        key_origin_state: AnalyzerState | None = None
        key_origin_tooltip = ""
        xpub_state: AnalyzerState | None = None
        xpub_tooltip = ""

        if expected_key_origin != key_origin_value:
            key_origin_state = key_origin_analysis.state
            key_origin_tooltip = self.tr(
                "Standard for the selected address type {type} is {expected_key_origin}.  Please correct if you are not sure."
            ).format(expected_key_origin=expected_key_origin, type=self.get_address_type().name)

            xpub_state = (
                xpub_analysis.state
                if xpub_analysis.state != AnalyzerState.Valid
                else key_origin_analysis.state
            )
            xpub_tooltip = self.tr(
                "The xPub origin {key_origin} and the xPub belong together. Please choose the correct xPub origin pair."
            ).format(key_origin=key_origin_value)

        self._apply_field_analysis(
            edit=self.edit_key_origin,
            text=self.edit_key_origin.text(),
            analysis=key_origin_analysis,
            override_state=key_origin_state,
            extra_tooltip=key_origin_tooltip,
        )
        self._apply_field_analysis(
            edit=self.edit_xpub,
            text=self.edit_xpub.text(),
            analysis=xpub_analysis,
            override_state=xpub_state,
            extra_tooltip=xpub_tooltip,
        )
        self.edit_key_origin.setPlaceholderText(expected_key_origin)
        self.edit_key_origin_input.reset_memory()
        self.edit_key_origin_input.add_to_memory(expected_key_origin)
        self._update_header_status_icon()

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
            Message(analyzer_message.msg, type=MessageType.Error, parent=self)
            return
        if analyzer_message.state == AnalyzerState.Warning and not question_dialog(
            self.tr("{msg}\nDo you want to proceed anyway?").format(msg=analyzer_message.msg),
        ):
            return

        self.edit_xpub.setText(signer_info.xpub)
        self.key_origin = signer_info.key_origin
        self.edit_fingerprint.setText(signer_info.fingerprint)
        self._apply_state()

    def _on_handle_input(self, data: Data, parent: QLineEdit | QTextEdit | None = None) -> None:
        """On handle input."""
        if data.data_type == DataType.SignerInfo:
            self.set_using_signer_info(data.data)
        elif data.data_type == DataType.SignerInfos and len(data.data) == 1:
            self.set_using_signer_info(data.data[0])
        elif data.data_type == DataType.SignerInfos:
            key_origin = self.get_key_origin()
            matching_signer_infos = [
                signer_info
                for signer_info in data.data
                if isinstance(signer_info, SignerInfo) and signer_info.key_origin == key_origin
            ]

            if len(matching_signer_infos) == 1:
                self.set_using_signer_info(matching_signer_infos[0])
            elif len(matching_signer_infos) > 1:
                self.signal_signer_infos.emit(matching_signer_infos)
            else:
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
        elif data.data_type in [DataType.Descriptor, DataType.MultisigWalletExport]:
            Message(
                self.tr("Please paste descriptors into the descriptor field in the top right."), parent=self
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
            raise ValueError("Could not recognize the QR Code")

    def xpub_validator(self) -> bool:
        """Xpub validator."""
        xpub = self.edit_xpub.text()
        if ConverterXpub.is_slip132(xpub):
            Message(
                self.tr("The xpub is in SLIP132 format. Converting to standard format."),
                title="Converting format",
                parent=self,
            )
            try:
                self.edit_xpub.setText(ConverterXpub.convert_slip132_to_bip32(xpub))
            except Exception as exc:
                logger.debug(f"{self.__class__.__name__}: {exc}")
                return False

        return KeyStore.is_xpub_valid(self.edit_xpub.text(), network=self.network)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.label_description.setText(self.tr("Personal notes:"))
        self.connect_help_label.setText(self.tr("Connect"))
        self.connect_help_label.set_icon_as_help(
            tooltip=self.tr("Import signer data with QR, USB, or text/file import.")
        )
        self.connect_help_label.icon_label.setCursor(Qt.CursorShape.PointingHandCursor)

        self.label_fingerprint.setText(self.tr("Fingerprint"))
        self.label_fingerprint.set_icon_as_help(
            tooltip=self.tr(
                "The 8 digit fingerprint identifies the seed.\nYou can write it onto the hardware signer\nto keep track of different seeds and signing devices."
            )
        )
        self.edit_fingerprint.input_field.display_name = self.label_fingerprint.textLabel.text()

        self.label_key_origin.setText(self.tr("Derivation path"))
        self.label_key_origin.set_icon_as_help(
            tooltip=self.tr(
                "The key origin is needed to construct\ntransactions (PSBTs) correctly and is connected to the xPub."
            )
        )
        self.edit_key_origin_input.display_name = self.label_key_origin.textLabel.text()

        self.label_xpub.setText(self.tr("xPub"))
        self.label_xpub.set_icon_as_help(tooltip=self.tr("Wallet addresses are derived from the xPub."))
        self.edit_xpub.input_field.display_name = self.label_xpub.textLabel.text()

        self.label_seed.setText(self.tr("Seed"))
        self.label_seed.set_icon_as_help(
            tooltip=self.tr(
                "The seed is the secret, that enables transaction signing.\nFor a single signature wallet it gives full control over the funds."
            )
        )
        self.edit_seed.input_field.display_name = self.label_seed.textLabel.text()

        self.header_title.setText(
            self.tr("Add New Signer") if self.state == KeyStoreUiState.Add else self.hardware_signer_label
        )
        self.textEdit_description.setPlaceholderText(
            self.tr("Write here notes relative to this signer, memos, etc...")
        )
        self.combo_brand.setToolTip(self.tr("Select the signer brand"))
        self.combo_model.setToolTip(self.tr("Select the signer model"))
        self.combo_brand.setPlaceholderText(self.tr("Select Brand"))
        self.combo_model.setPlaceholderText(self.tr("Select Model"))
        if self.combo_brand.count():
            self.combo_brand.setItemText(0, self.tr("Select Brand"))
        if self.combo_model.count() and self.combo_model.itemData(0) is None:
            self.combo_model.setItemText(0, self.tr("Select Model"))
        self.button_confirm_signer.setText(self.tr("OK"))
        self.button_device_instructions.setText(self.tr("Device instructions"))
        self.action_device_instructions.setText(self.tr("Device instructions"))
        self.button_register.setText(self.tr("Register"))
        self.action_reregister.setText(self.tr("Reregister multisig"))
        self.action_change_device_type.setText(self.tr("Change device type"))
        self.button_connect_qr.setText(self.tr("QR Code"))
        self.button_connect_usb.setText(self.tr("USB"))
        self.button_connect_import.setText(self.tr("Import"))
        self._update_device_type_help()

        self._update_header_subtitle()
        self._apply_state()

    def _on_hwi_click(self, key_origin: str) -> None:
        """On hwi click."""
        try:
            result = self.usb_gui.get_fingerprint_and_xpub(key_origin=key_origin)
        except Exception as exc:
            logger.debug(f"{self.__class__.__name__}: {exc}")
            Message(
                str(exc)
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
        if not self.textEdit_description.toPlainText().strip():
            self.textEdit_description.setText(f"{device.get('type', '')} - {device.get('model', '')}")

    def on_hwi_click(self) -> None:
        """On hwi click."""
        address_type = self.get_address_type()
        key_origin = address_type.key_origin(self.network)
        self._on_hwi_click(key_origin=key_origin)

    def get_ui_values_as_keystore(self) -> KeyStore:
        """Get ui values as keystore."""
        seed_str = self.edit_seed.text().strip()

        if seed_str:
            mnemonic = str(bdk.Mnemonic.from_string(seed_str))
            key_origin = self.edit_key_origin.text().strip()
            key_origin = key_origin if key_origin else self.get_address_type().key_origin(self.network)
            xpub, fingerprint = derive(mnemonic=mnemonic, key_origin=key_origin, network=self.network)
        else:
            mnemonic = None
            fingerprint = self.edit_fingerprint.text()
            xpub = self.edit_xpub.text()
            key_origin = self.key_origin

            if not KeyStore.is_xpub_valid(xpub, self.network):
                if xpub:
                    raise ValueError(self.tr("{xpub} is not a valid public xpub").format(xpub=xpub))
                raise ValueError(self.tr("Please import the information from all hardware signers first"))

        hardware_signer = self.selected_hardware_signer or HardwareSigners.generic
        return KeyStore(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            mnemonic=mnemonic if mnemonic else None,
            description=self.textEdit_description.toPlainText(),
            hardware_signer_id=hardware_signer.id,
            network=self.network,
        )

    def set_ui_from_keystore(self, keystore: KeyStore) -> None:
        """Set ui from keystore."""
        with BlockChangesSignals([self]):
            self.set_selected_hardware_signer(
                HardwareSigners.from_id(keystore.hardware_signer_id) or HardwareSigners.generic
            )

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

        self._device_type_editing = False
        self._apply_state()

    def close(self) -> bool:
        """Close."""
        SignalTools.disconnect_all_signals_from(self)
        if self._device_help_widget:
            self._device_help_widget.close()
        self.edit_seed.close()
        self.edit_key_origin.close()
        self.edit_fingerprint.close()
        self.edit_key_origin_input.close()
        self.edit_xpub.close()
        return super().close()
