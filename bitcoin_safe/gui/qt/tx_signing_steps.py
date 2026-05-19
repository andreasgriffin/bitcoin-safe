#
# Bitcoin Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging
from dataclasses import dataclass, field
from typing import TypeVar

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from bitcoin_qr_tools.unified_encoder import QrExportType, QrExportTypes
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.dialogs import AutoScanMode
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.card_base import CardBase, CardList
from bitcoin_safe.gui.qt.export_data import ExportDataSimple, FileToolButton, SyncChatToolButton
from bitcoin_safe.gui.qt.qr_components.square_buttons import CloseButton
from bitcoin_safe.gui.qt.signer_ui import SignedUI, SignerUI
from bitcoin_safe.gui.qt.step_progress_bar import StepProgressContainer
from bitcoin_safe.gui.qt.tx_util import get_clients
from bitcoin_safe.gui.qt.util import clear_layout, set_no_margins, svg_tools, svg_tools_hardware_signer
from bitcoin_safe.hardware_signers import FeatureLevel, HardwareSigner, HardwareSigners
from bitcoin_safe.keystore import KeyStore, KeyStoreImporterTypes
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.plugin_framework.plugins.chat_sync.constants import SYNC_CHAT_ICON_NAME
from bitcoin_safe.psbt_util import PartialSig, SimplePSBT
from bitcoin_safe.signals import WalletFunctions
from bitcoin_safe.signer import (
    AbstractSignatureImporter,
    SignatureImporterClipboard,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from bitcoin_safe.wallet import Wallet, get_wallets

logger = logging.getLogger(__name__)
T_AbstractSignatureImporter = TypeVar("T_AbstractSignatureImporter", bound=AbstractSignatureImporter)


@dataclass
class SigningDevice:
    fingerprint: str
    label: str
    hardware_signer: HardwareSigner
    wallet_ids: list[str] = field(default_factory=list)
    has_seed: bool = False
    signatures: dict[int, PartialSig] = field(default_factory=dict)

    @property
    def signature_available(self) -> bool:
        """Whether this device already signed at least one input."""
        return bool(self.signatures)

    @property
    def subtitle(self) -> str:
        """Compact device subtitle for the card header."""
        parts = [self.fingerprint]
        if self.wallet_ids:
            parts.append(", ".join(self.wallet_ids))
        return " - ".join(parts)


def preferred_psbt_qr_type(hardware_signer: HardwareSigner) -> QrExportType | None:
    psbt_qr_type_names = {item.name for item in QrExportTypes.as_list()}
    psbt_qr_types = [qr_type for qr_type in hardware_signer.qr_types if qr_type.name in psbt_qr_type_names]
    for qr_type in psbt_qr_types:
        if qr_type.name == QrExportTypes.bbqr.name:
            return qr_type
    return psbt_qr_types[0] if psbt_qr_types else None


def allows_psbt_qr_type_choice(hardware_signer: HardwareSigner) -> bool:
    return hardware_signer.id == HardwareSigners.generic.id


def format_signed_signature_lines(translator: QWidget, signatures: dict[int, PartialSig]) -> str:
    """Format individual input signatures for signed-state summaries."""
    return "\n".join(
        [
            translator.tr("Input {i}: Signed with flag {sighash_type} , Signature: {signature}").format(
                i=i,
                sighash_type=partial_sig.sighash_type,
                signature=partial_sig.signature,
            )
            for i, partial_sig in signatures.items()
        ]
    )


def format_signed_summary_text(
    translator: QWidget,
    label: str,
    signatures: dict[int, PartialSig],
) -> str:
    """Format the complete signed-state summary text."""
    return translator.tr(
        "Transaction signed with the private key belonging to {label}\n\nSignatures:\n{signatures}\n\n\n"
    ).format(
        label=label,
        signatures=format_signed_signature_lines(translator=translator, signatures=signatures),
    )


class ExportImportUI(QWidget):
    def __init__(
        self,
        export_button: FileToolButton | SyncChatToolButton,
        import_widget: SignerUI,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.export_button = export_button
        self.import_widget = import_widget
        self.export_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.import_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.import_widget.button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        set_no_margins(layout)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(export_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(import_widget, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.import_widget.setEnabled(False)
        self.export_button.signal_exported.connect(self.on_exported)

    def on_exported(self) -> None:
        """Unlock the import step after the unsigned PSBT was exported."""
        self.export_button.setIcon(svg_tools.get_QIcon("checkmark.svg"))
        self.import_widget.setEnabled(True)


class TxSigningDeviceCard(CardBase):
    signal_collapse_requested = pyqtSignal()

    def __init__(
        self,
        device: SigningDevice,
        signature_importers: list[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.device = device
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network
        self.wallet_functions = wallet_functions
        self.loop_in_thread = loop_in_thread
        self.qr_export_widget: ExportDataSimple | None = None

        self.set_title(device.label)
        self.set_subtitle(device.subtitle)
        self.set_icon(svg_tools_hardware_signer.get_QIcon(device.hardware_signer.icon_name))

        self.button_sign = QPushButton(self.header_right_widget)
        self.button_sign.clicked.connect(self.signal_expand_requested.emit)
        self.header_right_layout.addWidget(self.button_sign)

        self.label_signed = QLabel(self.header_right_widget)
        self.header_right_layout.addWidget(self.label_signed)

        self.button_close = CloseButton(parent=self.header_right_widget)
        self.button_close.clicked.connect(self._collapse_from_header)
        self.header_right_layout.addWidget(self.button_close)

        self.body = QWidget(self.content_widget)
        self.body.setObjectName(f"{self.__class__.__name__}.body")
        self.body_layout = QVBoxLayout(self.body)
        set_no_margins(self.body_layout)
        self.set_content_widget(self.body)

        self._show_initial_body()
        self.collapse()
        self.updateUi()

    def expand(self) -> None:
        """Expand and show the correct first body for this device state."""
        super().expand()
        if self.device.signature_available:
            self._show_signature_details()
        else:
            self._show_connection_choices()
        self._update_header_actions()

    def collapse(self) -> None:
        """Collapse and reset the body back to its first screen."""
        super().collapse()
        self._show_initial_body()
        self._update_header_actions()

    def updateUi(self) -> None:
        """Update visible texts."""
        self.button_sign.setText(self.tr("Sign with this device"))
        self.label_signed.setText(self.tr("Signed"))
        self.button_close.setToolTip(self.tr("Collapse"))
        self._update_header_actions()

    def _update_header_actions(self) -> None:
        self.button_close.setVisible(self.is_expanded)
        self.button_sign.setVisible(not self.device.signature_available and not self.is_expanded)
        self.label_signed.setVisible(self.device.signature_available and not self.is_expanded)

    def _collapse_from_header(self) -> None:
        self.collapse()
        self.signal_collapse_requested.emit()

    def _show_initial_body(self) -> None:
        if self.device.signature_available:
            self._show_signature_details()
        else:
            self._show_connection_choices()

    def _show_signature_details(self) -> None:
        clear_layout(self.body_layout)
        self.body_layout.addWidget(
            SignedUI(
                text=format_signed_summary_text(
                    translator=self,
                    label=self.device.fingerprint or self.device.label,
                    signatures=self.device.signatures,
                ),
                psbt=self.psbt,
                network=self.network,
                parent=self.body,
            )
        )
        self._body_layout_changed()

    def _show_connection_choices(self) -> None:
        clear_layout(self.body_layout)
        row = QWidget(self.body)
        # Keep action rows compact even when the expanded card gets extra height.
        row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row_layout = QHBoxLayout(row)
        row_layout.setSpacing(16)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        row_layout.addStretch()
        for label, button in self._connection_buttons():
            group = QWidget(row)
            group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            group_layout = QVBoxLayout(group)
            set_no_margins(group_layout)
            group_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label_widget = QLabel(label, group)
            label_widget.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            group_layout.addWidget(label_widget, alignment=Qt.AlignmentFlag.AlignHCenter)
            group_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
            row_layout.addWidget(group, alignment=Qt.AlignmentFlag.AlignTop)

        self.body_layout.addWidget(row, alignment=Qt.AlignmentFlag.AlignCenter)
        self._body_layout_changed()

    def _connection_buttons(self) -> list[tuple[str, QPushButton | QToolButton]]:
        buttons: list[tuple[str, QPushButton | QToolButton]] = []

        if self._qr_importer() and self._preferred_qr_type():
            button_qr = self._action_button(
                self.tr("Show QR Code"),
                KeyStoreImporterTypes.qr.icon_filename,
            )
            button_qr.clicked.connect(self._show_qr_detail)
            buttons.append((self.tr("Sign via QR"), button_qr))

        if self._usb_importer() and self.device.hardware_signer.usb != FeatureLevel.not_capable:
            button_usb = self._action_button(
                self.tr("Detect Device"),
                KeyStoreImporterTypes.hwi.icon_filename,
            )
            button_usb.clicked.connect(self._sign_with_usb)
            buttons.append((self.tr("Sign via USB"), button_usb))

        if self._usb_importer() and self.device.hardware_signer.bluetooth != FeatureLevel.not_capable:
            button_bluetooth = self._action_button(
                self.tr("Detect Device"),
                KeyStoreImporterTypes.bluetooth.icon_filename,
            )
            button_bluetooth.clicked.connect(self._sign_with_bluetooth)
            buttons.append((self.tr("Sign via Bluetooth"), button_bluetooth))

        if self._file_importer():
            button_file = self._action_button(
                self.tr("Export / Import"),
                KeyStoreImporterTypes.file.icon_filename,
            )
            button_file.clicked.connect(self._show_file_detail)
            buttons.append((self.tr("Sign via File"), button_file))

        if self._clipboard_importer():
            button_share = self._action_button(self.tr("Share with..."), icon_name=SYNC_CHAT_ICON_NAME)
            button_share.clicked.connect(self._show_share_detail)
            buttons.append((self.tr("Sign via Chat&Sync"), button_share))

        if self.device.has_seed and self._wallet_importer():
            button_seed = self._action_button(
                self.tr("Sign now"),
                KeyStoreImporterTypes.seed.icon_filename,
            )
            button_seed.clicked.connect(self._sign_with_seed)
            buttons.append((self.tr("Use Wallet Seed"), button_seed))

        for _, button in buttons:
            button.setObjectName(str(id(button)))
            button.setStyleSheet(f"#{button.objectName()} {{ padding: 5px 16px; }}")
            button.setIconSize(QSize(22, 22))

            font = button.font()
            font.setPointSizeF(font.pointSizeF() * 1.1)
            button.setFont(font)

        return buttons

    def _action_button(self, text: str, icon_name: str) -> QPushButton:
        button = QPushButton(text, self.body)
        button.setIcon(svg_tools.get_QIcon(icon_name))
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    def _show_qr_detail(self) -> None:
        qr_importer = self._qr_importer()
        qr_type = self._preferred_qr_type()
        if not qr_importer or not qr_type:
            return
        self._show_qr_export_widget(qr_type)
        signer_ui = SignerUI(qr_importer, self.psbt, self.network)
        signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
        self._show_detail_widget(signer_ui)

    def _show_qr_export_widget(self, qr_type: QrExportType) -> None:
        """Show the QR export popup using the preferred type for this signer."""
        export_widget = self._get_qr_export_widget()
        export_widget.combo_qr_type.select_export_type(qr_type)
        export_widget.combo_qr_type.setVisible(allows_psbt_qr_type_choice(self.device.hardware_signer))
        export_widget.show()

    def _get_qr_export_widget(self) -> ExportDataSimple:
        """Create the reusable QR export popup on first use."""
        if self.qr_export_widget:
            return self.qr_export_widget

        self.qr_export_widget = ExportDataSimple(
            data=Data.from_psbt(self.psbt, network=self.network),
            signals_min=self.wallet_functions.signals,
            enable_clipboard=False,
            enable_usb=False,
            enable_file=False,
            enable_qr=True,
            network=self.network,
            loop_in_thread=self.loop_in_thread,
        )
        self.qr_export_widget.set_minimum_size_as_floating_window()
        return self.qr_export_widget

    def _show_file_detail(self) -> None:
        file_importer = self._file_importer()
        if not file_importer:
            return
        signer_ui = SignerUI(file_importer, self.psbt, self.network, button_prefix="2. ")
        signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
        self._show_detail_widget(
            ExportImportUI(
                FileToolButton(
                    data=Data.from_psbt(self.psbt, network=self.network),
                    wallet_id=None,
                    network=self.network,
                    parent=self.body,
                    button_prefix="1. ",
                ),
                signer_ui,
                parent=self.body,
            )
        )

    def _show_share_detail(self) -> None:
        clipboard_importer = self._clipboard_importer()
        if not clipboard_importer:
            return
        signer_ui = SignerUI(clipboard_importer, self.psbt, self.network, button_prefix="2. ")
        signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
        self._show_detail_widget(
            ExportImportUI(
                SyncChatToolButton(
                    data=Data.from_psbt(self.psbt, network=self.network),
                    network=self.network,
                    sync_client=get_clients(wallet_functions=self.wallet_functions, cls=SyncClient),
                    parent=self.body,
                    button_prefix="1. ",
                ),
                signer_ui,
                parent=self.body,
            )
        )

    def _show_detail_widget(self, widget: QWidget) -> None:
        clear_layout(self.body_layout)
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.body_layout.addStretch()
        self.body_layout.addWidget(
            widget,
            alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        )
        self.body_layout.addStretch()
        self._body_layout_changed()

    def _body_layout_changed(self) -> None:
        self.updateGeometry()

    def _sign_with_usb(self) -> None:
        usb_importer = self._usb_importer()
        if usb_importer:
            usb_importer.sign(self.psbt, autoscan_mode=AutoScanMode.USB)

    def _sign_with_bluetooth(self) -> None:
        usb_importer = self._usb_importer()
        if usb_importer:
            usb_importer.sign(self.psbt, autoscan_mode=AutoScanMode.BLUETOOTH)

    def _sign_with_seed(self) -> None:
        wallet_importer = self._wallet_importer()
        if wallet_importer:
            wallet_importer.sign(self.psbt)

    def _preferred_qr_type(self) -> QrExportType | None:
        return preferred_psbt_qr_type(self.device.hardware_signer)

    def _qr_importer(self) -> SignatureImporterQR | None:
        return self._exact_importer(SignatureImporterQR)

    def _file_importer(self) -> SignatureImporterFile | None:
        return self._exact_importer(SignatureImporterFile)

    def _clipboard_importer(self) -> SignatureImporterClipboard | None:
        for importer in self.signature_importers:
            if isinstance(importer, SignatureImporterClipboard):
                return importer
        return None

    def _usb_importer(self) -> SignatureImporterUSB | None:
        return self._exact_importer(SignatureImporterUSB)

    def _wallet_importer(self) -> SignatureImporterWallet | None:
        for importer in self.signature_importers:
            if isinstance(importer, SignatureImporterWallet):
                return importer
        return None

    def _exact_importer(self, cls: type[T_AbstractSignatureImporter]) -> T_AbstractSignatureImporter | None:
        for importer in self.signature_importers:
            if type(importer) is cls:
                return importer
        return None


class TxSigningDeviceList(QWidget):
    def __init__(
        self,
        devices: list[SigningDevice],
        signature_importers: list[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent)
        self.devices = devices
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network
        self.wallet_functions = wallet_functions
        self.loop_in_thread = loop_in_thread
        self.cards: list[TxSigningDeviceCard] = []

        layout = QVBoxLayout(self)
        set_no_margins(layout)
        self.card_list = CardList(self)
        self.card_list.set_only_one_expanded_at_a_time(True)
        layout.addWidget(self.card_list)

        for device in devices:
            card = TxSigningDeviceCard(
                device=device,
                signature_importers=signature_importers,
                psbt=psbt,
                network=network,
                wallet_functions=wallet_functions,
                loop_in_thread=loop_in_thread,
                parent=self,
            )
            self.cards.append(card)
            self.card_list.add_card(card)

        self.card_list.collapse_all()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


class TxSigningSteps(StepProgressContainer):
    def __init__(
        self,
        signature_importer_dict: dict[str, list[AbstractSignatureImporter]],
        psbt: bdk.Psbt,
        network: bdk.Network,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize instance."""
        step_labels = [self.tr("Signature {n}").format(n=i + 1) for i in range(len(signature_importer_dict))]
        self.sub_indices: list[int] = []
        self._allow_lazy_step_widget_creation = False

        super().__init__(
            step_labels=step_labels,
            parent=parent,
            use_resizing_stacked_widget=False,
            signals_min=wallet_functions.signals,
            loop_in_thread=loop_in_thread,
            clickable=False,
        )

        self.psbt = psbt
        self.network = network
        self.wallet_functions = wallet_functions
        self.signature_importer_dict = signature_importer_dict
        self.signature_importer_steps = list(signature_importer_dict.values())
        self.signing_devices = self._collect_signing_devices()
        self._initialized_step_widgets: set[int] = set()
        self._allow_lazy_step_widget_creation = True

        first_non_signed_index = None
        for i, signature_importer_list in enumerate(self.signature_importer_steps):
            if not signature_importer_list:
                continue
            if first_non_signed_index is None and not any(
                importer.signature_available for importer in signature_importer_list
            ):
                first_non_signed_index = i

        if first_non_signed_index is not None:
            self.set_current_index(first_non_signed_index)
        else:
            self._ensure_step_widget(self.current_index())

    def set_current_index(self, index: int) -> None:
        """Set current index."""
        if self._allow_lazy_step_widget_creation:
            self._ensure_step_widget(index)
        super().set_current_index(index)

    def go_to_next_index(self) -> None:
        """Go to next index."""
        if self.current_index() + 1 < self.count():
            self.set_current_index(self.current_index() + 1)

    def go_to_previous_index(self) -> None:
        """Go to previous index."""
        self.step_bar.set_mark_current_step_as_completed(False)
        if self.current_index() - 1 >= 0:
            self.set_current_index(self.current_index() - 1)

    def create_export_import_widget(self, signature_importers: list[AbstractSignatureImporter]) -> QWidget:
        """Create the card-based signing widget for one progress step."""
        if not signature_importers:
            return QWidget()
        return TxSigningDeviceList(
            devices=self.signing_devices,
            signature_importers=signature_importers,
            psbt=self.psbt,
            network=self.network,
            wallet_functions=self.wallet_functions,
            loop_in_thread=self.loop_in_thread,
            parent=self,
        )

    def _ensure_step_widget(self, index: int) -> None:
        """Create the heavy step widget only when that step becomes accessible."""
        if index in self._initialized_step_widgets:
            return
        if not (0 <= index < len(self.signature_importer_steps)):
            return

        self.set_custom_widget(index, self.create_export_import_widget(self.signature_importer_steps[index]))
        self._initialized_step_widgets.add(index)

    def _collect_signing_devices(self) -> list[SigningDevice]:
        """Collect every relevant device from the wallets touched by this PSBT."""
        devices = self._collect_wallet_devices()
        self._apply_signature_importer_details(devices)
        self._apply_psbt_signature_details(devices)
        if not devices:
            devices[""] = SigningDevice(
                fingerprint="",
                label=self.tr("Signing Device"),
                hardware_signer=HardwareSigners.generic,
            )
        self._apply_seed_importer_availability(devices)
        return list(devices.values())

    def _collect_wallet_devices(self) -> dict[str, SigningDevice]:
        devices: dict[str, SigningDevice] = {}
        for wallet in self._involved_wallets():
            for index, keystore in enumerate(wallet.keystores):
                fingerprint = self._normalize_fingerprint(keystore.fingerprint)
                if not fingerprint:
                    continue
                hardware_signer = (
                    HardwareSigners.from_id(keystore.hardware_signer_id) or HardwareSigners.generic
                )
                device = devices.get(fingerprint)
                if not device:
                    device = SigningDevice(
                        fingerprint=fingerprint,
                        label=keystore.hardware_signer_label(
                            fallback_name=wallet.signer_fallback_name(index)
                        ),
                        hardware_signer=hardware_signer,
                        has_seed=bool(keystore.mnemonic),
                    )
                    devices[fingerprint] = device
                device.has_seed = device.has_seed or bool(keystore.mnemonic)
                if wallet.id not in device.wallet_ids:
                    device.wallet_ids.append(wallet.id)

        if devices:
            return devices
        return self._collect_generic_psbt_devices()

    def _involved_wallets(self) -> list[Wallet]:
        involved_wallets = self._wallets_from_signature_importers()
        if involved_wallets:
            return involved_wallets

        inputs = self.psbt.extract_tx().input()
        for wallet in get_wallets(self.wallet_functions):
            txos = wallet.get_all_txos_dict()
            if any(str(txin.previous_output) in txos for txin in inputs) and wallet not in involved_wallets:
                involved_wallets.append(wallet)
        return involved_wallets

    def _wallets_from_signature_importers(self) -> list[Wallet]:
        involved_wallets: list[Wallet] = []
        signer_fingerprints: set[str] = set()
        for signature_importers in self.signature_importer_dict.values():
            for importer in signature_importers:
                # Example: wallet_id="vault", fingerprint="ABCD1234", hardware_signer=jade.
                # Seed path: SignatureImporterWallet already points to the wallet. Reason: use it directly.
                if isinstance(importer, SignatureImporterWallet) and importer.wallet not in involved_wallets:
                    involved_wallets.append(importer.wallet)
                # Non-seed path: QR/file importer still carries fingerprint="ABCD1234".
                # Reason: keep enough data to find the same wallet later.
                signer_fingerprints.update(
                    normalized_fingerprint
                    for signer_identity in importer.signer_identities
                    if (normalized_fingerprint := self._normalize_fingerprint(signer_identity.fingerprint))
                )

        if not signer_fingerprints:
            return involved_wallets

        for wallet in get_wallets(self.wallet_functions):
            if wallet in involved_wallets:
                continue
            # Match wallet.keystore.fingerprint="ABCD1234" back to wallet_id="vault".
            # Reason: preserve the wallet's jade label/icon for non-seed signing too.
            if any(
                self._normalize_fingerprint(keystore.fingerprint) in signer_fingerprints
                for keystore in wallet.keystores
            ):
                involved_wallets.append(wallet)
        return involved_wallets

    def _collect_generic_psbt_devices(self) -> dict[str, SigningDevice]:
        devices: dict[str, SigningDevice] = {}
        simple_psbt = SimplePSBT.from_psbt(self.psbt)
        for simple_input in simple_psbt.inputs:
            for pubkey_info in simple_input.pubkeys:
                if not pubkey_info.signer_id or pubkey_info.signer_id in devices:
                    continue
                fingerprint = self._normalize_fingerprint(pubkey_info.fingerprint)
                label = (
                    pubkey_info.label
                    or fingerprint
                    or pubkey_info.pubkey
                    or HardwareSigners.generic.display_name
                )
                devices[pubkey_info.signer_id] = SigningDevice(
                    fingerprint=fingerprint,
                    label=label,
                    hardware_signer=HardwareSigners.generic,
                )
        return devices

    def _apply_signature_importer_details(self, devices: dict[str, SigningDevice]) -> None:
        for signature_importers in self.signature_importer_dict.values():
            for importer in signature_importers:
                if not importer.signature_available:
                    continue
                for signer_identity in importer.signer_identities:
                    fingerprint = self._normalize_fingerprint(signer_identity.fingerprint)
                    if not signer_identity.id:
                        continue
                    if signer_identity.id not in devices:
                        devices[signer_identity.id] = SigningDevice(
                            fingerprint=fingerprint,
                            label=signer_identity.display_name
                            or importer.display_label
                            or HardwareSigners.generic.display_name,
                            hardware_signer=HardwareSigners.generic,
                        )
                    if importer.signatures:
                        devices[signer_identity.id].signatures.update(importer.signatures)

    def _apply_psbt_signature_details(self, devices: dict[str, SigningDevice]) -> None:
        simple_psbt = SimplePSBT.from_psbt(self.psbt)
        for input_index, simple_input in enumerate(simple_psbt.inputs):
            for pubkey_info in simple_input.pubkeys:
                if pubkey_info.signer_id not in devices or not pubkey_info.pubkey:
                    continue
                partial_sig = simple_input.partial_sigs.get(pubkey_info.pubkey)
                if partial_sig:
                    devices[pubkey_info.signer_id].signatures[input_index] = partial_sig

    def _apply_seed_importer_availability(self, devices: dict[str, SigningDevice]) -> None:
        if any(device.has_seed for device in devices.values()):
            return
        if not any(
            isinstance(importer, SignatureImporterWallet)
            for signature_importers in self.signature_importer_dict.values()
            for importer in signature_importers
        ):
            return
        for device in devices.values():
            device.has_seed = True
            return

    @staticmethod
    def _normalize_fingerprint(fingerprint: str | None) -> str:
        if not fingerprint:
            return ""
        if not KeyStore.is_fingerprint_valid(fingerprint):
            return ""
        return KeyStore.format_fingerprint(fingerprint)


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    sys.exit(app.exec())
