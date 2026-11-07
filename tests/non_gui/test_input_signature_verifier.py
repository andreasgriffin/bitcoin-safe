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

import io

import bdkpython as bdk
import pytest
from embit import hashes
from embit.ec import PrivateKey, Signature
from embit.script import Script
from embit.transaction import SIGHASH, Transaction, TransactionInput, TransactionOutput
from embit.util import secp256k1

from bitcoin_safe.input_signature_verifier import (
    InputVerdict,
    Prevout,
    _normalize_low_s,
    verify_transaction,
)

KEY = PrivateKey(b"\x11" * 32)
OTHER_KEY = PrivateKey(b"\x22" * 32)
VALUE = 100_000
PARENT_TXID = b"\xab" * 32


# Order n of secp256k1, written independently of the implementation under test.
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _der_signature(r: int, s: int) -> bytes:
    compact = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return secp256k1.ecdsa_signature_serialize_der(secp256k1.ecdsa_signature_parse_compact(compact))


def _signature_parts(signature: Signature) -> tuple[int, int]:
    """Read signature scalars without embit's DER parser."""
    stream = io.BytesIO()
    signature.write_to(stream)

    der = stream.getvalue()

    assert der[0] == 0x30
    assert der[1] == len(der) - 2

    r_len = der[3]
    r = int.from_bytes(
        der[4 : 4 + r_len],
        "big",
    )

    s_len = der[5 + r_len]
    s = int.from_bytes(
        der[6 + r_len : 6 + r_len + s_len],
        "big",
    )

    return r, s


def test_high_s_signature_is_normalized_to_low_s() -> None:
    r, high_s = 12345, SECP256K1_N - 1
    assert _signature_parts(_normalize_low_s(_der_signature(r, high_s))) == (r, 1)


def test_low_s_signature_is_unchanged() -> None:
    r, s = 12345, SECP256K1_N // 2
    assert _signature_parts(_normalize_low_s(_der_signature(r, s))) == (r, s)


def test_s_just_above_half_order_is_normalized() -> None:
    r, s = 12345, SECP256K1_N // 2 + 1
    assert _signature_parts(_normalize_low_s(_der_signature(r, s))) == (r, SECP256K1_N // 2)


def _p2pkh_spk(key: PrivateKey) -> Script:
    return Script(b"\x76\xa9\x14" + hashes.hash160(key.get_public_key().sec()) + b"\x88\xac")


def _p2wpkh_spk(key: PrivateKey) -> Script:
    return Script(b"\x00\x14" + hashes.hash160(key.get_public_key().sec()))


def _p2sh_p2wpkh_spk(key: PrivateKey) -> Script:
    redeem = b"\x00\x14" + hashes.hash160(key.get_public_key().sec())
    return Script(b"\xa9\x14" + hashes.hash160(redeem) + b"\x87")


def _p2tr_spk(key: PrivateKey) -> Script:
    return Script(b"\x51\x20" + key.taproot_tweak().get_public_key().xonly())


def _multisig_script(keys: list[PrivateKey]) -> Script:
    pubkeys = [key.get_public_key().sec() for key in keys]
    return Script(
        bytes([0x50 + len(keys)])
        + b"".join(bytes([len(pubkey)]) + pubkey for pubkey in pubkeys)
        + bytes([0x50 + len(keys), 0xAE])
    )


def _p2wsh_spk(witness_script: Script) -> Script:
    return Script(b"\x00\x20" + hashes.sha256(witness_script.data))


def _to_bdk(tx: Transaction) -> bdk.Transaction:
    return bdk.Transaction(tx.serialize())


def _spend(
    spk: Script,
    key: PrivateKey,
    input_kind: str,
    output_value: int = VALUE - 1000,
    sighash: int = SIGHASH.ALL,
) -> tuple[Transaction, list[Prevout]]:
    """Build a one-input transaction that spends ``spk`` and sign it with ``key``.

    Returns the signed transaction and the prevout list the wallet would know.
    """
    dest = _p2wpkh_spk(OTHER_KEY)
    tx = Transaction(
        vin=[TransactionInput(PARENT_TXID, 0)],
        vout=[TransactionOutput(output_value, dest)],
    )
    prevouts = [Prevout(script_pubkey=spk.data, value=VALUE)]
    pub = key.get_public_key()
    if input_kind == "p2pkh":
        msg = tx.sighash_legacy(0, spk, sighash)
        der = key.sign(msg).serialize() + bytes([sighash])
        tx.vin[0].script_sig = Script(bytes([len(der)]) + der + bytes([len(pub.sec())]) + pub.sec())
    elif input_kind == "p2wpkh":
        code = Script(b"\x76\xa9\x14" + hashes.hash160(pub.sec()) + b"\x88\xac")
        msg = tx.sighash_segwit(0, code, VALUE, sighash)
        der = key.sign(msg).serialize() + bytes([sighash])
        tx.vin[0].witness.items = [der, pub.sec()]
    elif input_kind == "p2sh_p2wpkh":
        redeem = b"\x00\x14" + hashes.hash160(pub.sec())
        tx.vin[0].script_sig = Script(bytes([len(redeem)]) + redeem)
        code = Script(b"\x76\xa9\x14" + hashes.hash160(pub.sec()) + b"\x88\xac")
        msg = tx.sighash_segwit(0, code, VALUE, sighash)
        der = key.sign(msg).serialize() + bytes([sighash])
        tx.vin[0].witness.items = [der, pub.sec()]
    elif input_kind == "p2tr":
        tweaked = key.taproot_tweak()
        msg = tx.sighash_taproot(0, [spk], [VALUE], sighash)
        signature = tweaked.schnorr_sign(msg).serialize()
        tx.vin[0].witness.items = [signature if sighash == SIGHASH.DEFAULT else signature + bytes([sighash])]
    else:
        raise ValueError(input_kind)
    return tx, prevouts


def _spend_p2wsh(keys: list[PrivateKey], nested: bool = False) -> tuple[Transaction, list[Prevout]]:
    witness_script = _multisig_script(keys)
    witness_program = _p2wsh_spk(witness_script)
    spk = Script(b"\xa9\x14" + hashes.hash160(witness_program.data) + b"\x87") if nested else witness_program
    tx = Transaction(
        vin=[TransactionInput(PARENT_TXID, 0)],
        vout=[TransactionOutput(VALUE - 1000, _p2wpkh_spk(OTHER_KEY))],
    )
    if nested:
        tx.vin[0].script_sig = Script(bytes([len(witness_program.data)]) + witness_program.data)
    script_code = Script(witness_script.data)
    sigs = [
        key.sign(tx.sighash_segwit(0, script_code, VALUE, SIGHASH.ALL)).serialize() + bytes([SIGHASH.ALL])
        for key in keys
    ]
    tx.vin[0].witness.items = [b"", *sigs, witness_script.data]
    return tx, [Prevout(spk.data, VALUE)]


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
    tx.vin[0].script_sig = Script(b"\x01\x01")
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
    tx.vin[0].script_sig = Script(b"\x01\x01")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_native_p2tr_script_path_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr")
    tx.vin[0].witness.items = [b"script", b"control block"]
    tx.vin[0].script_sig = Script(b"\x01\x01")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_native_p2wsh_rejects_nonempty_script_sig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    tx.vin[0].script_sig = Script(b"\x01\x01")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_valid_nested_p2sh_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], nested=True)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_nested_p2sh_p2wpkh_keeps_redeem_script_sig() -> None:
    tx, prevouts = _spend(_p2sh_p2wpkh_spk(KEY), KEY, "p2sh_p2wpkh")
    assert tx.vin[0].script_sig.data
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


@pytest.mark.parametrize("sighash", [0x01, 0x02, 0x03, 0x81, 0x82, 0x83])
def test_valid_explicit_taproot_sighash_types(sighash: int) -> None:
    tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr", sighash=sighash)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


@pytest.mark.parametrize("sighash", [0x00, 0x80, 0x04, 0x84, 0x7F])
def test_invalid_explicit_taproot_sighash_types(sighash: int) -> None:
    if sighash == 0x80:
        # embit can sign this forbidden type after masking ANYONECANPAY, so test
        # the verifier with an otherwise valid signature for exactly that hash.
        tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr", sighash=sighash)
    else:
        tx, prevouts = _spend(_p2tr_spk(KEY), KEY, "p2tr")
        signature = tx.vin[0].witness.items[0]
        tx.vin[0].witness.items[0] = signature + bytes([sighash])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def _spend_taproot_with_external_input(
    sighash: int, external_prevout: Prevout | None
) -> tuple[Transaction, list[Prevout | None]]:
    wallet_spk = _p2tr_spk(KEY)
    tx = Transaction(
        vin=[TransactionInput(PARENT_TXID, 0), TransactionInput(b"\xcd" * 32, 1)],
        vout=[TransactionOutput(VALUE - 2_000, _p2wpkh_spk(OTHER_KEY))],
    )
    prevouts = [Prevout(wallet_spk.data, VALUE), external_prevout]
    signing_external = external_prevout or Prevout(b"\x00\x14" + b"\x44" * 20, 25_000)
    script_pubkeys = [Script(wallet_spk.data), Script(signing_external.script_pubkey)]
    values = [VALUE, signing_external.value]
    message = tx.sighash_taproot(0, script_pubkeys, values, sighash)
    signature = KEY.taproot_tweak().schnorr_sign(message).serialize()
    tx.vin[0].witness.items = [signature if sighash == SIGHASH.DEFAULT else signature + bytes([sighash])]
    # An external signature is deliberately malformed; this wallet verifier must not
    # claim to validate a participant's input signature.
    tx.vin[1].witness.items = [b"not an external signature"]
    return tx, prevouts


def test_taproot_sighash_uses_known_external_prevout() -> None:
    external = Prevout(_p2wpkh_spk(OTHER_KEY).data, 25_000)
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH.DEFAULT, external)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.valid, InputVerdict.unchecked]


def test_taproot_default_is_unchecked_with_unknown_external_prevout() -> None:
    tx, prevouts = _spend_taproot_with_external_input(SIGHASH.DEFAULT, None)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.unchecked, InputVerdict.unchecked]


def test_taproot_anyonecanpay_allows_unknown_external_prevout() -> None:
    tx, prevouts = _spend_taproot_with_external_input(0x81, None)
    result = verify_transaction(_to_bdk(tx), prevouts, [True, False])
    assert result.verdicts == [InputVerdict.valid, InputVerdict.unchecked]


@pytest.mark.parametrize("input_kind", ["p2pkh", "p2wpkh"])
def test_undefined_ecdsa_sighash_byte_is_not_supported(input_kind: str) -> None:
    """Embit rejects 0x04 although consensus treats its undefined base mode as ALL."""
    spk = _p2pkh_spk(KEY) if input_kind == "p2pkh" else _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, input_kind)
    if input_kind == "p2pkh":
        script_sig = tx.vin[0].script_sig.data
        signature_length = script_sig[0]
        signature = script_sig[1 : signature_length + 1]
        tx.vin[0].script_sig = Script(
            bytes([signature_length]) + signature[:-1] + b"\x04" + script_sig[signature_length + 1 :]
        )
    else:
        signature = tx.vin[0].witness.items[0]
        tx.vin[0].witness.items[0] = signature[:-1] + b"\x04"

    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_tampered_output_is_invalid() -> None:
    """Changing an output after signing invalidates the signature."""
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2wpkh")
    tx.vout[0].value = tx.vout[0].value - 1
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
    """P2WSH is out of scope and must not cause the transaction to be treated as invalid."""
    witness_script = b"\x51"  # OP_TRUE, not the standard multisig template checked here
    spk = Script(b"\x00\x20" + hashes.sha256(witness_script))
    tx = Transaction(vin=[TransactionInput(PARENT_TXID, 0)], vout=[TransactionOutput(1000, _p2wpkh_spk(KEY))])
    tx.vin[0].witness.items = [witness_script]
    verdict = verify_transaction(_to_bdk(tx), [Prevout(spk.data, VALUE)])
    assert verdict.verdicts == [InputVerdict.unchecked]
    assert not verdict.is_invalid


def test_any_invalid_input_makes_tx_invalid() -> None:
    spk = _p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, OTHER_KEY, "p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).is_invalid


def test_malformed_p2wpkh_witness_is_invalid() -> None:
    tx, prevouts = _spend(_p2wpkh_spk(KEY), KEY, "p2wpkh")
    tx.vin[0].witness.items.append(b"extra")
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
        pushes = tx.vin[0].script_sig.data
        signature_length = pushes[0]
        signature = bytearray(pushes[1 : signature_length + 1])
        signature[5] ^= 1
        tx.vin[0].script_sig = Script(
            bytes([signature_length]) + bytes(signature) + pushes[signature_length + 1 :]
        )
    else:
        signature = bytearray(tx.vin[0].witness.items[signature_index])
        signature[5] ^= 1
        tx.vin[0].witness.items[signature_index] = bytes(signature)

    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.invalid]


def test_malformed_multisig_witness_is_invalid() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    tx.vin[0].witness.items.insert(1, b"unexpected")
    assert verify_transaction(_to_bdk(tx), prevouts).is_invalid


# secp256k1 group order, independent of the implementation under test.
SECP256K1_N_TEST = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _test_der_integer(value: int) -> bytes:
    """Encode a nonnegative integer as a DER INTEGER."""
    raw = value.to_bytes(
        max(1, (value.bit_length() + 7) // 8),
        "big",
    )

    # DER integers are signed, so prefix positive values when necessary.
    if raw[0] & 0x80:
        raw = b"\x00" + raw

    return b"\x02" + bytes([len(raw)]) + raw


def _test_der_signature(r: int, s: int) -> bytes:
    """Build a DER signature without using embit's DER parser."""
    body = _test_der_integer(r) + _test_der_integer(s)
    return b"\x30" + bytes([len(body)]) + body


def _test_signature_parts(der: bytes) -> tuple[int, int]:
    """Extract R and S from test-generated DER without using embit."""
    assert der[0] == 0x30
    assert der[1] == len(der) - 2

    r_len = der[3]
    r = int.from_bytes(der[4 : 4 + r_len], "big")

    s_len = der[5 + r_len]
    s = int.from_bytes(
        der[6 + r_len : 6 + r_len + s_len],
        "big",
    )

    return r, s


def _test_make_high_s(sig_with_type: bytes) -> bytes:
    """Convert a low-S transaction signature to equivalent high-S."""
    der = sig_with_type[:-1]
    sighash = sig_with_type[-1:]

    r, s = _test_signature_parts(der)

    assert 1 <= r < SECP256K1_N_TEST
    assert 1 <= s <= SECP256K1_N_TEST // 2

    high_s = SECP256K1_N_TEST - s

    assert high_s > SECP256K1_N_TEST // 2

    return _test_der_signature(r, high_s) + sighash


@pytest.mark.parametrize(
    ("s", "expected_s"),
    [
        (1, 1),
        (SECP256K1_N_TEST // 2, SECP256K1_N_TEST // 2),
        (
            SECP256K1_N_TEST // 2 + 1,
            SECP256K1_N_TEST // 2,
        ),
        (SECP256K1_N_TEST - 1, 1),
    ],
)
def test_low_s_normalization_boundaries(
    s: int,
    expected_s: int,
) -> None:
    """Check low-S normalization at important boundaries."""
    r = 12345

    der = _test_der_signature(r, s)

    normalized = _normalize_low_s(der)

    actual_r, actual_s = _test_signature_parts(normalized.serialize())

    assert actual_r == r
    assert actual_s == expected_s


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
        # Negative R.
        b"\x30\x06\x02\x01\x80\x02\x01\x01",
        # Negative S.
        b"\x30\x06\x02\x01\x01\x02\x01\x80",
        # Non-minimal R.
        b"\x30\x07\x02\x02\x00\x01\x02\x01\x01",
        # Non-minimal S.
        b"\x30\x07\x02\x01\x01\x02\x02\x00\x01",
        # Trailing garbage.
        b"\x30\x06\x02\x01\x01\x02\x01\x01\x00",
        # R outside secp256k1 range.
        _test_der_signature(SECP256K1_N_TEST, 1),
        # S outside secp256k1 range.
        _test_der_signature(1, SECP256K1_N_TEST),
    ],
)
def test_low_s_normalization_rejects_invalid_der(
    bad_der: bytes,
) -> None:
    """Invalid ECDSA signatures must not pass transaction verification."""

    # Create a valid signed P2WPKH transaction.
    tx, prevouts = _spend(
        _p2wpkh_spk(KEY),
        KEY,
        "p2wpkh",
    )

    # Replace its valid signature with the invalid DER encoding.
    # Append SIGHASH_ALL, as required by Bitcoin transactions.
    tx.vin[0].witness.items[0] = bad_der + b"\x01"

    # Verify the complete transaction.
    result = verify_transaction(
        _to_bdk(tx),
        prevouts,
    )

    assert result.verdicts == [InputVerdict.invalid]
