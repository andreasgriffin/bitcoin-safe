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


import json
import logging
import os
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import bdkpython as bdk
from bitcoin_nostr_chat.bitcoin_dm import BitcoinDM, ChatLabel
from bitcoin_nostr_chat.ui.ui import short_key
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.gui.qr_widgets import QRCodeWidgetSVG
from bitcoin_qr_tools.qr_generator import QRGenerator
from bitcoin_qr_tools.unified_encoder import QrExportType, QrExportTypes, UnifiedEncoder
from nostr_sdk import PublicKey
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.descriptor_export_tools import DescriptorExportTools
from bitcoin_safe.descriptors import MultipathDescriptor
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate
from bitcoin_safe.threading_manager import TaskThread, ThreadingManager
from bitcoin_safe.tx import short_tx_id, transaction_to_dict
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.wallet import filename_clean

from ...hardware_signers import (
    DescriptorExportType,
    DescriptorExportTypes,
    DescriptorQrExportTypes,
    HardwareSigner,
    HardwareSigners,
)
from ...signals import SignalsMin
from .sync_tab import SyncTab
from .util import Message, MessageType, do_copy, read_QIcon, save_file_dialog

logger = logging.getLogger(__name__)


class DataGroupBox(QGroupBox):
    def __init__(self, title: str | None = None, parent=None, data=None) -> None:
        super().__init__(title=title if title else "", parent=parent)
        self.data = data
        self._layout: Union[QVBoxLayout, QHBoxLayout] = QVBoxLayout()

    def set_layout(self, layout_cls: Union[QVBoxLayout, QHBoxLayout]):
        self._layout = layout_cls
        self.setLayout(self._layout)

    def setData(self, data) -> None:
        self.data = data


def pretty_name(data_type: DataType) -> str:
    if data_type == DataType.PSBT:
        return translate("general", "PSBT")
    if data_type == DataType.Tx:
        return translate("general", "Transaction")
    return ""


def get_txid(data: Data) -> str | None:
    if data.data_type == DataType.PSBT:
        if not isinstance(data.data, bdk.PartiallySignedTransaction):
            logger.error(f"{data.data} is not of type bdk.PartiallySignedTransaction")
            return None
        return data.data.txid()
    elif data.data_type == DataType.Tx:
        if not isinstance(data.data, bdk.Transaction):
            logger.error(f"{data.data} is not of type bdk.Transaction")
            return None
        return data.data.txid()
    return None


def get_json_data(data: Data, network: bdk.Network) -> str | None:
    if data.data_type == DataType.PSBT:
        if not isinstance(data.data, bdk.PartiallySignedTransaction):
            logger.error(f"{data.data} is not of type bdk.PartiallySignedTransaction")
            return None
        return json.dumps(json.loads(data.data.json_serialize()), indent=4)
    elif data.data_type == DataType.Tx:
        if not isinstance(data.data, bdk.Transaction):
            logger.error(f"{data.data} is not of type bdk.Transaction")
            return None
        return json.dumps(transaction_to_dict(data.data, network=network), indent=4)
    return None


def get_export_display_name(export_type: Union[DescriptorExportType, QrExportType]) -> str:
    parts = [export_type.display_name]
    filtered_hardware_signers = HardwareSigners.filtered_by([export_type])  # type:ignore

    hardware_names = ", ".join(
        [hardware_signer.display_name for hardware_signer in filtered_hardware_signers]
    )
    if hardware_names:
        parts += [hardware_names]
    return " - ".join(parts)


def get_export_icon(export_type: Union[DescriptorExportType, QrExportType]) -> QIcon:
    filtered_hardware_signers = HardwareSigners.filtered_by([export_type])  # type:ignore
    if filtered_hardware_signers:
        filtered_hardware_signer = filtered_hardware_signers[0]
        return QIcon(filtered_hardware_signer.icon_path)
    else:
        return QIcon()


class CopyToolButton(QToolButton):
    def __init__(self, data: Data, network: bdk.Network, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.network = network
        self.serialized: str | None = None
        self.txid: str | None = None
        self.json_data: str | None = None
        self._set_data(data=data)

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(read_QIcon("copy.png"))

        self._fill_menu()
        self.updateUi()

    def _fill_menu(self):
        self._menu.clear()
        self._menu.blockSignals(True)

        self.action_copy_data = self._menu.add_action("", self.on_action_copy_data)
        self._menu.addSeparator()
        self.action_copy_txid = self._menu.add_action("", self.on_action_copy_txid)
        self.action_json = self._menu.add_action("", self.on_action_json)

        self._menu.blockSignals(False)

    def copy_if_available(self, s: Optional[str]) -> None:
        if s:
            do_copy(s)
        else:
            Message(self.tr("Not available"))

    def on_action_copy_data(self):
        return self.copy_if_available(self.serialized)

    def on_action_copy_txid(self):
        return self.copy_if_available(self.txid)

    def on_action_json(self):
        return self.copy_if_available(self.json_data)

    def _set_data(self, data: Data) -> None:
        self.data = data
        self.serialized = data.data_as_string()
        self.txid = get_txid(data)
        self.json_data = get_json_data(data, network=self.network)

    def set_data(self, data: Data):
        self._set_data(data=data)
        self._fill_menu()
        self.updateUi()

    def updateUi(self) -> None:
        # copy button
        self.setText(self.tr("Copy to clipboard"))
        self.action_copy_data.setText(
            self.tr("Copy {name}").format(name=pretty_name(data_type=self.data.data_type))
        )
        self.action_copy_txid.setText(self.tr("Copy TxId"))
        self.action_json.setText(self.tr("Copy JSON"))


class FileToolButton(QToolButton):
    def __init__(
        self, data: Data, network: bdk.Network, wallet_id: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.wallet_id = wallet_id
        self.network = network
        self.data = data

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon((self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))

        self._fill_menu()
        self.updateUi()

    def _fill_menu(self):
        self._menu.clear()
        self._menu.blockSignals(True)

        if self.data.data_type in [DataType.MultiPathDescriptor] and isinstance(
            self.data.data, MultipathDescriptor
        ):
            self.fill_file_menu_descriptor_export_actions(
                self._menu,
                self.wallet_id if self.wallet_id else "descriptor",
                multipath_descriptor=self.data.data,
                network=self.network,
            )
        else:
            self.fill_file_menu_export_actions(self._menu)

        self._menu.blockSignals(False)

    def export_to_file(self, default_filename=None) -> Optional[str]:
        default_suffix = "txt"
        if self.data.data_type == DataType.Tx:
            default_suffix = "tx"
        if self.data.data_type == DataType.PSBT:
            default_suffix = "psbt"

        txid = get_txid(self.data)
        if not default_filename and txid:
            default_filename = f"{short_tx_id( txid)}.{default_suffix}"
        if not default_filename and self.data.data_type in [
            DataType.Descriptor,
            DataType.MultiPathDescriptor,
        ]:
            default_filename = (
                (f"{filename_clean( self.wallet_id, file_extension='', replace_spaces_by='_')}.txt")
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

    def updateUi(self) -> None:
        self.setText(self.tr("Export file"))

    def set_data(self, data: Data):
        self.data = data
        self._fill_menu()
        self.updateUi()

    @classmethod
    def _save_file(
        cls,
        wallet_id: str,
        multipath_descriptor: MultipathDescriptor,
        network: bdk.Network,
        descripor_type: DescriptorExportType,
    ):
        return DescriptorExportTools.export(
            wallet_id=wallet_id,
            multipath_descriptor=multipath_descriptor,
            network=network,
            descripor_type=descripor_type,
        )

    @classmethod
    def fill_file_menu_descriptor_export_actions(
        cls,
        menu: Menu,
        wallet_id: str,
        multipath_descriptor: MultipathDescriptor,
        network: bdk.Network,
    ):
        menu.blockSignals(True)
        menu.clear()

        for export_type in DescriptorExportTypes.as_list():
            menu.add_action(
                get_export_display_name(export_type=export_type),
                partial(
                    cls._save_file,
                    wallet_id=wallet_id,
                    multipath_descriptor=multipath_descriptor,
                    network=network,
                    descripor_type=export_type,
                ),
                icon=get_export_icon(export_type=export_type),
            )
        menu.blockSignals(False)

    def fill_file_menu_export_actions(
        self,
        menu: Menu,
    ):
        file_icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        menu.blockSignals(True)
        menu.clear()
        menu.add_action(
            self.tr("Export to file"),
            self.export_to_file,
            icon=file_icon,
        )
        menu.blockSignals(False)


class SyncChatToolButton(QToolButton):
    def __init__(
        self,
        data: Data,
        network: bdk.Network,
        sync_tabs: dict[str, SyncTab] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sync_tabs = sync_tabs
        self.network = network
        self.action_share_with_all_devices: Dict[str, QAction] = {}
        self.menu_share_with_single_devices: Dict[str, Menu] = {}
        self._set_data(data=data, sync_tabs=sync_tabs)

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(QIcon(read_QIcon("cloud-sync.svg")))

        self._fill_menu()
        self.updateUi()

    def _share_with_device(
        self, wallet_id: str, sync_tab: SyncTab, receiver_public_key_bech32: str | None = None
    ) -> None:
        if not sync_tab.enabled():
            Message(self.tr("Please enable the sync tab first"))
            return
        if receiver_public_key_bech32:
            self.on_nostr_share_with_member(PublicKey.parse(receiver_public_key_bech32), wallet_id, sync_tab)
        else:
            self.on_nostr_share_in_group(wallet_id, sync_tab)

    def _fill_menu(self):
        menu = self._menu
        menu.clear()
        if not self.sync_tabs:
            return

        self._menu.blockSignals(True)

        # Create a menu for the button
        self.action_share_with_all_devices.clear()
        self.menu_share_with_single_devices.clear()
        for wallet_id, sync_tab in self.sync_tabs.items():
            action_alldevices = partial(
                self._share_with_device,
                wallet_id=wallet_id,
                sync_tab=sync_tab,
                receiver_public_key_bech32=None,
            )
            self.action_share_with_all_devices[wallet_id] = menu.add_action("", action_alldevices)

            self.menu_share_with_single_devices[wallet_id] = menu.add_menu("")
            for member in sync_tab.nostr_sync.group_chat.members:
                action = partial(
                    self._share_with_device,
                    wallet_id=wallet_id,
                    sync_tab=sync_tab,
                    receiver_public_key_bech32=member.to_bech32(),
                )
                self.menu_share_with_single_devices[wallet_id].add_action(
                    f"{short_key(member.to_bech32())}", action
                )
            menu.addSeparator()

        menu.blockSignals(False)

    def _set_data(self, data: Data, sync_tabs: dict[str, SyncTab] | None) -> None:
        self.data = data
        self.sync_tabs = sync_tabs

    def set_data(self, data: Data, sync_tabs: dict[str, SyncTab] | None):
        self._set_data(data=data, sync_tabs=sync_tabs)
        self._fill_menu()
        self.updateUi()

    def updateUi(self) -> None:
        self.setText(self.tr("Share with trusted devices"))

        for wallet_id, action in self.action_share_with_all_devices.items():
            action.setText(self.tr("Share with all devices in {wallet_id}").format(wallet_id=wallet_id))
        for wallet_id, menu in self.menu_share_with_single_devices.items():
            menu.setTitle(self.tr("Share with single device"))

    def on_nostr_share_with_member(
        self, receiver_public_key: PublicKey, wallet_id: str, sync_tab: SyncTab
    ) -> None:
        if not sync_tab.enabled():
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id)
            )
            return
        sync_tab.nostr_sync.group_chat.dm_connection.send(
            self.to_dm(),
            receiver_public_key,
        )

    def to_dm(
        self,
    ) -> BitcoinDM:
        txid = get_txid(self.data)
        return BitcoinDM(
            label=ChatLabel.GroupChat,
            data=self.data,
            event=None,
            description=(
                f"{self.data.data_type.name} {short_tx_id(txid)}" if txid else self.data.data_type.name
            ),
            created_at=datetime.now(),
        )

    def on_nostr_share_in_group(self, wallet_id: str, sync_tab: SyncTab) -> None:
        if not sync_tab.enabled():
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id)
            )
            return

        sync_tab.nostr_sync.group_chat.send(
            self.to_dm(),
            send_also_to_me=False,
        )


class QrComboBox(QComboBox):
    def __init__(self, data: Data, network: bdk.Network, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.network = network
        self.setMaximumWidth(150)

    def fill_qr_menu_export_actions(self, qr_types: List[QrExportType]):
        self.blockSignals(True)
        self.clear()
        for qr_type in qr_types:
            self.addItem(
                get_export_icon(qr_type),
                get_export_display_name(qr_type),
                userData=qr_type,
            )
        self.blockSignals(False)

    def setCurrentQrType(self, value: QrExportType):
        for i in range(self.count()):
            if value == self.itemData(i):
                self.setCurrentIndex(i)

    def getCurrentExportType(self) -> Optional[QrExportType]:
        return self.currentData()

    def getItemExportType(self, i: int) -> QrExportType:
        return self.itemData(i)


class HorizontalImportExportGroups(QWidget):
    "Basis for a unified layout for import and export"

    def __init__(
        self,
        layout: Optional[QBoxLayout] = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
        **kwargs,
    ) -> None:
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

        self.group_qr_buttons = QWidget()
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


class ExportDataSimple(HorizontalImportExportGroups, ThreadingManager):
    signal_set_qr_images: TypedPyQtSignal[List[str]] = pyqtSignal(list)  # type: ignore

    def __init__(
        self,
        data: Data,
        signals_min: SignalsMin,
        network: bdk.Network,
        sync_tabs: dict[str, SyncTab] | None = None,
        usb_signer_ui: SignerUI | None = None,
        layout: QBoxLayout | None = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
        threading_parent: ThreadingManager | None = None,
        wallet_name: str = "MultiSig",
    ) -> None:
        super().__init__(
            layout=layout,
            enable_qr=enable_qr,
            enable_file=enable_file,
            enable_usb=enable_usb,
            enable_clipboard=enable_clipboard,
            threading_parent=threading_parent,
        )
        self.network = network
        self.sync_tabs = sync_tabs if sync_tabs else {}
        self.signals_min = signals_min
        self.txid = None
        self.json_data = None
        self.serialized = None
        self.qr_types = QrExportTypes.as_list()
        self.wallet_id = wallet_name
        self.set_data(data)

        # qr
        self.qr_label = QRCodeWidgetSVG(always_animate=True)
        self.qr_label.set_always_animate(True)
        self.group_qr._layout.insertWidget(0, self.qr_label)

        self.button_enlarge_qr = QPushButton()
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))
        # self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.group_qr_buttons_layout.addWidget(self.button_enlarge_qr)

        self.button_save_qr = QPushButton()
        self.button_save_qr.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.group_qr_buttons_layout.addWidget(self.button_save_qr)

        self.combo_qr_type = QrComboBox(data=self.data, network=network, parent=self)
        self.group_qr_buttons_layout.addWidget(self.combo_qr_type)
        self.combo_qr_type.currentIndexChanged.connect(self.switch_qr_type)

        # file
        self.button_file = FileToolButton(data=data, wallet_id=wallet_name, network=network, parent=self)
        self.group_file._layout.addWidget(self.button_file)

        # qr
        self.refresh_qr_and_file_menus_if_needed()

        # usb
        show_usb = bool(usb_signer_ui and self.data.data_type == DataType.PSBT)
        self.group_usb.setVisible(show_usb)
        if show_usb and usb_signer_ui:
            self.group_usb._layout.addWidget(usb_signer_ui)

        # clipboard
        self.copy_toolbutton = CopyToolButton(data=data, network=network, parent=self)
        self.group_share._layout.addWidget(self.wrap_in_widget(self.copy_toolbutton))

        self.button_sync_share = SyncChatToolButton(
            data=data, network=network, sync_tabs=sync_tabs, parent=self
        )
        self.group_share._layout.addWidget(self.wrap_in_widget(self.button_sync_share))

        self.updateUi()
        self.lazy_load_qr(data)
        self.signals_min.language_switch.connect(self.updateUi)
        self.signal_set_qr_images.connect(self.qr_label.set_images)

    def set_minimum_size_as_floating_window(self):
        self.setMinimumSize(650, 300)

    def refresh_qr_and_file_menus_if_needed(self):
        if [t.name for t in self.qr_types] == [
            self.combo_qr_type.getItemExportType(i).name for i in range(self.combo_qr_type.count())
        ]:
            # no  change needed
            return

        # combo_qr_type
        self.combo_qr_type.fill_qr_menu_export_actions(qr_types=self.qr_types)
        self.button_file.set_data(self.data)

    def updateUi(self) -> None:
        selected_qr_type = self.combo_qr_type.getCurrentExportType()
        self.button_enlarge_qr.setText(
            self.tr("Enlarge {} QR").format(selected_qr_type.display_name if selected_qr_type else "")
        )
        self.button_save_qr.setText(self.tr("Save as image"))

        self.refresh_qr_and_file_menus_if_needed()

        # copy button
        self.copy_toolbutton.updateUi()
        self.copy_toolbutton.updateUi()

        # sync share
        self.button_sync_share.updateUi()

        self.setWindowTitle(
            self.tr("Export {data_type} to hardware signer").format(data_type=self.data.data_type.name)
        )

    def switch_qr_type(self) -> None:
        self.clear_qr()
        self.lazy_load_qr(self.data)
        self.updateUi()

    def set_data(self, data: Data) -> None:
        self.data = data
        self.serialized = data.data_as_string()
        if data.data_type == DataType.PSBT:
            if not isinstance(data.data, bdk.PartiallySignedTransaction):
                logger.error(f"{data.data} is not of type bdk.PartiallySignedTransaction")
                return
            self.txid = data.data.txid()
            self.json_data = json.dumps(json.loads(data.data.json_serialize()), indent=4)
        if data.data_type == DataType.Tx:
            if not isinstance(data.data, bdk.Transaction):
                logger.error(f"{data.data} is not of type bdk.Transaction")
                return
            self.txid = data.data.txid()
            self.json_data = json.dumps(transaction_to_dict(data.data, network=self.network), indent=4)

        if data.data_type in [DataType.Descriptor, DataType.MultiPathDescriptor]:
            self.qr_types = DescriptorQrExportTypes.as_list()
        else:
            self.qr_types = QrExportTypes.as_list()

    @staticmethod
    def wrap_in_widget(widget: QWidget) -> QWidget:
        outer_widget = QWidget()
        outer_widget_layout = QVBoxLayout(outer_widget)
        outer_widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        outer_widget_layout.addWidget(widget)
        return outer_widget

    def export_qrcode(self) -> Optional[Path]:
        image_format = "gif" if len(self.qr_label.svg_renderers) > 1 else "png"

        filename = save_file_dialog(
            name_filters=[
                self.tr("Image (*.{image_format})", "All Files (*.*)").format(image_format=image_format)
            ],
            default_suffix=image_format,
            default_filename=f"{short_tx_id( self.txid)}.{image_format}" if self.txid else None,
        )
        if not filename:
            return None

        file_path = Path(filename)
        self.qr_label.save_file(
            filename=file_path,
        )
        return file_path

    def clear_qr(self) -> None:
        self.qr_label.set_images([])

    def generate_qr_fragments(self, data: Data) -> List[str]:
        qr_export_type = self.combo_qr_type.getCurrentExportType()
        if not qr_export_type:
            return []

        # only handle the DescriptorExportTypes, everything else is handles in  generate_fragments_for_qr
        if qr_export_type.name == DescriptorExportTypes.specterdiy.name:
            assert data.data_type in [DataType.MultiPathDescriptor, DataType.Descriptor], "Wrong datatype"
            return [
                DescriptorExportTools._get_specter_diy_str(
                    wallet_id=self.wallet_id, descriptor_str=data.data_as_string()
                )
            ]
        elif qr_export_type.name == DescriptorExportTypes.passport.name:
            assert data.data_type in [DataType.MultiPathDescriptor, DataType.Descriptor], "Wrong datatype"
            passport_str = DescriptorExportTools._get_passport_str(
                wallet_id=self.wallet_id,
                descriptor_str=data.data_as_string(),
            )
            return UnifiedEncoder.string_to_ur_byte_fragments(string_data=passport_str)
        elif qr_export_type.name == DescriptorExportTypes.keystone.name:
            assert data.data_type in [DataType.MultiPathDescriptor, DataType.Descriptor], "Wrong datatype"
            passport_str = DescriptorExportTools._get_keystone_str(
                wallet_id=self.wallet_id, descriptor_str=data.data_as_string(), network=self.network
            )
            return UnifiedEncoder.string_to_ur_byte_fragments(string_data=passport_str)
        else:
            return UnifiedEncoder.generate_fragments_for_qr(data=data, qr_export_type=qr_export_type)

    def lazy_load_qr(self, data: Data) -> None:
        def do() -> Any:
            fragments = self.generate_qr_fragments(data=data)
            images = [QRGenerator.create_qr_svg(fragment) for fragment in fragments]
            return images

        def on_done(result) -> None:
            pass

        def on_error(packed_error_info) -> None:
            Message(packed_error_info, type=MessageType.Error)

        def on_success(result) -> None:
            if result:
                if any([(item is None) for item in result]):
                    return self.signal_set_qr_images.emit([])
                # here i must use a signal, and not set the image directly, because
                # self.qr_label can reference a destroyed c++ object
                self.signal_set_qr_images.emit(result)

        self.append_thread(TaskThread().add_and_start(do, on_success, on_done, on_error))

    def _export_wallet(self, s: str, hardware_signer: HardwareSigner) -> Optional[str]:
        if not isinstance(self.data.data, MultipathDescriptor):
            return None

        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=filename_clean(self.wallet_id, file_extension=".txt")[:24],
            window_title=f"Save {hardware_signer.display_name} file",
        )
        if not filename:
            return None

        with open(filename, "w") as file:
            file.write(s)
        return filename


class QrToolButton(QToolButton):
    def __init__(
        self,
        data: Data,
        network: bdk.Network,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.export_qr_widget = ExportDataSimple(
            data=data,
            signals_min=signals_min,
            enable_clipboard=False,
            enable_usb=False,
            enable_file=False,
            enable_qr=True,
            network=network,
            threading_parent=threading_parent,
        )
        self.export_qr_widget.set_minimum_size_as_floating_window()

        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._menu = Menu(self)
        self.setMenu(self._menu)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.setIcon(read_QIcon("qr-code.svg"))

        self._fill_menu()
        self.updateUi()

    def _show_export_widget(self, export_type: QrExportType):
        if not self.export_qr_widget:
            return
        self.export_qr_widget.combo_qr_type.setCurrentQrType(value=export_type)
        self.export_qr_widget.show()

    def _fill_menu(self):
        self._menu.clear()
        self._menu.blockSignals(True)

        for qr_type in self.export_qr_widget.qr_types:
            self._menu.add_action(
                get_export_display_name(qr_type),
                partial(self._show_export_widget, qr_type),
                icon=get_export_icon(qr_type),
            )

        self._menu.blockSignals(False)

    def set_data(self, data: Data):
        self.export_qr_widget.set_data(data)
        self._fill_menu()
        self.updateUi()

    def updateUi(self) -> None:
        self.setText(self.tr("QR Code"))
        self.export_qr_widget.updateUi()
