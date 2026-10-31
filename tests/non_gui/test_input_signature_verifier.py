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
import pytest
from embit import hashes
from embit.ec import PrivateKey
from embit.script import Script
from embit.transaction import SIGHASH, Transaction, TransactionInput, TransactionOutput

from bitcoin_safe.input_signature_verifier import InputVerdict, Prevout, verify_transaction

KEY = PrivateKey(b"\x11" * 32)
OTHER_KEY = PrivateKey(b"\x22" * 32)
VALUE = 100_000
PARENT_TXID = b"\xab" * 32


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
        msg = tx.sighash_taproot(0, [spk], [VALUE], SIGHASH.DEFAULT)
        tx.vin[0].witness.items = [tweaked.schnorr_sign(msg).serialize()]
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


def test_valid_p2sh_p2wpkh() -> None:
    spk = _p2sh_p2wpkh_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2sh_p2wpkh")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_p2tr_keypath() -> None:
    spk = _p2tr_spk(KEY)
    tx, prevouts = _spend(spk, KEY, "p2tr")
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY])
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


def test_valid_nested_p2sh_p2wsh_multisig() -> None:
    tx, prevouts = _spend_p2wsh([KEY, OTHER_KEY], nested=True)
    assert verify_transaction(_to_bdk(tx), prevouts).verdicts == [InputVerdict.valid]


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
