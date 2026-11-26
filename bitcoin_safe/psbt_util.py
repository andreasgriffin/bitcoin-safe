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
from bitcoin_safe_lib.util import network_kind
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
from btclib.script.sig_hash import SIG_HASH_TYPES
from btclib.tx import Tx
from btclib.tx import TxIn as BtclibTxIn
from btclib.tx import TxOut as BtclibTxOut
from btclib_wallet.psbt import Psbt, PsbtIn, miniscript_sizer, prevouts
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


def read_psbt(psbt: bdk.Psbt) -> Psbt:
    """Decode for inspection, including incomplete PSBTs."""
    return Psbt.b64decode(psbt.serialize(), check_validity=False)


def input_outpoint(inp: PsbtIn) -> OutPoint:
    point = inp.prev_out
    return OutPoint(txid=bdk.Txid.from_string(point.tx_id.hex()), vout=point.vout)


def previous_txout(inp: PsbtIn) -> TxOut | None:
    out = previous_output(inp, inp.output_index if inp.output_index is not None else -1)
    if out is not None:
        try:
            return TxOut(
                value=bdk.Amount.from_sat(out.value), script_pubkey=bdk.Script(out.script_pub_key.script)
            )
        except (OverflowError, ValueError):
            pass
    return None


def address_derivations(inp: PsbtIn) -> set[tuple[bdk.KeychainKind, int]]:
    """Standard receive/change suffixes from native BIP32 origins."""
    result: set[tuple[bdk.KeychainKind, int]] = set()
    for origin in (*inp.hd_key_paths.values(), *(origin for _, origin in inp.taproot_hd_key_paths.values())):
        path = origin.der_path
        if len(path) >= 2 and path[-2] in (0, 1) and 0 <= path[-1] < 0x80000000:
            kind = bdk.KeychainKind.INTERNAL if path[-2] else bdk.KeychainKind.EXTERNAL
            result.add((kind, path[-1]))
    return result


def psbt_prev_txouts(psbt: Psbt) -> dict[str, TxOut]:
    """Available spent outputs, indexed by their actual outpoints."""
    return {str(input_outpoint(inp)): out for inp in psbt.inputs if (out := previous_txout(inp)) is not None}


def psbt_input_utxos(psbt: Psbt, network: bdk.Network) -> dict[str, PythonUtxo]:
    return {
        point: PythonUtxo(
            address=robust_address_str_from_txout(out, network=network),
            txout=out,
            outpoint=OutPoint.from_str(point),
        )
        for point, out in psbt_prev_txouts(psbt).items()
    }


def input_is_finalized(inp: PsbtIn, raw: bytes) -> bool:
    # Upstream 2026.11.19 accepts either final field, even for incomplete
    # nested SegWit. Keep the spend-type-aware check at this boundary.
    address_type = input_address_type(raw, inp.redeem_script, inp.final_script_sig)
    return has_finalized_unlocking_data(
        address_type,
        bool(inp.final_script_sig),
        bool(inp.final_script_witness),
        is_p2sh(raw) and address_type is None,
    )


def psbt_is_finalized(psbt: Psbt) -> bool:
    return bool(psbt.inputs) and all(
        input_is_finalized(inp, out.spk_bytes if (out := previous_txout(inp)) else b"") for inp in psbt.inputs
    )


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
            analysis = read_psbt(psbt)
            # prevouts validates the PSBT, including conflicting UTXO fields.
            spent_outputs = prevouts(analysis)
            fee = psbt.fee()
            if not analysis.inputs or fee < 0:
                return None
            finalized = []
            needs_legacy_estimator = False
            for inp, spent in zip(analysis.inputs, spent_outputs, strict=True):
                raw = spent.script_pub_key.script
                has_final_fields = bool(inp.final_script_sig or inp.final_script_witness)
                complete = input_is_finalized(inp, raw)
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
class SigningInput:
    """UI-only annotations for one native PSBT input; never rewrites the PSBT."""

    source: PsbtIn
    pubkeys: list[PubKeyInfo] = field(default_factory=list)
    wallet_id: str | None = None
    m_of_n: tuple[int, int] | None = None
    recovered_signatures: dict[str, PartialSig] = field(default_factory=dict)
    verified_finalized_tap_key_sig: PartialSig | None = None
    verified_fingerprints: dict[bytes, str] = field(default_factory=dict, repr=False)

    @classmethod
    def from_btclib(cls, inp: PsbtIn) -> SigningInput:
        item = cls(inp, [PubKeyInfo.from_origin(key, origin) for key, origin in inp.hd_key_paths.items()])
        for key, (leaves, origin) in inp.taproot_hd_key_paths.items():
            if len(key) != 32 or any(len(leaf) != 32 for leaf in leaves):
                continue
            if len(origin.master_fingerprint) not in (0, 4):
                continue
            try:
                item.pubkeys.append(PubKeyInfo.from_origin(key, origin))
            except ValueError:
                continue
        if inp.sig_hash_type is not None and any(
            sig.sighash_type != cls._format_sighash_type(inp.sig_hash_type)
            for raw in (inp.taproot_key_spend_signature, *inp.taproot_script_spend_signatures.values())
            if (sig := cls._taproot_signature(raw)) is not None
        ):
            logger.warning("Taproot signature sighash conflicts with PSBT input sighash")
        item._recover_finalized_singlesig_signer_data()
        item.m_of_n = item._get_m_of_n()
        return item

    @staticmethod
    def _format_sighash_type(sighash_type: int | str) -> str:
        if isinstance(sighash_type, str):
            normalized = sighash_type.upper().replace("SIGHASH_", "")
            return (
                SigningInput._format_sighash_type(int(normalized)) if normalized.isdecimal() else normalized
            )
        if sighash_type not in SIG_HASH_TYPES:
            return hex(sighash_type)
        base = ("DEFAULT", "ALL", "NONE", "SINGLE")[sighash_type & 3]
        return base + ("|ANYONECANPAY" if sighash_type & 0x80 else "")

    @classmethod
    def _taproot_signature(cls, raw: bytes) -> PartialSig | None:
        if len(raw) == 64:
            return PartialSig(raw.hex(), "DEFAULT")
        if len(raw) == 65 and raw[-1] and raw[-1] in SIG_HASH_TYPES:
            return PartialSig(raw[:-1].hex(), cls._format_sighash_type(raw[-1]))
        return None

    def _recovered_sig(self, raw: bytes) -> PartialSig:
        flag = self.source.sig_hash_type
        if flag is None and raw:
            flag = raw[-1]
        return PartialSig(raw.hex(), self._format_sighash_type(flag) if flag is not None else "unknown")

    def _finalized_singlesig(self) -> tuple[str, PartialSig] | None:
        # Preserve the existing display-only heuristic for the common two-item
        # finalized singlesig witness. This is not script verification.
        stack = self.source.final_script_witness.stack
        if len(stack) == 2 and len(stack[1]) == 33 and stack[1][0] in (2, 3):
            return stack[1].hex(), self._recovered_sig(stack[0])
        return None

    def _recover_finalized_singlesig_signer_data(self) -> None:
        if not self.pubkeys and not self.source.partial_sigs and (recovered := self._finalized_singlesig()):
            key, sig = recovered
            self.pubkeys.append(PubKeyInfo("", key))
            self.recovered_signatures[key] = sig
            self.m_of_n = (1, 1)

    def set_verified_fingerprint(self, pubkey_info: PubKeyInfo, fingerprint: str) -> None:
        """Wallet-verified display metadata does not modify the native key origin."""
        if pubkey_info.fingerprint or not fingerprint:
            return
        pubkey_info.fingerprint = PubKeyInfo(fingerprint).fingerprint
        if not pubkey_info.pubkey:
            return
        try:
            key = bytes.fromhex(pubkey_info.pubkey)
        except ValueError:
            return
        if (entry := self.source.taproot_hd_key_paths.get(key)) is not None:
            try:
                origin = PubKeyInfo.from_origin(key, entry[1])
            except ValueError:
                return
            if not origin.fingerprint and origin.derivation_path == pubkey_info.derivation_path:
                self.verified_fingerprints[key] = pubkey_info.fingerprint

    def signature_for_pubkey(self, pubkey_info: PubKeyInfo) -> PartialSig | None:
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
        if recovered := self.recovered_signatures.get(pubkey_info.pubkey):
            return recovered
        try:
            key = bytes.fromhex(pubkey_info.pubkey)
        except ValueError:
            return None
        if pubkey_info.pubkey.lower() != key.hex():
            return None
        if raw := self.source.partial_sigs.get(key):
            flag = self._format_sighash_type(raw[-1]).replace("|", "|SIGHASH_")
            return PartialSig(raw[:-1].hex(), "SIGHASH_" + flag)
        if len(key) == 32 and (entry := self.source.taproot_hd_key_paths.get(key)) is not None:
            leaves, origin = entry
            if len(origin.master_fingerprint) not in (0, 4) or any(len(leaf) != 32 for leaf in leaves):
                return None
            try:
                origin_info = PubKeyInfo.from_origin(key, origin)
            except ValueError:
                return None
            fingerprint = self.verified_fingerprints.get(key, origin_info.fingerprint)
            if not fingerprint or fingerprint != pubkey_info.fingerprint:
                return None
            if pubkey_info.derivation_path and pubkey_info.derivation_path != origin_info.derivation_path:
                return None
            if key == self.source.taproot_internal_key:
                if sig := self._taproot_signature(self.source.taproot_key_spend_signature):
                    return sig
            for leaf in sorted(leaves):
                if sig := self._taproot_signature(
                    self.source.taproot_script_spend_signatures.get(key + leaf, b"")
                ):
                    return sig
        if (recovered2 := self._finalized_singlesig()) and recovered2[0] == pubkey_info.pubkey:
            return recovered2[1]
        return None

    def is_fully_signed(self) -> bool:
        out = self.previous_txout()
        return input_is_finalized(self.source, out.spk_bytes if out else b"")

    def _get_m_of_n(self) -> tuple[int, int] | None:
        if self.m_of_n:
            return self.m_of_n
        for script in (self.source.witness_script, self.source.redeem_script):
            if is_p2ms_var(script):
                m, keys = p2ms_m_and_keys_var(script)
                return m, len(keys)
        return None

    def get_estimated_m_of_n(self) -> tuple[int, int]:
        if mn := self._get_m_of_n():
            return mn
        n = len(self.pubkeys)
        if not n and not self.is_fully_signed():
            n = 1
        return n, n

    @property
    def outpoint(self) -> OutPoint:
        return input_outpoint(self.source)

    def previous_txout(self) -> TxOut | None:
        return previous_txout(self.source)

    def enrich(self, wallet_id: str, m_of_n: tuple[int, int], pubkeys: list[PubKeyInfo]) -> None:
        self.wallet_id, self.m_of_n = wallet_id, m_of_n
        if not self.pubkeys:
            self.pubkeys = [key.clone() for key in pubkeys]
            return
        for key in self.pubkeys:
            match = next((candidate for candidate in pubkeys if candidate.signer_id == key.signer_id), None)
            if not match and key.pubkey:
                match = next((candidate for candidate in pubkeys if candidate.pubkey == key.pubkey), None)
            if match:
                key.fingerprint = key.fingerprint or match.fingerprint
                key.pubkey = key.pubkey or match.pubkey
                key.derivation_path = key.derivation_path or match.derivation_path
                key.label = match.label or key.label


@dataclass
class InputGroup:
    group_id: str
    inputs: list[SigningInput]
    input_indices: list[int]
    wallet_id: str | None
    m_of_n: tuple[int, int]
    signer_identifiers: dict[str, PubKeyInfo]

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


@dataclass
class SigningProgress:
    """Only signer UI state, not another PSBT model."""

    inputs: list[SigningInput] = field(default_factory=list)

    @classmethod
    def from_psbt(cls, psbt: bdk.Psbt) -> SigningProgress:
        parsed = read_psbt(psbt)
        progress = cls([SigningInput.from_btclib(inp) for inp in parsed.inputs])
        if any(inp.final_script_sig or inp.final_script_witness for inp in parsed.inputs):
            progress._recover_finalized_signatures(psbt.extract_tx_unchecked_fee_rate())
        return progress

    def _recover_finalized_signatures(self, tx: bdk.Transaction) -> None:
        # Finalization removes key origins and partial signatures. Attribute
        # multisig/legacy/Taproot spends only to keys verified by the script engine.
        spent = [item.previous_txout() for item in self.inputs]
        prev = [Prevout(out.spk_bytes, out.value.to_sat()) if out else None for out in spent]
        verify = [
            bool(
                item.is_fully_signed()
                and (
                    (out and is_p2pkh(out.spk_bytes))
                    or (
                        item.source.final_script_witness
                        and is_p2ms_var(item.source.final_script_witness.stack[-1])
                    )
                    or (out and item.source.final_script_witness and is_p2tr(out.spk_bytes))
                )
            )
            for item, out in zip(self.inputs, spent, strict=True)
        ]
        if not any(verify):
            return
        results = verify_transaction(tx, prev, verify).results
        for item, out, result in zip(self.inputs, spent, results, strict=True):
            witness = item.source.final_script_witness.stack
            if result.verdict == InputVerdict.valid and witness and out and is_p2tr(out.spk_bytes):
                keypath = witness[:-1] if len(witness) == 2 and witness[-1].startswith(b"\x50") else witness
                if len(keypath) == 1:
                    item.verified_finalized_tap_key_sig = item._taproot_signature(keypath[0])
            if result.signatures and witness and is_p2ms_var(witness[-1]):
                m, keys = p2ms_m_and_keys_var(witness[-1])
                item.m_of_n = (m, len(keys))
            for pubkey, signature in result.signatures:
                key = pubkey.hex()
                if not any(info.pubkey == key for info in item.pubkeys):
                    item.pubkeys.append(PubKeyInfo("", key))
                item.recovered_signatures[key] = item._recovered_sig(signature)

    @staticmethod
    def _input_group_id(simple_input: SigningInput, index: int) -> str:
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

    def group_inputs(self) -> list[InputGroup]:
        grouped_inputs: dict[str, list[tuple[int, SigningInput]]] = {}
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
