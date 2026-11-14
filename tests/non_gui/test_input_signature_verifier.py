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

from __future__ import annotations

import bdkpython as bdk
import ecc.dsa as dsa
import ecc.ssa as ssa
import pytest
from btclib.hashes import hash160, sha256
from btclib.script import sig_hash as sighash
from btclib.script.taproot import output_prvkey_from_merkle_root
from btclib.script.witness import Witness
from btclib.tx import OutPoint, Tx, TxIn, TxOut

from bitcoin_safe.input_signature_verifier import (
    InputVerdict,
    Prevout,
    verify_transaction,
)

# Keys are plain integers: the secp256k1 scalars used by the helpers below.
KEY = 0x11 * 0x0101010101010101010101010101010101010101010101010101010101010101 % ssa.secp256k1.n
OTHER_KEY = 0x22 * 0x0101010101010101010101010101010101010101010101010101010101010101 % ssa.secp256k1.n
VALUE = 100_000
PARENT_TXID = b"\xab" * 32
SIGHASH_ALL = 1
SIGHASH_DEFAULT = 0
SIGHASH_ANYONECANPAY_ALL = 0x81
SECP256K1_N = ssa.secp256k1.n


def _sec(key: int) -> bytes:
    """Return the compressed public key of ``key``."""
    x, y = dsa.gen_keys(key)[1]
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


def _xonly(key: int) -> bytes:
    """Return the x-only public key of ``key``."""
    return ssa.gen_keys(key)[1].to_bytes(32, "big")


def _ecdsa_sig(msg: bytes, key: int, sighash_type: int) -> bytes:
    """DER-encode an ECDSA signature over ``msg`` and append the sighash byte."""
    return dsa.sign_(msg, key).serialize() + bytes([sighash_type])


def _schnorr_sig(msg: bytes, key: int, sighash_type: int) -> bytes:
    """Sign ``msg`` with the taproot output key of ``key`` (the key-path signer)."""
    output_key = output_prvkey_from_merkle_root(key, b"")
    signature = ssa.sign_(msg, output_key).serialize()
    return signature if sighash_type == SIGHASH_DEFAULT else signature + bytes([sighash_type])


def _p2pkh_spk(key: int) -> bytes:
    return b"\x76\xa9\x14" + hash160(_sec(key)) + b"\x88\xac"


def _p2wpkh_spk(key: int) -> bytes:
    return b"\x00\x14" + hash160(_sec(key))


def _p2sh_p2wpkh_spk(key: int) -> bytes:
    redeem = b"\x00\x14" + hash160(_sec(key))
    return b"\xa9\x14" + hash160(redeem) + b"\x87"


def _p2tr_spk(key: int) -> bytes:
    return b"\x51\x20" + _xonly(output_prvkey_from_merkle_root(key, b""))


def _multisig_script(keys: list[int]) -> bytes:
    pubkeys = [_sec(key) for key in keys]
    return (
        bytes([0x50 + len(keys)])
        + b"".join(bytes([len(pubkey)]) + pubkey for pubkey in pubkeys)
        + bytes([0x50 + len(keys), 0xAE])
    )


def _p2wsh_spk(witness_script: bytes) -> bytes:
    return b"\x00\x20" + sha256(witness_script)


def _to_bdk(tx: Tx) -> bdk.Transaction:
    return bdk.Transaction(tx.serialize(include_witness=True))


def _new_tx(input_count: int = 1, output_value: int = VALUE - 1000) -> Tx:
    return Tx(
        vin=[
            TxIn(OutPoint(PARENT_TXID if i == 0 else bytes([i]) * 32, i), b"", 0xFFFFFFFD)
            for i in range(input_count)
        ],
        vout=[TxOut(output_value, _p2wpkh_spk(OTHER_KEY))],
    )


def _spend(
    spk: bytes,
    key: int,
    input_kind: str,
    output_value: int = VALUE - 1000,
    sighash_type: int = SIGHASH_ALL,
    input_count: int = 1,
) -> tuple[Tx, list[Prevout]]:
    """Build a transaction that spends ``spk`` in input 0 and sign it with ``key``.

    Returns the signed transaction and the prevout list the wallet would know.
    Inputs after 0 are unsigned; they must exist before signing because BIP143 and
    legacy sighashes commit to every input's outpoint and sequence.
    """
    tx = _new_tx(input_count=input_count, output_value=output_value)
    prevouts = [Prevout(script_pubkey=spk, value=VALUE)]
    sec = _sec(key)
    if input_kind == "p2pkh":
        msg = sighash.legacy(spk, tx, 0, sighash_type)
        der = _ecdsa_sig(msg, key, sighash_type)
        tx.vin[0].script_sig = bytes([len(der)]) + der + bytes([len(sec)]) + sec
    elif input_kind == "p2wpkh":
        code = b"\x76\xa9\x14" + hash160(sec) + b"\x88\xac"
        der = _ecdsa_sig(sighash.segwit_v0(code, tx, 0, sighash_type, VALUE), key, sighash_type)
        tx.vin[0].script_witness = Witness([der, sec])
    elif input_kind == "p2sh_p2wpkh":
        redeem = b"\x00\x14" + hash160(sec)
        tx.vin[0].script_sig = bytes([len(redeem)]) + redeem
        code = b"\x76\xa9\x14" + hash160(sec) + b"\x88\xac"
        der = _ecdsa_sig(sighash.segwit_v0(code, tx, 0, sighash_type, VALUE), key, sighash_type)
        tx.vin[0].script_witness = Witness([der, sec])
    elif input_kind == "p2tr":
        msg = sighash.taproot(tx, 0, [TxOut(VALUE, spk)], sighash_type, 0, b"", b"")
        tx.vin[0].script_witness = Witness([_schnorr_sig(msg, key, sighash_type)])
    else:
        raise ValueError(input_kind)
    return tx, prevouts


def _spend_p2wsh(keys: list[int], nested: bool = False, input_count: int = 1) -> tuple[Tx, list[Prevout]]:
    witness_script = _multisig_script(keys)
    witness_program = _p2wsh_spk(witness_script)
    spk = b"\xa9\x14" + hash160(witness_program) + b"\x87" if nested else witness_program
    tx = _new_tx(input_count=input_count)
    if nested:
        tx.vin[0].script_sig = bytes([len(witness_program)]) + witness_program
    sigs = [
        _ecdsa_sig(sighash.segwit_v0(witness_script, tx, 0, SIGHASH_ALL, VALUE), key, SIGHASH_ALL)
        for key in keys
    ]
    tx.vin[0].script_witness = Witness([b"", *sigs, witness_script])
    return tx, [Prevout(spk, VALUE)]


def test_valid_p2pkh() -> None:
    spk = _p2pkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2pkh")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_p2wpkh() -> None:
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_native_p2wpkh_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh")
    tx.vin[0].script_sig = b"\x01\x01"
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_p2sh_p2wpkh() -> None:
    spk = _p2sh_p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2sh_p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_p2tr_keypath() -> None:
    spk = _p2tr_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2tr")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_native_p2tr_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr")
    tx.vin[0].script_sig = b"\x01\x01"
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_native_p2tr_script_path_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr")
    tx.vin[0].script_witness = Witness([b"script", b"control block"])
    tx.vin[0].script_sig = b"\x01\x01"
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_native_p2wsh_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    tx.vin[0].script_sig = b"\x01\x01"
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_nested_p2sh_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], nested=True)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_nested_p2sh_p2wpkh_keeps_redeem_script_sig() -> None:
    tx, prevouts = _spend(_p2sh_p2wpkh_spk(KEY), KEY, "p2sh_p2wpkh")
    assert tx.vin[0].scriptSig
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


@pytest.mark.parametrize("sighash_type", [0x01, 0x02, 0x03, 0x81, 0x82, 0x83])
def test_valid_explicit_taproot_sighash_types(sighash_type: int) -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr", sighash_type=sighash_type)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


@pytest.mark.parametrize("sighash_type", [0x00, 0x80, 0x04, 0x84, 0x7F])
def test_invalid_explicit_taproot_sighash_types(sighash_type: int) -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr")
    signature = tx.vin[0].script_witness.stack[0]
    tx.vin[0].script_witness = Witness([signature + bytes([sighash_type])])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def _spend_taproot_with_external_input(
    sighash_type: int, external_prevout: Prevout | None
) -> tuple[Tx, list[Prevout | None]]:
    wallet_spk = _p2tr_spk(KEY)
    tx = Tx(
        vin=[
            TxIn(OutPoint(PARENT_TXID, 0), b"", 0xFFFFFFFD),
            TxIn(OutPoint(b"\xcd" * 32, 1), b"", 0xFFFFFFFD),
        ],
        vout=[TxOut(VALUE - 2_000, _p2wpkh_spk(OTHER_KEY))],
    )
    prevouts = [Prevout(wallet_spk, VALUE), external_prevout]
    signing_external = external_prevout or Prevout(b"\x00\x14" + b"\x44" * 20, 25_000)
    message = sighash.taproot(
        tx,
        0,
        [TxOut(VALUE, wallet_spk), TxOut(signing_external.value, signing_external.script_pubkey)],
        sighash_type,
        0,
        b"",
        b"",
    )
    tx.vin[0].script_witness = Witness([_schnorr_sig(message, KEY, sighash_type)])
    # An external signature is deliberately malformed; this wallet verifier must not
    # claim to validate a participant's input signature.
    tx.vin[1].script_witness = Witness([b"not an external signature"])
    return tx, prevouts


def test_taproot_sighash_uses_known_external_prevout() -> None:
    external = Prevout(_p2wpkh_spk(OTHER_KEY), 25_000)
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH_DEFAULT, external)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.valid, InputVerdict.unchecked]


def test_taproot_default_is_unchecked_with_unknown_external_prevout() -> None:
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH_DEFAULT, None)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.unchecked, InputVerdict.unchecked]


def test_taproot_anyonecanpay_allows_unknown_external_prevout() -> None:
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH_ANYONECANPAY_ALL, None)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.valid, InputVerdict.unchecked]


def test_taproot_anyonecanpay_ignores_unknown_sibling_value_and_script() -> None:
    """The placeholder sibling must not influence an ANYONECANPAY sighash."""
    external = Prevout(_p2wpkh_spk(OTHER_KEY), 25_000)
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH_ANYONECANPAY_ALL, external)
    other = Prevout(_p2wpkh_spk(OTHER_KEY), 99_999)
    prevouts_with_other_sibling = [prevouts[0], other]
    assert verify_transaction(_to_bdk(tx), prevouts_with_other_sibling, [True, False]).verdicts == [
        InputVerdict.valid,
        InputVerdict.unchecked,
    ]


@pytest.mark.parametrize("input_kind", ["p2pkh", "p2wpkh"])
def test_undefined_ecdsa_sighash_byte_is_valid(input_kind: str) -> None:
    """Consensus hashes undefined ECDSA base types as SIGHASH_ALL, so 0x04 must verify.

    Regression: a previous verifier rejected such signatures although consensus accepts them.
    """
    spk = _p2pkh_spk(KEY) if input_kind == "p2pkh" else _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, input_kind, sighash_type=0x04)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


@pytest.mark.parametrize("input_kind", ["p2pkh", "p2wpkh"])
def test_high_s_ecdsa_signature_is_valid(input_kind: str) -> None:
    """Consensus accepts high-S signatures, so they must verify (low-S is policy only)."""
    spk = _p2pkh_spk(KEY) if input_kind == "p2pkh" else _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, input_kind)
    if input_kind == "p2pkh":
        script_sig = tx.vin[0].scriptSig
        length = script_sig[0]
        der, sighash_type = script_sig[1:length], script_sig[length : length + 1]
        high = _high_s_der(der)
        tx.vin[0].script_sig = bytes([len(high) + 1]) + high + sighash_type + script_sig[length + 1 :]
    else:
        der = tx.vin[0].script_witness.stack[0]
        tx.vin[0].script_witness = Witness(
            [_high_s_der(der[:-1]) + der[-1:], tx.vin[0].script_witness.stack[1]]
        )
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def _high_s_der(der: bytes) -> bytes:
    """Return the same ECDSA signature with S replaced by n - S (the high-S form)."""
    r_length = der[3]
    r = int.from_bytes(der[4 : 4 + r_length], "big")
    s_length = der[5 + r_length]
    s = int.from_bytes(der[6 + r_length : 6 + r_length + s_length], "big")
    high_s = SECP256K1_N - s
    assert high_s > SECP256K1_N // 2
    return dsa.Sig(r, high_s).serialize()


def test_tampered_output_is_invalid() -> None:
    """Changing an output after signing invalidates the signature."""
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2wpkh")
    tx.vout = [TxOut(tx.vout[0].value - 1, tx.vout[0].script_pub_key)]
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_wrong_key_is_invalid() -> None:
    """A signature from a key that does not own the prevout is rejected."""
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, OTHER_KEY, "p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_unknown_prevout_is_unchecked() -> None:
    spk = _p2wpkh_spk(KEY)
    tx, _ = _spend(spk, KEY, "p2wpkh")
    assert verify_transaction(_to_bdk(tx), [None]).verdicts == [InputVerdict.unchecked]


def test_unsupported_script_is_unchecked_not_invalid() -> None:
    """A witness script that runs without checking a signature is not proof of validity.

    OP_TRUE executes successfully and checks no signature, so it must stay unchecked
    and must not cause the transaction to be treated as invalid.
    """
    witness_script = b"\x51"  # OP_TRUE
    spk = _p2wsh_spk(witness_script)
    tx = _new_tx()
    tx.vin[0].script_witness = Witness([witness_script])
    verdict = verify_transaction(_to_bdk(tx), [Prevout(spk, VALUE)])
    assert verdict.verdicts == [InputVerdict.unchecked]
    assert not verdict.is_invalid


def test_failing_p2wsh_script_is_invalid() -> None:
    """A witness script that the engine refuses makes the input invalid."""
    witness_script = b"\x00"  # OP_0 leaves a false top stack element
    spk = _p2wsh_spk(witness_script)
    tx = _new_tx()
    tx.vin[0].script_witness = Witness([witness_script])
    assert verify_transaction(_to_bdk(tx), [Prevout(spk, VALUE)]).verdicts == [InputVerdict.invalid]


def test_any_invalid_input_makes_tx_invalid() -> None:
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, OTHER_KEY, "p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).is_invalid


def test_malformed_p2wpkh_witness_is_invalid() -> None:
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh")
    tx.vin[0].script_witness = Witness([*tx.vin[0].script_witness.stack, b"extra"])
    assert verify_transaction(_to_bdk(tx), prevouts).is_invalid


@pytest.mark.parametrize("input_kind", ["p2pkh", "p2wpkh", "p2sh_p2wpkh", "p2tr", "p2wsh", "p2sh_p2wsh"])
def test_tampered_signature_is_invalid_for_supported_input_types(input_kind: str) -> None:
    if input_kind in ("p2wsh", "p2sh_p2wsh"):
        tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], nested=input_kind == "p2sh_p2wsh")
        signature_index = 1  # Witness item zero is CHECKMULTISIG's historical dummy.
    else:
        prevout_script = {
            "p2pkh": _p2pkh_spk(KEY),
            "p2wpkh": _p2wpkh_spk(KEY),
            "p2sh_p2wpkh": _p2sh_p2wpkh_spk(KEY),
            "p2tr": _p2tr_spk(KEY),
        }[input_kind]
        tx, prevouts = _spend(prevout_script, KEY, input_kind)
        signature_index = 0

    if input_kind == "p2pkh":
        pushes = tx.vin[0].scriptSig
        signature_length = pushes[0]
        signature = bytearray(pushes[1 : signature_length + 1])
        signature[5] ^= 1
        tx.vin[0].script_sig = bytes([signature_length]) + bytes(signature) + pushes[signature_length + 1 :]
    else:
        stack = list(tx.vin[0].script_witness.stack)
        signature = bytearray(stack[signature_index])
        signature[5] ^= 1
        stack[signature_index] = bytes(signature)
        tx.vin[0].script_witness = Witness(stack)

    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_malformed_multisig_witness_is_invalid() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    stack = list(tx.vin[0].script_witness.stack)
    stack.insert(1, b"unexpected")
    tx.vin[0].script_witness = Witness(stack)
    assert verify_transaction(_to_bdk(tx), prevouts).is_invalid


@pytest.mark.parametrize(
    "bad_der",
    [
        b"",
        # Incorrect sequence tag.
        b"\x31\x06\x02\x01\x01\x02\x01\x01",
        # Incorrect sequence length.
        b"\x30\x05\x02\x01\x01\x02\x01\x01",
        # Zero R.
        b"\x30\x06\x02\x01\x00\x02\x01\x01",
        # Zero S.
        b"\x30\x06\x02\x01\x01\x02\x01\x00",
        # Non-minimal R.
        b"\x30\x07\x02\x02\x00\x01\x02\x01\x01",
    ],
)
def test_malformed_der_signature_is_invalid(bad_der: bytes) -> None:
    """Invalid ECDSA encodings must not pass transaction verification."""
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh")
    # Replace the valid signature with the malformed DER, keeping SIGHASH_ALL.
    tx.vin[0].script_witness = Witness([bad_der + b"\x01", tx.vin[0].script_witness.stack[1]])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_p2wpkh_with_unknown_external_sibling() -> None:
    """Legacy and SegWit v0 sighashes read only their own prevout, so an unknown sibling is fine."""
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh", input_count=2)
    assert verify_transaction(_to_bdk(tx), [prevouts[0], None], [True, False]).verdicts == [
        InputVerdict.valid,
        InputVerdict.unchecked,
    ]


def test_valid_p2pkh_with_unknown_external_sibling() -> None:
    tx, prevouts = _spend(_p2pkh_spk(KEY), KEY, "p2pkh", input_count=2)
    assert verify_transaction(_to_bdk(tx), [prevouts[0], None], [True, False]).verdicts == [
        InputVerdict.valid,
        InputVerdict.unchecked,
    ]


def test_valid_p2wsh_multisig_with_unknown_external_sibling() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], input_count=2)
    assert verify_transaction(_to_bdk(tx), [prevouts[0], None], [True, False]).verdicts == [
        InputVerdict.valid,
        InputVerdict.unchecked,
    ]


def test_invalid_p2wpkh_with_unknown_external_sibling() -> None:
    """A wallet signature over different outputs is rejected even when a sibling prevout is unknown."""
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh", input_count=2)
    tx.vout = [TxOut(tx.vout[0].value - 1, tx.vout[0].script_pub_key)]
    assert verify_transaction(_to_bdk(tx), [prevouts[0], None], [True, False]).verdicts == [
        InputVerdict.invalid,
        InputVerdict.unchecked,
    ]


def test_invalid_p2wsh_multisig_with_unknown_external_sibling() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], input_count=2)
    tx.vout = [TxOut(tx.vout[0].value - 1, tx.vout[0].script_pub_key)]
    assert verify_transaction(_to_bdk(tx), [prevouts[0], None], [True, False]).verdicts == [
        InputVerdict.invalid,
        InputVerdict.unchecked,
    ]
