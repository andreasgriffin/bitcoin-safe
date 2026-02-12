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

import json
import logging
import os
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import cast

import bdkpython as bdk
from bitcoin_nostr_chat.chat_dm import ChatDM, ChatLabel
from bitcoin_qr_tools.data import ConverterSignMessageRequest, Data, DataType
from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_qr_tools.unified_encoder import QrExportType, QrExportTypes, UnifiedEncoder
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from nostr_sdk import PublicKey
from PyQt6.QtCore import QLocale, QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QShowEvent
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.descriptor_export_tools import DescriptorExportTools, shorten_filename
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate
from bitcoin_safe.pdfrecovery import DataExportPDF
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.tx import short_tx_id, transaction_to_dict
from bitcoin_safe.util import filename_clean

from ...hardware_signers import (
    DescriptorExportType,
    DescriptorExportTypes,
    DescriptorQrExportTypes,
    HardwareSigner,
    HardwareSigners,
    SignMessageRequestQrExportTypes,
)
from ...signals import SignalsMin
from .util import (
    Message,
    MessageType,
    do_copy,
    save_file_dialog,
    svg_tools_hardware_signer,
)

logger = logging.getLogger(__name__)


class DataGroupBox(QGroupBox):
    def __init__(self, title: str | None = None, parent=None, data=None) -> None:
        """Initialize instance."""
        super().__init__(title=title if title else "", parent=parent)
        self.data = data
        self._layout: QVBoxLayout | QHBoxLayout = QVBoxLayout()

    def set_layout(self, layout_cls: QVBoxLayout | QHBoxLayout):
        """Set layout."""
        self._layout = layout_cls
        self.setLayout(self._layout)

    def setData(self, data) -> None:
        """SetData."""
        self.data = data


def pretty_name(data_type: DataType) -> str:
    """Pretty name."""
    if data_type == DataType.PSBT:
        return translate("general", "PSBT")
    if data_type == DataType.Tx:
        return translate("general", "Transaction")
    return ""


def get_txid(data: Data) -> str | None:
    """Get txid."""
    if data.data_type == DataType.PSBT:
        if not isinstance(data.data, bdk.Psbt):
            logger.error("data is not of type bdk.Psbt")
            return None
        return str(data.data.extract_tx().compute_txid())
    elif data.data_type == DataType.Tx:
        if not isinstance(data.data, bdk.Transaction):
            logger.error("data is not of type bdk.Transaction")
            return None
        return str(data.data.compute_txid())
    return None


def get_json_data(data: Data, network: bdk.Network) -> str | None:
    """Get json data."""
    if data.data_type == DataType.PSBT:
        if not isinstance(data.data, bdk.Psbt):
            logger.error("data is not of type bdk.Psbt")
            return None
        return json.dumps(json.loads(data.data.json_serialize()), indent=4)
    elif data.data_type == DataType.Tx:
        if not isinstance(data.data, bdk.Transaction):
            logger.error("data is not of type bdk.Transaction")
            return None
        return json.dumps(transaction_to_dict(data.data, network=network), indent=4)
    return None


def get_export_display_name(export_type: DescriptorExportType | QrExportType) -> str:
    """Get export display name."""
    parts = [export_type.display_name]
    filtered_hardware_signers = HardwareSigners.filtered_by([export_type])  # type:ignore

    hardware_names = ", ".join(
        [hardware_signer.display_name for hardware_signer in filtered_hardware_signers]
    )
    if hardware_names:
        parts += [hardware_names]
    return " - ".join(parts)


def get_export_icon(export_type: DescriptorExportType | QrExportType) -> QIcon:
    """Get export icon."""
    filtered_hardware_signers = HardwareSigners.filtered_by([export_type])  # type:ignore
    if filtered_hardware_signers:
        filtered_hardware_signer = filtered_hardware_signers[0]
        return svg_tools_hardware_signer.get_QIcon(filtered_hardware_signer.icon_name)
    else:
        return QIcon()


class FileToolButton(QToolButton):
    def __init__(
        self,
        data: Data,
        network: bdk.Network,
        wallet_id: str | None = None,
        parent: QWidget | None = None,
        button_prefix: str = "",
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.wallet_id = wallet_id
        self.network = network
        self.button_prefix = button_prefix

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(svg_tools.get_QIcon("bi--download.svg"))

        self.set_data(data=data)
        self.updateUi()

    def _fill_menu(self):
        """Fill menu."""
        self._menu.clear()
        with QSignalBlocker(self._menu):
            if self.data.data_type in [DataType.Descriptor] and isinstance(self.data.data, bdk.Descriptor):
                self.fill_file_menu_descriptor_export_actions(
                    self._menu,
                    self.wallet_id if self.wallet_id else "descriptor",
                    multipath_descriptor=self.data.data,
                    network=self.network,
                )
            else:
                self.fill_file_menu_export_actions(self._menu)

    def export_to_file(self, default_filename=None) -> str | None:
        """Export to file."""
        default_suffix = "txt"
        if self.data.data_type == DataType.Tx:
            default_suffix = "tx"
        if self.data.data_type == DataType.PSBT:
            default_suffix = "psbt"

        txid = get_txid(self.data)
        if not default_filename and txid:
            default_filename = f"{short_tx_id(txid)}.{default_suffix}"
        if not default_filename and self.data.data_type in [
            DataType.Descriptor,
        ]:
            default_filename = (
                (f"{filename_clean(self.wallet_id, file_extension='', replace_spaces_by='_')}.txt")
                if self.wallet_id
                else "descriptor.txt"
            )

        filename = save_file_dialog(
            name_filters=[
                f"{default_suffix.upper()} Files (*.{default_suffix})",
                "All Files (*.*)",
            ],
            default_suffix=default_suffix,
            default_filename=default_filename,
        )
        if not filename:
            return None

        # create a file descriptor
        fd = os.open(filename, os.O_CREAT | os.O_WRONLY)

        self.data.write_to_filedescriptor(fd)
        return filename

    def export_to_pdf(self, filepath: Path | None = None) -> str | None:
        """Export the serialized data into a PDF with BBQr codes."""
        if self.data.data_type not in [DataType.Tx, DataType.PSBT]:
            Message(self.tr("PDF export is only available for transactions or PSBTs."), parent=self)
            return None

        if not self.serialized:
            Message(self.tr("Not available"), parent=self)
            return None

        default_filename = f"{short_tx_id(self.txid)}.pdf" if self.txid else None
        if not default_filename:
            default_filename = f"transaction_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        elif not default_filename.lower().endswith(".pdf"):
            default_filename = f"{default_filename}.pdf"

        filepath = filepath if filepath else Path.home() / default_filename

        qr_fragments = UnifiedEncoder.generate_fragments_for_qr(
            data=self.data, qr_export_type=QrExportTypes.bbqr
        )
        qr_images = [QRGenerator.create_qr_PILimage(fragment) for fragment in qr_fragments]

        ur_fragments = UnifiedEncoder.generate_fragments_for_qr(
            data=self.data, qr_export_type=QrExportTypes.ur
        )
        ur_qr_images = [QRGenerator.create_qr_PILimage(fragment) for fragment in ur_fragments]

        pdf = DataExportPDF(lang_code=QLocale().name())
        pdf.create_pdf(
            title=self.tr("Transaction export"),
            txid=self.txid,
            serialized=self.serialized,
            data_label=pretty_name(self.data.data_type),
            qr_images=qr_images,
            ur_qr_images=ur_qr_images,
        )
        pdf.save_pdf(str(filepath))
        pdf.open_pdf(str(filepath))
        return str(filepath)

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setText(self.button_prefix + self.tr("Export"))
        self.action_copy_data.setText(
            self.tr("Copy {name}").format(name=pretty_name(data_type=self.data.data_type))
        )
        self.action_copy_txid.setText(self.tr("Copy TxId"))
        self.action_json.setText(self.tr("Copy JSON"))

    def set_data(self, data: Data):
        """Set data."""
        self.data = data
        self.serialized = data.data_as_string()
        self.txid = get_txid(data)
        self.json_data = get_json_data(data, network=self.network)
        self._fill_menu()
        self.updateUi()

    @classmethod
    def _save_file(
        cls,
        wallet_id: str,
        multipath_descriptor: bdk.Descriptor,
        network: bdk.Network,
        descripor_type: DescriptorExportType,
    ):
        """Save file."""
        return DescriptorExportTools.export(
            wallet_id=wallet_id,
            multipath_descriptor=multipath_descriptor,
            network=network,
            descripor_type=descripor_type,
        )

    def fill_file_menu_descriptor_export_actions(
        self,
        menu: Menu,
        wallet_id: str,
        multipath_descriptor: bdk.Descriptor,
        network: bdk.Network,
    ):
        """Fill file menu descriptor export actions."""
        with QSignalBlocker(menu):
            menu.clear()

            for export_type in DescriptorExportTypes.as_list():
                menu.add_action(
                    get_export_display_name(export_type=export_type),
                    partial(
                        self._save_file,
                        wallet_id=wallet_id,
                        multipath_descriptor=multipath_descriptor,
                        network=network,
                        descripor_type=export_type,
                    ),
                    icon=get_export_icon(export_type=export_type),
                )
            menu.addSeparator()
            self.action_copy_data = menu.add_action(
                "", self.on_action_copy_data, icon=svg_tools.get_QIcon("bi--copy.svg")
            )
            self.action_copy_txid = menu.add_action(
                "", self.on_action_copy_txid, icon=svg_tools.get_QIcon("bi--copy.svg")
            )
            self.action_copy_txid.setVisible(False)
            self.action_json = menu.add_action(
                "", self.on_action_json, icon=svg_tools.get_QIcon("bi--copy.svg")
            )
            self.action_json.setVisible(False)

    def fill_file_menu_export_actions(
        self,
        menu: Menu,
    ):
        """Fill file menu export actions."""
        file_icon = svg_tools.get_QIcon("bi--download.svg")
        with QSignalBlocker(menu):
            menu.clear()
            menu.add_action(
                self.tr("Export to file"),
                self.export_to_file,
                icon=file_icon,
            )

            self.action_pdf_export = menu.add_action(
                self.tr("PDF Export"),
                self.export_to_pdf,
                icon=svg_tools.get_QIcon("bi--filetype-pdf.svg"),
            )
            self.action_pdf_export.setVisible(self.data.data_type in [DataType.Tx, DataType.PSBT])

            menu.addSeparator()

            self.action_copy_data = menu.add_action(
                "", self.on_action_copy_data, icon=svg_tools.get_QIcon("bi--copy.svg")
            )
            self.action_copy_txid = menu.add_action(
                "", self.on_action_copy_txid, icon=svg_tools.get_QIcon("bi--copy.svg")
            )
            self.action_json = menu.add_action(
                "", self.on_action_json, icon=svg_tools.get_QIcon("bi--copy.svg")
            )

    def copy_if_available(self, s: str | None) -> None:
        """Copy if available."""
        if s:
            do_copy(s)
        else:
            Message(self.tr("Not available"), parent=self)

    def on_action_copy_data(self):
        """On action copy data."""
        return self.copy_if_available(self.serialized)

    def on_action_copy_txid(self):
        """On action copy txid."""
        return self.copy_if_available(self.txid)

    def on_action_json(self):
        """On action json."""
        return self.copy_if_available(self.json_data)


class SyncChatToolButton(QToolButton):
    def __init__(
        self,
        data: Data,
        network: bdk.Network,
        sync_client: dict[str, SyncClient] | None = None,
        parent: QWidget | None = None,
        button_prefix: str = "",
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.sync_clients = sync_client
        self.network = network
        self.button_prefix = button_prefix
        self._set_data(data=data, sync_clients=sync_client)

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self._menu.aboutToShow.connect(self._fill_menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(svg_tools.get_QIcon("bi--cloud.svg"))

        self.updateUi()

    def _share_with_device(
        self, wallet_id: str, sync_client: SyncClient, receiver_public_key_bech32: str | None = None
    ) -> None:
        """Share with device."""
        if not sync_client.enabled:
            Message(self.tr("Please enable the sync tab first"), parent=self)
            return
        if receiver_public_key_bech32:
            self.on_nostr_share_with_member(
                PublicKey.parse(receiver_public_key_bech32), wallet_id, sync_client
            )
        else:
            self.on_nostr_share_in_group(wallet_id, sync_client)

    def _fill_menu(self):
        """Fill menu."""
        menu = self._menu
        menu.clear()
        if not self.sync_clients:
            return

        # Create a menu for the button
        for wallet_id, sync_client in self.sync_clients.items():
            action_alldevices = partial(
                self._share_with_device,
                wallet_id=wallet_id,
                sync_client=sync_client,
                receiver_public_key_bech32=None,
            )
            menu.add_action(
                self.tr("Share with all devices in {wallet_id}").format(wallet_id=wallet_id),
                action_alldevices,
            )

            sub_menu = menu.add_menu(self.tr("Share with single device"))
            for member in sync_client.nostr_sync.group_chat.members:
                action = partial(
                    self._share_with_device,
                    wallet_id=wallet_id,
                    sync_client=sync_client,
                    receiver_public_key_bech32=member.to_bech32(),
                )
                sub_menu.add_action(f"{sync_client.nostr_sync.chat.get_alias(member)}", action)

            menu.addSeparator()

        self.updateUi()

    def _set_data(self, data: Data, sync_clients: dict[str, SyncClient] | None) -> None:
        """Set data."""
        self.data = data
        self.sync_clients = sync_clients

    def set_data(self, data: Data, sync_clients: dict[str, SyncClient] | None):
        """Set data."""
        self._set_data(data=data, sync_clients=sync_clients)
        self._menu.clear()
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setText(self.button_prefix + self.tr("Share with trusted devices"))

    def on_nostr_share_with_member(
        self, receiver_public_key: PublicKey, wallet_id: str, sync_client: SyncClient
    ) -> None:
        """On nostr share with member."""
        if not sync_client.enabled:
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id),
                parent=self,
            )
            return
        sync_client.nostr_sync.group_chat.dm_connection.send(
            self.to_dm(use_compression=sync_client.nostr_sync.group_chat.use_compression),
            receiver_public_key,
        )

    def to_dm(self, use_compression: bool) -> ChatDM:
        """To dm."""
        txid = get_txid(self.data)
        return ChatDM(
            label=ChatLabel.GroupChat,
            data=self.data,
            event=None,
            description=(
                f"{self.data.data_type.name} {short_tx_id(txid)}" if txid else self.data.data_type.name
            ),
            created_at=datetime.now(),
            use_compression=use_compression,
        )

    def on_nostr_share_in_group(self, wallet_id: str, sync_client: SyncClient) -> None:
        """On nostr share in group."""
        if not sync_client.enabled:
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id),
                parent=self,
            )
            return

        sync_client.nostr_sync.group_chat.send(
            self.to_dm(use_compression=sync_client.nostr_sync.group_chat.use_compression),
            send_also_to_me=False,
        )


class QrComboBox(QComboBox):
    def __init__(self, data: Data, network: bdk.Network, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.data = data
        self.network = network
        self.setMaximumWidth(150)

    def fill_qr_menu_export_actions(self, qr_types: list[QrExportType]):
        """Fill qr menu export actions."""
        with QSignalBlocker(self):
            self.clear()
            for qr_type in qr_types:
                self.addItem(
                    get_export_icon(qr_type),
                    get_export_display_name(qr_type),
                    userData=qr_type,
                )

    def setCurrentQrType(self, value: QrExportType):
        """SetCurrentQrType."""
        for i in range(self.count()):
            if value == self.itemData(i):
                self.setCurrentIndex(i)

    def getCurrentExportType(self) -> QrExportType | None:
        """GetCurrentExportType."""
        return self.currentData()

    def getItemExportType(self, i: int) -> QrExportType:
        """GetItemExportType."""
        return self.itemData(i)


class HorizontalImportExportGroups(QWidget):
    "Basis for a unified layout for import and export"

    def __init__(
        self,
        layout: QBoxLayout | None = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(**kwargs)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = layout if layout is not None else QHBoxLayout()
        self.setLayout(self._layout)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # qr
        self.group_qr = DataGroupBox("QR Code")
        self.group_qr.set_layout(QHBoxLayout())
        self.group_qr._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_qr:
            self._layout.addWidget(self.group_qr)

        self.group_qr_buttons = QWidget(self)
        self.group_qr_buttons_layout = QVBoxLayout(self.group_qr_buttons)
        self.group_qr_buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.group_qr._layout.addWidget(self.group_qr_buttons)

        # one of the groupboxes i have to make expanding, otherwise nothing is expanding
        self.group_qr.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # file
        self.group_file = DataGroupBox("File")
        self.group_file.set_layout(QVBoxLayout())
        self.group_file._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_file:
            self._layout.addWidget(self.group_file)

        # usb
        self.group_usb = DataGroupBox("USB")
        self.group_usb.set_layout(QVBoxLayout())
        self.group_usb._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_usb:
            self._layout.addWidget(self.group_usb)

        # clipboard
        self.group_share = DataGroupBox("Share")
        self.group_share.set_layout(QVBoxLayout())
        self.group_share._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_clipboard:
            self._layout.addWidget(self.group_share)

        # seed
        self.group_seed = DataGroupBox("Seed")
        self.group_seed.set_layout(QVBoxLayout())
        self.group_seed._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.group_seed)
        self.group_seed.setVisible(False)


class ExportDataSimple(HorizontalImportExportGroups):
    signal_set_qr_images = cast(SignalProtocol[[list[str]]], pyqtSignal(list))
    signal_close = cast(SignalProtocol[[]], pyqtSignal())
    signal_show = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        data: Data,
        signals_min: SignalsMin,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
        sync_client: dict[str, SyncClient] | None = None,
        usb_signer_ui: SignerUI | None = None,
        layout: QBoxLayout | None = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
        wallet_name: str = "MultiSig",
    ) -> None:
        """Initialize instance."""
        super().__init__(
            layout=layout,
            enable_qr=enable_qr,
            enable_file=enable_file,
            enable_usb=enable_usb,
            enable_clipboard=enable_clipboard,
        )
        self.loop_in_thread = loop_in_thread
        self.network = network
        self.sync_client = sync_client if sync_client else {}
        self.signals_min = signals_min
        self.txid = None
        self.json_data = None
        self.serialized = None
        self.qr_types = QrExportTypes.as_list()
        self.wallet_id = wallet_name
        self._set_data(data)

        # qr
        self.qr_label = QRCodeWidgetSVG(always_animate=True)
        self.qr_label.set_always_animate(True)
        self.group_qr._layout.insertWidget(0, self.qr_label)

        self.button_enlarge_qr = QPushButton()
        self.button_enlarge_qr.setIcon(svg_tools.get_QIcon("bi--zoom-in.svg"))
        # self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.group_qr_buttons_layout.addWidget(self.button_enlarge_qr)

        self.button_save_qr = QPushButton()
        self.button_save_qr.setIcon(svg_tools.get_QIcon("bi--download.svg"))
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.group_qr_buttons_layout.addWidget(self.button_save_qr)

        self.combo_qr_type = QrComboBox(data=self.data, network=network, parent=self)
        self.group_qr_buttons_layout.addWidget(self.combo_qr_type)
        self.combo_qr_type.currentIndexChanged.connect(self.refresh_qr)

        # usb
        show_usb = bool(usb_signer_ui and self.data.data_type == DataType.PSBT)
        self.group_usb.setVisible(show_usb)
        if show_usb and usb_signer_ui:
            self.group_usb._layout.addWidget(usb_signer_ui)

        # file
        self.button_file = FileToolButton(data=data, wallet_id=wallet_name, network=network, parent=self)
        self.group_file._layout.addWidget(self.button_file)

        # sync
        self.button_sync_share = SyncChatToolButton(
            data=data, network=network, sync_client=sync_client, parent=self
        )
        self.group_share._layout.addWidget(self.wrap_in_widget(self.button_sync_share))

        # refresh
        self.refresh_qr_and_file_menus_if_needed()

        self.updateUi()
        self.lazy_load_qr(data)
        self.signals_min.language_switch.connect(self.updateUi)
        self.signal_set_qr_images.connect(self.qr_label.set_images)

    def set_minimum_size_as_floating_window(self):
        """Set minimum size as floating window."""
        self.setMinimumSize(650, 300)

    def refresh_qr_and_file_menus_if_needed(self):
        """Refresh qr and file menus if needed."""
        if [t.name for t in self.qr_types] == [
            self.combo_qr_type.getItemExportType(i).name for i in range(self.combo_qr_type.count())
        ]:
            # no  change needed
            return

        # combo_qr_type
        self.combo_qr_type.fill_qr_menu_export_actions(qr_types=self.qr_types)
        self.button_file.set_data(self.data)

    def updateUi(self) -> None:
        """UpdateUi."""
        selected_qr_type = self.combo_qr_type.getCurrentExportType()
        self.button_enlarge_qr.setText(
            self.tr("Enlarge {} QR").format(selected_qr_type.display_name if selected_qr_type else "")
        )
        self.button_save_qr.setText(self.tr("Save as image"))

        self.refresh_qr_and_file_menus_if_needed()

        # sync share
        self.button_sync_share.updateUi()

        self.setWindowTitle(
            self.tr("Export {data_type} to hardware signer").format(data_type=self.data.data_type.name)
        )

    def refresh_qr(self) -> None:
        """Refresh qr."""
        self.clear_qr()
        self.lazy_load_qr(self.data)
        self.updateUi()

    def _set_data(self, data: Data) -> None:
        """Set data."""
        self.data = data
        self.serialized = data.data_as_string()
        if data.data_type == DataType.PSBT:
            if not isinstance(data.data, bdk.Psbt):
                logger.error("data is not of type bdk.Psbt")
                return
            self.txid = data.data.extract_tx().compute_txid()
            self.json_data = json.dumps(json.loads(data.data.json_serialize()), indent=4)
        if data.data_type == DataType.Tx:
            if not isinstance(data.data, bdk.Transaction):
                logger.error("data is not of type bdk.Transaction")
                return
            self.txid = data.data.compute_txid()
            self.json_data = json.dumps(transaction_to_dict(data.data, network=self.network), indent=4)

        if data.data_type in [DataType.Descriptor, DataType.Descriptor]:
            self.qr_types = DescriptorQrExportTypes.as_list()
        elif data.data_type in [DataType.SignMessageRequest]:
            self.qr_types = SignMessageRequestQrExportTypes.as_list()
        else:
            self.qr_types = QrExportTypes.as_list()

    def set_data(self, data: Data) -> None:
        """Set data."""
        self._set_data(data=data)
        self.refresh_qr()

    @staticmethod
    def wrap_in_widget(widget: QWidget) -> QWidget:
        """Wrap in widget."""
        outer_widget = QWidget()
        outer_widget_layout = QVBoxLayout(outer_widget)
        outer_widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        outer_widget_layout.addWidget(widget)
        return outer_widget

    def export_qrcode(self) -> Path | None:
        """Export qrcode."""
        image_format = "gif" if len(self.qr_label.svg_renderers) > 1 else "png"

        filename = save_file_dialog(
            name_filters=[
                self.tr("Image (*.{image_format})", "All Files (*.*)").format(image_format=image_format)
            ],
            default_suffix=image_format,
            default_filename=f"{short_tx_id(self.txid)}.{image_format}" if self.txid else None,
        )
        if not filename:
            return None

        file_path = Path(filename)
        self.qr_label.save_file(
            filename=file_path,
        )
        return file_path

    def clear_qr(self) -> None:
        """Clear qr."""
        self.qr_label.set_images([])

    def generate_qr_fragments(self, data: Data) -> list[str]:
        """Generate qr fragments."""
        qr_export_type = self.combo_qr_type.getCurrentExportType()
        if not qr_export_type:
            return []

        # only handle the DescriptorExportTypes, everything else is handles in  generate_fragments_for_qr

        ## descriptors
        if qr_export_type.name == DescriptorQrExportTypes.specterdiy.name:
            assert data.data_type in [DataType.Descriptor], "Wrong datatype"
            return [
                DescriptorExportTools._get_specter_diy_str(
                    wallet_id=self.wallet_id, descriptor_str=data.data_as_string()
                )
            ]
        elif qr_export_type.name == DescriptorQrExportTypes.default.name:
            assert data.data_type in [DataType.Descriptor], "Wrong datatype"
            passport_str = DescriptorExportTools._get_passport_str(
                wallet_id=self.wallet_id,
                descriptor_str=data.data_as_string(),
            )
            return UnifiedEncoder.string_to_ur_byte_fragments(string_data=passport_str)
        elif qr_export_type.name == DescriptorQrExportTypes.coldcard_legacy.name:
            assert data.data_type in [DataType.Descriptor], "Wrong datatype"
            coldcard_str = DescriptorExportTools._get_coldcard_str_legacy(
                wallet_id=self.wallet_id, descriptor_str=data.data_as_string(), network=self.network
            )
            return UnifiedEncoder.raw_generate_fragments_for_bbqr(raw=coldcard_str.encode(), file_type="U")
        ## SignMessageRequest
        elif qr_export_type.name in [SignMessageRequestQrExportTypes.text.name]:
            assert data.data_type in [DataType.SignMessageRequest], "Wrong datatype"
            return [ConverterSignMessageRequest(data.data).to_text_str()]
        elif qr_export_type.name in [SignMessageRequestQrExportTypes.bbqr.name]:
            # this is necessary, because SignMessageRequestQrExportTypes.bbqr != QrExportTypes.bbqr
            assert data.data_type in [DataType.SignMessageRequest], "Wrong datatype"
            return UnifiedEncoder.generate_fragments_for_qr(data=data, qr_export_type=QrExportTypes.bbqr)
        else:
            return UnifiedEncoder.generate_fragments_for_qr(data=data, qr_export_type=qr_export_type)

    def lazy_load_qr(self, data: Data) -> None:
        """Lazy load qr."""

        async def do() -> list[str | None]:
            """Do."""
            fragments = self.generate_qr_fragments(data=data)
            images = [QRGenerator.create_qr_svg(fragment) for fragment in fragments]
            return images

        def on_done(result: list[str | None] | None) -> None:
            """On done."""
            pass

        def on_error(packed_error_info: ExcInfo) -> None:
            """On error."""
            if not packed_error_info:
                return
            Message(str(packed_error_info), type=MessageType.Error, parent=self)

        def on_success(result: list[str | None] | None) -> None:
            """On success."""
            if result:
                if any([(item is None) for item in result]):
                    return self.signal_set_qr_images.emit([])
                # here i must use a signal, and not set the image directly, because
                # self.qr_label can reference a destroyed c++ object
                self.signal_set_qr_images.emit([r for r in result if r])

        if self.loop_in_thread:
            self.loop_in_thread.run_task(
                do(),
                on_done=on_done,
                on_success=on_success,
                on_error=on_error,
                key=f"{id(self)}lazy_load_qr",
                multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
            )

    def _export_wallet(self, s: str, hardware_signer: HardwareSigner) -> str | None:
        """Export wallet."""
        if not isinstance(self.data.data, bdk.Descriptor):
            return None

        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=shorten_filename(
                filename_clean(self.wallet_id, file_extension=".txt"), max_total_length=20
            ),
            window_title=self.tr("Save {name} file").format(name=hardware_signer.display_name),
        )
        if not filename:
            return None

        with open(filename, "w") as file:
            file.write(s)
        return filename

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """CloseEvent."""
        self.signal_close.emit()
        return super().closeEvent(a0)

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        self.signal_show.emit()  # Emit custom signal when the widget is shown.


class QrToolButton(QToolButton):
    def __init__(
        self,
        data: Data,
        network: bdk.Network,
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread | None,
        parent: QWidget | None = None,
        button_prefix: str = "",
        wallet_name: str = "MultiSig",
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.button_prefix = button_prefix

        self.export_qr_widget = ExportDataSimple(
            data=data,
            signals_min=signals_min,
            enable_clipboard=False,
            enable_usb=False,
            enable_file=False,
            enable_qr=True,
            network=network,
            loop_in_thread=loop_in_thread,
            wallet_name=wallet_name,
        )
        self.export_qr_widget.set_minimum_size_as_floating_window()

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(svg_tools.get_QIcon("bi--qr-code.svg"))

        self._fill_menu()
        self.updateUi()

    def _show_export_widget(self, export_type: QrExportType):
        """Show export widget."""
        if not self.export_qr_widget:
            return
        self.export_qr_widget.combo_qr_type.setCurrentQrType(value=export_type)
        self.export_qr_widget.show()

    def _fill_menu(self):
        """Fill menu."""
        self._menu.clear()
        with QSignalBlocker(self._menu):
            for qr_type in self.export_qr_widget.qr_types:
                self._menu.add_action(
                    get_export_display_name(qr_type),
                    partial(self._show_export_widget, qr_type),
                    icon=get_export_icon(qr_type),
                )

    def set_data(self, data: Data):
        """Set data."""
        self.export_qr_widget.set_data(data)
        self._fill_menu()
        self.updateUi()

    def updateUi(self) -> None:
        """UpdateUi."""
        self.setText(self.button_prefix + self.tr("QR Code"))
        self.export_qr_widget.updateUi()
