#
# Bitcoin-Safe
# Copyright (C) 2023-2026 Andreas Griffin
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
#

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import ceil
from typing import cast

import bdkpython as bdk
from bip32_descriptors.bip32.key_origin import BIP32KeyOrigin
from bip32_descriptors.descriptors import miniscript
from bitcoin_safe_lib.tx_util import hex_to_script
from bitcoin_safe_lib.util import network_kind, remove_duplicates_keep_order
from bitcoin_usb.address_types import AddressType, AddressTypes, SimplePubKeyProvider
from btclib import var_int
from btclib.script import Witness, serialize
from btclib.script.script_pub_key import (
    is_p2ms_var,
    is_p2pkh,
    is_p2sh,
    is_p2tr,
    is_p2wpkh,
    is_p2wsh,
    p2ms_m_and_keys_var,
)
from btclib.tx import Tx
from btclib.tx import TxIn as BtclibTxIn
from btclib.tx import TxOut as BtclibTxOut
from btclib_wallet.psbt import Psbt, PsbtIn, PsbtOut, miniscript_sizer, prevouts
from btclib_wallet.psbt.psbt_size import COMPRESSED_PUB_KEY_SIZE, SCHNORR_SIG_SIZE, SIG_SIZE
from ecc.hashes import tagged_hash

from .input_signature_verifier import InputVerdict, Prevout, verify_transaction
from .pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    TransactionDetails,
    TxInputInfo,
    TxOut,
    is_address,
    robust_address_str_from_txout,
)

logger = logging.getLogger(__name__)
VSIZE_OF_ZERO_FEE_TX = 200
# Used only while an output script is unknown, such as an incomplete address.
DEFAULT_OUTPUT_SCRIPT = bdk.Script(b"\x00\x14" + bytes(20))


def parse_witness_script(script_hex: str) -> tuple[int, list[str]]:
    """Return the threshold and keys of a standard multisig script."""
    threshold, keys = p2ms_m_and_keys_var(bytes.fromhex(script_hex))
    return threshold, [key.hex() for key in keys]


def weight_to_vsize(weight) -> int:
    """Weight to vsize."""
    return ceil(weight / 4)


def compact_size_length(value: int) -> int:
    """Return the number of bytes used by a Bitcoin CompactSize integer."""
    return len(var_int.serialize(value))


def unsigned_tx_bytes(tx: bdk.Transaction) -> bytes:
    """Serialize a transaction without input unlocking data, for signing compatibility checks."""
    unsigned = Tx.parse(bytes(tx.serialize()), check_validity=False)
    for txin in unsigned.vin:
        txin.script_sig = b""
    return unsigned.serialize(include_witness=False, check_validity=False)


def witness_satisfaction_weight(item_sizes: Sequence[int]) -> int:
    """BDK satisfaction delta relative to an empty witness."""
    return len(Witness([bytes(size) for size in item_sizes]).serialize()) - 1


def estimate_tapscript_weight(psbt_input: bdk.Input | PsbtIn) -> int:
    """Estimate signed Taproot leaves, not the protocol-wide stack limit."""
    if isinstance(psbt_input, PsbtIn):
        signatures = Counter(key[32:].hex() for key in psbt_input.taproot_script_spend_signatures)
        leaves = [
            (script, version, len(control))
            for control, (script, version) in psbt_input.taproot_leaf_scripts.items()
        ]
    else:
        signatures = Counter(key.tap_leaf_hash for key in psbt_input.tap_script_sigs)
        leaves = [
            (bytes(entry.script.to_bytes()), entry.leaf_version, 33 + 32 * len(control.merkle_branch))
            for control, entry in psbt_input.tap_scripts.items()
        ]
    weights = []
    for script, version, control_size in leaves:
        leaf_hash = tagged_hash(b"TapLeaf", bytes([version]) + var_int.serialize(len(script)) + script).hex()
        if leaf_hash not in signatures:
            continue

        try:
            stack = miniscript.from_script(script, miniscript.TAPSCRIPT).max_witness_stack
        except ValueError:
            stack = None
        if stack is None:
            # Unknown custom script: retain the previous rough draft estimate.
            sigops = sum(
                op in ("OP_CHECKSIG", "OP_CHECKSIGVERIFY", "OP_CHECKSIGADD")
                for op in str(bdk.Script(script)).split()
            )
            stack = (SCHNORR_SIG_SIZE + 1,) * max(signatures[leaf_hash], sigops)
            logger.warning("Rough Taproot weight estimate for unsupported leaf %s", leaf_hash)
        weights.append(witness_satisfaction_weight([*stack, len(script), control_size]))

    if weights:
        return max(weights)
    # No matching script/control block: estimate only the minimum witness shape.
    logger.warning("Rough Taproot weight estimate: missing signed leaf metadata")
    return witness_satisfaction_weight([SCHNORR_SIG_SIZE + 1] * max(signatures.values(), default=1) + [0, 33])


def input_address_type(raw: bytes, redeem: bytes, final_script_sig: bytes) -> AddressType | None:
    """Infer the spend type, including a nested witness program in final scriptSig."""
    if is_p2pkh(raw):
        return AddressTypes.p2pkh
    if is_p2wpkh(raw):
        return AddressTypes.p2wpkh
    if is_p2wsh(raw):
        return AddressTypes.p2wsh
    if is_p2tr(raw):
        return AddressTypes.p2tr
    if not raw or is_p2sh(raw):
        # A finalizer may remove redeem_script, leaving only its canonical push.
        if not redeem and final_script_sig[:1] in (b"\x16", b"\x22"):
            program = final_script_sig[1:]
            if final_script_sig[0] == len(program):
                redeem = program
        if is_p2wpkh(redeem):
            return AddressTypes.p2sh_p2wpkh
        if is_p2wsh(redeem):
            return AddressTypes.p2sh_p2wsh
    return None


def has_finalized_unlocking_data(
    address_type: AddressType | None, has_script_sig: bool, has_witness: bool, legacy_p2sh: bool
) -> bool:
    """Check for the required unlocking fields, not cryptographic validity."""
    if address_type in (AddressTypes.p2sh_p2wpkh, AddressTypes.p2sh_p2wsh):
        return has_script_sig and has_witness
    if address_type in (AddressTypes.p2wpkh, AddressTypes.p2wsh, AddressTypes.p2tr):
        return has_witness
    if address_type == AddressTypes.p2pkh or legacy_p2sh:
        return has_script_sig
    # Retain the existing heuristic for other or unknown script types.
    return has_script_sig or has_witness


def previous_output(inp: PsbtIn, vout: int) -> BtclibTxOut | None:
    """Read available metadata; fee estimation separately validates with prevouts()."""
    if inp.witness_utxo is not None:
        return inp.witness_utxo
    if inp.non_witness_utxo is not None and 0 <= vout < len(inp.non_witness_utxo.vout):
        return inp.non_witness_utxo.vout[vout]
    return None


@dataclass
class InputWeight:
    """Optional spend information; unknown inputs default to native SegWit.

    satisfaction_weight uses BDK's convention: it excludes the empty witness
    byte and includes the increase in scriptSig weight.
    """

    mn: tuple[int, int] = (1, 1)
    address_type: AddressType | None = None
    satisfaction_weight: int | None = None
    legacy_multisig: bool = False
    script_size: int | None = None
    tap_script_path: bool = False
    tap_script_weight: int = 66
    finalized_witness: bool | None = None

    @classmethod
    def from_psbt_input(
        cls,
        script: bdk.Script | None,
        psbt_input: bdk.Input | PsbtIn | None,
        mn: tuple[int, int] = (1, 1),
        satisfaction_weight: int | None = None,
    ) -> InputWeight:
        raw = bytes(script.to_bytes()) if script else b""
        if isinstance(psbt_input, PsbtIn):
            redeem = psbt_input.redeem_script
            witness = psbt_input.witness_script
            final_script_sig = psbt_input.final_script_sig
            final_witness = psbt_input.final_script_witness.stack or None
        else:
            redeem = (
                bytes(psbt_input.redeem_script.to_bytes()) if psbt_input and psbt_input.redeem_script else b""
            )
            witness = (
                bytes(psbt_input.witness_script.to_bytes())
                if psbt_input and psbt_input.witness_script
                else b""
            )
            final_script_sig = (
                bytes(psbt_input.final_script_sig.to_bytes())
                if psbt_input and psbt_input.final_script_sig
                else b""
            )
            final_witness = psbt_input.final_script_witness if psbt_input else None
        multisig_script = witness or (
            redeem if redeem and not is_p2wpkh(redeem) and not is_p2wsh(redeem) else b""
        )
        if is_p2ms_var(multisig_script):
            m, keys = p2ms_m_and_keys_var(multisig_script)
            mn = (m, len(keys))
        address_type = input_address_type(raw, redeem, final_script_sig)
        legacy_multisig = is_p2sh(raw) and address_type is None
        tap_script_path = (
            bool(psbt_input.taproot_script_spend_signatures and not psbt_input.taproot_key_spend_signature)
            if isinstance(psbt_input, PsbtIn)
            else bool(psbt_input and psbt_input.tap_script_sigs and not psbt_input.tap_key_sig)
        )
        tap_script_weight = 66
        if address_type == AddressTypes.p2tr and psbt_input:
            if final_witness is not None:
                satisfaction_weight = witness_satisfaction_weight([len(item) for item in final_witness])
            elif tap_script_path and satisfaction_weight is None:
                tap_script_weight = estimate_tapscript_weight(psbt_input)
        return cls(
            mn,
            address_type,
            satisfaction_weight,
            legacy_multisig,
            len(multisig_script) or None,
            tap_script_path,
            tap_script_weight,
        )

    def use_descriptor(self, descriptor: str, network: bdk.Network) -> None:
        """Prefer the descriptor's maximum satisfaction over metadata estimates."""
        desc = bdk.Descriptor(descriptor, network_kind(network))
        self.satisfaction_weight = desc.max_weight_to_satisfy()
        self.address_type = None
        self.legacy_multisig = desc.desc_type() in (
            bdk.DescriptorType.BARE,
            bdk.DescriptorType.PKH,
            bdk.DescriptorType.SH,
            bdk.DescriptorType.SH_SORTED_MULTI,
        )

    def is_witness(self) -> bool:
        if self.finalized_witness is not None:
            return self.finalized_witness
        return not (self.address_type == AddressTypes.p2pkh or self.legacy_multisig)

    def weight(self) -> int:
        if self.satisfaction_weight is not None:
            return self.satisfaction_weight
        m, n = self.mn
        if self.address_type == AddressTypes.p2tr:
            return self.tap_script_weight if self.tap_script_path else SCHNORR_SIG_SIZE + 2
        script_size = self.script_size or 3 + (COMPRESSED_PUB_KEY_SIZE + 1) * n
        if self.legacy_multisig:
            pushes = [b"", *[bytes(SIG_SIZE)] * m, bytes(script_size)]
            size = len(serialize(pushes))
            return 4 * (size + compact_size_length(size) - 1)
        if self.address_type == AddressTypes.p2pkh:
            return 4 * len(serialize([bytes(SIG_SIZE), bytes(COMPRESSED_PUB_KEY_SIZE)]))
        if self.address_type in (AddressTypes.p2wpkh, AddressTypes.p2sh_p2wpkh) or (
            self.address_type is None and (m, n) == (1, 1)
        ):
            return witness_satisfaction_weight([SIG_SIZE, COMPRESSED_PUB_KEY_SIZE]) + (
                23 * 4 if self.address_type == AddressTypes.p2sh_p2wpkh else 0
            )
        return witness_satisfaction_weight([0, *[SIG_SIZE] * m, script_size]) + (
            35 * 4 if self.address_type == AddressTypes.p2sh_p2wsh else 0
        )


@dataclass
class TxWeight:
    inputs: Sequence[InputWeight]
    output_scripts: Sequence[bdk.Script | None]

    @classmethod
    def from_inputs(
        cls,
        inputs: Sequence[TxInputInfo],
        output_scripts: Sequence[bdk.Script | None],
        wallet: bdk.Wallet | None = None,
        mn: tuple[int, int] = (1, 1),
        assume_one_input: bool = False,
    ) -> TxWeight:
        """Estimate the selected inputs, using wallet descriptors where available."""
        weights = []
        for item in inputs:
            script = item.utxo.txout.script_pubkey
            weight = InputWeight.from_psbt_input(script, item.psbt_input, mn, item.satisfaction_weight)
            if wallet and weight.satisfaction_weight is None:
                derivation = wallet.derivation_of_spk(script)
                if derivation is not None:
                    weight.use_descriptor(wallet.public_descriptor(derivation.keychain), wallet.network())
            weights.append(weight)
        if not weights and assume_one_input:
            weight = InputWeight(mn)
            if wallet:
                weight.use_descriptor(wallet.public_descriptor(bdk.KeychainKind.EXTERNAL), wallet.network())
            weights.append(weight)
        return cls(weights, output_scripts)

    @classmethod
    def from_recipients(
        cls,
        inputs: Sequence[TxInputInfo],
        recipients: Sequence[Recipient],
        network: bdk.Network,
        wallet: bdk.Wallet | None = None,
        mn: tuple[int, int] = (1, 1),
    ) -> TxWeight:
        """Estimate a draft, including change and incomplete recipient scripts."""
        output_scripts: list[bdk.Script | None] = []
        for recipient in recipients:
            # An incomplete address still needs a placeholder output in the estimate.
            if not recipient.address.startswith("script:") and not is_address(recipient.address, network):
                output_scripts.append(None)
                continue
            try:
                output_scripts.append(recipient.script_pubkey(network))
            except ValueError:
                output_scripts.append(None)
        if not any(recipient.checked_max_amount for recipient in recipients):
            output_scripts.append(
                wallet.peek_address(bdk.KeychainKind.INTERNAL, 0).address.script_pubkey() if wallet else None
            )
        return cls.from_inputs(inputs, output_scripts, wallet, mn, assume_one_input=True)

    @classmethod
    def from_psbt(cls, psbt: bdk.Psbt, analysis: Psbt | None = None) -> TxWeight:
        """Draft fallback for incomplete metadata, using the same upstream parser."""
        analysis = (
            analysis if analysis is not None else Psbt.b64decode(psbt.serialize(), check_validity=False)
        )
        tx = analysis.tx
        inputs = []
        for txin, inp in zip(tx.vin, analysis.inputs, strict=True):
            prev = previous_output(inp, txin.prev_out.vout)
            script = bdk.Script(prev.script_pub_key.script) if prev is not None else None
            weight = InputWeight.from_psbt_input(script, inp)
            size, witness = len(inp.final_script_sig), inp.final_script_witness.stack
            if has_finalized_unlocking_data(
                weight.address_type, bool(size), bool(witness), weight.legacy_multisig
            ):
                weight.satisfaction_weight = 4 * (
                    compact_size_length(size) - 1 + size
                ) + witness_satisfaction_weight([len(item) for item in witness])
                weight.finalized_witness = bool(witness)
            inputs.append(weight)
        return cls(inputs, [bdk.Script(out.script_pub_key.script) for out in tx.vout])

    def estimate(self) -> int:
        """Estimate a draft using btclib's transaction serialization rules."""
        # A one-item empty witness makes btclib include the marker, flag and
        # one witness count per input. Remove the extra item's length byte:
        # InputWeight uses BDK's weight delta from an empty witness.
        tx = Tx(
            vin=[
                BtclibTxIn(
                    script_witness=Witness([b""]) if item.is_witness() else Witness(),
                    check_validity=False,
                )
                for item in self.inputs
            ],
            vout=[
                BtclibTxOut(
                    0,
                    bytes((script if script is not None else DEFAULT_OUTPUT_SCRIPT).to_bytes()),
                    check_validity=False,
                )
                for script in self.output_scripts
            ],
            check_validity=False,
        )
        return tx.weight + sum(item.weight() - int(item.is_witness()) for item in self.inputs)


class FeeRate(bdk.FeeRate):
    @classmethod
    def from_fee_rate(cls, fee_rate: bdk.FeeRate) -> FeeRate:
        """From fee rate."""
        return cast(FeeRate, cls.from_sat_per_kwu(fee_rate.to_sat_per_kwu()))

    @classmethod
    def from_float_sats_vB(cls, fee_rate: float) -> FeeRate:
        """From float sats vB."""
        sat_per_kwu = int(250 * fee_rate)
        return cast(FeeRate, cls.from_sat_per_kwu(sat_per_kwu))

    @classmethod
    def from_btc_per_kb(cls, fee_rate: float) -> FeeRate:
        """Create a fee rate from BTC/kB."""
        sat_per_kwu = round(fee_rate * 25_000_000)
        return cast(FeeRate, cls.from_sat_per_kwu(sat_per_kwu))

    @classmethod
    def to_sats_per_vb(cls, fee_rate: bdk.FeeRate) -> float:
        """To sats per vb."""
        return fee_rate.to_sat_per_kwu() / 250


class FeeInfo:
    def __init__(
        self, fee_amount: int, vsize: int, fee_amount_is_estimated: bool, vsize_is_estimated: bool
    ) -> None:
        """Initialize instance."""
        self.fee_amount = fee_amount
        self.vsize = vsize
        self.fee_amount_is_estimated = fee_amount_is_estimated
        self.vsize_is_estimated = vsize_is_estimated

    def fee_rate(self) -> float:
        """Fee rate."""
        return self.fee_amount / self.vsize

    def fee_rate_is_estimated(self):
        """Fee rate is estimated."""
        return self.any_is_estimated()

    def any_is_estimated(self):
        """Any is estimated."""
        return self.vsize_is_estimated or self.fee_amount_is_estimated

    @classmethod
    def from_fee_rate(
        cls, fee_amount: int, fee_rate: float, fee_amount_is_estimated: bool, fee_rate_is_estimated: bool
    ) -> FeeInfo | None:
        """From fee rate."""
        vsize = int(fee_amount / fee_rate) if fee_rate > 0 else VSIZE_OF_ZERO_FEE_TX
        return FeeInfo(
            fee_amount=fee_amount,
            vsize=vsize,
            fee_amount_is_estimated=fee_amount_is_estimated,
            vsize_is_estimated=fee_rate_is_estimated or fee_amount_is_estimated,
        )

    @classmethod
    def from_fee_rate_and_vsize(
        cls, vsize: int, fee_rate: float, fee_rate_is_estimated: bool, vsize_is_estimated: bool
    ) -> FeeInfo:
        """From fee rate and vsize."""
        return FeeInfo(
            fee_amount=int(vsize * fee_rate),
            vsize=vsize,
            vsize_is_estimated=vsize_is_estimated,
            fee_amount_is_estimated=fee_rate_is_estimated or vsize_is_estimated,
        )

    @classmethod
    def from_txdetails(cls, tx_details: TransactionDetails) -> FeeInfo | None:
        """From txdetails."""
        fee = tx_details.fee
        if fee is None:
            # coinbase transaction have fee=None
            # it is also possible that the blockchain client (rpc) doesnt provide this
            # info for an incoming tx, so the field is also None
            return None
        return FeeInfo(fee, tx_details.vsize, vsize_is_estimated=False, fee_amount_is_estimated=False)

    @classmethod
    def estimate_segwit_fee_rate_from_psbt(cls, psbt: bdk.Psbt) -> FeeInfo | None:
        """Estimate the PSBT fee rate, or use its finalized transaction's actual size."""
        try:
            analysis = Psbt.b64decode(psbt.serialize(), check_validity=False)
            # prevouts validates the PSBT, including conflicting UTXO fields.
            spent_outputs = prevouts(analysis)
            fee = psbt.fee()
            if not analysis.inputs or fee < 0:
                return None
            finalized = []
            needs_legacy_estimator = False
            for inp, spent in zip(analysis.inputs, spent_outputs, strict=True):
                raw = spent.script_pub_key.script
                address_type = input_address_type(raw, inp.redeem_script, inp.final_script_sig)
                has_final_fields = bool(inp.final_script_sig or inp.final_script_witness)
                complete = has_finalized_unlocking_data(
                    address_type,
                    bool(inp.final_script_sig),
                    bool(inp.final_script_witness),
                    is_p2sh(raw) and address_type is None,
                )
                finalized.append(complete)
                # The pinned upstream release treats any final field as a complete
                # spend and does not choose a Taproot leaf. Retain main's existing
                # estimator for these specific cases until upstream supports them.
                needs_legacy_estimator |= (has_final_fields and not complete) or (
                    not complete
                    and is_p2tr(raw)
                    and bool(inp.taproot_leaf_scripts or inp.taproot_script_spend_signatures)
                )
            if all(finalized):
                vsize = psbt.extract_tx_unchecked_fee_rate().vsize()
            elif needs_legacy_estimator:
                vsize = weight_to_vsize(TxWeight.from_psbt(psbt, analysis).estimate())
            else:
                vsize = analysis.vsize_estimate(sizer=miniscript_sizer)
        except (ValueError, bdk.CalculateFeeError, bdk.PsbtError) as exc:  # pyright: ignore[reportGeneralTypeIssues]
            logger.info("Could not estimate PSBT weight with btclib: %s", exc)
            return None
        return FeeInfo(fee, vsize, vsize_is_estimated=not all(finalized), fee_amount_is_estimated=False)

    def __add__(self, other: FeeInfo) -> FeeInfo:
        """Add."""
        if isinstance(other, FeeInfo):
            return FeeInfo(
                fee_amount=self.fee_amount + other.fee_amount,
                vsize=self.vsize + other.vsize,
                vsize_is_estimated=self.vsize_is_estimated or other.vsize_is_estimated,
                fee_amount_is_estimated=self.fee_amount_is_estimated or other.fee_amount_is_estimated,
            )

    @classmethod
    def combined_fee_info(cls, txs: Iterable[TransactionDetails]) -> FeeInfo | None:
        """Combined fee info."""
        combined_info: FeeInfo | None = None
        if not txs:
            return combined_info
        for tx in txs:
            info = FeeInfo.from_txdetails(tx)
            if info:
                combined_info = (combined_info + info) if combined_info else info
        return combined_info


class PubKeyInfo:
    def __init__(
        self,
        fingerprint: str,
        pubkey: str | None = None,
        derivation_path: str | None = None,
        label: str = "",
    ) -> None:
        """Initialize instance."""
        self.fingerprint = SimplePubKeyProvider.format_fingerprint(fingerprint) if fingerprint else ""
        self.pubkey = pubkey
        self.derivation_path = (
            (derivation_path if derivation_path.startswith("m/") else "m/" + derivation_path)
            if derivation_path
            else None
        )
        self.label = label

    @classmethod
    def from_origin(cls, key: bytes, origin: BIP32KeyOrigin) -> PubKeyInfo:
        return cls(
            origin.master_fingerprint.hex(), key.hex(), origin.description.partition("/")[2].replace("h", "'")
        )

    @property
    def signer_id(self) -> str:
        if self.fingerprint:
            return self.fingerprint
        if self.pubkey:
            return self.pubkey
        return self.label

    def clone(self) -> PubKeyInfo:
        return PubKeyInfo(
            fingerprint=self.fingerprint,
            pubkey=self.pubkey,
            derivation_path=self.derivation_path,
            label=self.label,
        )


@dataclass
class PartialSig:
    signature: str
    sighash_type: str


@dataclass
class SimpleInput:
    txin: bdk.TxIn
    witness_script: str | None = None
    # partial_sigs example: {"0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6": "304402202976966c2996b3c17005342eebb60133741286460b135020dcb4f2089629d851022044402ada00dc6acb4040f44099f537a138f4558cb10f874656d9d544a19b0f6e"}    # noqa: E501
    # {pubkey: signature}
    partial_sigs: dict[str, PartialSig] = field(default_factory=dict)
    final_script_sig: str | None = None
    final_script_witness: list[str] | None = None
    pubkeys: list[PubKeyInfo] = field(default_factory=list)
    wallet_id: str | None = None
    m_of_n: tuple[int, int] | None = None
    source: PsbtIn = field(default_factory=lambda: PsbtIn(check_validity=False), repr=False)
    sighash_type: int | str | None = None
    redeem_script: str | None = None
    tap_key_sig: PartialSig | None = None
    verified_finalized_tap_key_sig: PartialSig | None = None
    tap_script_sigs: dict[tuple[str, str], PartialSig] = field(default_factory=dict)
    tap_key_origins: list[tuple[str, tuple[list[str], tuple[str, str]]]] = field(default_factory=list)
    tap_internal_key: str | None = None
    tap_merkle_root: str | None = None

    @classmethod
    def from_btclib(cls, inp: PsbtIn, txin: bdk.TxIn) -> SimpleInput:
        """Project only the fields the UI needs; keep the complete upstream map."""
        self = cls(
            txin=txin,
            source=inp,
            witness_script=inp.witness_script.hex() or None,
            redeem_script=inp.redeem_script.hex() or None,
            final_script_sig=inp.final_script_sig.hex() or None,
            final_script_witness=[item.hex() for item in inp.final_script_witness.stack] or None,
            sighash_type=inp.sig_hash_type,
            tap_internal_key=inp.taproot_internal_key.hex() or None,
            tap_merkle_root=inp.taproot_merkle_root.hex() or None,
            partial_sigs={
                key.hex(): PartialSig(
                    sig[:-1].hex(), "SIGHASH_" + cls._format_sighash_type(sig[-1]).replace("|", "|SIGHASH_")
                )
                for key, sig in sorted(inp.partial_sigs.items())
                if sig
            },
            pubkeys=[PubKeyInfo.from_origin(key, origin) for key, origin in inp.hd_key_paths.items()],
            tap_key_sig=cls._taproot_signature(inp.taproot_key_spend_signature),
        )
        for key, sig in sorted(inp.taproot_script_spend_signatures.items()):
            signature = cls._taproot_signature(sig)
            if len(key) == 64 and signature is not None:
                self.tap_script_sigs[(key[:32].hex(), key[32:].hex())] = signature
        for key, (leaves, origin) in inp.taproot_hd_key_paths.items():
            try:
                origin.assert_valid()
            except ValueError:
                continue
            if len(key) != 32 or any(len(leaf) != 32 for leaf in leaves):
                continue
            pubkey = PubKeyInfo.from_origin(key, origin)
            self.pubkeys.append(pubkey)
            self.tap_key_origins.append(
                (
                    key.hex(),
                    (
                        [leaf.hex() for leaf in leaves],
                        (origin.master_fingerprint.hex(), pubkey.derivation_path or ""),
                    ),
                )
            )
        if self.sighash_type is not None and any(
            sig and sig.sighash_type != cls._format_sighash_type(self.sighash_type)
            for sig in [self.tap_key_sig, *self.tap_script_sigs.values()]
        ):
            logger.warning("Taproot signature sighash conflicts with PSBT input sighash")
        self._recover_finalized_singlesig_signer_data()
        self.m_of_n = self._get_m_of_n()
        return self

    @classmethod
    def _taproot_signature(cls, raw: bytes) -> PartialSig | None:
        if len(raw) not in (64, 65) or (len(raw) == 65 and raw[-1] not in (1, 2, 3, 0x81, 0x82, 0x83)):
            return None
        return PartialSig(raw[:64].hex(), cls._format_sighash_type(raw[64] if len(raw) == 65 else 0))

    def _recover_finalized_singlesig_signer_data(self) -> None:
        """Recover signer data from finalized singlesig witnesses when derivation data is absent."""
        if self.pubkeys or self.partial_sigs:
            return

        finalized_signature = self._finalized_singlesig_signature_and_pubkey()
        if not finalized_signature:
            return

        signature, pubkey = finalized_signature

        self.pubkeys.append(PubKeyInfo(fingerprint="", pubkey=pubkey))
        self.partial_sigs[pubkey] = PartialSig(
            signature=signature, sighash_type=self._recovered_sighash_type(signature)
        )
        # Heuristic: recover the common finalized singlesig witness shape as 1-of-1.
        self.m_of_n = (1, 1)

    def _finalized_singlesig_signature_and_pubkey(self) -> tuple[str, str] | None:
        """Return ``(signature, pubkey)`` for a likely finalized singlesig witness.

        This treats a 2-item ``final_script_witness`` whose second item is a
        compressed pubkey as the common finalized singlesig pattern.

        It only inspects witness shape. It does not validate script semantics,
        recover the fingerprint, or rule out custom scripts that look similar.
        """
        if self.final_script_witness and len(self.final_script_witness) == 2:
            signature, pubkey = self.final_script_witness
            if len(pubkey) == 66 and pubkey.startswith(("02", "03")):
                return signature, pubkey

        return None

    def _recovered_sighash_type(self, signature: str) -> str:
        """Resolve the sighash flag for recovered finalized signatures.

        Prefer the PSBT input's explicit ``sighash_type`` when present. If it is
        absent, fall back to the sighash byte appended to the DER signature.
        """
        if self.sighash_type is not None:
            return self._format_sighash_type(self.sighash_type)
        if len(signature) >= 2:
            return self._format_sighash_type(int(signature[-2:], 16))
        return "unknown"

    @staticmethod
    def _normalize_hex_32(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.lower()
        if len(value) != 64:
            return None
        try:
            if len(bytes.fromhex(value)) != 32:
                return None
        except ValueError:
            return None
        return value

    def _taproot_keypath_signature_for_pubkey(self, pubkey_info: PubKeyInfo) -> PartialSig | None:
        pubkey = self._normalize_hex_32(pubkey_info.pubkey)
        if not self.tap_key_sig or not pubkey or self._normalize_hex_32(self.tap_internal_key) != pubkey:
            return None
        return self.tap_key_sig if self._taproot_origin_for_pubkey(pubkey_info) is not None else None

    def set_verified_fingerprint(self, pubkey_info: PubKeyInfo, fingerprint: str) -> None:
        """Record a wallet-verified fingerprint on the public key and its matching Taproot origin."""
        if pubkey_info.fingerprint or not fingerprint:
            return
        pubkey_info.fingerprint = PubKeyInfo(fingerprint).fingerprint
        pubkey = self._normalize_hex_32(pubkey_info.pubkey)
        if not pubkey:
            return
        for index, (key, (leaves, (origin_fingerprint, path))) in enumerate(self.tap_key_origins):
            if (
                self._normalize_hex_32(key) == pubkey
                and not origin_fingerprint
                and PubKeyInfo("", key, path).derivation_path == pubkey_info.derivation_path
            ):
                self.tap_key_origins[index] = (key, (leaves, (pubkey_info.fingerprint, path)))

    def _taproot_origin_for_pubkey(self, pubkey_info: PubKeyInfo) -> list[str] | None:
        pubkey = self._normalize_hex_32(pubkey_info.pubkey)
        origins = [origin for origin in self.tap_key_origins if self._normalize_hex_32(origin[0]) == pubkey]
        if not pubkey or len(origins) != 1:
            return None
        _, (leaves, (fingerprint, path)) = origins[0]
        if not fingerprint:
            return None
        origin = PubKeyInfo(fingerprint, pubkey, path)
        if pubkey_info.fingerprint != origin.fingerprint:
            return None
        if pubkey_info.derivation_path and pubkey_info.derivation_path != origin.derivation_path:
            return None
        return (
            [leaf.lower() for leaf in leaves]
            if all(self._normalize_hex_32(leaf) for leaf in leaves)
            else None
        )

    def _taproot_scriptpath_signature_for_pubkey(self, pubkey_info: PubKeyInfo) -> PartialSig | None:
        pubkey = self._normalize_hex_32(pubkey_info.pubkey)
        leaves = self._taproot_origin_for_pubkey(pubkey_info)
        if pubkey and leaves is not None:
            for (signer_pubkey, leaf_hash), signature in self.tap_script_sigs.items():
                if signer_pubkey == pubkey and leaf_hash in leaves:
                    return signature
        return None

    @staticmethod
    def _format_sighash_type(sighash_type: int | str) -> str:
        """Format a sighash flag as a display string.

        References:
        - BIP 143 for ALL/NONE/SINGLE and ANYONECANPAY semantics:
          https://github.com/bitcoin/bips/blob/master/bip-0143.mediawiki
        - BIP 341 for the taproot DEFAULT sighash value:
          https://github.com/bitcoin/bips/blob/master/bip-0341.mediawiki#common-signature-message
        """
        if isinstance(sighash_type, str):
            normalized = sighash_type.upper().replace("SIGHASH_", "")
            if normalized.isdecimal():
                return SimpleInput._format_sighash_type(int(normalized))
            return normalized

        base_names = {
            0: "DEFAULT",
            1: "ALL",
            2: "NONE",
            3: "SINGLE",
        }
        if sighash_type not in (0, 1, 2, 3, 0x81, 0x82, 0x83):
            return hex(sighash_type)
        base_type = sighash_type & 0x1F
        parts = [base_names.get(base_type, hex(sighash_type))]
        if sighash_type & 0x80:
            parts.append("ANYONECANPAY")
        return "|".join(parts)

    def is_fully_signed(self) -> bool:
        """Whether the input has all required final unlocking fields."""
        if not (self.final_script_sig or self.final_script_witness):
            return False
        previous = self.previous_txout()
        raw = bytes(previous.script_pubkey.to_bytes()) if previous else b""
        redeem = bytes.fromhex(self.redeem_script or "")
        script_sig = bytes.fromhex(self.final_script_sig or "")
        address_type = input_address_type(raw, redeem, script_sig)
        return has_finalized_unlocking_data(
            address_type,
            bool(script_sig),
            bool(self.final_script_witness),
            is_p2sh(raw) and address_type is None,
        )

    def signature_count(self) -> str:
        # Just return the count of partial signatures, as we can't determine the total required
        """Signature count."""
        return str(len(self.get_pub_keys_with_signature()))

    def signature_for_pubkey(self, pubkey_info: PubKeyInfo) -> PartialSig | None:
        # A verified Taproot key-path spend of a known 1-of-1 wallet has only one signer.
        if (
            self.verified_finalized_tap_key_sig
            and self.m_of_n == (1, 1)
            and len(self.pubkeys) == 1
            and pubkey_info.fingerprint
            and pubkey_info.fingerprint == self.pubkeys[0].fingerprint
        ):
            return self.verified_finalized_tap_key_sig
        if not pubkey_info.pubkey:
            return None

        partial_sig = self.partial_sigs.get(pubkey_info.pubkey)
        if partial_sig:
            return partial_sig

        taproot_signature = self._taproot_keypath_signature_for_pubkey(
            pubkey_info
        ) or self._taproot_scriptpath_signature_for_pubkey(pubkey_info)
        if taproot_signature:
            return taproot_signature

        finalized_signature = self._finalized_singlesig_signature_and_pubkey()
        if not finalized_signature:
            return None

        signature, finalized_pubkey = finalized_signature
        if finalized_pubkey != pubkey_info.pubkey:
            return None

        return PartialSig(signature=signature, sighash_type=self._recovered_sighash_type(signature))

    def get_pub_keys_without_signature(self) -> list[PubKeyInfo]:
        # If the input is fully signed, there are no pubkeys without a signature
        """Get pub keys without signature."""
        if self.is_fully_signed():
            return []
        return [pubkey_info for pubkey_info in self.pubkeys if not self.signature_for_pubkey(pubkey_info)]

    def get_pub_keys_with_signature(self) -> list[PubKeyInfo]:
        # If the input is fully signed, all pubkeys are considered to have a signature
        """Get pub keys with signature."""
        if self.is_fully_signed():
            return self.pubkeys
        return [pubkey_info for pubkey_info in self.pubkeys if self.signature_for_pubkey(pubkey_info)]

    def fingerprint_has_signature(self, fingerprint: str) -> bool:
        """Fingerprint has signature."""
        if self.is_fully_signed():
            return True
        for pubkey_info in self.pubkeys:
            if pubkey_info.fingerprint == fingerprint and self.signature_for_pubkey(pubkey_info):
                return True
        return False

    def get_estimated_m_of_n(self) -> tuple[int, int]:
        """Get estimated m of n."""
        mn = self._get_m_of_n()
        if mn:
            return mn
        if not self.pubkeys and not self.is_fully_signed():
            # An unfinished input without signer metadata still needs a signing step.
            return (1, 1)
        return (len(self.pubkeys), len(self.pubkeys))

    def _get_m_of_n(self) -> tuple[int, int] | None:
        """Get m of n."""
        if self.m_of_n:
            return self.m_of_n

        for script_hex in (self.witness_script, self.redeem_script):
            if not script_hex:
                continue
            try:
                script = bytes.fromhex(script_hex)
                if is_p2ms_var(script):
                    m, public_keys = p2ms_m_and_keys_var(script)
                    return (m, len(public_keys))
            except ValueError:
                logger.warning("Invalid multisig script for input %s", self.txin.previous_output)
        return None

    def get_prev_txouts(self) -> dict[str, TxOut]:
        "Returns {str(outpoint): List[TxOut]}"
        previous_txout = self.previous_txout()
        if not previous_txout:
            return {}
        return {str(OutPoint.from_bdk(self.txin.previous_output)): previous_txout}

    def previous_txout(self) -> TxOut | None:
        """Return available previous-output metadata from the typed PSBT map."""
        out = previous_output(self.source, self.txin.previous_output.vout)
        if out is None:
            return None
        try:
            return TxOut(
                value=bdk.Amount.from_sat(out.value), script_pubkey=bdk.Script(out.script_pub_key.script)
            )
        except (OverflowError, ValueError):
            return None

    def address_derivations(self) -> set[tuple[bdk.KeychainKind, int]]:
        """Return standard descriptor keychain/index pairs encoded in the PSBT."""
        derivations: set[tuple[bdk.KeychainKind, int]] = set()
        for pubkey in self.pubkeys:
            if not pubkey.derivation_path:
                continue
            components = pubkey.derivation_path.removeprefix("m/").split("/")
            if len(components) < 2:
                continue
            keychain, index = components[-2:]
            if keychain not in {"0", "1"} or not index.isdecimal():
                continue
            derivations.add(
                (
                    bdk.KeychainKind.INTERNAL if keychain == "1" else bdk.KeychainKind.EXTERNAL,
                    int(index),
                )
            )
        return derivations


@dataclass
class SimpleOutput:
    value: int = 0
    script_pubkey: str = ""
    witness_script: str | None = None
    redeem_script: str | None = None
    bip32_derivation: list[PubKeyInfo] = field(default_factory=list)
    tap_internal_key: str | None = None
    source: PsbtOut = field(default_factory=lambda: PsbtOut(check_validity=False), repr=False)

    @classmethod
    def from_btclib(cls, out: PsbtOut, txout: BtclibTxOut) -> SimpleOutput:
        return cls(
            value=txout.value,
            script_pubkey=txout.script_pub_key.script.hex(),
            witness_script=out.witness_script.hex() or None,
            redeem_script=out.redeem_script.hex() or None,
            tap_internal_key=out.taproot_internal_key.hex() or None,
            bip32_derivation=[
                PubKeyInfo.from_origin(key, origin) for key, origin in out.hd_key_paths.items()
            ],
            source=out,
        )

    def to_txout(self) -> TxOut:
        """To txout."""
        return TxOut(value=bdk.Amount.from_sat(self.value), script_pubkey=hex_to_script(self.script_pubkey))


@dataclass
class InputGroup:
    group_id: str
    inputs: list[SimpleInput]
    input_indices: list[int]
    wallet_id: str | None
    m_of_n: tuple[int, int]
    signer_identifiers: dict[str, PubKeyInfo]

    @property
    def display_label(self) -> str:
        return self.group_id

    @property
    def has_wallet_id(self) -> bool:
        return bool(self.wallet_id)

    def _signatures_for_pubkey(self, pubkey_info: PubKeyInfo) -> dict[int, PartialSig]:
        signatures: dict[int, PartialSig] = {}
        for input_index, simple_input in zip(self.input_indices, self.inputs, strict=False):
            candidates = [key for key in simple_input.pubkeys if key.signer_id == pubkey_info.signer_id]
            for candidate in candidates or [pubkey_info]:
                if partial_sig := simple_input.signature_for_pubkey(candidate):
                    signatures[input_index] = partial_sig
                    break
        return signatures

    def signatures_by_identifier(self) -> dict[str, dict[int, PartialSig]]:
        return {
            signer_identifier: signatures
            for signer_identifier, pubkey_info in self.signer_identifiers.items()
            if (signatures := self._signatures_for_pubkey(pubkey_info))
        }

    def signed_signers(self) -> list[tuple[str, PubKeyInfo, dict[int, PartialSig]]]:
        signatures_by_identifier = self.signatures_by_identifier()
        return [
            (signer_identifier, pubkey_info, signatures_by_identifier[signer_identifier])
            for signer_identifier, pubkey_info in self.signer_identifiers.items()
            if signer_identifier in signatures_by_identifier
        ]

    def unsigned_signers(self) -> list[tuple[str, PubKeyInfo]]:
        signatures_by_identifier = self.signatures_by_identifier()
        return [
            (signer_identifier, pubkey_info)
            for signer_identifier, pubkey_info in self.signer_identifiers.items()
            if signer_identifier not in signatures_by_identifier
        ]

    @property
    def signed_signer_identifiers(self) -> list[str]:
        return [signer_identifier for signer_identifier, _pubkey_info, _signatures in self.signed_signers()]

    @property
    def unsigned_signer_identifiers(self) -> list[str]:
        return [signer_identifier for signer_identifier, _pubkey_info in self.unsigned_signers()]


@dataclass
class InputEnrichment:
    wallet_id: str
    m_of_n: tuple[int, int]
    pubkeys: list[PubKeyInfo]


@dataclass
class SimplePSBT:
    txid: str
    inputs: list[SimpleInput] = field(default_factory=list)
    outputs: list[SimpleOutput] = field(default_factory=list)

    @classmethod
    def from_psbt(cls, psbt: bdk.Psbt) -> SimplePSBT:
        """Read the typed PSBT once; keep BDK only at the UI/signing boundary."""
        parsed = Psbt.b64decode(psbt.serialize(), check_validity=False)
        tx = psbt.extract_tx_unchecked_fee_rate()
        instance = cls(
            txid=str(tx.compute_txid()),
            inputs=[
                SimpleInput.from_btclib(inp, txin)
                for inp, txin in zip(parsed.inputs, tx.input(), strict=True)
            ],
            outputs=[
                SimpleOutput.from_btclib(out, txout)
                for out, txout in zip(parsed.outputs, parsed.tx.vout, strict=True)
            ],
        )
        instance._recover_finalized_signatures(tx)
        return instance

    def _recover_finalized_signatures(self, tx: bdk.Transaction) -> None:
        # Finalization removes PSBT key origins and partial signatures. Verify the witness
        # to identify the signer: in a 1-of-2 input, either key could have signed.
        prevouts: list[Prevout | None] = []
        verify_inputs: list[bool] = []
        for item in self.inputs:
            previous = item.previous_txout()
            prevouts.append(
                Prevout(bytes(previous.script_pubkey.to_bytes()), previous.value.to_sat())
                if previous
                else None
            )
            witness = item.final_script_witness
            verify_inputs.append(
                bool(
                    item.is_fully_signed()
                    and (
                        (previous and is_p2pkh(bytes(previous.script_pubkey.to_bytes())))
                        or (witness and is_p2ms_var(bytes.fromhex(witness[-1])))
                        or (previous and witness and is_p2tr(bytes(previous.script_pubkey.to_bytes())))
                    )
                )
            )
        if not any(verify_inputs):
            return
        results = verify_transaction(tx, prevouts, verify_inputs).results
        for item, result in zip(self.inputs, results, strict=True):
            witness = item.final_script_witness
            if (
                result.verdict == InputVerdict.valid
                and witness
                and (previous := item.previous_txout())
                and is_p2tr(bytes(previous.script_pubkey.to_bytes()))
            ):
                keypath_witness = (
                    witness[:-1] if len(witness) == 2 and witness[-1].startswith("50") else witness
                )
                if len(keypath_witness) == 1 and len(keypath_witness[0]) in (128, 130):
                    tap_signature = keypath_witness[0]
                    item.verified_finalized_tap_key_sig = PartialSig(
                        signature=tap_signature[:128],
                        sighash_type=item._format_sighash_type(
                            int(tap_signature[128:], 16) if len(tap_signature) == 130 else 0
                        ),
                    )
            if result.signatures and item.final_script_witness:
                script = bytes.fromhex(item.final_script_witness[-1])
                if is_p2ms_var(script):
                    threshold, keys = p2ms_m_and_keys_var(script)
                    item.m_of_n = (threshold, len(keys))
            for pubkey, signature in result.signatures:
                pubkey_hex, signature_hex = pubkey.hex(), signature.hex()
                if not any(info.pubkey == pubkey_hex for info in item.pubkeys):
                    item.pubkeys.append(PubKeyInfo(fingerprint="", pubkey=pubkey_hex))
                item.partial_sigs[pubkey_hex] = PartialSig(
                    signature=signature_hex, sighash_type=item._recovered_sighash_type(signature_hex)
                )

    def get_fingerprint_tuples(self) -> tuple[list[PubKeyInfo], list[PubKeyInfo]]:
        # set of all fingerprints of all inputs
        # sorted_pubkeys = remove_duplicates_keep_order(
        #     sum(
        #         [simple_input.pubkeys for simple_input in self.inputs ],
        #         [],
        #     )
        # )

        """Get fingerprint tuples."""
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

    @staticmethod
    def _input_group_id(simple_input: SimpleInput, index: int) -> str:
        if simple_input.wallet_id and simple_input.m_of_n:
            return simple_input.wallet_id
        if simple_input.pubkeys:
            return ", ".join(sorted([pubkey.signer_id for pubkey in simple_input.pubkeys]))
        return f"Input {index}"

    @staticmethod
    def _pubkeys_by_signer_id(pubkeys_of_inputs: list[list[PubKeyInfo]]) -> dict[str, PubKeyInfo]:
        pubkeys: dict[str, PubKeyInfo] = {}
        for pubkeys_of_input in pubkeys_of_inputs:
            for pubkey in pubkeys_of_input:
                if pubkey.signer_id and pubkey.signer_id not in pubkeys:
                    pubkeys[pubkey.signer_id] = pubkey
        return pubkeys

    def enrich_with_outpoint_data(
        self,
        outpoint_dict: dict[str, InputEnrichment],
    ) -> SimplePSBT:
        for simple_input in self.inputs:
            outpoint_str = str(simple_input.txin.previous_output)
            enrichment = outpoint_dict.get(outpoint_str)
            if not enrichment:
                continue

            simple_input.wallet_id = enrichment.wallet_id
            simple_input.m_of_n = enrichment.m_of_n

            if not simple_input.pubkeys:
                simple_input.pubkeys = [pubkey.clone() for pubkey in enrichment.pubkeys]
                continue

            enrichment_pubkeys = self._pubkeys_by_signer_id([enrichment.pubkeys])
            for pubkey in simple_input.pubkeys:
                enrichment_pubkey = enrichment_pubkeys.get(pubkey.signer_id)
                if not enrichment_pubkey and pubkey.pubkey:
                    enrichment_pubkey = next(
                        (
                            candidate
                            for candidate in enrichment.pubkeys
                            if candidate.pubkey and candidate.pubkey == pubkey.pubkey
                        ),
                        None,
                    )
                if not enrichment_pubkey:
                    continue
                if not pubkey.fingerprint and enrichment_pubkey.fingerprint:
                    pubkey.fingerprint = enrichment_pubkey.fingerprint
                if not pubkey.pubkey and enrichment_pubkey.pubkey:
                    pubkey.pubkey = enrichment_pubkey.pubkey
                if not pubkey.derivation_path:
                    pubkey.derivation_path = enrichment_pubkey.derivation_path
                if enrichment_pubkey.label:
                    pubkey.label = enrichment_pubkey.label

        return self

    def group_inputs(self) -> list[InputGroup]:
        grouped_inputs: dict[str, list[tuple[int, SimpleInput]]] = {}
        for index, simple_input in enumerate(self.inputs):
            group_id = self._input_group_id(simple_input, index)
            grouped_inputs.setdefault(group_id, []).append((index, simple_input))

        result: list[InputGroup] = []
        for group_id, entries in grouped_inputs.items():
            input_indices = [index for index, _ in entries]
            inputs = [simple_input for _, simple_input in entries]
            signer_identifiers = self._pubkeys_by_signer_id([simple_input.pubkeys for simple_input in inputs])
            wallet_id = next(
                (simple_input.wallet_id for simple_input in inputs if simple_input.wallet_id), None
            )

            result.append(
                InputGroup(
                    group_id=group_id,
                    inputs=inputs,
                    input_indices=input_indices,
                    wallet_id=wallet_id,
                    m_of_n=inputs[0].get_estimated_m_of_n(),
                    signer_identifiers=signer_identifiers,
                )
            )

        return result

    def get_prev_txouts(self) -> dict[str, TxOut]:
        """Get prev txouts."""
        d = self.inputs[0].get_prev_txouts()
        for inp in self.inputs[1:]:
            d.update(inp.get_prev_txouts())

        return d

    def outpoints_as_python_utxo_dict(self, network: bdk.Network) -> dict[str, PythonUtxo]:
        "Returns {str(outpoint) : python_utxo}  for all outpoints"
        txout_dict = self.get_prev_txouts()

        python_txos = [
            PythonUtxo(
                address=robust_address_str_from_txout(txout, network=network),
                txout=txout,
                outpoint=OutPoint(vout=vout, txid=bdk.Txid.from_string(self.txid)),
            )
            for vout, txout in enumerate(txout_dict.values())
        ]

        return {str(python_txo.outpoint): python_txo for python_txo in python_txos}
