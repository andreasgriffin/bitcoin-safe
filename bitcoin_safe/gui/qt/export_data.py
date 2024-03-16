import logging
from typing import Optional

from bitcoin_qrreader.bitcoin_qr import Data, DataType

from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.gui.qt.nostr_sync.connected_devices.connected_devices import short_key
from bitcoin_safe.gui.qt.nostr_sync.nostr import BitcoinDM, ChatLabel
from bitcoin_safe.tx import transaction_to_dict

from .qr_components.image_widget import QRCodeWidgetSVG
from .sync_tab import SyncTab

logger = logging.getLogger(__name__)

import json
import os

import bdkpython as bdk
from nostr_sdk import PublicKey
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
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

from ...signals import pyqtSignal
from ...util import TaskThread
from .qr_components.qr import create_qr_svg
from .util import Message, MessageType, do_copy, read_QIcon, save_file_dialog


class HorizontalImportExportGroups(QWidget):
    "Basis for a unified layout for import and export"

    def __init__(
        self,
    ) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setLayout(QHBoxLayout())
        self.layout().setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # qr
        self.group_qr = QGroupBox("QR Code")
        self.group_qr.setLayout(QVBoxLayout())
        self.group_qr.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_qr)

        # one of the groupboxes i have to make expanding, otherwise nothing is expanding
        self.group_qr.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        # file
        self.group_file = QGroupBox("File")
        self.group_file.setLayout(QVBoxLayout())
        self.group_file.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_file)

        # usb
        self.group_usb = QGroupBox("USB")
        self.group_usb.setLayout(QVBoxLayout())
        self.group_usb.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_usb)

        # clipboard
        self.group_share = QGroupBox("Share")
        self.group_share.setLayout(QVBoxLayout())
        self.group_share.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_share)

        # seed
        self.group_seed = QGroupBox("Seed")
        self.group_seed.setLayout(QVBoxLayout())
        self.group_seed.layout().setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout().addWidget(self.group_seed)
        self.group_seed.setVisible(False)


class ExportDataSimple(HorizontalImportExportGroups):
    signal_export_to_file = pyqtSignal()
    signal_set_qr_images = pyqtSignal(list)

    def __init__(
        self,
        data: Data,
        sync_tabs: dict[str, SyncTab] = None,
        usb_signer_ui: SignerUI = None,
    ) -> None:
        super().__init__()
        self.sync_tabs = sync_tabs if sync_tabs else {}
        self.txid = None
        self.json_data = None
        self.serialized = None
        self.set_data(data)

        self.signal_export_to_file.connect(self.export_to_file)

        # qr
        self.qr_label = QRCodeWidgetSVG()
        self.qr_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.group_qr.layout().addWidget(self.qr_label)
        self.lazy_load_qr(data)

        self.button_enlarge_qr = QPushButton("Enlarge")
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))
        # self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.group_qr.layout().addWidget(self.button_enlarge_qr)

        self.button_save_qr = QPushButton("Save as image")
        self.button_save_qr.setIcon(read_QIcon("download.png"))
        self.button_save_qr.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.group_qr.layout().addWidget(self.button_save_qr)

        # file
        self.button_file = QPushButton("Export file")
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

    def set_data(self, data: Data):
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

    def _get_data_name(self) -> str:
        if self.data.data_type == DataType.PSBT:
            return "PSBT"
        if self.data.data_type == DataType.Tx:
            return "Transaction"
        return ""

    def create_copy_button(self, title="Copy to clipboard"):
        outer_widget = QWidget()
        outer_widget.setLayout(QVBoxLayout())
        outer_widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(QIcon(read_QIcon("clip.svg")))
        button.setText(title)

        # Create a menu for the button
        def copy_if_available(s: Optional[str]):
            if s:
                do_copy(s)
            else:
                Message("Not available")

        menu = QMenu(self)
        action = menu.addAction(f"Copy {self._get_data_name()}")
        action.triggered.connect(lambda: copy_if_available(self.data.data_as_string()))
        menu.addSeparator()
        action = menu.addAction(f"Copy TxId")
        action.triggered.connect(lambda: copy_if_available(self.txid))
        action = menu.addAction(f"Copy JSON")
        action.triggered.connect(lambda: copy_if_available(self.json_data))

        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        outer_widget.layout().addWidget(button)
        return outer_widget

    def create_sync_share_button(self, title="Share with trusted devices"):
        outer_widget = QWidget()
        outer_widget.setLayout(QVBoxLayout())
        outer_widget.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        button = QToolButton()
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIcon(QIcon(read_QIcon("cloud-sync.svg")))
        button.setText(title)

        def factory(wallet_id: str, sync_tab: SyncTab, receiver_public_key_bech32: str = None):
            def f(
                wallet_id=wallet_id, sync_tab=sync_tab, receiver_public_key_bech32=receiver_public_key_bech32
            ):
                if receiver_public_key_bech32:
                    self.on_nostr_share_with_member(
                        PublicKey.from_bech32(receiver_public_key_bech32), wallet_id, sync_tab
                    )
                else:
                    self.on_nostr_share_in_group(wallet_id, sync_tab)

            return f

        # Create a menu for the button
        menu = QMenu(self)
        for wallet_id, sync_tab in self.sync_tabs.items():
            action = menu.addAction(f"Share with all devices in {wallet_id}")
            action.triggered.connect(factory(wallet_id, sync_tab))

            menu_single_device = menu.addMenu(f"Share with single device")
            for member in sync_tab.nostr_sync.group_chat.members:
                action = menu_single_device.addAction(f"{short_key(member.to_bech32())}")
                action.triggered.connect(factory(wallet_id, sync_tab, member.to_bech32()))
            menu.addSeparator()

        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        outer_widget.layout().addWidget(button)
        return outer_widget

    def on_nostr_share_with_member(self, receiver_public_key: PublicKey, wallet_id: str, sync_tab: SyncTab):
        if not sync_tab.enabled():
            Message(f"Please enable syncing in the wallet {wallet_id} first")
            return
        sync_tab.nostr_sync.group_chat.dm_connection.send(
            BitcoinDM(label=ChatLabel.SingleRecipient, data=self.data, event=None, description=""),
            receiver_public_key,
        )

    def on_nostr_share_in_group(self, wallet_id: str, sync_tab: SyncTab):
        if not sync_tab.enabled():
            Message(f"Please enable syncing in the wallet {wallet_id} first")
            return

        sync_tab.nostr_sync.group_chat.send(
            BitcoinDM(label=ChatLabel.GroupChat, data=self.data, event=None, description=""),
            send_also_to_me=False,
        )

    def export_qrcode(self):
        filename = save_file_dialog(name_filters=["Image (*.png)", "All Files (*.*)"], default_suffix="png")
        if not filename:
            return

        # Ensure the file has the .png extension
        if not filename.lower().endswith(".png"):
            filename += ".png"

        self.qr_label.save_file(filename)

    def lazy_load_qr(self, data: Data, max_length=200):
        def do():
            self.signal_set_qr_images.connect(self.qr_label.set_images)
            fragments = data.generate_fragments_for_qr(max_qr_size=max_length)
            images = [create_qr_svg(fragment) for fragment in fragments]
            return images

        def on_done(result):
            pass

        def on_error(packed_error_info):
            Message(packed_error_info, type=MessageType.Error)

        def on_success(result):
            if result:
                # here i must use a signal, and not set the image directly, because
                # self.qr_label can reference a destroyed c++ object
                self.signal_set_qr_images.emit(result)

        TaskThread(self).add_and_start(do, on_success, on_done, on_error)

    def export_to_file(self):
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
            default_filename=f"{self.txid}.{default_suffix}",
        )
        if not filename:
            return

        # create a file descriptor
        fd = os.open(filename, os.O_CREAT | os.O_WRONLY)

        self.data.write_to_filedescriptor(fd)
