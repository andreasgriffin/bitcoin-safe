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

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.util import network_kind

from bitcoin_safe.foreign_utxo import ForeignUtxo
from bitcoin_safe.mempool_manager import MempoolManager
from bitcoin_safe.outpoint_parser import parse_outpoints
from bitcoin_safe.pythonbdk_types import OutPoint, PythonUtxo, Recipient, TxOut, UtxosForInputs
from bitcoin_safe.tx import TxInputInfo, TxUiInfos
from bitcoin_safe.wallet import BdkWallet, Wallet

NETWORK = bdk.Network.REGTEST


def foreign_utxo(outpoint, txout, transaction, wallets):
    wallet_descriptors = [(wallet.id, wallet.bdkwallet) for wallet in wallets]
    return ForeignUtxo.from_outpoint(outpoint, txout, transaction, wallet_descriptors, NETWORK)


async def resolve_outpoints(outpoints, wallets, active_wallet, mempool_manager):
    return await Wallet.resolve_foreign_outpoints(active_wallet, outpoints, wallets, mempool_manager)


def make_wallet(seed: str, wallet_id: str) -> MagicMock:
    mnemonic = bdk.Mnemonic.from_string(seed)
    key = bdk.DescriptorSecretKey(network_kind(NETWORK), mnemonic, "")
    receive = bdk.Descriptor.new_bip84(key, bdk.KeychainKind.EXTERNAL, network_kind(NETWORK))
    change = bdk.Descriptor.new_bip84(key, bdk.KeychainKind.INTERNAL, network_kind(NETWORK))
    wallet = MagicMock(spec=Wallet)
    wallet.id = wallet_id
    wallet.network = NETWORK
    wallet.bdkwallet = BdkWallet(receive, change, NETWORK, bdk.Persister.new_in_memory())
    wallet.serialize_persistence = SimpleNamespace(change_set=bdk.ChangeSet())
    wallet.get_graph_changesets.side_effect = lambda: Wallet.get_graph_changesets(wallet)
    wallet.get_graph_transactions.side_effect = lambda *args, **kwargs: Wallet.get_graph_transactions(
        wallet, *args, **kwargs
    )
    wallet.iter_graph_txouts.side_effect = lambda *args, **kwargs: Wallet.iter_graph_txouts(
        wallet, *args, **kwargs
    )
    wallet.get_graph_transaction.side_effect = lambda txid: Wallet.get_graph_transaction(wallet, txid)
    wallet.get_graph_txout.side_effect = lambda outpoint: Wallet.get_graph_txout(wallet, outpoint)
    wallet.get_all_txos_dict.return_value = {}
    wallet.get_dict_fulltxdetail.return_value = {}
    return wallet


def transaction(scripts: list[bytes]) -> bdk.Transaction:
    raw = bytes.fromhex("0200000001" + "11" * 32 + "0000000000ffffffff") + bytes([len(scripts)])
    for script in scripts:
        raw += (100_000).to_bytes(8, "little") + bytes([len(script)]) + script
    return bdk.Transaction(raw + bytes.fromhex("00000000"))


@pytest.fixture
def wallets() -> tuple[MagicMock, MagicMock]:
    active = make_wallet(
        "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about",
        "active",
    )
    other = make_wallet(
        "legal winner thank year wave sausage worth useful legal winner thank yellow", "other"
    )
    return active, other


def test_empty_outpoints_do_not_scan_wallets() -> None:
    wallet = MagicMock(spec=Wallet)
    assert Wallet.get_known_wallet_outputs(set(), [wallet]) == {}
    assert not wallet.mock_calls


def test_parse_multiple_outpoints_and_report_errors() -> None:
    txid = "12" * 32
    points, errors = parse_outpoints(f"{txid}:0\ninvalid\n{txid}:1\n{txid}:0\n{txid}:-1", set())
    assert [op.vout for op in points] == [0, 1]
    assert len(errors) == 3
    assert "duplicate" in errors[1]


@pytest.mark.parametrize("sighash_type", [2, 3, 0x81, 0x82, 0x83])
def test_import_discards_sighash_policy(sighash_type: int) -> None:
    funding = transaction([b"\x00\x14" + b"\x42" * 20])
    point = OutPoint(txid=funding.compute_txid(), vout=0)
    item = ForeignUtxo.from_outpoint(point, funding.output()[0], funding, [], NETWORK)
    imported = ForeignUtxo._empty_input(funding.output()[0], funding)
    # The original policy must be cleared before the input is sent to BDK.
    cast(Any, imported).sighash_type = sighash_type
    item.use_imported_input(imported)
    assert item.psbt_input.sighash_type is None


def test_known_spent_foreign_input_is_rejected(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    point = OutPoint(txid=funding.compute_txid(), vout=0)
    other.get_all_txos_dict.return_value = {
        str(point): PythonUtxo(
            str(address), point, TxOut.from_bdk(funding.output()[0]), is_spent_by_txid="ab" * 32
        )
    }
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    resolved, errors = asyncio.run(resolve_outpoints([point], [active, other], active, manager))
    assert not resolved
    assert "already spent" in errors[0]
    manager.fetch_transaction.assert_not_awaited()
    resolved, errors = asyncio.run(
        Wallet.resolve_foreign_outpoints(active, [point], [active, other], manager, skip_spent=True)
    )
    assert not resolved
    assert not errors
    manager.fetch_transaction.assert_not_awaited()


def test_import_wallet_utxos_after_parent_transaction_update(wallets: tuple[MagicMock, MagicMock]) -> None:
    from tests.helpers import TestConfig
    from tests.non_gui.utils import create_multisig_protowallet

    config = TestConfig()
    config.network = NETWORK
    protowallet = create_multisig_protowallet(1, 1, ["m/84h/1h/0h"], network=NETWORK)
    other = Wallet.from_protowallet(protowallet=protowallet, config=config, loop_in_thread=None)
    active, _ = wallets
    try:
        address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
        funding = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
        other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=0)])
        other.clear_cache()
        spent = OutPoint(txid=funding.compute_txid(), vout=0)
        remaining = OutPoint(txid=funding.compute_txid(), vout=1)
        child = (
            bdk.TxBuilder()
            .add_utxo(spent)
            .manually_selected_only()
            .drain_to(address.script_pubkey())
            .finish(other.bdkwallet)
            .extract_tx()
        )
        other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=child, last_seen=0)])
        other.clear_cache()
        child_outpoint = OutPoint(txid=child.compute_txid(), vout=0)
        assert {utxo.outpoint for utxo in other.get_all_utxos()} == {remaining, child_outpoint}

        # The parent moves from locally stored to seen in the mempool; the child is unchanged.
        other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=2)])
        other.clear_cache()
        outpoints = [utxo.outpoint for utxo in other.get_all_utxos()]
        assert set(outpoints) == {remaining, child_outpoint}
        resolved, errors = asyncio.run(resolve_outpoints(outpoints, [active, other], active, None))
        assert not errors
        assert set(resolved) == {remaining, child_outpoint}
    finally:
        other.close()


def test_resolve_other_wallet_transaction_and_sign(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    tx = transaction([bytes(address.script_pubkey().to_bytes())])
    other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not errors
    manager.fetch_transaction.assert_not_awaited()
    item = resolved[op]
    assert item.wallet_id == "other"
    assert (
        item.satisfaction_weight
        == bdk.Descriptor(
            other.bdkwallet.public_descriptor(bdk.KeychainKind.EXTERNAL), network_kind(NETWORK)
        ).max_weight_to_satisfy()
    )
    assert item.psbt_input.bip32_derivation
    assert item.psbt_input.non_witness_utxo.compute_txid() == tx.compute_txid()
    destination = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    psbt = (
        bdk.TxBuilder()
        .add_foreign_utxo(op, item.psbt_input, item.satisfaction_weight)
        .manually_selected_only()
        .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(90_000))
        .finish(active.bdkwallet)
    )
    assert other.bdkwallet.sign(psbt)


def test_resolve_download_once_with_mixed_failures(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    script = b"\x00\x14" + b"\x42" * 20
    tx = transaction([script, script])
    ops = [OutPoint(txid=tx.compute_txid(), vout=index) for index in (0, 1, 2)]
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(resolve_outpoints(ops, [active, other], active, manager))
    assert set(resolved) == set(ops[:2])
    assert "output index" in errors[0]
    assert manager.fetch_transaction.await_count == 1
    descriptor = bdk.Descriptor(
        other.bdkwallet.public_descriptor(bdk.KeychainKind.EXTERNAL), network_kind(NETWORK)
    )
    assert descriptor.max_weight_to_satisfy() == 107
    assert all(item.satisfaction_weight == descriptor.max_weight_to_satisfy() for item in resolved.values())


def test_resolve_rejects_conflicting_psbt_previous_output(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    active.get_all_utxos.return_value = []
    other.get_all_utxos.return_value = []
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    psbt_input = foreign_utxo(op, tx.output()[0], None, []).psbt_input
    psbt_input.witness_utxo = bdk.TxOut(
        value=bdk.Amount.from_sat(99_999), script_pubkey=tx.output()[0].script_pubkey
    )
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(
        Wallet.resolve_foreign_outpoints(active, [op], [active, other], manager, {op: psbt_input})
    )
    assert not resolved
    assert "conflicts with transaction" in errors[0]
    manager.fetch_transaction.assert_awaited_once()

    psbt_input.non_witness_utxo = tx
    manager.fetch_transaction.reset_mock()
    resolved, errors = asyncio.run(
        Wallet.resolve_foreign_outpoints(active, [op], [active, other], manager, {op: psbt_input})
    )
    assert not resolved
    assert "conflicting previous outputs" in errors[0]
    manager.fetch_transaction.assert_not_awaited()


def test_output_only_requires_download(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    from bitcoin_safe.pythonbdk_types import PythonUtxo, TxOut

    active.get_all_txos_dict.return_value = {str(op): PythonUtxo("", op, TxOut.from_bdk(tx.output()[0]))}
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not errors
    assert resolved[op].psbt_input.non_witness_utxo is not None
    manager.fetch_transaction.assert_awaited_once()


@pytest.mark.parametrize(
    "script",
    [
        b"\x00\x20" + b"\x42" * 32,  # P2WSH
        b"\x51\x20" + b"\x42" * 32,  # Taproot
        b"\x00\x14" + b"\x42" * 19,
        b"\x00\x14" + b"\x42" * 21,
        b"\x51\x14" + b"\x42" * 20,
        b"\x00\x15" + b"\x42" * 20,
    ],
)
def test_unsupported_script_is_rejected(script: bytes, wallets: tuple[MagicMock, MagicMock]) -> None:
    active, _ = wallets
    tx = transaction([script])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    with pytest.raises(ValueError, match="Unsupported or ambiguous"):
        foreign_utxo(op, tx.output()[0], tx, [active])


def test_create_psbt_with_local_and_multiple_foreign(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    local_address = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    local_tx = transaction([bytes(local_address.script_pubkey().to_bytes())])
    active.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=local_tx, last_seen=1)])
    local_op = OutPoint(txid=local_tx.compute_txid(), vout=0)
    local_txout = local_tx.output()[0]
    from bitcoin_safe.pythonbdk_types import PythonUtxo, TxOut

    local = PythonUtxo(str(local_address), local_op, TxOut.from_bdk(local_txout))
    other_address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    foreign_tx = transaction([bytes(other_address.script_pubkey().to_bytes()), b"\x00\x14" + b"\x42" * 20])
    other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=foreign_tx, last_seen=1)])
    a, b = [OutPoint(txid=foreign_tx.compute_txid(), vout=i) for i in range(2)]
    first = foreign_utxo(a, foreign_tx.output()[0], foreign_tx, [other])
    second = foreign_utxo(b, foreign_tx.output()[1], foreign_tx, [other])
    infos = TxUiInfos()
    infos.inputs = {
        local.outpoint: TxInputInfo(local),
        a: TxInputInfo(first.utxo, first.psbt_input, first.satisfaction_weight),
        b: TxInputInfo(second.utxo, second.psbt_input, second.satisfaction_weight),
    }
    infos.spend_all_utxos = True
    infos.fee_rate = 2
    infos.recipients = [Recipient(address=str(local_address), amount=250_000)]
    active.handle_opportunistic_merge_utxos.return_value = UtxosForInputs(
        list(infos.selected_utxos()), spend_all_utxos=True
    )
    active.get_address.return_value = active.bdkwallet.reveal_next_address(bdk.KeychainKind.INTERNAL)
    active.determine_recipient_category.return_value = None
    result = Wallet.create_psbt(active, infos)
    assert {OutPoint.from_bdk(inp.previous_output) for inp in result.psbt.extract_tx().input()} == {
        local_op,
        a,
        b,
    }
    assert result.psbt.fee() > 0
    inputs = {
        OutPoint.from_bdk(txin.previous_output): psbt_input
        for txin, psbt_input in zip(
            result.psbt.extract_tx_unchecked_fee_rate().input(), result.psbt.input(), strict=True
        )
    }
    assert inputs[local_op].non_witness_utxo is not None
    assert inputs[local_op].non_witness_utxo.compute_txid() == local_tx.compute_txid()
    assert inputs[local_op].witness_utxo is not None
    assert inputs[local_op].bip32_derivation
    assert inputs[a].non_witness_utxo is not None
    assert inputs[b].non_witness_utxo is not None

    # Both owning wallets can sign a transaction built with local and imported inputs.
    mixed = TxUiInfos(
        inputs={
            local_op: TxInputInfo(local),
            a: TxInputInfo(first.utxo, first.psbt_input, first.satisfaction_weight),
        },
        fee_rate=2,
        recipients=[Recipient(str(local_address), 150_000)],
    )
    mixed.spend_all_utxos = True
    active.handle_opportunistic_merge_utxos.return_value = UtxosForInputs(
        [local, first.utxo], spend_all_utxos=True
    )
    mixed_psbt = Wallet.create_psbt(active, mixed).psbt
    active.bdkwallet.sign(mixed_psbt)
    assert other.bdkwallet.sign(mixed_psbt)
    assert all(item.final_script_witness is not None for item in mixed_psbt.input())
    active.handle_opportunistic_merge_utxos.return_value = UtxosForInputs(
        list(infos.selected_utxos()), spend_all_utxos=True
    )

    infos.recipients = [Recipient(address=str(local_address), amount=0, checked_max_amount=True)]
    maximum = Wallet.create_psbt(active, infos).psbt
    outputs = maximum.extract_tx_unchecked_fee_rate().output()
    assert len(outputs) == 1
    assert outputs[0].value.to_sat() + maximum.fee() == local.value + first.utxo.value + second.utxo.value

    infos.recipients = [Recipient(str(local_address), 10_000, checked_max_amount=True) for _ in range(2)]
    outputs = Wallet.create_psbt(active, infos).psbt.extract_tx_unchecked_fee_rate().output()
    assert len(outputs) == 2
    assert any(output.value.to_sat() == 10_000 for output in outputs)

    infos.fee_rate = 1
    infos.recipients = [
        Recipient(str(local_address), 299_600),
        Recipient(str(local_address), 0, checked_max_amount=True),
    ]
    with pytest.raises(ValueError, match="send-max output is too small"):
        Wallet.create_psbt(active, infos)


@pytest.mark.parametrize(
    ("manual", "selected_count", "actual_count", "reject"),
    [(True, 2, 1, True), (True, 1, 2, True), (True, 1, 1, False), (False, 2, 1, False)],
)
def test_create_psbt_checks_manual_input_set(
    wallets: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    manual: bool,
    selected_count: int,
    actual_count: int,
    reject: bool,
) -> None:
    active, _ = wallets
    address = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())] * 2)
    active.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    points = [OutPoint(txid=funding.compute_txid(), vout=i) for i in range(2)]
    utxos = [PythonUtxo(str(address), op, TxOut.from_bdk(funding.output()[op.vout])) for op in points]

    builder = bdk.TxBuilder().manually_selected_only()
    for point in points[:actual_count]:
        builder = builder.add_utxo(point)
    psbt = builder.add_recipient(address.script_pubkey(), bdk.Amount.from_sat(50_000)).finish(
        active.bdkwallet
    )

    builder_mock = MagicMock()
    builder_mock.add_global_xpubs.return_value = builder_mock
    builder_mock.fee_rate.return_value = builder_mock
    builder_mock.manually_selected_only.return_value = builder_mock
    builder_mock.add_utxo.return_value = builder_mock
    builder_mock.drain_to.return_value = builder_mock
    builder_mock.unspendable.return_value = builder_mock
    builder_mock.add_recipient.return_value = builder_mock
    builder_mock.finish.return_value = psbt
    monkeypatch.setattr("bitcoin_safe.wallet.bdk.TxBuilder", lambda: builder_mock)
    selected = utxos[:selected_count]
    active.handle_opportunistic_merge_utxos.return_value = UtxosForInputs(selected, spend_all_utxos=manual)
    active.get_address.return_value = active.bdkwallet.reveal_next_address(bdk.KeychainKind.INTERNAL)
    active.determine_recipient_category.return_value = None
    infos = TxUiInfos(
        inputs={utxo.outpoint: TxInputInfo(utxo) for utxo in selected},
        fee_rate=2,
        recipients=[Recipient(str(address), 50_000)],
    )
    infos.spend_all_utxos = manual
    if reject:
        with pytest.raises(ValueError, match="Created PSBT inputs do not match selected inputs"):
            Wallet.create_psbt(active, infos)
        active.persist.assert_not_called()
    else:
        assert Wallet.create_psbt(active, infos).psbt is psbt


def test_owner_output_only_requires_synchronized_wallet(wallets: tuple[MagicMock, MagicMock]) -> None:
    from bitcoin_safe.pythonbdk_types import PythonUtxo, TxOut

    active, other = wallets
    address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    tx = transaction([bytes(address.script_pubkey().to_bytes())])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    active.get_all_txos_dict.return_value = {
        str(op): PythonUtxo(str(address), op, TxOut.from_bdk(tx.output()[0]))
    }
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not resolved
    assert "synchronize the originating wallet" in errors[0]
    manager.fetch_transaction.assert_awaited_once()


def test_descriptor_script_mismatch_rejected(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL)
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    actual = other.bdkwallet
    other.bdkwallet = MagicMock()
    other.bdkwallet.derivation_of_spk.return_value = bdk.KeychainAndIndex(
        keychain=bdk.KeychainKind.EXTERNAL, index=0
    )
    other.bdkwallet.public_descriptor.return_value = actual.public_descriptor(bdk.KeychainKind.EXTERNAL)
    with pytest.raises(ValueError, match="does not match"):
        foreign_utxo(op, tx.output()[0], tx, [active, other])


def test_fetch_transaction_verifies_txid(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    urls: list[str] = []

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        async def text(self):
            return bytes(tx.serialize()).hex()

    class Session:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            urls.append(url)
            return Response()

    monkeypatch.setattr("bitcoin_safe.mempool_manager.aiohttp.ClientSession", Session)
    manager = MagicMock(spec=MempoolManager)
    manager.network_config = SimpleNamespace(mempool_url="https://example.test/testnet/", proxy_url=None)
    got = asyncio.run(MempoolManager.fetch_transaction(manager, tx.compute_txid()))
    assert str(got.compute_txid()) == str(tx.compute_txid())
    assert urls == [f"https://example.test/testnet/api/tx/{tx.compute_txid()}/hex"]
    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(MempoolManager.fetch_transaction(manager, bdk.Txid.from_string("11" * 32)))


def test_foreign_only_witness_input_requires_previous_transaction(
    wallets: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bitcoin_safe.psbt_util import SimplePSBT

    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    item = foreign_utxo(op, tx.output()[0], None, [active, other])
    destination = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    infos = TxUiInfos()
    infos.inputs = {op: TxInputInfo(item.utxo, item.psbt_input, item.satisfaction_weight)}
    infos.spend_all_utxos = True
    infos.fee_rate = 2
    infos.recipients = [Recipient(address=str(destination), amount=90_000)]
    active.handle_opportunistic_merge_utxos.return_value = UtxosForInputs([item.utxo], spend_all_utxos=True)
    active.get_address.return_value = active.bdkwallet.reveal_next_address(bdk.KeychainKind.INTERNAL)
    active.determine_recipient_category.return_value = None
    with pytest.raises(ValueError, match="full previous transaction"):
        Wallet.create_psbt(active, infos)
    item.psbt_input.non_witness_utxo = tx
    result = Wallet.create_psbt(active, infos)
    assert len(result.psbt.extract_tx().input()) == 1
    assert SimplePSBT.from_psbt(result.psbt).get_prev_txouts()[str(op)].value.to_sat() == 100_000
    infos.recipients.append(Recipient(address="script:6a026869", amount=0))
    with_script = Wallet.create_psbt(active, infos).psbt.extract_tx_unchecked_fee_rate()
    assert any(
        bytes(output.script_pubkey.to_bytes()) == bytes.fromhex("6a026869") and output.value.to_sat() == 0
        for output in with_script.output()
    )
    infos.recipients[-1].amount = 1_000
    with pytest.raises(ValueError, match="OP_RETURN outputs must have an amount of zero"):
        Wallet.create_psbt(active, infos)
    assert infos.recipients[-1].amount == 1_000

    infos.recipients = [Recipient("script:51", 1_000)]
    with pytest.raises(ValueError, match="output script is not allowed"):
        Wallet.create_psbt(active, infos)
    monkeypatch.setattr("bitcoin_safe.execute_config.ALLOW_ALL_SCRIPTS", True)
    built = Wallet.create_psbt(active, infos).psbt.extract_tx_unchecked_fee_rate()
    assert any(bytes(output.script_pubkey.to_bytes()) == b"\x51" for output in built.output())

    # The final send-max value can be nonzero even when its initial estimate is zero.
    infos.recipients = [Recipient("script:6a026869", 0, checked_max_amount=True)]
    with pytest.raises(ValueError, match="OP_RETURN outputs must have an amount of zero"):
        Wallet.create_psbt(active, infos)


def test_standalone_graph_output_requires_download(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    other.bdkwallet.insert_txout(op, tx.output()[0])
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not errors
    assert resolved[op].utxo.value == 100_000
    assert resolved[op].psbt_input.non_witness_utxo is not None
    manager.fetch_transaction.assert_awaited_once()


def test_noncanonical_graph_transaction_is_reused(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    op = OutPoint(txid=tx.compute_txid(), vout=0)
    other.serialize_persistence.change_set = bdk.ChangeSet.from_tx_graph_changeset(
        bdk.TxGraphChangeSet(txs=[tx], txouts={}, anchors=[], last_seen={}, first_seen={}, last_evicted={})
    )
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not errors
    assert resolved[op].psbt_input.non_witness_utxo is not None
    manager.fetch_transaction.assert_not_awaited()


def test_foreign_output_in_active_wallet_transaction_is_reused(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    owned = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    tx = transaction([bytes(owned.script_pubkey().to_bytes()), b"\x00\x14" + b"\x42" * 20])
    active.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=1)])
    op = OutPoint(txid=tx.compute_txid(), vout=1)
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    resolved, errors = asyncio.run(resolve_outpoints([op], [active, other], active, manager))
    assert not errors
    assert resolved[op].utxo.value == 100_000
    manager.fetch_transaction.assert_not_awaited()


def test_network_failure_does_not_discard_local_input(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20])
    local = OutPoint(txid=tx.compute_txid(), vout=0)
    missing = OutPoint(txid=bdk.Txid.from_string("ab" * 32), vout=0)
    active.get_graph_transactions.side_effect = lambda txids, **kwargs: (
        {local.txid_str: tx} if local.txid_str in txids else {}
    )
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(side_effect=TimeoutError("timed out"))
    resolved, errors = asyncio.run(resolve_outpoints([local, missing], [active, other], active, manager))
    assert set(resolved) == {local}
    assert len(errors) == 1 and str(missing) in errors[0] and "timed out" in errors[0]


def test_downloaded_shared_transaction_replaces_output_only_data(
    wallets: tuple[MagicMock, MagicMock],
) -> None:
    active, other = wallets
    tx = transaction([b"\x00\x14" + b"\x42" * 20, b"\x00\x14" + b"\x43" * 20])
    first, second = [OutPoint(txid=tx.compute_txid(), vout=i) for i in range(2)]
    active.bdkwallet.insert_txout(first, tx.output()[0])
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock(return_value=tx)
    resolved, errors = asyncio.run(resolve_outpoints([first, second], [active, other], active, manager))
    assert not errors
    assert all(item.psbt_input.non_witness_utxo is not None for item in resolved.values())
    assert manager.fetch_transaction.await_count == 1


def test_imported_signatures_are_discarded(wallets: tuple[MagicMock, MagicMock]) -> None:
    active, other = wallets
    address = other.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    other.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    point = OutPoint(txid=funding.compute_txid(), vout=0)
    item = foreign_utxo(point, funding.output()[0], funding, [other])
    destination = active.bdkwallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    psbt = (
        bdk.TxBuilder()
        .add_foreign_utxo(point, item.psbt_input, item.satisfaction_weight)
        .manually_selected_only()
        .add_recipient(destination.script_pubkey(), bdk.Amount.from_sat(90_000))
        .finish(active.bdkwallet)
    )
    assert other.bdkwallet.sign(psbt)
    supplied = psbt.input()[0]
    assert supplied.final_script_witness is not None or supplied.partial_sigs
    cast(Any, supplied).sighash_type = 2
    manager = MagicMock(spec=MempoolManager)
    manager.fetch_transaction = AsyncMock()
    imported, errors = asyncio.run(
        Wallet.resolve_foreign_outpoints(active, [point], [active], manager, {point: supplied})
    )
    assert not errors
    result = imported[point].psbt_input
    assert not result.partial_sigs
    assert result.final_script_witness is None
    assert result.final_script_sig is None
    assert result.tap_key_sig is None
    assert not result.tap_script_sigs
    assert result.sighash_type is None
    assert result.bip32_derivation == supplied.bip32_derivation
    manager.fetch_transaction.assert_not_awaited()
