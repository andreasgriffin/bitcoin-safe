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

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.tx_util import hex_to_serialized, serialized_to_hex

from bitcoin_safe.mempool_manager import MempoolManager
from bitcoin_safe.psbt_util import FeeInfo
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init

from .pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    TxOut,
    UtxosForInputs,
    robust_address_str_from_txout,
)

logger = logging.getLogger(__name__)


def short_tx_id(txid: str | bdk.Txid) -> str:
    """Short tx id."""
    if isinstance(txid, bdk.Txid):
        txid = str(txid)
    return f"{txid[:4]}...{txid[-4:]}"


def calc_minimum_rbf_fee_info(
    fee_amount: int,
    fee_amount_is_estimated: bool,
    new_tx_vsize: float,
    vsize_is_estimated: bool,
    mempool_manager: MempoolManager,
) -> FeeInfo:
    """
    see https://github.com/bitcoin/bips/blob/master/bip-0125.mediawiki


    1. The original transactions signal replaceability explicitly or through
            inheritance as described in the above Summary section.
    2. The replacement transaction may only include an unconfirmed input if
            that input was included in one of the original transactions.
            (An unconfirmed input spends an output from a currently-unconfirmed transaction.)
    3. The replacement transaction pays an absolute fee of at least the
            sum paid by the original transactions.
    4. The replacement transaction must also pay for its own bandwidth at or
            above the rate set by the node's minimum relay fee setting.
            For example, if the minimum relay fee is 1 satoshi/byte and the
            replacement transaction is 500 bytes total, then the replacement
            must pay a fee at least 500 satoshis higher than the sum of the originals.
    5. The number of original transactions to be replaced and their descendant
            transactions which will be evicted from the mempool must not
            exceed a total of 100 transactions.


    """
    new_absolute_fee: float = 0

    # 3.
    new_absolute_fee += fee_amount
    # 4.
    new_absolute_fee += new_tx_vsize * mempool_manager.get_min_relay_fee_rate()
    return FeeInfo(
        fee_amount=int(new_absolute_fee),
        vsize=int(new_tx_vsize),
        vsize_is_estimated=vsize_is_estimated,
        fee_amount_is_estimated=fee_amount_is_estimated,
    )


@dataclass
class TxUiInfos(BaseSaveableClass):
    "A wrapper around tx_builder to collect even more infos"

    VERSION = "0.0.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        PythonUtxo.__name__: PythonUtxo,
        Recipient.__name__: Recipient,
        OutPoint.__name__: OutPoint,
    }

    # {outpoint_string:utxo} It is Ok if outpoint_string:None
    utxo_dict: dict[OutPoint, PythonUtxo] = field(default_factory=dict)
    fee_rate: float | None = None
    opportunistic_merge_utxos = True
    spend_all_utxos = False
    main_wallet_id: str | None = None

    recipients: list[Recipient] = field(default_factory=list)
    hide_entire_input_column: bool = False
    hide_UTXO_selection: bool = True
    recipient_read_only: bool = False
    utxos_read_only: bool = False
    replace_tx: bdk.Transaction | None = None

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["fee_rate"] = self.fee_rate
        d["recipients"] = [asdict(r) for r in self.recipients]
        d["hide_entire_input_column"] = self.hide_entire_input_column
        d["hide_UTXO_selection"] = self.hide_UTXO_selection
        d["recipient_read_only"] = self.recipient_read_only
        d["utxos_read_only"] = self.utxos_read_only
        d["replace_tx"] = serialized_to_hex(self.replace_tx.serialize()) if self.replace_tx else None
        d["utxo_dict"] = {str(k): v for k, v in self.utxo_dict.items()}
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        if replace_tx := dct.get("replace_tx"):
            dct["replace_tx"] = bdk.Transaction(hex_to_serialized(replace_tx))
        dct["recipients"] = [Recipient(**filtered_for_init(r, Recipient)) for r in dct.get("recipients", [])]

        if isinstance(utxo_dict := dct.get("utxo_dict"), dict):
            dct["utxo_dict"] = {OutPoint.from_str(k): v for k, v in utxo_dict.items()}

        return cls(**filtered_for_init(dct, cls))

    def add_recipient(self, recipient: Recipient):
        """Add recipient."""
        self.recipients.append(recipient)

    def set_fee_rate(self, fee_rate: float):
        """Set fee rate."""
        self.fee_rate = fee_rate

    def fill_utxo_dict_from_utxos(self, utxos: list[PythonUtxo]):
        """Fill utxo dict from utxos."""
        for utxo in utxos:
            self.utxo_dict[OutPoint.from_bdk(utxo.outpoint)] = utxo


class TxBuilderInfos:
    "A wrapper around tx_builder to collect even more infos"

    def __init__(
        self,
        recipients: list[Recipient],
        utxos_for_input: UtxosForInputs,
        psbt: bdk.Psbt,
        recipient_category: str | None = None,
        fee_rate: float | None = None,
    ):
        """Initialize instance."""
        self.fee_rate = fee_rate
        self.recipients = recipients

        self.utxos_for_input = utxos_for_input
        self.psbt = psbt
        self.recipient_category = recipient_category

    def add_recipient(self, recipient: Recipient):
        """Add recipient."""
        self.recipients.append(recipient)

    def set_fee_rate(self, fee_rate: float):
        """Set fee rate."""
        self.fee_rate = fee_rate


def transaction_to_dict(tx: bdk.Transaction, network: bdk.Network) -> dict[str, Any]:
    # Serialize inputs
    """Transaction to dict."""
    inputs = []
    for inp in tx.input():
        inputs.append(
            {
                "previous_output": {"txid": str(inp.previous_output.txid), "vout": inp.previous_output.vout},
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
                "value": out.value.to_sat(),
                "script_pubkey": serialized_to_hex(out.script_pubkey.to_bytes()),
                "address": robust_address_str_from_txout(TxOut.from_bdk(out), network=network),
            }
        )

    # Construct the transaction dictionary
    tx_dict = {
        "txid": str(tx.compute_txid()),
        "weight": tx.weight(),
        "size": tx.total_size(),
        "vsize": tx.vsize(),
        "serialize": serialized_to_hex(tx.serialize()),
        "is_coin_base": tx.is_coinbase(),
        "is_explicitly_rbf": tx.is_explicitly_rbf(),
        "is_lock_time_enabled": tx.is_lock_time_enabled(),
        "version": tx.version(),
        "lock_time": tx.lock_time(),
        "input": inputs,
        "output": outputs,
    }

    # Convert the dictionary to a JSON string
    return tx_dict
