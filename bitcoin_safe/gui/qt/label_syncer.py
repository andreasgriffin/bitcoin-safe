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
from time import sleep
from typing import List

from bitcoin_nostr_chat.connected_devices.connected_devices import (
    TrustedDevice,
    short_key,
)
from bitcoin_nostr_chat.nostr import BitcoinDM, ChatLabel
from nostr_sdk import PublicKey
from PyQt6.QtCore import QObject

from bitcoin_safe.gui.qt.sync_tab import SyncTab

logger = logging.getLogger(__name__)
from bitcoin_nostr_chat.nostr_sync import Data, DataType

from bitcoin_safe.labels import Labels, LabelType
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason, WalletSignals


class LabelSyncer(QObject):
    def __init__(self, labels: Labels, sync_tab: SyncTab, wallet_signals: WalletSignals) -> None:
        super().__init__()
        self.labels = labels
        self.sync_tab = sync_tab
        self.nostr_sync = sync_tab.nostr_sync
        self.wallet_signals = wallet_signals

        self.apply_own_labels = True

        self.nostr_sync.signal_label_bip329_received.connect(self.on_nostr_label_bip329_received)
        self.nostr_sync.signal_add_trusted_device.connect(self.on_add_trusted_device)
        self.wallet_signals.updated.connect(self.on_labels_updated)

    @staticmethod
    def chunk_lines(lines: List[str], max_len: int = 60_000) -> List[List[str]]:
        len_of_lines = [len(line) for line in lines]  # Calculate the length of each line

        # Determine split points
        split_indices = []
        current_length = 0

        for i, line_length in enumerate(len_of_lines):
            if current_length + line_length > max_len:
                split_indices.append(i)
                current_length = line_length  # Start new chunk with current line
            else:
                current_length += line_length + 1  # +1 for the newline, included in the next chunk

        # Use split indices to construct chunks
        chunks = []
        start_index = 0

        for index in split_indices:
            chunks.append(lines[start_index:index])
            start_index = index

        # Add the final chunk
        if start_index < len(lines):
            chunks.append(lines[start_index:])

        return chunks

    def get_chunked_bitcoin_data(self, refs: List[str]) -> List[Data]:
        lines = self.labels.dumps_data_jsonline_list(refs=refs)
        chunks = self.chunk_lines(lines, max_len=60_000)
        return [Data(data="\n".join(chunk), data_type=DataType.LabelsBip329) for chunk in chunks]

    def on_add_trusted_device(self, trusted_device: TrustedDevice) -> None:
        if not self.sync_tab.enabled():
            return
        logger.debug(f"on_add_trusted_device")

        # send entire label data
        refs = list(self.labels.data.keys())

        for bitcoin_data in self.get_chunked_bitcoin_data(refs):
            self.nostr_sync.group_chat.dm_connection.send(
                BitcoinDM(
                    event=None,
                    label=ChatLabel.SingleRecipient,
                    description="",
                    data=bitcoin_data,
                    created_at=datetime.now(),
                ),
                PublicKey.from_bech32(trusted_device.pub_key_bech32),
            )
        logger.info(f"Sent all labels to trusted device {short_key( trusted_device.pub_key_bech32)}")

    def on_nostr_label_bip329_received(self, data: Data, author: PublicKey) -> None:
        if not self.sync_tab.enabled():
            return

        if data.data_type != DataType.LabelsBip329:
            logger.debug(f"on_nostr_label_bip329_received received wrong type {type(data)}")
            return

        if self.sync_tab.nostr_sync.is_me(author) and not self.apply_own_labels:
            logger.debug(f"on_nostr_label_bip329_received do not apply laybels from myself {author}")
            return

        changed_labels = self.labels.import_dumps_data(data.data)
        if not changed_labels:
            logger.debug(f"no labels changed in on_nostr_label_bip329_received")
            return
        logger.info(f"on_nostr_label_bip329_received applied {len(changed_labels)} labels: {changed_labels} ")

        addresses: List[str] = []
        txids: List[str] = []
        for label in changed_labels.values():
            if label.type == LabelType.addr:
                addresses.append(label.ref)
            elif label.type == LabelType.tx:
                txids.append(label.ref)

        new_categories = [label.category for label in changed_labels.values()]
        update_filter = UpdateFilter(
            addresses=addresses,
            txids=txids,
            categories=new_categories,
            reason=UpdateFilterReason.SourceLabelSyncer,
        )
        #  make the wallet add new addresses
        self.wallet_signals.updated.emit(update_filter)
        logger.info(
            f"{self.__class__.__name__}: Received {len(addresses)} addresses, {len(txids)} txids, {len(new_categories)} categories  from {short_key(author.to_bech32())}"
        )

    def on_labels_updated(self, update_filter: UpdateFilter) -> None:
        if not self.sync_tab.enabled():
            return
        if update_filter.reason == UpdateFilterReason.SourceLabelSyncer:
            logger.debug("on_labels_updated: Do nothing because update_filter was sent from here.")
            return
        if update_filter.refresh_all:
            logger.debug("on_labels_updated: Do nothing on refresh_all.")
            return

        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.addresses:
            should_update = True
        if should_update or update_filter.categories:
            should_update = True

        if not should_update:
            return

        logger.debug(f"{self.__class__.__name__} update_with_filter {update_filter}")

        refs = list(update_filter.addresses) + list(update_filter.txids)
        if not refs:
            return

        for bitcoin_data in self.get_chunked_bitcoin_data(refs):
            self.nostr_sync.group_chat.send(
                BitcoinDM(
                    event=None,
                    label=ChatLabel.GroupChat,
                    description="",
                    data=bitcoin_data,
                    created_at=datetime.now(),
                )
            )
        logger.info(
            f"{self.__class__.__name__}: Sent {len(update_filter.addresses)} addresses, {len(update_filter.txids)} txids to {[short_key(m.to_bech32()) for m in  self.nostr_sync.group_chat.members]}"
        )

    def send_all_labels_to_myself(self):
        if not self.sync_tab.enabled():
            return
        logger.debug(f"send_all_labels_to_myself")

        # send entire label data
        refs = list(self.labels.data.keys())

        my_key = self.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.public_key()
        for bitcoin_data in self.get_chunked_bitcoin_data(refs):
            self.nostr_sync.group_chat.dm_connection.send(
                BitcoinDM(
                    event=None,
                    label=ChatLabel.SingleRecipient,
                    description="",
                    data=bitcoin_data,
                    created_at=datetime.now(),
                ),
                my_key,
            )
        # sleep here to give the relays time to receive the message
        # but if the relays fail, then better fail sending the messages,
        # than blocking the wallet from closing
        sleep(0.2)
