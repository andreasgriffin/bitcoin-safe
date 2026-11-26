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

import json

import bdkpython as bdk
import pytest
from btclib.tx import TxOut as BtclibTxOut
from btclib_wallet.psbt import Psbt, PsbtIn, miniscript_sizer

from bitcoin_safe.psbt_util import (
    FeeInfo,
    InputWeight,
    PubKeyInfo,
    SigningInput,
    TxWeight,
    analyze_signing_inputs,
    psbt_input_utxos,
    psbt_is_finalized,
    psbt_prev_txouts,
    read_psbt,
)
from bitcoin_safe.pythonbdk_types import OutPoint
from tests.non_gui.test_psbt_util import (
    electrum_psbt,
    mixed_inputs_finalized_and_partially_signed_psbt,
    p2sh_0_2of3,
    p2sh_1_2of3,
    p2sh_2_2of3,
    p2wsh_psbt_0_1of1,
    p2wsh_psbt_0_2of2,
    p2wsh_psbt_0_2of3,
    p2wsh_psbt_1_1of1,
    p2wsh_psbt_1_2of3,
    psbt_sparrow_2of2,
    tr_psbt_singlesig,
)


@pytest.mark.parametrize(
    "original",
    [
        electrum_psbt,
        mixed_inputs_finalized_and_partially_signed_psbt,
        p2sh_0_2of3,
        p2sh_1_2of3,
        p2sh_2_2of3,
        p2wsh_psbt_0_1of1,
        p2wsh_psbt_0_2of2,
        p2wsh_psbt_0_2of3,
        p2wsh_psbt_1_1of1,
        p2wsh_psbt_1_2of3,
        psbt_sparrow_2of2,
        tr_psbt_singlesig,
    ],
)
def test_upstream_projection_preserves_legacy_display(original: bdk.Psbt) -> None:
    psbt = bdk.Psbt(original.serialize())
    before = psbt.serialize()
    data = json.loads(psbt.json_serialize())
    native = read_psbt(psbt)
    actual = analyze_signing_inputs(psbt)
    assert len(native.outputs) == len(data["outputs"])
    for got, expected, unsigned in zip(
        native.outputs, data["outputs"], data["unsigned_tx"]["output"], strict=True
    ):
        assert got.amount == unsigned["value"]
        assert got.script_pub_key.hex() == unsigned["script_pubkey"]
        assert got.witness_script.hex() == (expected.get("witness_script") or "")
        assert got.redeem_script.hex() == (expected.get("redeem_script") or "")
        assert got.taproot_internal_key.hex() == (expected.get("tap_internal_key") or "")
        assert [key.hex() for key in got.hd_key_paths] == [
            key for key, _ in expected.get("bip32_derivation", [])
        ]
    assert len(actual) == len(data["inputs"])
    for got, expected in zip(actual, data["inputs"], strict=True):
        prev = expected.get("witness_utxo")
        if prev is None and expected.get("non_witness_utxo"):
            prev = expected["non_witness_utxo"]["output"][got.outpoint.vout]
        out = got.previous_txout()
        if prev is None:
            assert out is None
        else:
            assert out is not None
            assert out.value.to_sat() == prev["value"]
            assert out.spk_hex == prev["script_pubkey"]
        assert got.source.final_script_sig.hex() == (expected.get("final_script_sig") or "")
        assert [item.hex() for item in got.source.final_script_witness.stack] == (
            expected.get("final_script_witness") or []
        )
        if not got.is_fully_signed():
            for key, sig in expected.get("partial_sigs", {}).items():
                displayed = got.signature_for_pubkey(PubKeyInfo("", key))
                assert displayed is not None
                assert displayed.signature == sig["signature"]
                assert displayed.sighash_type == sig["sighash_type"]
        for key, (fingerprint, _) in expected.get("bip32_derivation", []):
            assert any(k.pubkey == key and k.fingerprint == fingerprint.upper() for k in got.pubkeys)
    assert psbt.serialize() == before


def test_simple_psbt_does_not_require_fee_or_bdk_json(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = Psbt.b64decode(p2wsh_psbt_0_2of3.serialize(), check_validity=False)
    parsed.inputs[0].witness_utxo = None
    parsed.inputs[0].non_witness_utxo = None
    parsed.unknown[b"\xfc\x01x\x01"] = b"global metadata"
    parsed.inputs[0].unknown[b"\xfc\x01x\x02"] = b"input metadata"
    parsed.outputs[0].unknown[b"\xfc\x01x\x03"] = b"output metadata"
    psbt = bdk.Psbt(parsed.b64encode(check_validity=False))
    before = psbt.serialize()

    def unexpected_json(*args, **kwargs):
        pytest.fail("typed PSBT projection must not depend on BDK JSON")

    monkeypatch.setattr(bdk.Psbt, "json_serialize", unexpected_json)
    simple = analyze_signing_inputs(psbt)
    assert simple[0].previous_txout() is None
    assert simple[0].source.unknown[b"\xfc\x01x\x02"] == b"input metadata"
    assert read_psbt(psbt).outputs[0].unknown[b"\xfc\x01x\x03"] == b"output metadata"
    assert simple[0].m_of_n == (2, 3)
    assert len(read_psbt(psbt).outputs) == 2
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    assert psbt.serialize() == before


def test_upstream_decode_refusal_is_not_silently_reinterpreted(monkeypatch: pytest.MonkeyPatch) -> None:
    psbt = bdk.Psbt(p2wsh_psbt_0_2of3.serialize())
    before = psbt.serialize()

    def refuse(*args, **kwargs):
        raise ValueError("upstream cannot decode")

    monkeypatch.setattr(Psbt, "b64decode", refuse)
    with pytest.raises(ValueError, match="upstream cannot decode"):
        analyze_signing_inputs(psbt)
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    assert psbt.serialize() == before


def test_negative_fee_is_not_displayed() -> None:
    parsed = Psbt.b64decode(p2wsh_psbt_0_2of3.serialize(), check_validity=False)
    previous = parsed.inputs[0].witness_utxo
    assert previous is not None
    parsed.outputs[0].amount = previous.value + 1
    psbt = bdk.Psbt(parsed.b64encode(check_validity=False))
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None


def test_finalized_fee_matches_extracted_transaction() -> None:
    psbt = bdk.Psbt(p2wsh_psbt_1_1of1.serialize())
    actual = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert actual is not None
    assert not actual.vsize_is_estimated
    assert not actual.fee_amount_is_estimated
    assert actual.fee_amount == psbt.fee()
    assert actual.vsize == psbt.extract_tx_unchecked_fee_rate().vsize()


def test_mixed_finalized_and_partial_fee_is_still_estimated() -> None:
    psbt = bdk.Psbt(mixed_inputs_finalized_and_partially_signed_psbt.serialize())
    before = psbt.serialize()
    info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert info is not None
    assert info.vsize_is_estimated
    assert not info.fee_amount_is_estimated
    assert info.fee_amount == psbt.fee()
    assert info.vsize >= psbt.extract_tx_unchecked_fee_rate().vsize()
    assert psbt.serialize() == before


@pytest.mark.parametrize("n", [0, 1, 252, 253])
def test_draft_weight_input_count_boundary(n: int) -> None:
    # Independently calculated for empty output list and 68-vB native
    # SegWit inputs (41 stripped bytes, 108 witness bytes).
    count_size = 1 if n < 253 else 3
    expected = 4 * (8 + count_size + 1 + 41 * n) + (2 + 108 * n if n else 0)
    assert TxWeight([InputWeight()] * n, []).estimate() == expected


def test_conflicting_utxo_refuses_fee_estimate() -> None:
    from bitcoin_safe.psbt_util import previous_output, previous_txout

    parsed = Psbt.b64decode(p2wsh_psbt_0_2of3.serialize(), check_validity=False)
    inp = parsed.inputs[0]
    previous = inp.witness_utxo
    assert previous is not None
    assert previous_txout(inp) is not None
    inp.witness_utxo = BtclibTxOut(previous.value + 1, previous.script_pub_key)
    psbt = bdk.Psbt(parsed.b64encode(check_validity=False))
    before = psbt.serialize()
    with pytest.raises(ValueError, match="Conflicting PSBT UTXO metadata"):
        previous_output(inp, inp.prev_out.vout)
    assert previous_txout(inp) is None
    assert not psbt_prev_txouts(parsed)
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    assert psbt.serialize() == before


def test_standard_psbt_fee_uses_upstream_estimator(monkeypatch: pytest.MonkeyPatch) -> None:
    psbt = bdk.Psbt(p2wsh_psbt_0_2of3.serialize())
    parsed = Psbt.b64decode(psbt.serialize())
    expected = parsed.vsize_estimate(sizer=miniscript_sizer)

    from bitcoin_safe import psbt_util

    calls = []
    real_sizer = psbt_util.estimated_input_sizes

    def record(inp, txin, **kwargs):
        calls.append(inp)
        return real_sizer(inp, txin, **kwargs)

    monkeypatch.setattr(psbt_util, "estimated_input_sizes", record)
    before = psbt.serialize()
    info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert info is not None
    assert info.vsize == expected
    assert info.fee_amount == psbt.fee()
    assert info.vsize_is_estimated
    assert len(calls) == len(parsed.inputs)
    assert psbt.serialize() == before


@pytest.mark.parametrize("threshold", [2, 17, 20])
def test_multisig_thresholds_above_sixteen(threshold: int) -> None:
    key = bytes.fromhex("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")
    count = bytes([0x50 + threshold]) if threshold <= 16 else bytes([1, threshold])
    script = count + (bytes([len(key)]) + key) * 20 + bytes([1, 20, 0xAE])
    item = SigningInput(PsbtIn(witness_script=script, check_validity=False))
    assert item._get_m_of_n() == (threshold, 20)


def test_native_prevouts_and_finalization_do_not_build_signing_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("protocol-only consumers must not construct signer UI state")

    monkeypatch.setattr("bitcoin_safe.psbt_util.analyze_signing_inputs", unexpected)
    psbt = p2wsh_psbt_0_2of3
    native = read_psbt(psbt)
    tx = psbt.extract_tx_unchecked_fee_rate()
    expected_points = {str(OutPoint.from_bdk(inp.previous_output)) for inp in tx.input()}
    spent = psbt_prev_txouts(native)
    assert set(spent) == expected_points
    utxos = psbt_input_utxos(native, bdk.Network.REGTEST)
    assert set(utxos) == expected_points
    for point, utxo in utxos.items():
        assert str(utxo.outpoint) == point
        assert utxo.txout == spent[point]
    assert not psbt_is_finalized(native)
    assert psbt_is_finalized(read_psbt(p2wsh_psbt_1_1of1))


def test_missing_utxo_does_not_invent_an_outpoint() -> None:
    native = read_psbt(p2wsh_psbt_0_2of3)
    native.inputs[0].witness_utxo = None
    native.inputs[0].non_witness_utxo = None
    assert not psbt_prev_txouts(native)
    assert not psbt_input_utxos(native, bdk.Network.REGTEST)
