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
from btclib_wallet.psbt import Psbt, miniscript_sizer

from bitcoin_safe.psbt_util import FeeInfo, InputWeight, SimpleInput, SimplePSBT, TxWeight
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
    tx = psbt.extract_tx_unchecked_fee_rate()
    data = json.loads(psbt.json_serialize())
    actual = SimplePSBT.from_psbt(psbt)
    assert actual.txid == str(tx.compute_txid())
    assert len(actual.outputs) == len(data["outputs"])
    for got, expected, unsigned in zip(
        actual.outputs, data["outputs"], data["unsigned_tx"]["output"], strict=True
    ):
        assert got.value == unsigned["value"]
        assert got.script_pubkey == unsigned["script_pubkey"]
        assert (got.witness_script or "") == (expected.get("witness_script") or "")
        assert (got.redeem_script or "") == (expected.get("redeem_script") or "")
        assert (got.tap_internal_key or "") == (expected.get("tap_internal_key") or "")
        assert [key.pubkey for key in got.bip32_derivation] == [
            key for key, _ in expected.get("bip32_derivation", [])
        ]
    assert len(actual.inputs) == len(data["inputs"])
    for got, expected in zip(actual.inputs, data["inputs"], strict=True):
        prev = expected.get("witness_utxo")
        if prev is None and expected.get("non_witness_utxo"):
            prev = expected["non_witness_utxo"]["output"][got.txin.previous_output.vout]
        out = got.previous_txout()
        if prev is None:
            assert out is None
        else:
            assert out is not None
            assert out.value.to_sat() == prev["value"]
            assert out.spk_hex == prev["script_pubkey"]
        assert (got.final_script_sig or "") == (expected.get("final_script_sig") or "")
        assert (got.final_script_witness or []) == (expected.get("final_script_witness") or [])
        if not got.is_fully_signed():
            for key, sig in expected.get("partial_sigs", {}).items():
                assert got.partial_sigs[key].signature == sig["signature"]
                assert got.partial_sigs[key].sighash_type == sig["sighash_type"]
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
    simple = SimplePSBT.from_psbt(psbt)
    assert simple.inputs[0].previous_txout() is None
    assert simple.inputs[0].source.unknown[b"\xfc\x01x\x02"] == b"input metadata"
    assert simple.outputs[0].source.unknown[b"\xfc\x01x\x03"] == b"output metadata"
    assert simple.inputs[0].m_of_n == (2, 3)
    assert len(simple.outputs) == 2
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    assert psbt.serialize() == before


def test_upstream_decode_refusal_is_not_silently_reinterpreted(monkeypatch: pytest.MonkeyPatch) -> None:
    psbt = bdk.Psbt(p2wsh_psbt_0_2of3.serialize())
    before = psbt.serialize()

    def refuse(*args, **kwargs):
        raise ValueError("upstream cannot decode")

    monkeypatch.setattr(Psbt, "b64decode", refuse)
    with pytest.raises(ValueError, match="upstream cannot decode"):
        SimplePSBT.from_psbt(psbt)
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
    parsed = Psbt.b64decode(p2wsh_psbt_0_2of3.serialize(), check_validity=False)
    previous = parsed.inputs[0].witness_utxo
    assert previous is not None
    parsed.inputs[0].witness_utxo = BtclibTxOut(previous.value + 1, previous.script_pub_key)
    psbt = bdk.Psbt(parsed.b64encode(check_validity=False))
    before = psbt.serialize()
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt) is None
    assert psbt.serialize() == before


def test_standard_psbt_fee_uses_upstream_estimator(monkeypatch: pytest.MonkeyPatch) -> None:
    psbt = bdk.Psbt(p2wsh_psbt_0_2of3.serialize())
    parsed = Psbt.b64decode(psbt.serialize())
    expected = parsed.vsize_estimate(sizer=miniscript_sizer)

    def unexpected_fallback(*args, **kwargs):
        pytest.fail("standard PSBT should use upstream sizing")

    monkeypatch.setattr(TxWeight, "from_psbt", unexpected_fallback)
    info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert info is not None
    assert info.vsize == expected
    assert info.fee_amount == psbt.fee()
    assert info.vsize_is_estimated


@pytest.mark.parametrize("threshold", [2, 17, 20])
def test_multisig_thresholds_above_sixteen(threshold: int) -> None:
    key = bytes.fromhex("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")
    count = bytes([0x50 + threshold]) if threshold <= 16 else bytes([1, threshold])
    script = count + (bytes([len(key)]) + key) * 20 + bytes([1, 20, 0xAE])
    item = SimpleInput(txin=tr_psbt_singlesig.extract_tx().input()[0], witness_script=script.hex())
    assert item._get_m_of_n() == (threshold, 20)
