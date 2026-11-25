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
    inp.tap_script_sigs = {"leaf": b"signature"}  # type: ignore[dict-item]
    tap = InputWeight.from_psbt_input(bdk.Script(b"\x51\x20" + bytes(32)), inp)
    assert tap.tap_script_path and tap.weight() > InputWeight(address_type=AddressTypes.p2tr).weight()
    assert (
        InputWeight.from_psbt_input(None, None).weight()
        == InputWeight(address_type=AddressTypes.p2wpkh).weight()
    )


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
