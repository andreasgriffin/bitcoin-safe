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
"""Verify signatures of transaction inputs that spend wallet-owned outputs.

A backend can serve an unconfirmed transaction that spends the same outputs as a
wallet transaction but pays to different addresses. Such a transaction cannot carry
valid signatures for the wallet's own record of the spent output. This module checks
the signatures of the supported script types against that prevout data.

Checked: P2PKH, P2WPKH, P2SH-wrapped P2WPKH/P2WSH multisig, native P2WSH
multisig (ECDSA), and P2TR key-path (BIP340). Reported as ``unchecked``: other
P2WSH scripts, P2TR script-path, unknown scripts, and inputs whose prevout the
wallet does not know.
Full script validation is out of scope.



This entire file should be removed once BDK has implmeneted signature checks for unconfirmed tx.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import bdkpython as bdk
from embit.ec import PublicKey, SchnorrSig, Signature
from embit.hashes import hash160, sha256
from embit.script import Script
from embit.transaction import SIGHASH, Transaction
from embit.util import secp256k1


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
class TxVerification:
    """Per-input verdicts. A transaction is invalid if any of its inputs is invalid."""

    verdicts: list[InputVerdict]

    @property
    def is_invalid(self) -> bool:
        return InputVerdict.invalid in self.verdicts


def _is_p2pkh(spk: bytes) -> bool:
    # P2PKH is: OP_DUP OP_HASH160 PUSH20 <key hash> OP_EQUALVERIFY OP_CHECKSIG.
    return len(spk) == 25 and spk[:3] == b"\x76\xa9\x14" and spk[23:] == b"\x88\xac"


def _is_p2sh(spk: bytes) -> bool:
    # P2SH commits to a redeem script with HASH160: OP_HASH160 PUSH20 <hash> OP_EQUAL.
    return len(spk) == 23 and spk[:2] == b"\xa9\x14" and spk[22] == 0x87


def _is_p2wpkh(spk: bytes) -> bool:
    # A v0 witness program is OP_0 followed by a 20-byte public-key hash.
    return len(spk) == 22 and spk[:2] == b"\x00\x14"


def _is_p2tr(spk: bytes) -> bool:
    # A v1 witness program is OP_1 followed by a 32-byte x-only output key.
    return len(spk) == 34 and spk[:2] == b"\x51\x20"


def _direct_pushes(script: bytes) -> list[bytes]:
    """Return the data pushed by a script made only of direct pushes (1..75 bytes).

    Returns an empty list if the script contains any other opcode.
    """
    pushes: list[bytes] = []
    i = 0
    while i < len(script):
        # In the supported P2PKH templates, each item fits in one direct-push
        # opcode (for example, 0x47 <71-byte signature>). Other opcodes require
        # full script execution, so do not interpret them as simple data pushes.
        length = script[i]
        if not 1 <= length <= 75 or i + 1 + length > len(script):
            return []
        pushes.append(script[i + 1 : i + 1 + length])
        i += 1 + length
    return pushes


def _parse_pubkey(pubkey: bytes) -> PublicKey | None:
    try:
        return PublicKey.parse(pubkey)
    except Exception:
        return None


def _ecdsa_verdict(
    tx: Transaction,
    index: int,
    script_code: Script,
    value: int,
    sig_with_type: bytes,
    pubkey: bytes,
    legacy: bool,
) -> InputVerdict:
    """Verify an ECDSA signature. A malformed signature or key is consensus-invalid."""
    pub = _parse_pubkey(pubkey)
    if pub is None or not sig_with_type:
        return InputVerdict.invalid
    # Bitcoin appends the sighash flag to the DER-encoded ECDSA signature, e.g.
    # DER(r, s) || 0x01 for SIGHASH_ALL. embit rejects undefined ECDSA base modes
    # such as 0x04, although consensus treats them as SIGHASH_ALL. This verifier
    # intentionally accepts that narrow false-negative edge case to use embit's
    # standard sighash parser instead of maintaining a second implementation.
    sighash = sig_with_type[-1]
    try:
        # libsecp256k1 rejects high-S signatures that consensus accepts, so normalize first.
        compact = secp256k1.ecdsa_signature_parse_der(sig_with_type[:-1])
        sig = Signature(secp256k1.ecdsa_signature_normalize(compact))
    except Exception:
        return InputVerdict.invalid
    msg = (
        tx.sighash_legacy(index, script_code, sighash)
        if legacy
        else tx.sighash_segwit(index, script_code, value, sighash)
    )
    return InputVerdict.valid if pub.verify(sig, msg) else InputVerdict.invalid


def _verify_p2pkh(tx: Transaction, index: int, prevout: Prevout, script_sig: bytes) -> InputVerdict:
    # The standard unlocking script is exactly: <signature+sighash> <public key>.
    pushes = _direct_pushes(script_sig)
    if len(pushes) != 2:
        return InputVerdict.invalid
    sig_with_type, pubkey = pushes
    if hash160(pubkey) != prevout.script_pubkey[3:23]:
        return InputVerdict.invalid
    return _ecdsa_verdict(
        tx, index, Script(prevout.script_pubkey), prevout.value, sig_with_type, pubkey, legacy=True
    )


def _verify_p2wpkh(
    tx: Transaction, index: int, prevout: Prevout, witness: list[bytes], pubkey_hash: bytes
) -> InputVerdict:
    # Witness items have the same logical pair as P2PKH's scriptSig, but are
    # serialized separately: [signature+sighash, public key].
    if len(witness) != 2:
        return InputVerdict.invalid
    sig_with_type, pubkey = witness
    if hash160(pubkey) != pubkey_hash:
        return InputVerdict.invalid
    # BIP143 scriptCode for P2WPKH is the P2PKH script of the key hash.
    script_code = Script(b"\x76\xa9\x14" + pubkey_hash + b"\x88\xac")
    return _ecdsa_verdict(tx, index, script_code, prevout.value, sig_with_type, pubkey, legacy=False)


def _verify_p2sh_p2wpkh(
    tx: Transaction, index: int, prevout: Prevout, script_sig: bytes, witness: list[bytes]
) -> InputVerdict:
    # Nested SegWit keeps the P2SH commitment in the prevout and pushes its
    # witness program in scriptSig, e.g. <0x00 0x14 <20-byte key hash>>.
    # A 0x00 0x20 program means nested P2WSH and is routed to its multisig checker.
    pushes = _direct_pushes(script_sig)
    if not pushes:
        return InputVerdict.unchecked
    redeem_script = pushes[-1]
    is_nested_witness = (len(redeem_script) == 22 and redeem_script[:2] == b"\x00\x14") or (
        len(redeem_script) == 34 and redeem_script[:2] == b"\x00\x20"
    )
    if not is_nested_witness:
        return InputVerdict.unchecked
    if hash160(redeem_script) != prevout.script_pubkey[2:22]:
        return InputVerdict.invalid
    if len(redeem_script) != 22 or redeem_script[:2] != b"\x00\x14":
        if len(pushes) != 1:
            return InputVerdict.invalid
        return _verify_p2wsh(tx, index, prevout, witness, redeem_script[2:])
    if len(pushes) != 1:
        return InputVerdict.invalid
    return _verify_p2wpkh(tx, index, prevout, witness, redeem_script[2:])


def _parse_multisig_script(script: bytes) -> tuple[int, list[bytes]] | None:
    """Parse standard OP_m <pubkeys...> OP_n OP_CHECKMULTISIG, e.g. 2-of-3."""
    if len(script) < 3 or not 0x51 <= script[0] <= 0x60 or script[-1] != 0xAE:
        return None
    required = script[0] - 0x50
    count_opcode = script[-2]
    if not 0x51 <= count_opcode <= 0x60:
        return None
    key_count = count_opcode - 0x50
    if not 1 <= required <= key_count:
        return None

    pubkeys: list[bytes] = []
    cursor = 1
    while cursor < len(script) - 2:
        length = script[cursor]
        if length not in (33, 65) or cursor + 1 + length > len(script) - 2:
            return None
        pubkey = script[cursor + 1 : cursor + 1 + length]
        if _parse_pubkey(pubkey) is None:
            return None
        pubkeys.append(pubkey)
        cursor += 1 + length
    if cursor != len(script) - 2 or len(pubkeys) != key_count:
        return None
    return required, pubkeys


def _verify_p2wsh(
    tx: Transaction, index: int, prevout: Prevout, witness: list[bytes], witness_script_hash: bytes
) -> InputVerdict:
    # The last witness item is the script itself; the witness program commits to
    # SHA256(script). Only the standard multisig form is interpreted below.
    if not witness:
        return InputVerdict.invalid
    witness_script = witness[-1]
    if sha256(witness_script) != witness_script_hash:
        return InputVerdict.invalid
    parsed_script = _parse_multisig_script(witness_script)
    if parsed_script is None:
        return InputVerdict.unchecked
    required, pubkeys = parsed_script
    stack = witness[:-1]
    if len(stack) != required + 1 or stack[0] != b"":
        return InputVerdict.invalid

    # CHECKMULTISIG matches signatures to pubkeys in script order. For a 2-of-3
    # script with keys [A, B, C], signatures for A and C match while B is skipped.
    script_code = Script(witness_script)
    key_index = 0
    for sig_with_type in stack[1:]:
        matched = False
        while key_index < len(pubkeys):
            verdict = _ecdsa_verdict(
                tx, index, script_code, prevout.value, sig_with_type, pubkeys[key_index], legacy=False
            )
            key_index += 1
            if verdict is InputVerdict.valid:
                matched = True
                break
        if not matched:
            return InputVerdict.invalid
    return InputVerdict.valid


def _verify_p2tr_keypath(
    tx: Transaction, index: int, prevouts: list[Prevout], witness: list[bytes]
) -> InputVerdict:
    """Verify a BIP341 key-path spend. The sighash commits to every prevout of the transaction."""
    # BIP341 annexes are optional and, when present, are the final item beginning
    # with 0x50. Remove it before deciding whether this is key-path or script-path.
    annex = None
    if len(witness) == 2 and witness[-1].startswith(b"\x50"):
        annex = witness[-1]
        witness = witness[:1]
    if len(witness) > 1:
        return InputVerdict.unchecked  # taproot script-path spend
    if not witness or len(witness[0]) not in (64, 65):
        return InputVerdict.invalid
    sig_bytes = witness[0]
    # A 64-byte Schnorr signature implies DEFAULT; a 65-byte form appends an
    # explicit sighash flag (which may not be DEFAULT/zero).
    if len(sig_bytes) == 64:
        sighash = SIGHASH.DEFAULT
    else:
        sighash = sig_bytes[64]
        if sighash == SIGHASH.DEFAULT:
            return InputVerdict.invalid  # BIP341: an explicit 0x00 sighash byte is not allowed
    try:
        output_key = PublicKey.from_xonly(prevouts[index].script_pubkey[2:34])
    except Exception:
        return InputVerdict.invalid
    msg = tx.sighash_taproot(
        index,
        [Script(p.script_pubkey) for p in prevouts],
        [p.value for p in prevouts],
        sighash,
        annex=annex,
    )
    return (
        InputVerdict.valid
        if output_key.schnorr_verify(SchnorrSig(sig_bytes[:64]), msg)
        else InputVerdict.invalid
    )


def _verify_input(tx: Transaction, index: int, prevouts: list[Prevout | None]) -> InputVerdict:
    # A prevout is the exact output being spent. Its script selects the
    # verification template; without it, there is no trustworthy sighash context.
    prevout = prevouts[index]
    if prevout is None:
        return InputVerdict.unchecked
    tx_input = tx.vin[index]
    witness = list(tx_input.witness.items)
    script_sig = tx_input.script_sig.data

    if _is_p2pkh(prevout.script_pubkey):
        return _verify_p2pkh(tx, index, prevout, script_sig)
    if _is_p2wpkh(prevout.script_pubkey):
        return _verify_p2wpkh(tx, index, prevout, witness, prevout.script_pubkey[2:22])
    if _is_p2sh(prevout.script_pubkey):
        return _verify_p2sh_p2wpkh(tx, index, prevout, script_sig, witness)
    if len(prevout.script_pubkey) == 34 and prevout.script_pubkey[:2] == b"\x00\x20":
        return _verify_p2wsh(tx, index, prevout, witness, prevout.script_pubkey[2:])
    if _is_p2tr(prevout.script_pubkey):
        if any(p is None for p in prevouts):
            return InputVerdict.unchecked  # the taproot sighash needs every prevout
        return _verify_p2tr_keypath(tx, index, [p for p in prevouts if p is not None], witness)
    return InputVerdict.unchecked


def verify_transaction(tx: bdk.Transaction, prevouts: list[Prevout | None]) -> TxVerification:
    """Verify every input of ``tx``.

    ``prevouts`` holds the spent output of each input, in input order, or ``None`` when the
    wallet does not know that output.
    """
    # embit provides the sighash and secp256k1 helpers used here; round-trip the
    # BDK transaction bytes so verification uses the same inputs and outputs.
    embit_tx = Transaction.parse(tx.serialize())
    if len(prevouts) != len(embit_tx.vin):
        return TxVerification(verdicts=[InputVerdict.invalid] * len(embit_tx.vin))
    return TxVerification(
        verdicts=[_verify_input_safely(embit_tx, index, prevouts) for index in range(len(embit_tx.vin))],
    )


def _verify_input_safely(tx: Transaction, index: int, prevouts: list[Prevout | None]) -> InputVerdict:
    """Treat malformed input encodings as invalid instead of aborting transaction processing."""
    try:
        return _verify_input(tx, index, prevouts)
    except Exception:
        return InputVerdict.invalid
