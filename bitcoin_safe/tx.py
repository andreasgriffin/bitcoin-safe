import logging

from .pythonbdk_types import Recipient, TxOut

logger = logging.getLogger(__name__)

import bdkpython as bdk
from typing import List
from .pythonbdk_types import OutPoint


class TxUiInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.utxo_dict = {}  # {outpoint_string:utxo}
        self.fee_rate = None
        self.opportunistic_merge_utxos = True
        self.spend_all_utxos = False
        self.main_wallet_id = None

        self.recipients: List[Recipient] = []

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate):
        self.fee_rate = feerate

    def fill_utxo_dict_from_utxos(self, utxos: List[bdk.LocalUtxo]):
        for utxo in utxos:
            self.utxo_dict[str(OutPoint.from_bdk(utxo.outpoint))] = utxo

    def fill_utxo_dict_from_outpoints(
        self, outpoints: List[OutPoint], wallets: List["Wallet"]
    ):
        def get_utxo(outpoint):
            for wallet in wallets:
                utxo = wallet.utxo_of_outpoint(outpoint)
                if utxo:
                    return utxo
            logger.warning(
                f"{self.__class__.__name__}: utxo for {outpoint} could not be found"
            )

        for outpoint in outpoints:
            utxo = get_utxo(outpoint)
            if utxo:
                self.utxo_dict[str(outpoint)] = utxo

    def fill_utxo_dict_from_categories(
        self, categories: List[str], wallets: List["Wallet"]
    ):
        for wallet in wallets:
            for utxo in wallet.list_unspent():
                if (
                    wallet.labels.get_category(
                        wallet.get_address_of_txout(TxOut.from_bdk(utxo.txout))
                    )
                    in categories
                ):
                    self.utxo_dict[str(utxo.outpoint)] = utxo


class TxBuilderInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.labels = {}
        self.fee_rate = None

        self.recipients: List[Recipient] = []

        self.utxos_for_input: "UtxosForInputs" = None
        self.builder_result: bdk.TxBuilderResult = None
        self.recipient_category = None

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate):
        self.fee_rate = feerate
