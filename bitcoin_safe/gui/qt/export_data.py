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
from typing import Any, Callable, Dict, List, Optional

from bitcoin_nostr_chat.connected_devices.connected_devices import short_key
from bitcoin_nostr_chat.nostr import BitcoinDM, ChatLabel
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.qr_widgets import QRCodeWidgetSVG

from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.threading_manager import TaskThread
from bitcoin_safe.tx import short_tx_id, transaction_to_dict

from .sync_tab import SyncTab

logger = logging.getLogger(__name__)

import json
import os

import bdkpython as bdk
from bitcoin_qr_tools.qr_generator import QRGenerator
from nostr_sdk import PublicKey
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...signals import SignalsMin, pyqtSignal
from .util import Message, MessageType, do_copy, read_QIcon, save_file_dialog


class DataGroupBox(QGroupBox):
    def __init__(self, title: str = None, parent=None, data=None) -> None:
        super().__init__(title=title, parent=parent)
        self.data = data

    def setData(self, data) -> None:
        self.data = data


class HorizontalImportExportGroups(QWidget):
    "Basis for a unified layout for import and export"

    def __init__(
        self,
        layout: QBoxLayout = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
    ) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setLayout(layout if layout is not None else QHBoxLayout())
        self.layout().setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # qr
        self.group_qr = DataGroupBox("QR Code")
        self.group_qr.setLayout(QHBoxLayout())
        self.group_qr.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_qr:
            self.layout().addWidget(self.group_qr)

        self.group_qr_buttons = QWidget()
        self.group_qr_buttons.setLayout(QVBoxLayout())
        self.group_qr_buttons.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.group_qr.layout().addWidget(self.group_qr_buttons)

        # one of the groupboxes i have to make expanding, otherwise nothing is expanding
        self.group_qr.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # file
        self.group_file = DataGroupBox("File")
        self.group_file.setLayout(QVBoxLayout())
        self.group_file.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_file:
            self.layout().addWidget(self.group_file)

        # usb
        self.group_usb = DataGroupBox("USB")
        self.group_usb.setLayout(QVBoxLayout())
        self.group_usb.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_usb:
            self.layout().addWidget(self.group_usb)

        # clipboard
        self.group_share = DataGroupBox("Share")
        self.group_share.setLayout(QVBoxLayout())
        self.group_share.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        if enable_clipboard:
            self.layout().addWidget(self.group_share)

        # seed
        self.group_seed = DataGroupBox("Seed")
        self.group_seed.setLayout(QVBoxLayout())
        self.group_seed.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_seed)
        self.group_seed.setVisible(False)


class ExportDataSimple(HorizontalImportExportGroups):
    signal_export_to_file = pyqtSignal()
    signal_set_qr_images = pyqtSignal(list)
    default_qr_types = ["bbqr", "ur", "text"]
    qr_types_descriptions = {"ur": "Legacy", "bbqr": "BBQr", "text": "Text"}

    def __init__(
        self,
        data: Data,
        signals_min: SignalsMin,
        sync_tabs: dict[str, SyncTab] = None,
        usb_signer_ui: SignerUI = None,
        layout: QBoxLayout = None,
        enable_qr=True,
        enable_file=True,
        enable_usb=True,
        enable_clipboard=True,
    ) -> None:
        super().__init__(
            layout=layout,
            enable_qr=enable_qr,
            enable_file=enable_file,
            enable_usb=enable_usb,
            enable_clipboard=enable_clipboard,
        )
        self.sync_tabs = sync_tabs if sync_tabs else {}
        self.signals_min = signals_min
        self.txid = None
        self.json_data = None
        self.serialized = None
        self.qr_types = self.default_qr_types.copy()
        self.set_data(data)

        self.signal_export_to_file.connect(self.export_to_file)

        # qr
        self.qr_label = QRCodeWidgetSVG()
        self.qr_label.setMinimumSize(20, 20)
        self.qr_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        group_qr_layout: QHBoxLayout = self.group_qr.layout()
        group_qr_layout.insertWidget(0, self.qr_label)

        self.button_enlarge_qr = QPushButton()
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))
        # self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.group_qr_buttons.layout().addWidget(self.button_enlarge_qr)

        self.button_save_qr = QPushButton()
        # self.button_save_qr.setIcon(read_QIcon("download.png"))
        self.button_save_qr.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.group_qr_buttons.layout().addWidget(self.button_save_qr)

        self.combo_qr_type = QComboBox()
        self.fill_combo_qr_type(self.default_qr_types)
        self.group_qr_buttons.layout().addWidget(self.combo_qr_type)
        self.combo_qr_type.currentIndexChanged.connect(self.switch_qr_type)

        # file
        self.button_file = QPushButton()
        self.button_file.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.button_file.clicked.connect(lambda: self.signal_export_to_file.emit())

        self.group_file.layout().addWidget(self.button_file)

        # usb
        show_usb = bool(usb_signer_ui and self.data.data_type == DataType.PSBT)
        self.group_usb.setVisible(show_usb)
        if show_usb:
            self.group_usb.layout().addWidget(usb_signer_ui)

        # clipboard
        self.group_share.layout().addWidget(self.create_copy_button())

        self.group_share.layout().addWidget(self.create_sync_share_button())

        self.updateUi()
        self.lazy_load_qr(data)
        self.signals_min.language_switch.connect(self.updateUi)
        self.signal_set_qr_images.connect(self.qr_label.set_images)

    def fill_combo_qr_type(self, qr_types: List[str]):
        self.combo_qr_type.blockSignals(True)
        self.combo_qr_type.clear()
        for qr_type in qr_types:
            self.combo_qr_type.addItem(
                read_QIcon("qr-code.svg"),
                self.tr("{} QR code").format(self.qr_types_descriptions[qr_type]),
                userData=qr_type,
            )
        self.combo_qr_type.blockSignals(False)

    def updateUi(self) -> None:
        self.button_enlarge_qr.setText(
            self.tr("Enlarge {} QR").format(self.qr_types_descriptions[self.combo_qr_type.currentData()])
        )
        self.button_save_qr.setText(self.tr("Save as image"))

        if self.qr_types != [self.combo_qr_type.itemData(i) for i in range(self.combo_qr_type.count())]:
            self.fill_combo_qr_type(self.qr_types)

        self.button_file.setText(self.tr("Export file"))

        # copy button
        self.copy_toolbutton.setText(self.tr("Copy to clipboard"))
        self.action_copy_data.setText(self.tr("Copy {name}").format(name=self._get_data_name()))
        self.action_copy_txid.setText(self.tr("Copy TxId"))
        self.action_json.setText(self.tr("Copy JSON"))

        # sync share
        self.button_sync_share.setText(self.tr("Share with trusted devices"))

        for wallet_id, action in self.action_share_with_all_devices.items():
            action.setText(self.tr("Share with all devices in {wallet_id}").format(wallet_id=wallet_id))
        for wallet_id, menu in self.menu_share_with_single_devices.items():
            menu.setTitle(self.tr("Share with single device"))

    def switch_qr_type(self) -> None:
        self.clear_qr()
        self.lazy_load_qr(self.data)
        self.updateUi()

    def set_data(self, data: Data) -> None:
        self.data = data
        self.serialized = data.data_as_string()
        if data.data_type == DataType.PSBT:
            assert isinstance(data.data, bdk.PartiallySignedTransaction)
            self.txid = data.data.txid()
            self.json_data = json.dumps(json.loads(data.data.json_serialize()), indent=4)
        if data.data_type == DataType.Tx:
            assert isinstance(data.data, bdk.Transaction)
            self.txid = data.data.txid()
            self.json_data = json.dumps(transaction_to_dict(data.data), indent=4)

        if data.data_type in [DataType.Descriptor, DataType.MultiPathDescriptor]:
            self.qr_types = ["text", "bbqr"]
        else:
            self.qr_types = self.default_qr_types.copy()

    def _get_data_name(self) -> str:
        if self.data.data_type == DataType.PSBT:
            return self.tr("PSBT")
        if self.data.data_type == DataType.Tx:
            return self.tr("Transaction")
        return ""

    def create_copy_button(self) -> QWidget:
        outer_widget = QWidget()
        outer_widget.setLayout(QVBoxLayout())
        outer_widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.copy_toolbutton = QToolButton()
        self.copy_toolbutton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.copy_toolbutton.setIcon(QIcon(read_QIcon("clip.svg")))

        # Create a menu for the button
        def copy_if_available(s: Optional[str]) -> None:
            if s:
                do_copy(s)
            else:
                Message(self.tr("Not available"))

        menu = QMenu(self)
        self.action_copy_data = menu.addAction("", lambda: copy_if_available(self.data.data_as_string()))
        menu.addSeparator()
        self.action_copy_txid = menu.addAction("", lambda: copy_if_available(self.txid))
        self.action_json = menu.addAction("", lambda: copy_if_available(self.json_data))

        self.copy_toolbutton.setMenu(menu)
        self.copy_toolbutton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        outer_widget.layout().addWidget(self.copy_toolbutton)
        return outer_widget

    def create_sync_share_button(self) -> QWidget:
        outer_widget = QWidget()
        outer_widget.setLayout(QVBoxLayout())
        outer_widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.button_sync_share = QToolButton()
        self.button_sync_share.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button_sync_share.setIcon(QIcon(read_QIcon("cloud-sync.svg")))

        def factory(wallet_id: str, sync_tab: SyncTab, receiver_public_key_bech32: str = None) -> Callable:
            def f(
                wallet_id=wallet_id, sync_tab=sync_tab, receiver_public_key_bech32=receiver_public_key_bech32
            ) -> None:
                if not sync_tab.enabled():
                    Message(self.tr("Please enable the sync tab first"))
                    return
                if receiver_public_key_bech32:
                    self.on_nostr_share_with_member(
                        PublicKey.from_bech32(receiver_public_key_bech32), wallet_id, sync_tab
                    )
                else:
                    self.on_nostr_share_in_group(wallet_id, sync_tab)

            return f

        # Create a menu for the button
        menu = QMenu(self)
        self.action_share_with_all_devices: Dict[str, QAction] = {}
        self.menu_share_with_single_devices: Dict[str, QMenu] = {}
        for wallet_id, sync_tab in self.sync_tabs.items():
            self.action_share_with_all_devices[wallet_id] = menu.addAction("", factory(wallet_id, sync_tab))

            self.menu_share_with_single_devices[wallet_id] = menu.addMenu("")
            for member in sync_tab.nostr_sync.group_chat.members:
                self.menu_share_with_single_devices[wallet_id].addAction(
                    f"{short_key(member.to_bech32())}", factory(wallet_id, sync_tab, member.to_bech32())
                )
            menu.addSeparator()

        self.button_sync_share.setMenu(menu)
        self.button_sync_share.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        outer_widget.layout().addWidget(self.button_sync_share)
        return outer_widget

    def on_nostr_share_with_member(
        self, receiver_public_key: PublicKey, wallet_id: str, sync_tab: SyncTab
    ) -> None:
        if not sync_tab.enabled():
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id)
            )
            return
        sync_tab.nostr_sync.group_chat.dm_connection.send(
            BitcoinDM(label=ChatLabel.SingleRecipient, data=self.data, event=None, description=""),
            receiver_public_key,
        )

    def on_nostr_share_in_group(self, wallet_id: str, sync_tab: SyncTab) -> None:
        if not sync_tab.enabled():
            Message(
                self.tr("Please enable syncing in the wallet {wallet_id} first").format(wallet_id=wallet_id)
            )
            return

        sync_tab.nostr_sync.group_chat.send(
            BitcoinDM(label=ChatLabel.GroupChat, data=self.data, event=None, description=""),
            send_also_to_me=False,
        )

    def export_qrcode(self) -> Optional[str]:
        filename = save_file_dialog(
            name_filters=["Image (*.png)", "All Files (*.*)"],
            default_suffix="png",
            default_filename=f"{short_tx_id( self.txid)}.png" if self.txid else None,
        )
        if not filename:
            return None

        # Ensure the file has the .png extension
        if not filename.lower().endswith(".png"):
            filename += ".png"

        self.qr_label.save_file(filename)
        return filename

    def clear_qr(self) -> None:
        self.qr_label.set_images([])

    def lazy_load_qr(self, data: Data, max_length=200) -> None:
        def do() -> Any:
            if self.combo_qr_type.currentData() == "text":
                fragments = [data.data_as_string()]
            else:
                fragments = data.generate_fragments_for_qr(
                    max_qr_size=max_length, qr_type=self.combo_qr_type.currentData()
                )
            images = [QRGenerator.create_qr_svg(fragment) for fragment in fragments]
            return images

        def on_done(result) -> None:
            pass

        def on_error(packed_error_info) -> None:
            Message(packed_error_info, type=MessageType.Error)

        def on_success(result) -> None:
            if result:
                # here i must use a signal, and not set the image directly, because
                # self.qr_label can reference a destroyed c++ object
                self.signal_set_qr_images.emit(result)

        TaskThread(self, signals_min=self.signals_min).add_and_start(do, on_success, on_done, on_error)

    def export_to_file(self) -> Optional[str]:
        default_suffix = "txt"
        if self.data.data_type == DataType.Tx:
            default_suffix = "tx"
        if self.data.data_type == DataType.PSBT:
            default_suffix = "psbt"

        filename = save_file_dialog(
            name_filters=[
                f"{default_suffix.upper()} Files (*.{default_suffix})",
                "All Files (*.*)",
            ],
            default_suffix=default_suffix,
            default_filename=f"{short_tx_id( self.txid)}.{default_suffix}" if self.txid else None,
        )
        if not filename:
            return None

        # create a file descriptor
        fd = os.open(filename, os.O_CREAT | os.O_WRONLY)

        self.data.write_to_filedescriptor(fd)
        return filename
