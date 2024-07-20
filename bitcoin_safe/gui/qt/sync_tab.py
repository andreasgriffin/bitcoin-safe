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


import hashlib
import logging
from datetime import datetime

import nostr_sdk
from bitcoin_nostr_chat.connected_devices.chat_gui import FileObject
from bitcoin_nostr_chat.connected_devices.connected_devices import short_key
from bitcoin_nostr_chat.nostr import BitcoinDM
from bitcoin_nostr_chat.nostr_sync import NostrSync
from bitcoin_qr_tools.data import DataType
from PyQt6.QtCore import QObject, Qt
from PyQt6.QtWidgets import QCheckBox, QVBoxLayout

from bitcoin_safe.descriptors import MultipathDescriptor
from bitcoin_safe.gui.qt.controlled_groupbox import ControlledGroupbox
from bitcoin_safe.gui.qt.util import Message
from bitcoin_safe.signals import Signals
from bitcoin_safe.storage import filtered_for_init

logger = logging.getLogger(__name__)

from typing import Dict

import bdkpython as bdk


class SyncTab(QObject):
    def __init__(
        self,
        nostr_sync_dump: Dict,
        network: bdk.Network,
        signals: Signals,
        nostr_sync: NostrSync = None,
        enabled: bool = False,
        auto_open_psbts: bool = True,
        **kwargs,
    ) -> None:
        super().__init__()
        self.signals = signals
        self.network = network
        self.startup_time = datetime.now()

        self.main_widget = ControlledGroupbox(checkbox_text="", enabled=enabled)
        self.main_widget.groupbox.setLayout(QVBoxLayout())

        self.main_widget.checkbox.stateChanged.connect(self.checkbox_state_changed)

        self.checkbox_auto_open_psbts = QCheckBox()
        self.checkbox_auto_open_psbts.setChecked(auto_open_psbts)
        self.main_widget.groupbox.layout().addWidget(self.checkbox_auto_open_psbts)

        self.nostr_sync = (
            nostr_sync
            if nostr_sync
            else NostrSync.from_dump(d=nostr_sync_dump, network=network, signals_min=self.signals)
        )

        self.updateUi()

        # signals
        self.nostr_sync.signal_attachement_clicked.connect(self.open_file_object)
        self.nostr_sync.group_chat.signal_dm.connect(self.on_dm)
        self.main_widget.groupbox.layout().addWidget(self.nostr_sync.gui)
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self) -> None:
        self.main_widget.checkbox.setText(self.tr("Encrypted syncing to trusted devices"))
        self.checkbox_auto_open_psbts.setText(
            self.tr("Open received Transactions and PSBTs automatically in a new tab")
        )

    def unsubscribe_all(self) -> None:
        if self.enabled():
            self.nostr_sync.unsubscribe()

    def finish_init_after_signal_connection(self) -> None:
        if self.enabled():
            self.on_enable(self.enabled())

    def checkbox_state_changed(self, state) -> None:
        self.on_enable(state == Qt.CheckState.Checked.value)

    def subscribe(self) -> None:
        self.nostr_sync.subscribe()

    def on_dm(self, dm: BitcoinDM) -> None:
        if dm.created_at and self.startup_time > datetime.fromtimestamp(dm.created_at.as_secs()):
            # dm was created before startup
            return
        if dm.author:
            if self.nostr_sync.is_me(dm.author):
                # do nothing if i sent it
                return
            if dm.data and dm.data.data_type in [DataType.PSBT, DataType.Tx]:
                Message(
                    self.tr("Opening {name} from {author}").format(
                        name=dm.data.data_type.name, author=short_key(dm.author.to_bech32())
                    ),
                    no_show=True,
                ).emit_with(self.signals.notification)
                self.signals.open_tx_like.emit(dm.data.data)
            elif not dm.data:
                Message(
                    self.tr("Received message '{description}' from {author}").format(
                        description=dm.description, author=short_key(dm.author.to_bech32())
                    ),
                    no_show=True,
                ).emit_with(self.signals.notification)

    def enabled(self) -> bool:
        return self.main_widget.checkbox.isChecked()

    @classmethod
    def from_descriptor_new_device_keys(
        cls, multipath_descriptor: MultipathDescriptor, network: bdk.Network, signals: Signals
    ) -> "SyncTab":
        encoded_wallet_descriptor = hashlib.sha256(multipath_descriptor.as_string().encode()).hexdigest()
        protocol_keys = nostr_sdk.Keys(
            secret_key=nostr_sdk.SecretKey.from_hex(
                hashlib.sha256(encoded_wallet_descriptor.encode("utf-8")).hexdigest()
            )
        )

        device_keys = nostr_sdk.Keys.generate()
        logger.info(
            f"Generated a new nostr keypair with public key {device_keys.public_key().to_bech32()} and saving to wallet"
        )
        nostr_sync = NostrSync.from_keys(
            network=network,
            protocol_keys=protocol_keys,
            device_keys=device_keys,
            individual_chats_visible=False,
            signals_min=signals,
        )

        return SyncTab(nostr_sync_dump={}, nostr_sync=nostr_sync, network=network, signals=signals)

    def dump(self) -> Dict:
        return {
            "auto_open_psbts": self.checkbox_auto_open_psbts.isChecked(),
            "enabled": self.main_widget.checkbox.isChecked(),
            "nostr_sync_dump": self.nostr_sync.dump(),
        }

    @classmethod
    def from_dump(cls, sync_tab_dump: Dict, network: bdk.Network, signals: Signals) -> "SyncTab":
        return cls(**filtered_for_init(sync_tab_dump, cls), network=network, signals=signals)

    def open_file_object(self, file_object: FileObject) -> None:
        if not file_object or not file_object.data:
            return
        self.signals.open_tx_like.emit(file_object.data.data)

    def on_enable(self, enable: bool) -> None:
        if enable:
            self.subscribe()
        else:
            self.nostr_sync.unsubscribe()
