import logging

from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.psbt_util import FeeInfo

from .pythonbdk_types import OutPoint, PythonUtxo, Recipient, UtxosForInputs

logger = logging.getLogger(__name__)

from typing import Dict, List, Optional

import bdkpython as bdk


def calc_minimum_rbf_fee_info(fee_amount: int, new_tx_size: int, mempool_data: MempoolData) -> FeeInfo:
    """
    see https://github.com/bitcoin/bips/blob/master/bip-0125.mediawiki


    1. The original transactions signal replaceability explicitly or through inheritance as described in the above Summary section.
    2. The replacement transaction may only include an unconfirmed input if that input was included in one of the original transactions. (An unconfirmed input spends an output from a currently-unconfirmed transaction.)
    3. The replacement transaction pays an absolute fee of at least the sum paid by the original transactions.
    4. The replacement transaction must also pay for its own bandwidth at or above the rate set by the node's minimum relay fee setting. For example, if the minimum relay fee is 1 satoshi/byte and the replacement transaction is 500 bytes total, then the replacement must pay a fee at least 500 satoshis higher than the sum of the originals.
    5. The number of original transactions to be replaced and their descendant transactions which will be evicted from the mempool must not exceed a total of 100 transactions.


    """
    new_absolute_fee: float = 0

    # 3.
    new_absolute_fee += fee_amount
    # 4.
    new_absolute_fee += new_tx_size * mempool_data.get_min_relay_fee()
    return FeeInfo(int(new_absolute_fee), new_tx_size)


class TxUiInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.utxo_dict: Dict[str, PythonUtxo] = {}  # {outpoint_string:utxo} It is Ok if outpoint_string:None
        self.fee_rate: Optional[float] = None
        self.opportunistic_merge_utxos = True
        self.spend_all_utxos = False
        self.main_wallet_id: Optional[str] = None

        self.recipients: List[Recipient] = []

        # self.exclude_fingerprints_from_signing :List[str]=[]

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate: float):
        self.fee_rate = feerate

    def fill_utxo_dict_from_utxos(self, utxos: List[PythonUtxo]):
        for utxo in utxos:
            self.utxo_dict[str(OutPoint.from_bdk(utxo.outpoint))] = utxo


class TxBuilderInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(
        self,
        recipients: List[Recipient],
        utxos_for_input: UtxosForInputs,
        builder_result: bdk.TxBuilderResult,
        recipient_category: Optional[str] = None,
    ):
        self.fee_rate = None

        self.recipients = recipients

        self.utxos_for_input = utxos_for_input
        self.builder_result = builder_result
        self.recipient_category = recipient_category

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, feerate):
        self.fee_rate = feerate
