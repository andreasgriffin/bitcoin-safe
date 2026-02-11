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

import hashlib
import logging
from typing import Any

import bdkpython as bdk
import nostr_sdk
from bitcoin_nostr_chat.chat_dm import ChatDM
from bitcoin_nostr_chat.nostr_sync import NostrSync
from bitcoin_nostr_chat.ui.chat_gui import FileObject
from bitcoin_nostr_chat.ui.util import short_key
from bitcoin_qr_tools.data import DataType
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_usb.address_types import AddressType, DescriptorInfo
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import QPushButton

from bitcoin_safe.descriptor_export_tools import shorten_filename
from bitcoin_safe.gui.qt.controlled_groupbox import ControlledGroupbox
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import (
    Message,
    adjust_bg_color_for_darkmode,
    save_file_dialog,
    svg_tools,
)
from bitcoin_safe.signals import Signals
from bitcoin_safe.storage import filtered_for_init
from bitcoin_safe.util import filename_clean

logger = logging.getLogger(__name__)


class BackupNsecNotificationBar(NotificationBar):
    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__(
            text="",
            optional_button_text="Save",
            has_close_button=True,
            callback_optional_button=self.on_optional_button,
        )
        self.nsec = ""
        self.wallet_id = ""
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("lightblue")))
        self.optionalButton.setIcon(svg_tools.get_QIcon("bi--download.svg"))
        self.set_icon(svg_tools.get_QIcon("bi--download.svg"))
        self.setVisible(False)
        self.icon_label.textLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.import_button = QPushButton()
        self.import_button.setIcon(svg_tools.get_QIcon("bi--upload.svg"))
        self.add_styled_widget(self.import_button)

    def on_optional_button(self):
        """On optional button."""
        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=shorten_filename(
                filename_clean(f"Sync key {self.wallet_id}", file_extension=".txt"), max_total_length=20
            ),
            window_title="Save Label backup key",
        )

        if not filename:
            return None

        with open(filename, "w") as file:
            file.write(
                self.tr("Sync key of wallet {wallet_id}:  {nsec}").format(
                    wallet_id=self.wallet_id, nsec=self.nsec
                )
            )
        return filename

    def setText(self, value: str | None):
        """SetText."""
        self.icon_label.textLabel.setText(value if value else "")

    def set_nsec(self, nsec: str, wallet_id: str) -> None:
        """Set nsec."""
        self.nsec = nsec
        self.wallet_id = wallet_id
        self.setText(self.tr("Please backup your sync key.").format(nsec=nsec))
        self.setHidden(False)

    def updateUi(self):
        """UpdateUi."""
        self.import_button.setText(self.tr("Restore labels"))
        self.optionalButton.setText(self.tr("Save sync key"))


class SyncTab(ControlledGroupbox):
    def __init__(
        self,
        network: bdk.Network,
        signals: Signals,
        nostr_sync_dump: dict,
        loop_in_thread: LoopInThread | None,
        nostr_sync: NostrSync | None = None,
        enabled: bool = False,
        auto_open_psbts: bool = True,
        parent=None,
        **kwargs,
    ) -> None:
        """Initialize instance."""
        super().__init__(parent=parent, enabled=enabled)
        self.signals = signals
        self.network = network

        self.groupbox_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.backup_nsec_notificationbar = BackupNsecNotificationBar()
        self.groupbox_layout.addWidget(self.backup_nsec_notificationbar)

        self.nostr_sync = (
            nostr_sync
            if nostr_sync
            else NostrSync.from_dump(
                d=nostr_sync_dump, signals_min=self.signals, parent=parent, loop_in_thread=loop_in_thread
            )
        )
        assert self.nostr_sync.network == network, (
            f"Network inconsistency. {network=} != {self.nostr_sync.network=}"
        )

        self.groupbox_layout.addWidget(self.nostr_sync.ui)

        # Create a checkable QAction
        self.checkbox_auto_open_psbts = QAction("")
        self.checkbox_auto_open_psbts.setCheckable(True)
        self.checkbox_auto_open_psbts.setChecked(auto_open_psbts)  # Set default state to checked
        self.nostr_sync.ui.menu.addAction(self.checkbox_auto_open_psbts)
        # self.groupbox_layout.addWidget(self.checkbox_auto_open_psbts)

        self.updateUi()

        # signals
        self.nostr_sync.chat.signal_attachement_clicked.connect(self.open_file_object)
        self.nostr_sync.group_chat.signal_dm.connect(self.on_dm)
        self.signals.language_switch.connect(self.updateUi)
        self.backup_nsec_notificationbar.import_button.clicked.connect(self.import_nsec)
        self.checkbox.stateChanged.connect(self.on_checkbox_state_changed)

    def set_wallet_id(self, wallet_id: str):
        """Set wallet id."""
        self.backup_nsec_notificationbar.wallet_id = wallet_id

    def on_checkbox_state_changed(self, value) -> None:
        """On checkbox state changed."""
        self.on_enable(self.enabled())

        if not self.checkbox.isChecked():
            return
        self.backup_nsec_notificationbar.set_nsec(
            nsec=self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.secret_key().to_bech32(),
            wallet_id=self.backup_nsec_notificationbar.wallet_id,
        )

        self.publish_key()

    def publish_key(self):
        # just in case the relay lost the publish key message. I republish here
        """Publish key."""
        my_key = short_key(
            self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.public_key().to_bech32()
        )
        chat_key = short_key(
            self.nostr_sync.nostr_protocol.dm_connection.async_dm_connection.keys.public_key().to_bech32()
        )
        logger.info(f"Publish my key {my_key} in protocol chat {chat_key}")
        self.nostr_sync.publish_my_key_in_protocol(force=True)

    def import_nsec(self):
        """Import nsec."""
        self.nostr_sync.ui.signal_set_keys.emit()

    @staticmethod
    def get_icon_basename(enabled: bool) -> str:
        """Get icon basename."""
        return "bi--cloud.svg" if enabled else "bi--cloud-slash.svg"

    @classmethod
    def get_checkbox_text(cls):
        """Get checkbox text."""
        return cls.tr("Label backup and encrypted syncing to trusted devices")

    def updateUi(self) -> None:
        """UpdateUi."""
        self.checkbox.setText(self.get_checkbox_text())
        self.checkbox_auto_open_psbts.setText(self.tr("Open received Transactions and PSBTs"))
        self.backup_nsec_notificationbar.updateUi()

    def unsubscribe_all(self) -> None:
        """Unsubscribe all."""
        if self.enabled():
            self.nostr_sync.unsubscribe()

    def finish_init_after_signal_connection(self) -> None:
        """Finish init after signal connection."""
        if self.enabled():
            self.on_enable(self.enabled())

    def subscribe(self) -> None:
        """Subscribe."""
        self.nostr_sync.subscribe()

    def on_dm(self, dm: ChatDM) -> None:
        """Catches DataType.PSBT, DataType.Tx and opens them in a tab It also notifies
        of.

        Args:
            dm (ChatDM): _description_
        """
        if self.nostr_sync.group_chat.sync_start and (dm.created_at < self.nostr_sync.group_chat.sync_start):
            # dm was created before the last shutdown,
            # and therefore should have been received already.
            return
        if dm.author:
            if self.nostr_sync.is_me(dm.author):
                # do nothing if i sent it
                return
            if (
                dm.data
                and dm.data.data_type in [DataType.PSBT, DataType.Tx]
                and self.checkbox_auto_open_psbts.isChecked()
            ):
                Message(
                    self.tr("Opening {name} from {author}").format(
                        name=dm.data.data_type.name, author=self.nostr_sync.chat.get_alias(dm.author)
                    ),
                    no_show=True,
                    parent=self,
                ).emit_with(self.signals.notification)
                self.signals.open_tx_like.emit(dm.data.data)
            elif not dm.data:
                Message(
                    self.tr("{author}: {description}").format(
                        description=dm.description, author=self.nostr_sync.chat.get_alias(dm.author)
                    ),
                    no_show=True,
                    parent=self,
                ).emit_with(self.signals.notification)

    def enabled(self) -> bool:
        """Enabled."""
        return self.checkbox.isChecked()

    @classmethod
    def generate_hash_hex(
        cls,
        address_type: AddressType,
        xpubs: list[str],
        network: bdk.Network,
    ) -> str:
        """Generate hash hex."""
        default_key_origin = address_type.key_origin(network)

        total_string = default_key_origin + "".join(sorted(xpubs))
        return hashlib.sha256(total_string.encode()).hexdigest()

    @classmethod
    def from_descriptor_new_device_keys(
        cls,
        multipath_descriptor: bdk.Descriptor,
        network: bdk.Network,
        signals: Signals,
        loop_in_thread: LoopInThread | None,
        parent: QObject | None = None,
    ) -> SyncTab:
        """From descriptor new device keys."""
        descriptor_info = DescriptorInfo.from_str(str(multipath_descriptor))
        xpubs = [spk_provider.xpub for spk_provider in descriptor_info.spk_providers]

        protocol_keys = nostr_sdk.Keys(
            secret_key=nostr_sdk.SecretKey.parse(
                hashlib.sha256(
                    cls.generate_hash_hex(descriptor_info.address_type, xpubs, network).encode("utf-8")
                ).hexdigest()
            )
        )

        device_keys = nostr_sdk.Keys.generate()
        logger.info(
            f"Generated a new nostr keypair with public key "
            f"{short_key(device_keys.public_key().to_bech32())} and saving to wallet"
        )
        nostr_sync = NostrSync.from_keys(
            network=network,
            protocol_keys=protocol_keys,
            device_keys=device_keys,
            individual_chats_visible=False,
            signals_min=signals,
            parent=parent,
            loop_in_thread=loop_in_thread,
        )

        return SyncTab(
            nostr_sync_dump={},
            nostr_sync=nostr_sync,
            network=network,
            signals=signals,
            parent=parent,
            loop_in_thread=loop_in_thread,
        )

    def dump(self) -> dict[str, Any]:
        """Dump."""
        return {
            "auto_open_psbts": self.checkbox_auto_open_psbts.isChecked(),
            "enabled": self.checkbox.isChecked(),
            "nostr_sync_dump": self.nostr_sync.dump(),
        }

    @classmethod
    def from_dump(cls, sync_tab_dump: dict, network: bdk.Network, signals: Signals) -> SyncTab:
        """From dump."""
        return cls(**filtered_for_init(sync_tab_dump, cls), network=network, signals=signals)

    def open_file_object(self, file_object: FileObject) -> None:
        """Open file object."""
        if not file_object or not file_object.data:
            return
        self.signals.open_tx_like.emit(file_object.data.data)

    def on_enable(self, enable: bool) -> None:
        """On enable."""
        if enable:
            self.subscribe()
        else:
            self.nostr_sync.unsubscribe()

    def close(self) -> bool:
        """Close."""
        self.nostr_sync.close()
        return super().close()
