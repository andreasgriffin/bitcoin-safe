import logging

from .pythonbdk_types import Recipient, TxOut

logger = logging.getLogger(__name__)

import bdkpython as bdk
from typing import List
from .pythonbdk_types import OutPoint


class TXInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.labels = {}
        self.categories = []
        self.utxo_strings = []
        self.utxo_dict = {}  # {utxo_strings:utxo}
        self.fee_rate = None
        self.opportunistic_merge_utxos = True

        self.recipients: List[Recipient] = []

        self.utxos_for_input = None
        self.builder_result: bdk.TxBuilderResult = None
        self.recipient_category = None

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate):
        self.fee_rate = feerate

    def clone(self):
        infos = TXInfos()
        infos.labels = self.labels.copy()
        infos.categories = self.categories.copy()
        infos.utxo_strings = self.utxo_strings.copy()
        infos.utxo_dict = self.utxo_dict.copy()
        infos.fee_rate = self.fee_rate
        infos.opportunistic_merge_utxos = self.opportunistic_merge_utxos
        infos.recipients = [r.clone() for r in self.recipients]
        return infos

    def fill_utxo_dict(self, wallets: List["Wallet"]):
        def get_utxo(outpoint):
            for wallet in wallets:
                utxo = wallet.utxo_of_outpoint(outpoint)
                if utxo:
                    return utxo
            logger.warning(
                f"{self.__class__.__name__}: utxo for {outpoint} could not be found"
            )

        if self.utxo_strings:
            for s in self.utxo_strings:
                utxo = get_utxo(OutPoint.from_str(s))
                if utxo:
                    self.utxo_dict[s] = utxo
        elif self.categories:  # this will not be added if txinfos.utxo_strings
            for wallet in wallets:
                for utxo in wallet.list_unspent_based_on_tx():
                    if (
                        wallet.labels.get_category(
                            wallet.get_address_of_txout(TxOut.from_bdk(utxo.txout))
                        )
                        in self.categories
                    ):
                        self.utxo_dict[str(utxo.outpoint)] = utxo
        else:
            logger.debug("No utxos or categories for coin selection")
