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
from datetime import datetime

from bitcoin_safe.signals import SignalsMin

logger = logging.getLogger(__name__)

import os
from typing import Any, Dict, Optional

import bdkpython as bdk
from bitcoin_qrreader.bitcoin_qr import Data, DataType
from nostr_sdk import PublicKey
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from bitcoin_safe.gui.qt.nostr_sync.connected_devices.chat_gui import FileObject
from bitcoin_safe.html import html_f

from .connected_devices.connected_devices import (
    ConnectedDevices,
    TrustedDevice,
    UnTrustedDevice,
    short_key,
)
from .nostr import (
    BaseDM,
    BitcoinDM,
    ChatLabel,
    GroupChat,
    Keys,
    NostrProtocol,
    ProtocolDM,
)


def is_binary(file_path: str):
    """Check if a file is binary or text.

    Returns True if binary, False if text.
    """
    try:
        with open(file_path, "r") as f:
            for chunk in iter(lambda: f.read(1024), ""):
                if "\0" in chunk:  # found null byte
                    return True
    except UnicodeDecodeError:
        return True

    return False


def file_to_str(file_path: str):
    if is_binary(file_path):
        with open(file_path, "rb") as f:
            return bytes(f.read()).hex()
    else:
        with open(file_path, "r") as f:
            return f.read()


class NostrSync(QObject):
    signal_add_trusted_device = pyqtSignal(TrustedDevice)
    signal_attachement_clicked = pyqtSignal(FileObject)
    signal_label_bip329_received = pyqtSignal(Data)

    def __init__(
        self,
        network: bdk.Network,
        nostr_protocol: NostrProtocol,
        group_chat: GroupChat,
        signals_min: SignalsMin,
        individual_chats_visible=True,
        hide_data_types_in_chat: tuple[DataType] = (DataType.LabelsBip329,),
    ) -> None:
        super().__init__()
        self.network = network
        self.nostr_protocol = nostr_protocol
        self.group_chat = group_chat
        self.hide_data_types_in_chat = hide_data_types_in_chat
        self.signals_min = signals_min

        self.gui = ConnectedDevices(
            individual_chats_visible=individual_chats_visible, signals_min=signals_min
        )
        self.gui.set_title(self.group_chat.dm_connection.keys.public_key())
        self.gui.groupchat_gui.chat_list_display.signal_attachement_clicked.connect(
            self.signal_attachement_clicked
        )
        self.nostr_protocol.signal_dm.connect(self.on_signal_protocol_dm)
        self.group_chat.signal_dm.connect(self.on_dm)

        self.gui.groupchat_gui.signal_on_message_send.connect(self.on_send_message_in_groupchat)
        self.gui.groupchat_gui.signal_share_filepath.connect(self.on_share_filepath_in_groupchat)
        self.gui.signal_trust_device.connect(self.trust_device)
        self.gui.signal_untrust_device.connect(self.untrust_device)
        self.signal_attachement_clicked.connect(self.on_signal_attachement_clicked)
        self.gui.signal_renew_keys.connect(self.renew_own_key)
        self.gui.groupchat_gui.chat_list_display.signal_clear.connect(
            lambda: self.on_clear_chat_from_memory(chat_label=ChatLabel.GroupChat)
        )

    def is_me(self, public_key: PublicKey) -> bool:
        return public_key.to_bech32() == self.group_chat.dm_connection.keys.public_key().to_bech32()

    def on_clear_chat_from_memory(self, chat_label: ChatLabel, counterparty_key_bech32: str = None):
        def should_remove_item(item: BaseDM) -> bool:
            if isinstance(item, BitcoinDM):
                if item.label == chat_label:
                    if counterparty_key_bech32:
                        item_event = item.event
                        if not item_event:
                            return False

                        item_counterparty_public_key = self.get_counterparty_public_key(
                            item, dm_author_bech32=item_event.author().to_bech32()
                        )
                        return item_counterparty_public_key == counterparty_key_bech32
                    else:
                        return True
            return False

        for item in list(self.group_chat.dm_connection.queue):
            if should_remove_item(item):
                self.group_chat.dm_connection.queue.remove(item)

    def renew_own_key(self):
        self.group_chat.renew_own_key()
        self.publish_my_key_in_protocol()
        self.gui.set_title(self.group_chat.dm_connection.keys.public_key())

        # ask the members to trust my new key again (they need to manually approve)
        for member in self.group_chat.members:
            self.nostr_protocol.publish_trust_me_back(
                author_public_key=self.group_chat.dm_connection.keys.public_key(),
                recipient_public_key=member,
            )

    @classmethod
    def from_keys(
        cls,
        network: bdk.Network,
        protocol_keys: Keys,
        device_keys: Keys,
        signals_min: SignalsMin,
        individual_chats_visible=True,
    ) -> "NostrSync":
        nostr_protocol = NostrProtocol(network=network, keys=protocol_keys)
        group_chat = GroupChat(network=network, keys=device_keys)
        return NostrSync(
            network=network,
            nostr_protocol=nostr_protocol,
            group_chat=group_chat,
            individual_chats_visible=individual_chats_visible,
            signals_min=signals_min,
        )

    def dump(self) -> Dict[str, Any]:
        d = {}
        # exclude my own key. It's pointless to save and
        # later replay (internally) protocol messages that i sent previously
        d["nostr_protocol"] = self.nostr_protocol.dump(
            exclude_protocol_public_key_bech32s=[self.group_chat.dm_connection.keys.public_key().to_bech32()]
        )
        d["group_chat"] = self.group_chat.dump()
        d["individual_chats_visible"] = self.gui.individual_chats_visible
        return d

    @classmethod
    def from_dump(cls, d: Dict[str, Any], network: bdk.Network, signals_min: SignalsMin) -> "NostrSync":
        d["nostr_protocol"] = NostrProtocol.from_dump(d["nostr_protocol"], network=network)
        d["group_chat"] = GroupChat.from_dump(d["group_chat"], network=network)

        sync = NostrSync(**d, network=network, signals_min=signals_min)

        # add the gui elements for the trusted members
        for member in sync.group_chat.members:
            if sync.is_me(member):
                # do not add myself as a device
                continue
            untrusted_device = UnTrustedDevice(pub_key_bech32=member.to_bech32(), signals_min=signals_min)
            sync.gui.add_untrusted_device(untrusted_device)
            sync.trust_device(untrusted_device, show_message=False)

        # restore chat texts
        sync.nostr_protocol.dm_connection.replay_events()
        sync.group_chat.dm_connection.replay_events()
        return sync

    def subscribe(self):
        self.nostr_protocol.subscribe()
        self.group_chat.subscribe()
        self.publish_my_key_in_protocol()

    def unsubscribe(self):
        self.nostr_protocol.dm_connection.unsubscribe_all()
        self.group_chat.dm_connection.unsubscribe_all()

    def on_signal_attachement_clicked(self, file_object: FileObject):
        logger.debug(f"clicked: {file_object.__dict__}")

    def publish_my_key_in_protocol(self):
        self.nostr_protocol.publish_public_key(self.group_chat.dm_connection.keys.public_key())

    def on_dm(self, dm: BitcoinDM):
        if not dm.event:
            logger.debug(f"Dropping {dm}, because not event, and with that author can be determined.")
            return

        if dm.data and dm.data.data_type == DataType.LabelsBip329 and not self.is_me(dm.event.author()):
            # only emit a signal if I didn't send it
            self.signal_label_bip329_received.emit(dm.data)

        if dm.data and dm.data.data_type in self.hide_data_types_in_chat:
            # do not display it in chat
            pass
        elif dm.label == ChatLabel.DistrustMeRequest and not self.is_me(dm.event.author()):
            self.untrust_key(dm.event.author())
        elif dm.label == ChatLabel.DeleteMeRequest and not self.is_me(dm.event.author()):
            self.untrust_key(dm.event.author())
            untrusted_device = self.gui.untrusted_devices.get_device(dm.event.author().to_bech32())
            if untrusted_device:
                self.gui.untrusted_devices.remove_device(untrusted_device)
        else:
            self.add_to_chat(dm, author=dm.event.author())

    def untrust_key(self, member: PublicKey):
        trusted_device = self.gui.trusted_devices.get_device(member.to_bech32())
        if trusted_device:
            self.untrust_device(trusted_device)
        else:
            self.group_chat.remove_member(member)

    def add_to_chat(self, dm: BitcoinDM, author: PublicKey):
        author_bech32 = author.to_bech32()

        text = dm.description
        file_object = FileObject(path=dm.description, data=dm.data) if dm.data else None

        if dm.label == ChatLabel.GroupChat:
            chat_gui = self.gui.groupchat_gui
        elif dm.label == ChatLabel.SingleRecipient:
            trusted_device = self.get_trusted_device_of_single_recipient_dm(dm, author_bech32)
            if not trusted_device:
                return
            chat_gui = trusted_device.chat_gui
        else:
            logger.warning(f"Unrecognized dm.label {dm.label}")
            return

        if self.is_me(author):
            chat_gui.add_own(
                text=text,
                file_object=file_object,
                timestamp=dm.event.created_at().as_secs() if dm.event else datetime.now().timestamp(),
            )
        else:
            chat_gui.add_other(
                text=text,
                file_object=file_object,
                other_name=short_key(author_bech32),
                timestamp=dm.event.created_at().as_secs() if dm.event else datetime.now().timestamp(),
            )

    def get_counterparty_public_key(self, dm: BitcoinDM, dm_author_bech32: str) -> Optional[str]:
        if dm.label != ChatLabel.SingleRecipient:
            return None

        # if I sent it, and there is a intended_recipient
        # then the dm is a message from me to intended_recipient,
        # and should be displayed in trusted_device of the  intended_recipient
        if self.is_me(PublicKey.from_bech32(dm_author_bech32)):
            if dm.intended_recipient:
                return dm.intended_recipient
            return None
        else:
            return dm_author_bech32

    def get_trusted_device_of_single_recipient_dm(
        self, dm: BitcoinDM, dm_author_bech32: str
    ) -> Optional[TrustedDevice]:
        counterparty_public_key = self.get_counterparty_public_key(dm, dm_author_bech32)
        if counterparty_public_key:
            return self.gui.trusted_devices.get_device(counterparty_public_key)
        return None

    def on_send_message_in_groupchat(self, text: str):
        self.group_chat.send(BitcoinDM(label=ChatLabel.GroupChat, description=text, event=None))

    def filepath_to_dm(self, label: ChatLabel, file_path: str):
        s = file_to_str(file_path)
        bitcoin_data = Data.from_str(s, network=self.network)
        if not bitcoin_data:
            logger.warning(f"Could not recognize {s} as BitcoinData")
            return
        dm = BitcoinDM(label=label, description=os.path.basename(file_path), event=None, data=bitcoin_data)
        return dm

    def on_share_filepath_in_groupchat(self, file_path: str):
        dm = self.filepath_to_dm(label=ChatLabel.GroupChat, file_path=file_path)
        self.group_chat.send(dm)
        self.add_to_chat(dm, author=self.group_chat.dm_connection.keys.public_key())

    def connect_untrusted_device(self, untrusted_device: UnTrustedDevice):
        if untrusted_device.pub_key_bech32 in [k.to_bech32() for k in self.group_chat.members]:
            self.trust_device(untrusted_device, show_message=False)

    def on_signal_protocol_dm(self, dm: ProtocolDM):
        if self.is_me(PublicKey.from_bech32(dm.public_key_bech32)):
            # if I'm the autor do noting
            return
        if not dm.please_trust_public_key_bech32:
            # the message was just publishing an author_public_key_bech32
            untrusted_device = UnTrustedDevice(
                pub_key_bech32=dm.public_key_bech32, signals_min=self.signals_min
            )
            self.gui.add_untrusted_device(untrusted_device)
            self.connect_untrusted_device(untrusted_device)
        else:
            # the message is a request to trust the author
            untrusted_device2 = self.gui.untrusted_devices.get_device(dm.public_key_bech32)
            if not isinstance(untrusted_device2, UnTrustedDevice):
                return
            if not untrusted_device2:
                logger.warning(f"For {dm.public_key_bech32} could not be found an untrusted device")
                return
            untrusted_device2.set_button_status_to_accept()

    def untrust_device(self, trusted_device: TrustedDevice):
        self.group_chat.remove_member(PublicKey.from_bech32(trusted_device.pub_key_bech32))
        untrusted_device = self.gui.untrust_device(trusted_device)
        self.connect_untrusted_device(untrusted_device)

    def trust_device(self, untrusted_device: UnTrustedDevice, show_message=True) -> TrustedDevice:
        device_public_key = PublicKey.from_bech32(untrusted_device.pub_key_bech32)
        self.group_chat.add_member(device_public_key)

        def callback_on_message_send(text: str):
            event_id = self.group_chat.dm_connection.send(
                BitcoinDM(event=None, label=ChatLabel.SingleRecipient, description=text),
                receiver=PublicKey.from_bech32(untrusted_device.pub_key_bech32),
            )
            if event_id:
                # send copy to myself
                self.group_chat.dm_connection.send(
                    BitcoinDM(
                        event=None,
                        label=ChatLabel.SingleRecipient,
                        description=text,
                        intended_recipient=untrusted_device.pub_key_bech32,
                    ),
                    receiver=self.group_chat.dm_connection.keys.public_key(),
                )

        def callback_share_filepath(file_path: str):
            dm = self.filepath_to_dm(label=ChatLabel.SingleRecipient, file_path=file_path)
            event_id = self.group_chat.dm_connection.send(
                dm, receiver=PublicKey.from_bech32(untrusted_device.pub_key_bech32)
            )
            if event_id:
                # send copy to myself
                dm.intended_recipient = untrusted_device.pub_key_bech32
                self.group_chat.dm_connection.send(
                    dm, receiver=self.group_chat.dm_connection.keys.public_key()
                )

        trusted_device = self.gui.trust_device(
            untrusted_device,
            callback_attachement_clicked=self.signal_attachement_clicked.emit,
            callback_on_message_send=callback_on_message_send,
            callback_share_filepath=callback_share_filepath,
            callback_clear_chat=lambda: self.on_clear_chat_from_memory(
                chat_label=ChatLabel.SingleRecipient, counterparty_key_bech32=device_public_key.to_bech32()
            ),
        )
        self.nostr_protocol.publish_trust_me_back(
            author_public_key=self.group_chat.dm_connection.keys.public_key(),
            recipient_public_key=device_public_key,
        )

        assert trusted_device.pub_key_bech32 == untrusted_device.pub_key_bech32

        if show_message and not untrusted_device.trust_request_active():
            QMessageBox.information(
                self.gui,
                self.tr("Go to {untrusted}").format(untrusted=short_key(untrusted_device.pub_key_bech32)),
                self.tr(
                    "To complete the connection, accept my {id} request on the other device {other}."
                ).format(
                    id=html_f(
                        short_key(self.group_chat.dm_connection.keys.public_key().to_bech32()), bf=True
                    ),
                    other=html_f(short_key(untrusted_device.pub_key_bech32), bf=True),
                ),
            )

        self.signal_add_trusted_device.emit(trusted_device)
        return trusted_device
