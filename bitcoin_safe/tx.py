import logging
logger = logging.getLogger(__name__)

import bdkpython as bdk

class TXInfos:
    "A wrapper around tx_builder to collect even more infos"
    def __init__(self) -> None:
        self.labels = {}
        self.categories = []
        self.utxo_strings = []
        self.fee_rate = None
        
        self.tx_builder = bdk.TxBuilder()        
        self.tx_builder = self.tx_builder.enable_rbf()
        
        self.builder_result: bdk.TxBuilderResult = None
        
        
        
    def add_recipient(self, address, amount, label=None):
        self.tx_builder = self.tx_builder.add_recipient(bdk.Address(address).script_pubkey(), amount)        
        if label:
            self.labels[address] = label
            
    def set_fee_rate(self, feerate):
        self.fee_rate = feerate
        self.tx_builder = self.tx_builder.fee_rate(feerate)
