#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
"""Verify the consensus script rules of transaction inputs that spend wallet-owned outputs.

A backend can serve an unconfirmed transaction that spends the same outputs as a
wallet transaction but pays to different addresses. Such a transaction cannot carry
valid signatures for the wallet's own record of the spent output. This module runs
btclib's consensus script engine on each wallet-owned input against that prevout data.

An input is ``invalid`` when the engine refuses it, ``valid`` when the engine runs and
checks at least one signature, and ``unchecked`` when the input's prevout is unknown
or the script ran without checking a signature.
Participant inputs that are not wallet-owned are never executed; only the native
witness scriptSig rule is enforced for them.

This entire file should be removed once BDK has implemented signature checks for wallet-owned inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import bdkpython as bdk
from btclib.exceptions import ScriptError
from btclib.script.engine import verify_input
from btclib.script.sig_hash import ANYONECANPAY
from btclib.tx import Tx, TxOut


class InputVerdict(Enum):
    """Whether this verifier confirmed a signature, rejected it, or skipped it."""

    valid = "valid"
    invalid = "invalid"
    unchecked = "unchecked"


@dataclass(frozen=True)
class Prevout:
    """The output spent by an input: its scriptPubKey and value in satoshis."""

    script_pubkey: bytes
    value: int


@dataclass(frozen=True)
class InputResult:
    """Verdict for one input, plus the public keys whose signatures the engine confirmed."""

    verdict: InputVerdict
    signer_pubkeys: tuple[bytes, ...] = ()


@dataclass(frozen=True)
class TxVerification:
    """Per-input results. A transaction is invalid if any of its inputs is invalid."""

    results: list[InputResult]

    @property
    def verdicts(self) -> list[InputVerdict]:
        return [result.verdict for result in self.results]

    @property
    def is_invalid(self) -> bool:
        return InputVerdict.invalid in self.verdicts


def has_signature_material(tx: bdk.Transaction) -> bool:
    """Return True if every input carries a non-empty scriptSig or witness.

    Presence only: no prevout lookup and no signature validation.
    """
    return all(bool(tx_input.script_sig.to_bytes()) or bool(tx_input.witness) for tx_input in tx.input())


def _is_native_witness(script_pubkey: bytes) -> bool:
    # Witness v0 (P2WPKH/P2WSH) and v1 (P2TR) programs are OP_n followed by a push of
    # 20 or 32 bytes. Their scriptSig must be empty under consensus.
    return (len(script_pubkey) == 22 and script_pubkey[:2] == b"\x00\x14") or (
        len(script_pubkey) == 34 and script_pubkey[:2] in (b"\x00\x20", b"\x51\x20")
    )


def _is_taproot_program(script_pubkey: bytes) -> bool:
    return len(script_pubkey) == 34 and script_pubkey[:2] == b"\x51\x20"


def _verify_external_input(tx: Tx, index: int, prevout: Prevout | None) -> InputVerdict:
    """Enforce the native-witness scriptSig rule only, never a participant's signature."""
    if prevout is None:
        return InputVerdict.unchecked
    if _is_native_witness(prevout.script_pubkey) and tx.vin[index].scriptSig:
        return InputVerdict.invalid
    return InputVerdict.unchecked


def _taproot_keypath_allows_unknown_siblings(tx: Tx, index: int) -> bool:
    """Return True if the input is a key-path spend whose sighash commits only to its own prevout.

    Only ANYONECANPAY taproot key-path sighashes skip the other inputs' prevouts. Those
    placeholders are never read, as btclib's sig_hash reads only the signed input's prevout
    under ANYONECANPAY. Other hash types commit to every prevout and stay unchecked.
    """
    witness = list(tx.vin[index].script_witness.stack)
    if len(witness) == 2 and witness[-1].startswith(b"\x50"):
        witness = witness[:1]  # drop the BIP341 annex
    if len(witness) != 1 or len(witness[0]) not in (64, 65):
        return False
    return len(witness[0]) == 65 and bool(witness[0][64] & ANYONECANPAY)


def _verify_wallet_input(tx: Tx, index: int, prevouts: list[Prevout | None]) -> InputResult:
    """Run the consensus engine on one wallet-owned input and map the outcome to a result."""
    prevout = prevouts[index]
    if prevout is None:
        return InputResult(InputVerdict.unchecked)
    # The engine needs one TxOut per input. Unknown siblings are only replaced by
    # placeholders when no other input's data can reach this input's sighash: legacy
    # and SegWit v0 sighashes read only this input's prevout, and so do Taproot
    # ANYONECANPAY key-path sighashes. Other Taproot sighashes commit to every prevout.
    sibling_placeholders_allowed = not _is_taproot_program(
        prevout.script_pubkey
    ) or _taproot_keypath_allows_unknown_siblings(tx, index)
    tx_outs: list[TxOut] = []
    for other in prevouts:
        if other is not None:
            tx_outs.append(TxOut(other.value, other.script_pubkey, check_validity=False))
        elif sibling_placeholders_allowed:
            tx_outs.append(TxOut(0, b"", check_validity=False))
        else:
            return InputResult(InputVerdict.unchecked)
    hash_types: list[int] = []
    signatures: list[tuple[bytes, bytes]] = []
    try:
        verify_input(tx_outs, tx, index, hash_types=hash_types, signatures=signatures)
    except ScriptError:
        return InputResult(InputVerdict.invalid)
    # hash_types also records failed ECDSA checks, so only verified ECDSA pairs count.
    # btclib does not collect successful Schnorr signatures, so for Taproot any recorded
    # check is the signal. Scripts that ran without a verified signature stay unchecked.
    has_verified_signature = bool(signatures) or (
        _is_taproot_program(prevout.script_pubkey) and bool(hash_types)
    )
    if not has_verified_signature:
        return InputResult(InputVerdict.unchecked)
    return InputResult(InputVerdict.valid, tuple(pub_key for pub_key, _ in signatures))


def verify_transaction(
    tx: bdk.Transaction,
    prevouts: list[Prevout | None],
    wallet_owned_inputs: list[bool] | None = None,
) -> TxVerification:
    """Verify every input of ``tx``.

    ``prevouts`` holds known spent outputs regardless of ownership. Ownership is
    separate because external prevouts still contribute to non-ANYONECANPAY Taproot
    sighashes, while only wallet-owned input signatures are checked.
    """
    # check_validity=False: the verifier checks scripts and signatures, not the
    # transaction-level rules (BIP68 sequence locks, coinbase maturity, BIP54).
    # Rejecting such transactions here would hide a signature verdict from the wallet.
    consensus_tx = Tx.parse(tx.serialize(), check_validity=False)
    input_count = len(consensus_tx.vin)
    if wallet_owned_inputs is None:
        # Standalone callers historically ask to verify every input; wallet callers
        # pass explicit ownership flags so external participant signatures are skipped.
        wallet_owned_inputs = [True] * input_count
    if len(prevouts) != input_count or len(wallet_owned_inputs) != input_count:
        return TxVerification(results=[InputResult(InputVerdict.invalid)] * input_count)
    return TxVerification(
        results=[
            _verify_input_safely(consensus_tx, index, prevouts, wallet_owned_inputs[index])
            for index in range(input_count)
        ],
    )


def _verify_input_safely(
    tx: Tx, index: int, prevouts: list[Prevout | None], wallet_owned: bool
) -> InputResult:
    """Treat malformed input encodings as invalid instead of aborting transaction processing."""
    try:
        if not wallet_owned:
            return InputResult(_verify_external_input(tx, index, prevouts[index]))
        return _verify_wallet_input(tx, index, prevouts)
    except Exception:
        return InputResult(InputVerdict.invalid)
