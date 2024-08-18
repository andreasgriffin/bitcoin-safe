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

from bitcoin_safe.mempool import MempoolData
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.util import serialized_to_hex

from .pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    UtxosForInputs,
    robust_address_str_from_script,
)

logger = logging.getLogger(__name__)

from typing import Any, Dict, List, Optional, Tuple

import bdkpython as bdk


def short_tx_id(txid: str) -> str:
    return f"{txid[:4]}...{txid[-4:]}"


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
    new_absolute_fee += new_tx_size * mempool_data.get_min_relay_fee_rate()
    return FeeInfo(int(new_absolute_fee), new_tx_size)


class TxUiInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(self) -> None:
        self.utxo_dict: Dict[OutPoint, PythonUtxo] = (
            {}
        )  # {outpoint_string:utxo} It is Ok if outpoint_string:None
        self.global_xpubs: Dict[str, Tuple[str, str]] = {}  # xpub:(fingerprint, key_origin)
        self.fee_rate: Optional[float] = None
        self.opportunistic_merge_utxos = True
        self.spend_all_utxos = False
        self.main_wallet_id: Optional[str] = None

        self.recipients: List[Recipient] = []

        # self.exclude_fingerprints_from_signing :List[str]=[]

        self.hide_UTXO_selection = False
        self.recipient_read_only = False

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, fee_rate: float):
        self.fee_rate = fee_rate

    def fill_utxo_dict_from_utxos(self, utxos: List[PythonUtxo]):
        for utxo in utxos:
            self.utxo_dict[OutPoint.from_bdk(utxo.outpoint)] = utxo


class TxBuilderInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(
        self,
        recipients: List[Recipient],
        utxos_for_input: UtxosForInputs,
        builder_result: bdk.TxBuilderResult,
        recipient_category: Optional[str] = None,
    ):
        self.fee_rate: Optional[float] = None

        self.recipients = recipients

        self.utxos_for_input = utxos_for_input
        self.builder_result = builder_result
        self.recipient_category = recipient_category

    def add_recipient(self, recipient: Recipient):
        self.recipients.append(recipient)

    def set_fee_rate(self, fee_rate: float):
        self.fee_rate = fee_rate


def transaction_to_dict(tx: bdk.Transaction, network: bdk.Network) -> Dict[str, Any]:
    # Serialize inputs
    inputs = []
    for inp in tx.input():
        inputs.append(
            {
                "previous_output": {"txid": inp.previous_output.txid, "vout": inp.previous_output.vout},
                "script_sig": serialized_to_hex(inp.script_sig.to_bytes()),
                "sequence": inp.sequence,
                "witness": [serialized_to_hex(witness) for witness in inp.witness],
            }
        )

    # Serialize outputs
    outputs = []
    for out in tx.output():
        outputs.append(
            {
                "value": out.value,
                "script_pubkey": serialized_to_hex(out.script_pubkey.to_bytes()),
                "address": robust_address_str_from_script(out.script_pubkey, network=network),
            }
        )

    # Construct the transaction dictionary
    tx_dict = {
        "txid": tx.txid(),
        "weight": tx.weight(),
        "size": tx.size(),
        "vsize": tx.vsize(),
        "serialize": serialized_to_hex(tx.serialize()),
        "is_coin_base": tx.is_coin_base(),
        "is_explicitly_rbf": tx.is_explicitly_rbf(),
        "is_lock_time_enabled": tx.is_lock_time_enabled(),
        "version": tx.version(),
        "lock_time": tx.lock_time(),
        "input": inputs,
        "output": outputs,
    }

    # Convert the dictionary to a JSON string
    return tx_dict
