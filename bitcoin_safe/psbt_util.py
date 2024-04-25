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

logger = logging.getLogger(__name__)


import json
from dataclasses import dataclass
from math import ceil
from typing import Any, Dict, List, Tuple

import bdkpython as bdk

from .dynamic_lib_load import setup_libsecp256k1

setup_libsecp256k1()


from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.util import remove_duplicates_keep_order

from .pythonbdk_types import OutPoint, TxOut


def parse_redeem_script(script_hex: str) -> Tuple[int, List[str]]:
    """
    Parses a redeem script to extract the threshold (m) and public keys.

    Parameters:
    - script_hex (str): The hexadecimal string of the redeem script.

    Returns:
    - Tuple[int, List[str]]: A tuple containing the threshold (m) and a list of public keys.
    """
    m = int(script_hex[:2], 16) - 80
    script_body = script_hex[2:]
    public_keys = []
    while script_body:
        if script_body[:2] == "21":
            key = script_body[2:68]
            public_keys.append(key)
            script_body = script_body[68:]
        else:
            break

    return m, public_keys


def parse_witness_script(script_hex: str) -> Tuple[int, List[str]]:
    """
    Parses a witness script to extract the threshold (m) and public keys.

    Parameters:
    - script_hex (str): The hexadecimal string of the witness script.

    Returns:
    - Tuple[int, List[str]]: A tuple containing the threshold (m) and a list of public keys.
    """
    m = int(script_hex[:2], 16) - 80
    script_body = script_hex[2:]
    public_keys = []
    while script_body:
        if script_body[:2] == "21":
            key = script_body[2:68]
            public_keys.append(key)
            script_body = script_body[68:]
        else:
            break

    return m, public_keys


def weight_to_vsize(weight) -> int:
    return ceil(weight / 4)


def estimate_tx_weight(
    input_mn_tuples: List[Tuple[int, int]], num_outputs: int, include_signatures=True
) -> int:
    """Estimate the weight of a SegWit transaction in weight units, including
    support for multiple inputs with varying m-of-n multisignature
    configurations.

    Args:
    input_mn_tuples (list of tuples): A list where each tuple represents an input with (m, n) configuration.
    num_outputs (int): Number of outputs in the transaction.
    include_signatures (bool): Whether to include the size of signatures in the estimate.

    Returns:
    int: Estimated transaction weight in weight units.
    """
    # Transaction overheads
    version_size = 4
    segwit_marker_and_flag_size = 2
    locktime_size = 4

    # Input components
    outpoint_size = 36  # txid (32 bytes) + vout index (4 bytes)
    script_length_size = 1  # Size of the script length field
    sequence_size = 4  # Size of the sequence field
    base_input_size = outpoint_size + sequence_size  # Excluding scriptSig and witness

    # Output components
    output_value_size = 8  # Size of the value field
    output_script_length_size = 1  # Size of the script length field
    p2wpkh_script_size = 22  # P2WPKH script size
    base_output_size = output_value_size + output_script_length_size + p2wpkh_script_size

    # Witness components
    witness_stack_items_size = 1  # Size byte for the number of witness stack items
    average_signature_size = 72  # Approximate size of a signature
    average_pubkey_size = 33  # Size of a compressed public key

    # Calculate total witness data size
    total_witness_data_size = 0
    for m, n in input_mn_tuples:
        witness_data_size_per_input = (
            witness_stack_items_size + (m * (1 + average_signature_size)) + (n * (1 + average_pubkey_size))
        )
        total_witness_data_size += witness_data_size_per_input if include_signatures else 0

    # Calculate base transaction size (excluding witness data)
    num_inputs = len(input_mn_tuples)
    base_tx_size_without_witness = (
        version_size
        + segwit_marker_and_flag_size
        + locktime_size
        + num_inputs * (base_input_size + script_length_size)
        + num_outputs * base_output_size
    )

    # Calculate transaction weight
    # Non-witness data is weighted as 4 units per byte, witness data as 1 unit per byte
    tx_weight: int = (base_tx_size_without_witness * 4) + total_witness_data_size

    return tx_weight


class FeeInfo:
    def __init__(self, fee_amount: int, vsize: int, is_estimated=False) -> None:
        """_summary_

        Args:
            fee_amount (int): _description_
            vsize (int): transaction.vsize()
            is_estimated (bool, optional): _description_. Defaults to False.
        """
        self.fee_amount = fee_amount
        self.vsize = vsize
        self.is_estimated = is_estimated

    def fee_rate(self) -> float:
        return self.fee_amount / self.vsize

    @classmethod
    def from_txdetails(cls, tx_details: bdk.TransactionDetails) -> "FeeInfo":
        fee = tx_details.fee
        # coinbase transaction have fee=None
        fee = fee if fee is not None else 0
        return FeeInfo(fee, tx_details.transaction.vsize(), is_estimated=False)

    @classmethod
    def estimate_segwit_fee_rate_from_psbt(cls, psbt: bdk.PartiallySignedTransaction) -> "FeeInfo":
        """Estimate the fee rate of a SegWit transaction from a serialized PSBT
        JSON.

        Args:
        psbt_json_str (str): The serialized PSBT JSON string.

        Returns:
        float: Estimated fee rate in satoshis per byte.
        """

        # Get the simplified JSON representation of the PSBT
        simple_psbt = SimplePSBT.from_psbt(psbt)

        # for the input where i can determine the (m,n) use them:
        full_input_mn_tuples = [inp._get_m_of_n() for inp in simple_psbt.inputs]
        input_mn_tuples = [mn for mn in full_input_mn_tuples if mn]

        # Estimate the size of the transaction
        # This part requires the transaction size estimation logic, which might need information about inputs and outputs
        # For simplicity, let's assume you have a function estimate_tx_size(psbt_data) that can estimate the size
        vsize = weight_to_vsize(estimate_tx_weight(input_mn_tuples, len(psbt.extract_tx().output())))

        return FeeInfo(psbt.fee_amount(), vsize, is_estimated=True)

    @classmethod
    def estimate_from_num_inputs(
        cls,
        fee_rate: float,
        input_mn_tuples: List[Tuple[int, int]],
        num_outputs: int,
        include_signatures=True,
    ) -> "FeeInfo":
        "Estimation for segwit txs"
        vsize = weight_to_vsize(
            estimate_tx_weight(
                input_mn_tuples=input_mn_tuples,
                num_outputs=num_outputs,
                include_signatures=include_signatures,
            )
        )
        return FeeInfo(ceil(fee_rate * vsize), vsize, is_estimated=True)


from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class PubKeyInfo:
    def __init__(
        self,
        fingerprint: str,
        pubkey: Optional[str] = None,
        derivation_path: Optional[str] = None,
        label: str = "",
    ) -> None:
        self.fingerprint = SimplePubKeyProvider.format_fingerprint(fingerprint)
        self.pubkey = pubkey
        self.derivation_path = derivation_path
        self.label = label


@dataclass
class SimpleInput:
    txin: bdk.TxIn
    witness_script: Optional[str] = None
    # partial_sigs example: {"0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6": "304402202976966c2996b3c17005342eebb60133741286460b135020dcb4f2089629d851022044402ada00dc6acb4040f44099f537a138f4558cb10f874656d9d544a19b0f6e"}
    # {pubkey: signature}
    partial_sigs: Dict[str, str] = field(default_factory=dict)
    final_script_sig: Optional[str] = None
    final_script_witness: Optional[str] = None
    pubkeys: List[PubKeyInfo] = field(default_factory=list)
    wallet_id: Optional[str] = None
    m_of_n: Optional[Tuple[int, int]] = None
    non_witness_utxo: Optional[Dict[str, Any]] = None
    witness_utxo: Optional[Dict[str, Any]] = None
    sighash_type: Optional[int] = None
    redeem_script: Optional[str] = None
    ripemd160_preimages: Dict[str, str] = field(default_factory=dict)
    sha256_preimages: Dict[str, str] = field(default_factory=dict)
    hash160_preimages: Dict[str, str] = field(default_factory=dict)
    hash256_preimages: Dict[str, str] = field(default_factory=dict)
    tap_key_sig: Optional[str] = None
    tap_script_sigs: Dict[str, str] = field(default_factory=dict)
    tap_scripts: List[Tuple[str, str, str]] = field(default_factory=list)
    tap_key_origins: List[Tuple[str, List[str]]] = field(default_factory=list)
    tap_internal_key: Optional[str] = None
    tap_merkle_root: Optional[str] = None

    @classmethod
    def from_input(cls, input_data: Dict[str, Any], txin: bdk.TxIn) -> "SimpleInput":
        self = cls(
            txin,
            witness_script=input_data.get("witness_script"),
            partial_sigs={k: v.get("sig") for k, v in input_data.get("partial_sigs", {}).items()},
            final_script_sig=input_data.get("final_script_sig"),
            final_script_witness=input_data.get("final_script_witness"),
            non_witness_utxo=input_data.get("non_witness_utxo"),
            witness_utxo=input_data.get("witness_utxo"),
            sighash_type=input_data.get("sighash_type"),
            redeem_script=input_data.get("redeem_script"),
            ripemd160_preimages=input_data.get("ripemd160_preimages", {}),
            sha256_preimages=input_data.get("sha256_preimages", {}),
            hash160_preimages=input_data.get("hash160_preimages", {}),
            hash256_preimages=input_data.get("hash256_preimages", {}),
            tap_key_sig=input_data.get("tap_key_sig"),
            tap_script_sigs=input_data.get("tap_script_sigs", {}),
            tap_scripts=input_data.get("tap_scripts", []),
            tap_key_origins=input_data.get("tap_key_origins", []),
            tap_internal_key=input_data.get("tap_internal_key"),
            tap_merkle_root=input_data.get("tap_merkle_root"),
        )

        bip32_derivation = input_data.get("bip32_derivation", [])
        for pubkey_info in bip32_derivation:
            pubkey, (fingerprint, derivation_path) = pubkey_info
            self.pubkeys.append(
                PubKeyInfo(pubkey=pubkey, fingerprint=fingerprint, derivation_path=derivation_path)
            )

        self.m_of_n = self._get_m_of_n()
        return self

    def is_fully_signed(self) -> bool:
        # This heuristic assumes the presence of final_script_sig or final_script_witness indicates full signing
        return bool(self.final_script_sig or self.final_script_witness)

    def signature_count(self) -> str:
        # Just return the count of partial signatures, as we can't determine the total required
        return str(len(self.partial_sigs))

    def get_pub_keys_without_signature(self) -> List[PubKeyInfo]:
        # If the input is fully signed, there are no pubkeys without a signature
        if self.is_fully_signed():
            return []
        return [pubkey_info for pubkey_info in self.pubkeys if pubkey_info.pubkey not in self.partial_sigs]

    def get_pub_keys_with_signature(self) -> List[PubKeyInfo]:
        # If the input is fully signed, all pubkeys are considered to have a signature
        if self.is_fully_signed():
            return self.pubkeys
        return [pubkey_info for pubkey_info in self.pubkeys if pubkey_info.pubkey in self.partial_sigs]

    def fingerprint_has_signature(self, fingerprint: str) -> bool:
        if self.is_fully_signed():
            return True
        for pubkey_info in self.pubkeys:
            if pubkey_info.fingerprint == fingerprint and pubkey_info.pubkey in self.partial_sigs:
                return True
        return False

    def get_estimated_m_of_n(self) -> Tuple[int, int]:
        mn = self._get_m_of_n()
        if mn:
            return mn
        return (len(self.pubkeys), len(self.pubkeys))

    def _get_m_of_n(self) -> Optional[Tuple[int, int]]:
        if self.m_of_n:
            return self.m_of_n

        if self.witness_script:
            m, public_keys = parse_witness_script(self.witness_script)
            return (m, len(public_keys))
        if self.redeem_script:
            m, public_keys = parse_redeem_script(self.redeem_script)
            return (m, len(public_keys))
        return None

    def get_prev_txouts(self) -> Dict[str, TxOut]:
        "Returns {str(outpoint): List[TxOut]}"
        if not self.non_witness_utxo:
            return {}
        prev_out = OutPoint.from_bdk(self.txin.previous_output)
        output = self.non_witness_utxo.get("output", [])[prev_out.vout]
        non_witness_utxo_prev_out = TxOut(
            value=output["value"], script_pubkey=bdk.Script(bytes.fromhex(output["script_pubkey"]))
        )
        return {str(prev_out): non_witness_utxo_prev_out}


@dataclass
class SimpleOutput:
    value: int = 0
    script_pubkey: str = ""
    witness_script: Optional[str] = None
    redeem_script: Optional[str] = None
    bip32_derivation: List[PubKeyInfo] = field(default_factory=list)
    tap_internal_key: Optional[str] = None
    tap_tree: Optional[str] = None
    tap_key_origins: List[Tuple[str, List[str]]] = field(default_factory=list)

    @classmethod
    def from_output(cls, output_data: Dict[str, Any], unsigned_tx: Dict[str, Any]) -> "SimpleOutput":
        instance = cls(
            value=unsigned_tx.get("value", 0),
            script_pubkey=unsigned_tx.get("script_pubkey", ""),
            witness_script=output_data.get("witness_script"),
            redeem_script=output_data.get("redeem_script"),
            tap_internal_key=output_data.get("tap_internal_key"),
            tap_tree=output_data.get("tap_tree"),
        )

        bip32_derivation = output_data.get("bip32_derivation", [])
        for pubkey_info in bip32_derivation:
            pubkey, (fingerprint, derivation_path) = pubkey_info
            instance.bip32_derivation.append(
                PubKeyInfo(pubkey=pubkey, fingerprint=fingerprint, derivation_path=derivation_path)
            )

        return instance

    def to_txout(self) -> TxOut:
        return TxOut(self.value, self.script_pubkey)


@dataclass
class SimplePSBT:
    inputs: List[SimpleInput] = field(default_factory=list)
    outputs: List[SimpleOutput] = field(default_factory=list)

    @classmethod
    def from_psbt(cls, psbt: bdk.PartiallySignedTransaction) -> "SimplePSBT":
        instance = cls()
        psbt_json = json.loads(psbt.json_serialize())
        instance.inputs = [
            SimpleInput.from_input(input_data, txin)
            for input_data, txin in zip(psbt_json.get("inputs", []), psbt.extract_tx().input())
        ]

        outputs = psbt_json.get("outputs", [])
        unsigned_tx_outputs = psbt_json.get("unsigned_tx", {}).get("output", [])
        assert len(outputs) == len(unsigned_tx_outputs)
        instance.outputs = [
            SimpleOutput.from_output(output_data, unsigned_tx_output)
            for output_data, unsigned_tx_output in zip(outputs, unsigned_tx_outputs)
        ]
        return instance

    def get_fingerprint_tuples(self) -> Tuple[List[PubKeyInfo], List[PubKeyInfo]]:

        # set of all fingerprints of all inputs
        # sorted_pubkeys = remove_duplicates_keep_order(
        #     sum(
        #         [simple_input.pubkeys for simple_input in self.inputs ],
        #         [],
        #     )
        # )

        pubkeys_not_fully_signed = remove_duplicates_keep_order(
            sum(
                [simple_input.get_pub_keys_without_signature() for simple_input in self.inputs],
                [],
            )
        )
        pubkeys_fully_signed = remove_duplicates_keep_order(
            sum(
                [simple_input.get_pub_keys_with_signature() for simple_input in self.inputs],
                [],
            )
        )

        return (
            # sorted_pubkeys,
            pubkeys_fully_signed,
            pubkeys_not_fully_signed,
        )

    def get_prev_txouts(self) -> Dict[str, TxOut]:
        d = self.inputs[0].get_prev_txouts()
        for inp in self.inputs[1:]:
            d.update(inp.get_prev_txouts())

        return d
