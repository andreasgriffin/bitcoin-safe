import logging
from collections import deque
from typing import List

from bitcoin_safe.gui.qt.nostr_sync.nostr import BitcoinDM, ChatLabel

logger = logging.getLogger(__name__)
from bitcoin_safe.labels import Labels, LabelType
from bitcoin_safe.signals import Signals, UpdateFilter

from .nostr_sync.nostr_sync import Data, DataType, NostrSync


class LabelSyncer:
    def __init__(self, labels: Labels, nostr_sync: NostrSync, signals: Signals) -> None:
        self.labels = labels
        self.nostr_sync = nostr_sync
        self.signals = signals

        self.nostr_sync.signal_label_bip329_received.connect(self.on_nostr_label_bip329_received)
        self.signals.labels_updated.connect(self.on_labels_updated)

        # store sent UpdateFilters to prevent recursive behavior
        self.sent_update_filter: deque = deque(maxlen=1000)

    def on_nostr_label_bip329_received(self, data: Data):
        logger.info(f"on_nostr_label_bip329_received {data}")
        if data.data_type == DataType.LabelsBip329:
            changed_labels = self.labels.import_dumps_data(data.data)
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

    def on_labels_updated(self, update_filter: UpdateFilter):
        if update_filter in self.sent_update_filter:
            logger.debug("on_labels_updated: Do nothing because update_filter was sent from here.")
            return

        logger.info(f"on_labels_updated {update_filter}")

        refs = list(update_filter.addresses) + list(update_filter.txids)

        bitcoin_data = Data(data=self.labels.dumps_data_jsonlines(refs=refs), data_type=DataType.LabelsBip329)
        self.nostr_sync.group_chat.send(
            BitcoinDM(event=None, label=ChatLabel.GroupChat, description="", data=bitcoin_data)
        )
