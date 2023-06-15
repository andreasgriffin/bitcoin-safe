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
        
        self.tx_builder = bdk.TxBuilder()        
        self.tx_builder = self.tx_builder.enable_rbf()
        self.recipients:List[Recipient] = []
        
        self.builder_result: bdk.TxBuilderResult = None
        
        
        
    def add_recipient(self, recipient:Recipient):
        self.recipients.append(recipient)
        self.tx_builder = self.tx_builder.add_recipient(bdk.Address(recipient.address).script_pubkey(), recipient.amount)        
        if recipient.label:
            self.labels[recipient.address] = recipient.label
            
    def set_fee_rate(self, feerate):
        self.fee_rate = feerate
        self.tx_builder = self.tx_builder.fee_rate(feerate)
