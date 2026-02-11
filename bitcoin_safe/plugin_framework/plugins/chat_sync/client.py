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
import platform
import socket
from hashlib import sha256
from typing import cast

import bdkpython as bdk
import nostr_sdk
from bitcoin_nostr_chat.chat_dm import ChatDM
from bitcoin_nostr_chat.nostr_sync import NostrSync
from bitcoin_nostr_chat.ui.chat_gui import FileObject
from bitcoin_nostr_chat.ui.util import short_key
from bitcoin_qr_tools.data import DataType
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_usb.address_types import AddressType, DescriptorInfo
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from bitcoin_safe.descriptor_export_tools import shorten_filename
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import Message, adjust_bg_color_for_darkmode, save_file_dialog, svg_tools
from bitcoin_safe.html_utils import link
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_conditions import PluginConditions
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServerView
from bitcoin_safe.plugin_framework.plugins.chat_sync.label_syncer import LabelSyncer
from bitcoin_safe.signals import Signals
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


class SyncClient(PluginClient):
    VERSION = "0.0.3"
    known_classes = {**PluginClient.known_classes, PluginPermission.__name__: PluginPermission}
    plugin_conditions = PluginConditions()
    required_permissions: set[PluginPermission] = {
        PluginPermission.LABELS,
        PluginPermission.WALLET_SIGNALS,
        PluginPermission.MN_TUPLE,
        PluginPermission.ADDRESS,
        PluginPermission.DESCRIPTOR,
    }
    title = translate("SyncClient", "Sync & Chat")
    description = translate(
        "SyncClient",
        "- Backup your labels and coin categories in the cloud.<br>"
        "- Synchronize your labels and coin categories between multiple computers. {synclink}<br>"
        "- Sign a transaction with others collaboratively, "
        "no matter where you are in the world. {videolink}<br>"
        "- Everything is always encrypted (learn more about the {protocol_link})",
    ).format(
        videolink=link(
            url="https://bitcoin-safe.org/en/features/collaboration/",
            text=translate("SyncClient", "Collaboration Video"),
        ),
        synclink=link(
            url="https://bitcoin-safe.org/en/features/label-sync/",
            text=translate("SyncClient", "Synchronization Video"),
        ),
        protocol_link=link(
            url="https://github.com/andreasgriffin/bitcoin-nostr-chat/?tab=readme-ov-file#protocol",
            text=translate("SyncClient", "protocol"),
        ),
    )
    provider = "Bitcoin Safe (via Nostr)"

    @staticmethod
    def cls_kwargs(
        signals: Signals,
        network: bdk.Network,
        loop_in_thread: LoopInThread | None,
    ):
        return {
            "signals": signals,
            "network": network,
            "loop_in_thread": loop_in_thread,
        }

    def __init__(
        self,
        network: bdk.Network,
        signals: Signals,
        nostr_sync_dump: dict,
        loop_in_thread: LoopInThread | None,
        nostr_sync: NostrSync | None = None,
        enabled: bool = False,
        auto_open_psbts: bool = True,
        device_info: dict[str, str] | None = None,
    ):
        """Initialize instance."""
        super().__init__(enabled=enabled, icon=svg_tools.get_QIcon("bi--cloud.svg"))
        self.close_all_video_widgets: SignalProtocol[[]] | None = None
        self.label_syncer: LabelSyncer | None = None
        self.device_info = device_info or {}

        self.signals = signals
        self.network = network
        self.auto_open_psbts = auto_open_psbts

        self.nostr_sync = (
            nostr_sync
            if nostr_sync
            else NostrSync.from_dump(
                d=nostr_sync_dump, signals_min=self.signals, parent=self, loop_in_thread=loop_in_thread
            )
        )
        assert self.nostr_sync.network == network, (
            f"Network inconsistency. {network=} != {self.nostr_sync.network=}"
        )

        self.backup_nsec_notificationbar = BackupNsecNotificationBar()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._layout.addWidget(self.backup_nsec_notificationbar)
        self._layout.addWidget(self.nostr_sync.ui)

        # Create a checkable QAction
        self.checkbox_auto_open_psbts = QAction("")
        self.checkbox_auto_open_psbts.setCheckable(True)
        self.checkbox_auto_open_psbts.setChecked(auto_open_psbts)  # Set default state to checked
        self.nostr_sync.ui.menu.addAction(self.checkbox_auto_open_psbts)

        # signals
        self.signal_tracker.connect(self.nostr_sync.chat.signal_attachement_clicked, self.open_file_object)
        self.signal_tracker.connect(self.nostr_sync.group_chat.signal_dm, self.on_dm)
        self.signal_tracker.connect(self.signals.language_switch, self.updateUi)
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.backup_nsec_notificationbar.import_button.clicked), self.import_nsec
        )

        self.updateUi()

    def import_nsec(self):
        """Import nsec."""
        self.nostr_sync.ui.signal_set_keys.emit()

    @staticmethod
    def _hostname_hash(hostname: str) -> str:
        return sha256(hostname.encode("utf-8")).hexdigest()

    @classmethod
    def _current_device_info(cls) -> dict[str, str]:
        hostname = platform.node() or socket.gethostname() or "unknown"
        return {"hostname": cls._hostname_hash(hostname)}

    def _handle_possible_device_change(self) -> None:
        """Detect device change and optionally reset sync key."""
        current_info = self._current_device_info()
        current_hostname_hash = current_info.get("hostname")
        stored_hostname_hash = self.device_info.get("hostname")

        if (
            not current_hostname_hash
            or not stored_hostname_hash
            or stored_hostname_hash == current_hostname_hash
        ):
            return

        reset_keys = question_dialog(
            text=self.tr(
                "This wallet was last used on another computer.\n"
                "If you want to keep using both, please reset the Chat & Sync sync key (nsec) now."
            ).format(current=platform.node() or socket.gethostname() or self.tr("this computer")),
            title=self.tr("New computer detected"),
            true_button=self.tr("Reset sync key"),
            false_button=self.tr("Keep existing key"),
        )

        if reset_keys:
            self.nostr_sync.reset_own_key()
            if self.server:
                self.backup_nsec_notificationbar.set_nsec(
                    nsec=self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.secret_key().to_bech32(),
                    wallet_id=self.server.wallet_id,
                )

        self.device_info["hostname"] = current_hostname_hash

    def set_enabled(self, value: bool):
        """On set enabled."""
        if self.enabled == value:
            return
        super().set_enabled(value=value)
        if value and self.server:
            self.backup_nsec_notificationbar.set_nsec(
                nsec=self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.secret_key().to_bech32(),
                wallet_id=self.server.wallet_id,
            )
        if self.label_syncer:
            self.label_syncer.set_enabled(value=value)

    def get_widget(self) -> QWidget:
        """Get widget."""
        return self

    def set_server_view(
        self,
        server: PluginServerView,
    ):
        """Save connection details."""
        super().set_server_view(server=server)

        labels = server.get_labels()
        if not self.server:
            return
        wallet_signals = self.server.get_wallet_signals()
        if labels and wallet_signals:
            self.label_syncer = LabelSyncer(
                labels=labels,
                nostr_sync=self.nostr_sync,
                enabled=self.enabled,
                wallet_signals=wallet_signals,
            )

    @classmethod
    def from_descriptor(
        cls,
        multipath_descriptor: bdk.Descriptor,
        network: bdk.Network,
        signals: Signals,
        loop_in_thread: LoopInThread | None,
        parent: QWidget | None = None,
    ) -> SyncClient:
        """From descriptor."""
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

        return SyncClient(
            nostr_sync_dump={},
            nostr_sync=nostr_sync,
            network=network,
            signals=signals,
            loop_in_thread=loop_in_thread,
        )

    def load(self):
        # setting the parent here is crucial to avoid errors when closing
        """Load."""
        self.nostr_sync.setParent(self)
        self._handle_possible_device_change()
        self.subscribe()
        self.publish_key()

    def unload(self):
        """Unload."""
        self.nostr_sync.unsubscribe()

    def publish_key(self):
        # just in case the relay lost the publish key message. I republish here
        """Publish key."""
        if not self.enabled:
            return

        my_key = short_key(
            self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.public_key().to_bech32()
        )
        chat_key = short_key(
            self.nostr_sync.nostr_protocol.dm_connection.async_dm_connection.keys.public_key().to_bech32()
        )
        logger.info(f"Publish my key {my_key} in protocol chat {chat_key}")
        self.nostr_sync.publish_my_key_in_protocol(force=True)

    @classmethod
    def get_checkbox_text(cls):
        """Get checkbox text."""
        return cls.tr("Label backup and encrypted syncing to trusted devices")

    def updateUi(self) -> None:
        """UpdateUi."""
        self.node.setTitle(self.tr("Sync & Chat"))
        self.checkbox_auto_open_psbts.setText(self.tr("Open received Transactions and PSBTs"))
        self.backup_nsec_notificationbar.updateUi()
        super().updateUi()

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

    def drop_wallet_specific_things(self) -> bool:
        return False

    def dump(self) -> dict:
        """Dump."""
        d = super().dump()
        d["auto_open_psbts"] = self.checkbox_auto_open_psbts.isChecked()
        d["nostr_sync_dump"] = self.nostr_sync.dump()
        d["device_info"] = self.device_info

        return d

    def open_file_object(self, file_object: FileObject) -> None:
        """Open file object."""
        if not file_object or not file_object.data:
            return
        self.signals.open_tx_like.emit(file_object.data.data)

    def close(self) -> bool:
        """Close."""
        self.nostr_sync.unsubscribe()
        self.nostr_sync.ui.close()
        if self.label_syncer:
            self.label_syncer.close()
        return super().close()
