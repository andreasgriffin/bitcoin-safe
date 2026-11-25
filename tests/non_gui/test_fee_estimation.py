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

from typing import cast
from unittest.mock import MagicMock

import bdkpython as bdk
import pytest
from bitcoin_usb.address_types import AddressTypes

from bitcoin_safe.psbt_util import (
    FeeInfo,
    InputWeight,
    TxWeight,
    compact_size_length,
    weight_to_vsize,
)
from tests.non_gui.test_psbt_util import p2wsh_psbt_0_2of3


@pytest.mark.parametrize(
    ("value", "size"),
    [(0, 1), (252, 1), (253, 3), (65535, 3), (65536, 5), (2**32 - 1, 5), (2**32, 9)],
)
def test_compact_size_length(value: int, size: int) -> None:
    assert compact_size_length(value) == size


def test_estimate_accounts_for_script_and_output_count_lengths() -> None:
    base = TxWeight([InputWeight()], [bdk.Script(bytes(22))]).estimate()
    assert TxWeight([InputWeight()], [bdk.Script(bytes(200))]).estimate() - base == 178 * 4
    assert TxWeight([InputWeight()], [bdk.Script(bytes(252))]).estimate() - base == 230 * 4
    assert TxWeight([InputWeight()], [bdk.Script(bytes(253))]).estimate() - base == 233 * 4
    empty_script = bdk.Script(b"")
    assert (
        TxWeight([InputWeight()], [empty_script] * 253).estimate()
        - TxWeight([InputWeight()], [empty_script] * 252).estimate()
        == 11 * 4
    )
    assert TxWeight([InputWeight()], [None]).estimate() == base


def test_psbt_fee_estimate_uses_output_scripts() -> None:
    psbt = p2wsh_psbt_0_2of3
    assert [len(output.script_pubkey.to_bytes()) for output in psbt.extract_tx().output()] == [34, 34]
    estimate = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert estimate.vsize == weight_to_vsize(
        TxWeight(
            [InputWeight((2, 3))], [output.script_pubkey for output in psbt.extract_tx().output()]
        ).estimate()
    )
    assert estimate.fee_amount == psbt.fee()


def test_tx_weight_from_psbt_uses_previous_outputs_and_unknown_fallback() -> None:
    from bitcoin_safe.foreign_utxo import ForeignUtxo
    from tests.non_gui.test_foreign_utxo import transaction

    legacy = transaction([b"\x76\xa9\x14" + bytes(20) + b"\x88\xac"])
    witness = transaction([b"\x00\x14" + bytes(20)])
    witness_input = ForeignUtxo._empty_input(witness.output()[0], None)
    legacy_input = ForeignUtxo._empty_input(legacy.output()[0], legacy)
    legacy_input.witness_utxo = None
    unknown_input = ForeignUtxo._empty_input(witness.output()[0], None)
    unknown_input.witness_utxo = None

    tx = transaction([b"\x51"])
    psbt = MagicMock(spec=bdk.Psbt)
    psbt.extract_tx_unchecked_fee_rate.return_value.input.return_value = tx.input() * 3
    psbt.extract_tx_unchecked_fee_rate.return_value.output.return_value = tx.output()
    psbt.input.return_value = [witness_input, legacy_input, unknown_input]

    estimate = TxWeight.from_psbt(cast(bdk.Psbt, psbt))
    assert [item.address_type for item in estimate.inputs] == [
        AddressTypes.p2wpkh,
        AddressTypes.p2pkh,
        None,
    ]
    assert (
        estimate.estimate()
        == TxWeight(
            [
                InputWeight(address_type=AddressTypes.p2wpkh),
                InputWeight(address_type=AddressTypes.p2pkh),
                InputWeight(),
            ],
            [bdk.Script(b"\x51")],
        ).estimate()
    )


def test_tx_weight_from_inputs_prefers_supplied_weight_and_wallet_descriptor() -> None:
    from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, TxInputInfo, TxOut
    from tests.non_gui.test_foreign_utxo import make_wallet, transaction

    wallet = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "estimation",
    ).bdkwallet
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    utxo = PythonUtxo(
        str(address), OutPoint(txid=funding.compute_txid(), vout=0), TxOut.from_bdk(funding.output()[0])
    )
    estimate = TxWeight.from_inputs(
        [TxInputInfo(utxo), TxInputInfo(utxo, satisfaction_weight=200)], [], wallet
    )
    descriptor = wallet.public_descriptor(bdk.KeychainKind.EXTERNAL)
    expected = InputWeight()
    expected.use_descriptor(descriptor, bdk.Network.REGTEST)
    assert estimate.inputs[0].satisfaction_weight == expected.satisfaction_weight
    assert estimate.inputs[1].satisfaction_weight == 200
    assert TxWeight.from_inputs([], []).inputs == []


def test_tx_weight_from_recipients_handles_change_and_incomplete_drafts() -> None:
    from bitcoin_safe.pythonbdk_types import Recipient
    from tests.non_gui.test_foreign_utxo import make_wallet

    wallet = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "estimation",
    ).bdkwallet
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    recipients = [Recipient(str(address), 100), Recipient("script:6a00", 0), Recipient("script:0", 0)]
    estimate = TxWeight.from_recipients([], recipients, bdk.Network.REGTEST, wallet)
    assert len(estimate.inputs) == 1
    assert estimate.inputs[0].satisfaction_weight is not None
    assert [
        bytes(script.to_bytes()) if script is not None else None for script in estimate.output_scripts
    ] == [
        bytes(address.script_pubkey().to_bytes()),
        bytes.fromhex("6a00"),
        None,
        bytes(wallet.peek_address(bdk.KeychainKind.INTERNAL, 0).address.script_pubkey().to_bytes()),
    ]
    recipients[0].checked_max_amount = True
    without_wallet = TxWeight.from_recipients([], recipients, bdk.Network.REGTEST)
    assert len(without_wallet.output_scripts) == 3
    assert without_wallet.inputs == [InputWeight()]
    assert TxWeight.from_recipients([], [], bdk.Network.REGTEST).output_scripts == [None]


@pytest.mark.parametrize(
    ("wrapper", "address_type", "mn", "legacy"),
    [
        ("pkh({key})", "p2pkh", (1, 1), False),
        ("wpkh({key})", "p2wpkh", (1, 1), False),
        ("sh(wpkh({key}))", "p2sh_p2wpkh", (1, 1), False),
        ("wsh({multi})", "p2wsh", (2, 3), False),
        ("sh(wsh({multi}))", "p2sh_p2wsh", (2, 3), False),
        ("sh({multi})", None, (2, 3), True),
        ("tr({xkey})", "p2tr", (1, 1), False),
    ],
)
def test_input_satisfaction_matches_bdk_descriptor(wrapper, address_type, mn, legacy) -> None:
    from bitcoin_safe_lib.util import network_kind
    from bitcoin_usb.address_types import AddressTypes

    from bitcoin_safe.psbt_util import InputWeight

    keys = [
        "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798",
        "02c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5",
        "02f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9",
    ]
    types = {
        "p2pkh": AddressTypes.p2pkh,
        "p2wpkh": AddressTypes.p2wpkh,
        "p2sh_p2wpkh": AddressTypes.p2sh_p2wpkh,
        "p2wsh": AddressTypes.p2wsh,
        "p2sh_p2wsh": AddressTypes.p2sh_p2wsh,
        "p2tr": AddressTypes.p2tr,
        None: None,
    }
    descriptor = wrapper.format(key=keys[0], xkey=keys[0][2:], multi=f"multi(2,{','.join(keys)})")
    weight = bdk.Descriptor(descriptor, network_kind(bdk.Network.REGTEST)).max_weight_to_satisfy()
    assert InputWeight(mn, types[address_type], legacy_multisig=legacy).weight() == weight


def test_mixed_input_overhead_and_descriptor_weights() -> None:
    from bitcoin_usb.address_types import AddressTypes

    from bitcoin_safe.psbt_util import InputWeight

    legacy = InputWeight(address_type=AddressTypes.p2pkh)
    witness = InputWeight(address_type=AddressTypes.p2wpkh)
    output = [bdk.Script(b"\x51")]
    single_legacy = TxWeight([legacy], output).estimate()
    single_witness = TxWeight([witness], output).estimate()
    mixed = TxWeight([legacy, witness], output).estimate()
    # Adding a legacy input to a witness transaction adds an empty witness byte.
    assert mixed - single_witness == 41 * 4 + legacy.weight() + 1
    assert single_witness - single_legacy == witness.weight() + 3 - legacy.weight()
    assert TxWeight([InputWeight()], output).estimate() == single_witness
    assert TxWeight([InputWeight(satisfaction_weight=150)], output).estimate() == single_witness + 43


@pytest.mark.parametrize("wrapper", ["pkh({key})", "wpkh({key})", "sh(wpkh({key}))", "tr({key})"])
def test_psbt_estimation_and_final_signed_weight(wrapper: str) -> None:
    from tests.non_gui.test_foreign_utxo import transaction

    mnemonic = bdk.Mnemonic.from_string(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    )
    key = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, mnemonic, "")
    receive = bdk.Descriptor(wrapper.format(key=f"{key}/0/*"), bdk.NetworkKind.TEST)
    change = bdk.Descriptor(wrapper.format(key=f"{key}/1/*"), bdk.NetworkKind.TEST)
    wallet = bdk.Wallet(receive, change, bdk.Network.REGTEST, bdk.Persister.new_in_memory())
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    psbt = (
        bdk.TxBuilder()
        .add_utxo(bdk.OutPoint(txid=funding.compute_txid(), vout=0))
        .manually_selected_only()
        .drain_to(address.script_pubkey())
        .finish(wallet)
    )
    tx = psbt.extract_tx_unchecked_fee_rate()
    info = InputWeight.from_psbt_input(funding.output()[0].script_pubkey, psbt.input()[0])
    estimate = TxWeight([info], [output.script_pubkey for output in tx.output()]).estimate()
    viewer_estimate = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert viewer_estimate.vsize == weight_to_vsize(estimate)
    assert wallet.sign(psbt)
    signed = psbt.extract_tx_unchecked_fee_rate()
    assert signed.weight() <= estimate
    actual = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
    assert not actual.vsize_is_estimated
    assert actual.vsize == signed.vsize()


def test_input_types_are_inferred_from_prevout_and_scripts() -> None:
    from bitcoin_usb.address_types import AddressTypes

    from bitcoin_safe.foreign_utxo import ForeignUtxo
    from bitcoin_safe.psbt_util import InputWeight

    output = bdk.TxOut(value=bdk.Amount.from_sat(100_000), script_pubkey=bdk.Script(b"\x00\x14" + bytes(20)))
    inp = ForeignUtxo._empty_input(output, None)
    cases = [
        (b"\x76\xa9\x14" + bytes(20) + b"\x88\xac", b"", AddressTypes.p2pkh, False),
        (b"\x00\x14" + bytes(20), b"", AddressTypes.p2wpkh, False),
        (b"\xa9\x14" + bytes(20) + b"\x87", b"\x00\x14" + bytes(20), AddressTypes.p2sh_p2wpkh, False),
        (b"\x00\x20" + bytes(32), b"", AddressTypes.p2wsh, False),
        (b"\xa9\x14" + bytes(20) + b"\x87", b"\x00\x20" + bytes(32), AddressTypes.p2sh_p2wsh, False),
        (b"\xa9\x14" + bytes(20) + b"\x87", b"\x51\x51\xae", None, True),
        (b"\x51\x20" + bytes(32), b"", AddressTypes.p2tr, False),
    ]
    for script, redeem, address_type, legacy in cases:
        inp.redeem_script = bdk.Script(redeem) if redeem else None
        info = InputWeight.from_psbt_input(bdk.Script(script), inp)
        assert info.address_type == address_type
        assert info.legacy_multisig == legacy
    assert (
        InputWeight.from_psbt_input(None, None).weight()
        == InputWeight(address_type=AddressTypes.p2wpkh).weight()
    )


def test_taproot_weight_uses_signed_leaf_and_final_witness() -> None:
    from hwilib.psbt import PSBT, PartiallySignedInput
    from hwilib.tx import CTxOut

    key = bytes.fromhex("79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")
    key2 = bytes.fromhex("c6047f9441ed7d6d3045406e95c07cd85c778e4b8cef3ca7abac09b95c709ee5")
    key3 = bytes.fromhex("f9308a019258c31049344f85f89d5229b531c845836f99b08601f113bce036f9")
    pk = b"\x20" + key + b"\xac"
    multi_a = pk + b"\x20" + key2 + b"\xba\x20" + key3 + b"\xba\x52\x9c"
    pk_hash = "763e9da064b9dc0471fb0f3c8fa2c84b4b84d2ca992497c12d2274386795aa8e"
    multi_hash = "d98e12c453600f2b11ee3b7c0047b218477e0e328694177b3fa12a206eb4e95d"
    script = bdk.Script(b"\x51\x20" + key)
    inp = PartiallySignedInput(0)
    inp.witness_utxo = CTxOut(100_000, bytes(script.to_bytes()))
    pk_control = b"\xc0" + key + bytes(32)
    multi_control = b"\xc0" + key + bytes.fromhex("11" * 32 + "22" * 32)
    inp.tap_scripts = {(pk, 0xC0): {pk_control}, (multi_a, 0xC0): {multi_control}}

    # Exercise the serialized PSBT path, not just an in-memory record.
    hwi_psbt = PSBT()
    hwi_psbt.deserialize(p2wsh_psbt_0_2of3.serialize())
    hwi_psbt.inputs[0] = inp

    def estimated_weight() -> int:
        psbt = bdk.Psbt(hwi_psbt.serialize())
        estimate = TxWeight.from_psbt(psbt)
        return estimate.inputs[0].weight()

    # Merely disclosing leaves must not inflate the key-path estimate.
    assert estimated_weight() == 66

    # Only the signed leaf contributes, even if a larger unsigned leaf is disclosed.
    inp.tap_script_sigs = {(key, bytes.fromhex(pk_hash)): bytes(64)}
    assert estimated_weight() == 66 + 35 + 66
    psbt = bdk.Psbt(hwi_psbt.serialize())
    assert FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt).vsize == weight_to_vsize(
        TxWeight.from_psbt(psbt).estimate()
    )

    # Partially signed 2-of-3 multi_a: two signatures, one empty item.
    inp.tap_script_sigs = {(key, bytes.fromhex(multi_hash)): bytes(64)}
    assert estimated_weight() == 2 * 66 + 1 + 105 + 98
    assert InputWeight.from_psbt_input(script, inp, satisfaction_weight=400).weight() == 400

    # An available key-path signature takes precedence over leaf signatures.
    inp.tap_key_sig = bytes(64)
    assert estimated_weight() == 66

    # A finalized input uses its actual witness, even in a partially finalized PSBT.
    inp.final_script_witness.scriptWitness.stack = [bytes(64), pk, pk_control]
    assert InputWeight.from_psbt_input(script, inp).weight() == 65 + 35 + 66

    inp.final_script_witness.scriptWitness.stack = []
    inp.tap_key_sig = b""
    inp.tap_scripts = {}
    # Missing leaf metadata is only a rough estimate, not a protocol maximum.
    assert InputWeight.from_psbt_input(script, inp).weight() == 66 + 1 + 34


def test_cpfp_uses_descriptor_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from bitcoin_safe.gui.qt.tx_tools import TxTools
    from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, TxOut
    from tests.non_gui.test_foreign_utxo import make_wallet, transaction

    wallet = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "cpfp",
    )
    address = wallet.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    utxo = PythonUtxo(
        str(address), OutPoint(txid=funding.compute_txid(), vout=0), TxOut.from_bdk(funding.output()[0])
    )
    wallet.get_cpfp_utxos.return_value = utxo
    wallet.get_mn_tuple.return_value = (1, 1)
    wallet.get_categories_for_txid.return_value = []
    wallet.get_unused_category_address.return_value = SimpleNamespace(address=address)
    wallet.config = SimpleNamespace(network=bdk.Network.REGTEST)
    wallet.labels = SimpleNamespace(default_category="default")
    functions = MagicMock()
    details = SimpleNamespace(transaction=funding, txid=str(funding.compute_txid()))
    expected = InputWeight()
    descriptor = wallet.bdkwallet.public_descriptor(bdk.KeychainKind.EXTERNAL)
    expected.use_descriptor(descriptor, bdk.Network.REGTEST)
    output = wallet.bdkwallet.peek_address(bdk.KeychainKind.EXTERNAL, 0).address.script_pubkey()
    expected_vsize = weight_to_vsize(TxWeight([expected], [output]).estimate())
    captured = []

    class FakeCpfpTools:
        def __init__(self, wallets):
            pass

        def get_unconfirmed_ancestors(self, txids, known_ancestors):
            return {}

        def get_fee_info_of_new_tx(
            self, unconfirmed_ancestors_fee_info, new_tx_vsize, target_total_unconfirmed_fee_rate
        ):
            captured.append(new_tx_vsize)
            fee = FeeInfo(200, new_tx_vsize, True, True)
            return fee, fee

    monkeypatch.setattr("bitcoin_safe.gui.qt.tx_tools.CpfpTools", FakeCpfpTools)
    monkeypatch.setattr("bitcoin_safe.gui.qt.tx_tools.get_wallets", lambda _: [])
    TxTools.cpfp_tx(details, wallet, functions)
    assert captured == [expected_vsize]
    functions.signals.open_tx_like.emit.assert_called_once()


@pytest.mark.parametrize("m", [2, 17, 20])
def test_large_multisig_thresholds(m: int) -> None:
    from bitcoin_safe.foreign_utxo import ForeignUtxo

    key = bytes.fromhex("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")
    count = bytes([0x50 + m]) if m <= 16 else bytes([1, m])
    script = count + (bytes([len(key)]) + key) * 20 + bytes([1, 20, 0xAE])
    output = bdk.TxOut(value=bdk.Amount.from_sat(100_000), script_pubkey=bdk.Script(b"\x00\x20" + bytes(32)))
    inp = ForeignUtxo._empty_input(output, None)
    inp.witness_script = bdk.Script(script)
    info = InputWeight.from_psbt_input(output.script_pubkey, inp)
    assert info.mn == (m, 20)
    assert info.script_size == len(script)
    assert (
        info.weight()
        == compact_size_length(m + 2) + 1 + m * 73 + compact_size_length(len(script)) + len(script) - 1
    )


@pytest.mark.parametrize(
    ("wrapper", "witness"),
    [("wsh(and_v(v:pk({}),older(10)))", True), ("sh(pk({}))", False), ("pkh({})", False)],
)
def test_descriptor_weight_does_not_require_application_template(wrapper: str, witness: bool) -> None:
    key = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
    descriptor = wrapper.format(key)
    info = InputWeight()
    info.use_descriptor(descriptor, bdk.Network.REGTEST)
    assert info.weight() == bdk.Descriptor(descriptor, bdk.NetworkKind.TEST).max_weight_to_satisfy()
    assert info.is_witness() is witness


def test_viewer_refreshes_fee_info_when_psbt_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from bitcoin_qr_tools.data import Data

    from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
    from tests.non_gui.test_foreign_utxo import transaction

    mnemonic = bdk.Mnemonic.from_string(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    )
    key = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, mnemonic, "")
    receive = bdk.Descriptor(f"wpkh({key}/0/*)", bdk.NetworkKind.TEST)
    change = bdk.Descriptor(f"wpkh({key}/1/*)", bdk.NetworkKind.TEST)
    wallet = bdk.Wallet(receive, change, bdk.Network.REGTEST, bdk.Persister.new_in_memory())
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    psbt = (
        bdk.TxBuilder()
        .add_utxo(bdk.OutPoint(txid=funding.compute_txid(), vout=0))
        .manually_selected_only()
        .drain_to(address.script_pubkey())
        .finish(wallet)
    )
    original_txid = str(psbt.extract_tx().compute_txid())
    initial = FeeInfo(psbt.fee(), 999, False, True)
    stop = RuntimeError("stop after fee update")
    viewer = SimpleNamespace(
        data=Data.from_psbt(psbt, network=bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
        fee_info=initial,
        get_tx_status=MagicMock(),
        column_fee=SimpleNamespace(fee_group=SimpleNamespace(set_fee_infos=MagicMock(side_effect=stop))),
    )

    def update() -> None:
        with pytest.raises(RuntimeError, match="stop after fee update"):
            UITx_Viewer.set_psbt(viewer, psbt)  # type: ignore[arg-type]

    update()
    assert viewer.fee_info is not initial
    assert viewer.fee_info.vsize == FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt).vsize
    assert viewer.fee_info.vsize_is_estimated
    assert UITx_Viewer._fetch_cached_feeinfo(viewer, original_txid) is viewer.fee_info  # type: ignore[arg-type]
    assert UITx_Viewer._fetch_cached_feeinfo(viewer, "other") is None  # type: ignore[arg-type]
    options = bdk.SignOptions(
        trust_witness_utxo=False,
        assume_height=None,
        allow_all_sighashes=False,
        try_finalize=False,
        sign_with_tap_internal_key=True,
        allow_grinding=True,
    )
    wallet.sign(psbt, options)
    assert str(psbt.extract_tx().compute_txid()) == original_txid
    old_fee_info = viewer.fee_info
    update()
    assert viewer.fee_info is not old_fee_info
    assert viewer.fee_info.vsize_is_estimated
    finalized = psbt.finalize()
    assert finalized.could_finalize
    psbt = finalized.psbt
    update()
    assert not viewer.fee_info.vsize_is_estimated
    assert viewer.fee_info.vsize == psbt.extract_tx().vsize()

    # A finalized imported PSBT can provide the fee even for an unrelated viewer.
    imported_viewer = SimpleNamespace(set_tx=MagicMock())
    UITx_Viewer.import_trusted_psbt(imported_viewer, psbt)  # type: ignore[arg-type]
    imported_fee = imported_viewer.set_tx.call_args.kwargs["fee_info"]
    assert imported_fee.fee_amount == psbt.fee()
    assert imported_fee.vsize == psbt.extract_tx().vsize()
    assert not imported_fee.any_is_estimated()

    # Cached fee amounts remain useful when transitioning to a finalized transaction.
    viewer._fetch_cached_feeinfo = lambda txid: UITx_Viewer._fetch_cached_feeinfo(viewer, txid)
    viewer.get_chain_position = MagicMock(return_value=None)
    viewer.wallet_functions = MagicMock()
    viewer.txid = lambda: original_txid
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.get_tx_details", lambda **kwargs: (None, None)
    )
    with pytest.raises(RuntimeError, match="stop after fee update"):
        UITx_Viewer.set_tx(viewer, psbt.extract_tx())  # type: ignore[arg-type]
    assert viewer.fee_info.fee_amount == initial.fee_amount
    assert viewer.fee_info.vsize == psbt.extract_tx().vsize()
    assert not viewer.fee_info.vsize_is_estimated

    psbt = (
        bdk.TxBuilder()
        .add_utxo(bdk.OutPoint(txid=funding.compute_txid(), vout=0))
        .manually_selected_only()
        .add_recipient(address.script_pubkey(), bdk.Amount.from_sat(10_000))
        .finish(wallet)
    )
    assert str(psbt.extract_tx().compute_txid()) != original_txid
    update()
    assert viewer.fee_info.fee_amount == psbt.fee()
    assert viewer.fee_info.vsize_is_estimated


@pytest.mark.parametrize("embedded", [False, True])
def test_psbt_viewer_uses_size_estimate_instead_of_builder_target(
    embedded: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from bitcoin_safe.gui.qt.main import MainWindow
    from bitcoin_safe.gui.qt.qt_wallet import QTWallet
    from bitcoin_safe.tx import TxBuilderInfos

    psbt = p2wsh_psbt_0_2of3
    builder = TxBuilderInfos(recipients=[], utxos_for_input=[], psbt=psbt, fee_rate=100_000)
    create_viewer = MagicMock()
    config = SimpleNamespace(network=bdk.Network.REGTEST)
    common = dict(config=config, wallet_functions=MagicMock(), fx=MagicMock(), mempool_manager=MagicMock())
    if embedded:
        monkeypatch.setattr("bitcoin_safe.gui.qt.qt_wallet.create_tx_viewer", create_viewer)
        qt_wallet = SimpleNamespace(**common, wallet=SimpleNamespace(client=None), tabs=MagicMock())
        QTWallet.create_viewer_from_builder_infos(qt_wallet, builder)  # type: ignore[arg-type]
    else:
        monkeypatch.setattr("bitcoin_safe.gui.qt.main.create_tx_viewer", create_viewer)
        monkeypatch.setattr("bitcoin_safe.gui.qt.main.SidebarNode", MagicMock())
        main = SimpleNamespace(
            **common,
            tab_wallets=MagicMock(),
            get_tx_viewer=MagicMock(return_value=None),
            get_client_of_any_wallet=MagicMock(return_value=None),
        )
        MainWindow.open_psbt_in_tab(main, builder)  # type: ignore[arg-type]

    fee_info = create_viewer.call_args.kwargs["fee_info"]
    assert fee_info.fee_amount == psbt.fee()
    assert fee_info.vsize == FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt).vsize
    assert fee_info.vsize_is_estimated


def _taproot_psbt(script_path: bool, input_count: int = 1) -> tuple[bdk.Wallet, bdk.Psbt]:
    from tests.non_gui.test_foreign_utxo import transaction

    mnemonic = bdk.Mnemonic.from_string(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
    )
    key = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, mnemonic, "")
    fixed_key = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

    def descriptor(branch: int) -> bdk.Descriptor:
        derived_key = f"{key}/{branch}/*"
        internal, leaf = (fixed_key, derived_key) if script_path else (derived_key, fixed_key)
        return bdk.Descriptor(f"tr({internal},pk({leaf}))", bdk.NetworkKind.TEST)

    wallet = bdk.Wallet(descriptor(0), descriptor(1), bdk.Network.REGTEST, bdk.Persister.new_in_memory())
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())] * input_count)
    wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    builder = bdk.TxBuilder().manually_selected_only().drain_to(address.script_pubkey())
    for vout in range(input_count):
        builder = builder.add_utxo(bdk.OutPoint(txid=funding.compute_txid(), vout=vout))
    return wallet, builder.finish(wallet)


def test_taproot_leaves_do_not_imply_script_path() -> None:
    from hwilib.psbt import PSBT

    wallet, psbt = _taproot_psbt(script_path=False)
    hwi_psbt = PSBT()
    hwi_psbt.deserialize(psbt.serialize())
    assert hwi_psbt.inputs[0].tap_scripts
    estimate = TxWeight.from_psbt(psbt)
    assert estimate.inputs[0].weight() == 66
    assert wallet.sign(psbt)
    assert psbt.extract_tx().weight() <= estimate.estimate()


def test_taproot_script_path_and_finalized_weight() -> None:
    from hwilib.psbt import PSBT

    wallet, psbt = _taproot_psbt(script_path=True)
    options = bdk.SignOptions(
        trust_witness_utxo=False,
        assume_height=None,
        allow_all_sighashes=False,
        try_finalize=False,
        sign_with_tap_internal_key=False,
        allow_grinding=True,
    )
    wallet.sign(psbt, options)
    hwi_psbt = PSBT()
    hwi_psbt.deserialize(psbt.serialize())
    assert hwi_psbt.inputs[0].tap_script_sigs
    estimate = TxWeight.from_psbt(psbt).estimate()
    finalized = psbt.finalize()
    assert finalized.could_finalize
    tx = finalized.psbt.extract_tx()
    assert estimate == tx.weight() + 1  # Maximum 65-byte signature versus this 64-byte signature.
    assert TxWeight.from_psbt(finalized.psbt).estimate() == tx.weight()
    fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(finalized.psbt)
    assert not fee_info.vsize_is_estimated
    assert fee_info.vsize == tx.vsize()


def test_mixed_psbt_preserves_finalized_input_weight() -> None:
    from hwilib.psbt import PSBT

    wallet, psbt = _taproot_psbt(script_path=False, input_count=2)
    assert wallet.sign(psbt)
    tx = psbt.extract_tx()
    hwi_psbt = PSBT()
    hwi_psbt.deserialize(psbt.serialize())
    hwi_psbt.inputs[1].final_script_witness.scriptWitness.stack = []
    mixed = bdk.Psbt(hwi_psbt.serialize())

    weights = TxWeight.from_psbt(mixed)
    assert weights.inputs[0].weight() == 65  # Actual 64-byte signature and its length byte.
    assert weights.inputs[1].weight() == 66  # An unfinished signature may also include a sighash byte.
    assert weights.estimate() == tx.weight() + 1
