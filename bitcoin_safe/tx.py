import logging

from .pythonbdk_types import Recipient

logger = logging.getLogger(__name__)

import bdkpython as bdk
from typing import List


class TXInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.labels = {}
        self.categories = []
        self.utxo_strings = []
        self.fee_rate = None
        self.opportunistic_merge_utxos = True

        self.recipients: List[Recipient] = []

        self.utxos_for_input = None
        self.builder_result: bdk.TxBuilderResult = None

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate):
        self.fee_rate = feerate

    def clone(self):
        infos = TXInfos()
        infos.labels = self.labels.copy()
        infos.categories = self.categories.copy()
        infos.utxo_strings = self.utxo_strings.copy()
        infos.fee_rate = self.fee_rate
        infos.opportunistic_merge_utxos = self.opportunistic_merge_utxos
        infos.recipients = [r.clone() for r in self.recipients]
        return infos
