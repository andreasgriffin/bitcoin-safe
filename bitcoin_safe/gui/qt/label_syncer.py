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
from collections import deque
from typing import List

from bitcoin_nostr_chat.connected_devices.connected_devices import TrustedDevice
from bitcoin_nostr_chat.nostr import BitcoinDM, ChatLabel
from nostr_sdk import PublicKey

from bitcoin_safe.gui.qt.sync_tab import SyncTab

logger = logging.getLogger(__name__)
from bitcoin_nostr_chat.nostr_sync import Data, DataType

from bitcoin_safe.labels import Labels, LabelType
from bitcoin_safe.signals import Signals, UpdateFilter


class LabelSyncer:
    def __init__(self, labels: Labels, sync_tab: SyncTab, signals: Signals) -> None:
        self.labels = labels
        self.sync_tab = sync_tab
        self.nostr_sync = sync_tab.nostr_sync
        self.signals = signals

        self.nostr_sync.signal_label_bip329_received.connect(self.on_nostr_label_bip329_received)
        self.nostr_sync.signal_add_trusted_device.connect(self.on_add_trusted_device)
        self.signals.labels_updated.connect(self.on_labels_updated)
        self.signals.category_updated.connect(self.on_labels_updated)

        # store sent UpdateFilters to prevent recursive behavior
        self.sent_update_filter: deque = deque(maxlen=1000)

    def on_add_trusted_device(self, trusted_device: TrustedDevice) -> None:
        if not self.sync_tab.enabled():
            return
        logger.debug(f"on_add_trusted_device")

        # send entire label data
        refs = list(self.labels.data.keys())

        bitcoin_data = Data(data=self.labels.dumps_data_jsonlines(refs=refs), data_type=DataType.LabelsBip329)
        self.nostr_sync.group_chat.dm_connection.send(
            BitcoinDM(event=None, label=ChatLabel.SingleRecipient, description="", data=bitcoin_data),
            PublicKey.from_bech32(trusted_device.pub_key_bech32),
        )
        logger.debug(f"sent all labels to {trusted_device.pub_key_bech32}")

    def on_nostr_label_bip329_received(self, data: Data) -> None:
        if not self.sync_tab.enabled():
            return

        logger.info(f"on_nostr_label_bip329_received {data}")
        if data.data_type == DataType.LabelsBip329:
            changed_labels = self.labels.import_dumps_data(data.data)
            if not changed_labels:
                return
            logger.debug(f"on_nostr_label_bip329_received updated: {changed_labels} ")

            addresses: List[str] = []
            txids: List[str] = []
            for label in changed_labels.values():
                if label.type == LabelType.addr:
                    addresses.append(label.ref)
                elif label.type == LabelType.tx:
                    txids.append(label.ref)

            new_categories = [
                label.category
                for label in changed_labels.values()
                if label.category not in self.labels.categories
            ]
            update_filter = UpdateFilter(addresses=addresses, txids=txids, categories=new_categories)
            self.sent_update_filter.append(update_filter)
            #  make the wallet add new addresses
            self.signals.addresses_updated.emit(update_filter)

            # recognize new labels
            self.signals.labels_updated.emit(update_filter)

            # the category editor maybe also needs to add categories
            self.signals.category_updated.emit(update_filter)

    def on_labels_updated(self, update_filter: UpdateFilter) -> None:
        if not self.sync_tab.enabled():
            return
        if update_filter in self.sent_update_filter:
            logger.debug("on_labels_updated: Do nothing because update_filter was sent from here.")
            return
        if update_filter.refresh_all:
            logger.debug("on_labels_updated: Do nothing on refresh_all.")
            return

        logger.info(f"on_labels_updated {update_filter}")

        refs = list(update_filter.addresses) + list(update_filter.txids)
        if not refs:
            return

        bitcoin_data = Data(data=self.labels.dumps_data_jsonlines(refs=refs), data_type=DataType.LabelsBip329)
        self.nostr_sync.group_chat.send(
            BitcoinDM(event=None, label=ChatLabel.GroupChat, description="", data=bitcoin_data)
        )
