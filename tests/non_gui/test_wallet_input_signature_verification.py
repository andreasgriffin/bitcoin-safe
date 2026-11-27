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

from types import SimpleNamespace
from unittest.mock import Mock

import bdkpython as bdk
import ecc.dsa as dsa
import ecc.ssa as ssa
import pytest
from bitcoin_usb.address_types import AddressTypes
from bitcoin_usb.software_signer import SoftwareSigner
from btclib.hashes import hash160
from btclib.script import sig_hash
from btclib.script.taproot import output_prvkey_from_merkle_root
from btclib.script.witness import Witness
from btclib.tx import OutPoint, Tx, TxIn, TxOut

from bitcoin_safe.gui.qt.main import MainWindow
from bitcoin_safe.gui.qt.qt_wallet import QTWallet
from bitcoin_safe.input_signature_verifier import Prevout
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.pythonbdk_types import OutPoint as WalletOutPoint
from bitcoin_safe.wallet import ProtoWallet, Wallet
from bitcoin_safe.wallet_aggregation import prevouts_from_wallets
from tests.helpers import TestConfig as _TestConfig
from tests.non_gui.test_signers import TAPROOT_TEST_SEED
from tests.non_gui.utils import create_keystore, create_multisig_protowallet


def _taproot_script_path_tx() -> bdk.Transaction:
    tx = _build_tx([(b"\xab" * 32, 0)], [(1_000, b"\x51")])
    # More than one witness item is a Taproot script-path spend, which this
    # lightweight verifier deliberately reports as unchecked.
    tx.vin[0].script_witness = Witness([b"script", b"control block"])
    return bdk.Transaction(tx.serialize(include_witness=True))


def _fund_wallet_with_unconfirmed_tx(wallet: Wallet) -> bdk.OutPoint:
    address = wallet.bdkwallet.peek_address(keychain=bdk.KeychainKind.EXTERNAL, index=0)
    funding_tx = _build_tx(
        [(b"\x42" * 32, 0)],
        [(1_000_000, bytes(address.address.script_pubkey().to_bytes()))],
    )
    applied = wallet.apply_unconfirmed_txs(
        [bdk.Transaction(funding_tx.serialize(include_witness=True))], last_seen=1
    )
    assert len(applied) == 1

    outputs = wallet.bdkwallet.list_output()
    assert len(outputs) == 1
    return outputs[0].outpoint


def _create_signed_spend(wallet: Wallet, outpoint: bdk.OutPoint) -> bdk.Transaction:
    destination = wallet.bdkwallet.peek_address(keychain=bdk.KeychainKind.EXTERNAL, index=1)
    psbt = (
        bdk.TxBuilder()
        .add_utxo(outpoint)
        .manually_selected_only()
        .add_recipient(destination.address.script_pubkey(), bdk.Amount.from_sat(500_000))
        .fee_rate(bdk.FeeRate.from_sat_per_vb(1))
        .finish(wallet.bdkwallet)
    )
    descriptor, change_descriptor = wallet.multipath_descriptor.to_single_descriptors()
    signer = SoftwareSigner(
        mnemonic=wallet.keystores[0].mnemonic,
        network=wallet.network,
        receive_descriptor=str(descriptor),
        change_descriptor=str(change_descriptor),
    )
    signed_psbt = signer.sign_psbt(psbt)
    assert signed_psbt
    return signed_psbt.extract_tx()


def _wallet_with_funded_unconfirmed_output() -> tuple[Wallet, bdk.OutPoint]:
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/84h/1h/0h"],
        network=config.network,
    )
    wallet = Wallet.from_protowallet(protowallet=protowallet, config=config, loop_in_thread=None)
    return wallet, _fund_wallet_with_unconfirmed_tx(wallet)


def test_known_external_parent_output_is_preserved_without_wallet_ownership() -> None:
    transaction = _taproot_script_path_tx()
    parent = bdk.Transaction(
        _build_tx([(b"\xcd" * 32, 0)], [(2_000, b"\x51\x20" + b"\x00" * 32)]).serialize(include_witness=True)
    )
    wallet = SimpleNamespace(
        get_tx=lambda _txid: SimpleNamespace(transaction=parent),
        bdkwallet=SimpleNamespace(is_mine=lambda _script_pubkey: False),
    )

    prevouts, wallet_owned = Wallet._prevouts_of_tx(wallet, transaction)
    assert prevouts == [Prevout(b"\x51\x20" + b"\x00" * 32, 2_000)]
    assert wallet_owned == [False]


def _build_tx(inputs: list[tuple[bytes, int]], outputs: list[tuple[int, bytes]]) -> Tx:
    return Tx(
        vin=[TxIn(OutPoint(txid, vout), b"", 0xFFFFFFFF) for txid, vout in inputs],
        vout=[TxOut(value, script) for value, script in outputs],
    )


def _raw_tx(inputs: list[tuple[bytes, int]], outputs: list[tuple[int, bytes]]) -> bdk.Transaction:
    return bdk.Transaction(_build_tx(inputs, outputs).serialize(include_witness=True))


def _txid_bytes(tx: bdk.Transaction) -> bytes:
    return bytes.fromhex(str(tx.compute_txid()))


class _GraphWallet(SimpleNamespace):
    get_graph_changesets = Wallet.get_graph_changesets
    get_graph_transactions = Wallet.get_graph_transactions
    iter_graph_txouts = Wallet.iter_graph_txouts
    get_graph_transaction = Wallet.get_graph_transaction
    get_graph_txout = Wallet.get_graph_txout


def test_graph_lookup_returns_raw_data_and_preserves_staged_precedence() -> None:
    parent = _raw_tx([(b"\x73" * 32, 0)], [(2_000, b"\x51")])
    point = WalletOutPoint(txid=parent.compute_txid(), vout=0)
    key = bdk.HashableOutPoint(point)
    staged = bdk.TxOut(value=bdk.Amount.from_sat(2_000), script_pubkey=bdk.Script(b"\x51"))
    persisted = bdk.TxOut(value=bdk.Amount.from_sat(3_000), script_pubkey=bdk.Script(b"\x52"))
    staged_graph = Mock(return_value=SimpleNamespace(txs=[parent], txouts={key: staged}))
    persisted_graph = Mock(return_value=SimpleNamespace(txs=[], txouts={key: persisted}))
    wallet = _GraphWallet(
        bdkwallet=SimpleNamespace(
            get_tx=Mock(return_value=None),
            staged=Mock(return_value=SimpleNamespace(tx_graph_changeset=staged_graph)),
        ),
        serialize_persistence=SimpleNamespace(change_set=SimpleNamespace(tx_graph_changeset=persisted_graph)),
    )
    transaction = wallet.get_graph_transaction(point.txid)
    assert transaction is not None and transaction.compute_txid() == point.txid
    output = wallet.get_graph_txout(point)
    assert output is not None and output.value.to_sat() == 2_000
    persisted_graph.assert_not_called()
    assert [(op, output.value.to_sat()) for op, output in wallet.iter_graph_txouts([point])] == [
        (point, 2_000),
        (point, 3_000),
    ]


def test_prevouts_from_wallets_scans_each_graph_once() -> None:
    canonical = _raw_tx([(b"\x11" * 32, 0)], [(1_000, b"\x51")])
    staged = _raw_tx([(b"\x22" * 32, 0)], [(2_000, b"\x51"), (3_000, b"\x51")])
    persisted = _raw_tx([(b"\x33" * 32, 0)], [(4_000, b"\x51")])
    candidate = _raw_tx([(b"\x44" * 32, 0)], [(5_000, b"\x51")])
    child = _raw_tx(
        [
            (_txid_bytes(canonical), 0),
            (_txid_bytes(staged), 0),
            (_txid_bytes(staged), 1),
            (_txid_bytes(persisted), 0),
            (_txid_bytes(persisted), 1),  # Invalid output index.
            (_txid_bytes(candidate), 0),  # Candidate parent must not be shared.
            (b"\x55" * 32, 0),  # Unknown parent.
        ],
        [(1_000, b"\x51")],
    )
    staged_graph = Mock(return_value=SimpleNamespace(txs=[staged, candidate], txouts={}))
    persisted_graph = Mock(return_value=SimpleNamespace(txs=[persisted], txouts={}))
    get_tx = Mock(
        side_effect=lambda txid: (
            SimpleNamespace(transaction=canonical) if txid == canonical.compute_txid() else None
        )
    )
    wallet = _GraphWallet(
        bdkwallet=SimpleNamespace(
            get_tx=get_tx, staged=Mock(return_value=SimpleNamespace(tx_graph_changeset=staged_graph))
        ),
        serialize_persistence=SimpleNamespace(change_set=SimpleNamespace(tx_graph_changeset=persisted_graph)),
    )
    assert prevouts_from_wallets([candidate, child], [wallet]) == {
        (str(canonical.compute_txid()), 0): Prevout(b"\x51", 1_000),
        (str(staged.compute_txid()), 0): Prevout(b"\x51", 2_000),
        (str(staged.compute_txid()), 1): Prevout(b"\x51", 3_000),
        (str(persisted.compute_txid()), 0): Prevout(b"\x51", 4_000),
    }
    staged_graph.assert_called_once_with()
    persisted_graph.assert_called_once_with()
    assert get_tx.call_count == 5  # Includes the candidate's own unknown parent.


@pytest.mark.parametrize("reverse", [False, True])
def test_prevouts_from_wallets_standalone_fallback(reverse: bool) -> None:
    full_parent = _raw_tx([(b"\x61" * 32, 0)], [(1_000, b"\x51")])
    candidate = _raw_tx([(b"\x62" * 32, 0)], [(2_000, b"\x51")])
    shared = b"\x63" * 32
    conflict = b"\x64" * 32
    missing = b"\x65" * 32
    child = _raw_tx(
        [
            (_txid_bytes(full_parent), 0),
            (_txid_bytes(full_parent), 1),  # A full parent rules out this vout.
            (_txid_bytes(candidate), 0),
            (shared, 0),
            (conflict, 0),
            (missing, 0),
        ],
        [(1_000, b"\x51")],
    )

    def point(txid: bytes, vout: int = 0) -> bdk.HashableOutPoint:
        return bdk.HashableOutPoint(bdk.OutPoint(txid=bdk.Txid.from_string(txid.hex()), vout=vout))

    def output(value: int, script: bytes = b"\x51") -> bdk.TxOut:
        return bdk.TxOut(value=bdk.Amount.from_sat(value), script_pubkey=bdk.Script(script))

    def wallet(txs, staged_txouts, persisted_txouts):
        staged_graph = Mock(return_value=SimpleNamespace(txs=[], txouts=staged_txouts))
        persisted_graph = Mock(return_value=SimpleNamespace(txs=txs, txouts=persisted_txouts))
        return _GraphWallet(
            bdkwallet=SimpleNamespace(
                get_tx=Mock(return_value=None),
                staged=Mock(return_value=SimpleNamespace(tx_graph_changeset=staged_graph)),
            ),
            serialize_persistence=SimpleNamespace(
                change_set=SimpleNamespace(tx_graph_changeset=persisted_graph)
            ),
        )

    wallets = [
        wallet(
            [],
            {
                point(_txid_bytes(full_parent)): output(99_000),
                point(_txid_bytes(full_parent), 1): output(99_000),
                point(shared): output(3_000),
                point(conflict): output(4_000),
                point(_txid_bytes(candidate)): output(99_000),
            },
            {},
        ),
        wallet([full_parent], {}, {point(shared): output(3_000), point(conflict): output(4_000, b"\x52")}),
    ]
    if reverse:
        wallets.reverse()
    assert prevouts_from_wallets([candidate, child], wallets) == {
        (str(full_parent.compute_txid()), 0): Prevout(b"\x51", 1_000),
        (shared.hex(), 0): Prevout(b"\x51", 3_000),
    }
    for source in wallets:
        source.bdkwallet.staged.assert_called_once_with()
        source.bdkwallet.staged.return_value.tx_graph_changeset.assert_called_once_with()
        source.serialize_persistence.change_set.tx_graph_changeset.assert_called_once_with()


def test_prevouts_from_wallets_canonical_lookup_skips_graphs() -> None:
    parent = _raw_tx([(b"\x71" * 32, 0)], [(2_000, b"\x51")])
    child = _raw_tx([(_txid_bytes(parent), 0)], [(1_000, b"\x51")])
    wallet = _GraphWallet(
        bdkwallet=SimpleNamespace(
            get_tx=Mock(return_value=SimpleNamespace(transaction=parent)), staged=Mock()
        ),
        serialize_persistence=SimpleNamespace(change_set=Mock()),
    )
    assert prevouts_from_wallets([child], [wallet]) == {
        (str(parent.compute_txid()), 0): Prevout(b"\x51", 2_000)
    }
    wallet.bdkwallet.staged.assert_not_called()
    wallet.serialize_persistence.change_set.tx_graph_changeset.assert_not_called()


def test_prevouts_from_wallets_rejects_conflict_within_wallet() -> None:
    txid = b"\x72" * 32
    child = _raw_tx([(txid, 0)], [(1_000, b"\x51")])
    point = bdk.HashableOutPoint(bdk.OutPoint(txid=bdk.Txid.from_string(txid.hex()), vout=0))
    staged = bdk.TxOut(value=bdk.Amount.from_sat(2_000), script_pubkey=bdk.Script(b"\x51"))
    persisted = bdk.TxOut(value=bdk.Amount.from_sat(3_000), script_pubkey=bdk.Script(b"\x51"))
    wallet = _GraphWallet(
        bdkwallet=SimpleNamespace(
            get_tx=Mock(return_value=None),
            staged=Mock(
                return_value=SimpleNamespace(
                    tx_graph_changeset=Mock(return_value=SimpleNamespace(txs=[], txouts={point: staged}))
                )
            ),
        ),
        serialize_persistence=SimpleNamespace(
            change_set=SimpleNamespace(
                tx_graph_changeset=Mock(return_value=SimpleNamespace(txs=[], txouts={point: persisted}))
            )
        ),
    )
    assert prevouts_from_wallets([child], [wallet]) == {}


def _event_wallet(reject_txids: set[str]) -> SimpleNamespace:
    def apply(batch):
        return [
            bdk.WalletEvent.TX_REJECTED(
                txid=entry.tx.compute_txid(),
                tx=entry.tx,
                reason=bdk.TxRejectedReason.INVALID_INPUT(input_index=0),
            )
            for entry in batch
            if str(entry.tx.compute_txid()) in reject_txids
        ]

    return SimpleNamespace(
        get_output_addresses=lambda _tx: [],
        advance_tip_to_addresses=lambda _addresses: [],
        get_tx=lambda _txid: None,
        _prevouts_of_tx=lambda tx, _outputs=None: ([None] * len(tx.input()), [False] * len(tx.input())),
        bdkwallet=SimpleNamespace(apply_unconfirmed_txs_events=Mock(side_effect=apply)),
        persist=Mock(),
    )


@pytest.mark.parametrize("parent_first", [True, False])
@pytest.mark.parametrize("reject_index", [None, 0, 1])
def test_apply_unconfirmed_processes_dependencies(parent_first, reject_index, caplog) -> None:
    parent = _raw_tx([(b"\x41" * 32, 0)], [(3_000, b"\x51")])
    child = _raw_tx([(_txid_bytes(parent), 0)], [(2_000, b"\x51")])
    grandchild = _raw_tx([(_txid_bytes(child), 0)], [(1_000, b"\x51")])
    ordered = [parent, child, grandchild]
    reject_txids = {str(ordered[reject_index].compute_txid())} if reject_index is not None else set()
    wallet = _event_wallet(reject_txids)
    expected = ordered if reject_index is None else ordered[:reject_index]
    shared_prevouts = {(str(parent.compute_txid()), 0): Prevout(b"\x51", 3_000)}

    result = Wallet.apply_unconfirmed_txs(
        wallet, ordered if parent_first else ordered[::-1], last_seen=4, known_prevouts=shared_prevouts
    )

    assert [entry.tx.compute_txid() for entry in result] == [tx.compute_txid() for tx in expected]
    calls = wallet.bdkwallet.apply_unconfirmed_txs_events.call_args_list
    submitted = [entry.tx.compute_txid() for call in calls for entry in call.args[0]]
    expected_submitted = ordered if reject_index is None else ordered[: reject_index + 1]
    assert submitted == [tx.compute_txid() for tx in expected_submitted]
    for txid in reject_txids:
        assert txid in caplog.text
    wallet.persist.assert_called_once_with()


def test_apply_unconfirmed_logs_bdk_missing_prevouts(caplog) -> None:
    tx = _raw_tx([(b"\x41" * 32, 0)], [(2_000, b"\x51")])
    reason = bdk.TxRejectedReason.MISSING_PREVOUTS(input_index=0)
    event = bdk.WalletEvent.TX_REJECTED(txid=tx.compute_txid(), tx=tx, reason=reason)
    wallet = _event_wallet(set())
    wallet.bdkwallet.apply_unconfirmed_txs_events = Mock(return_value=[event])

    assert Wallet.apply_unconfirmed_txs(wallet, [tx], last_seen=4) == []
    assert str(event.txid) in caplog.text
    assert str(reason) in caplog.text
    wallet.persist.assert_called_once_with()


def test_apply_unconfirmed_accepts_real_bdk_signed_spend() -> None:
    wallet, outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        spend = _create_signed_spend(wallet, outpoint)

        applied = wallet.apply_unconfirmed_txs([spend], last_seen=2)

        assert len(applied) == 1
        assert wallet.get_tx(str(spend.compute_txid())) is not None
    finally:
        wallet.close()


def test_apply_unconfirmed_rejects_tampered_signature() -> None:
    wallet, outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        spend = _create_signed_spend(wallet, outpoint)
        tampered = Tx.parse(bytes(spend.serialize()))
        signature = bytearray(tampered.vin[0].script_witness.stack[0])
        signature[5] ^= 1
        tampered.vin[0].script_witness = Witness(
            [bytes(signature), *tampered.vin[0].script_witness.stack[1:]]
        )
        tampered_spend = bdk.Transaction(tampered.serialize(include_witness=True))

        assert tampered_spend.compute_txid() == spend.compute_txid()
        assert wallet.apply_unconfirmed_txs([tampered_spend], last_seen=2) == []
        assert wallet.get_tx(str(tampered_spend.compute_txid())) is None
    finally:
        wallet.close()


def _signed_chain_spend(parent: bdk.Transaction, vout: int, key: int) -> bdk.Transaction:
    """Create a real P2WPKH spend back to the same wallet address."""
    output = parent.output()[vout]
    script = bytes(output.script_pubkey.to_bytes())
    x, y = dsa.gen_keys(key)[1]
    pubkey = bytes([2 + (y & 1)]) + x.to_bytes(32, "big")
    assert script == b"\x00\x14" + hash160(pubkey)
    tx = _build_tx([(_txid_bytes(parent), vout)], [(output.value.to_sat() - 1_000, script)])
    script_code = b"\x76\xa9\x14" + hash160(pubkey) + b"\x88\xac"
    message = sig_hash.segwit_v0(script_code, tx, 0, 1, output.value.to_sat())
    tx.vin[0].script_witness = Witness([dsa.sign_(message, key).serialize() + b"\x01", pubkey])
    return bdk.Transaction(tx.serialize(include_witness=True))


@pytest.mark.parametrize("parent_first", [True, False])
@pytest.mark.parametrize("reject_index", [None, 0, 1], ids=["valid", "invalid-parent", "invalid-child"])
def test_real_bdk_verifies_independent_transaction_chains(parent_first, reject_index, caplog) -> None:
    wallet, outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        funding = wallet.get_tx(str(outpoint.txid))
        assert funding is not None
        first = funding.transaction
        output = first.output()[outpoint.vout]
        script = bytes(output.script_pubkey.to_bytes())
        # Another incoming payment spends an unknown foreign input. BDK cannot
        # verify that input, but must still discover our receiving output.
        second = _raw_tx([(b"\x43" * 32, 0)], [(output.value.to_sat(), script)])
        assert len(wallet.apply_unconfirmed_txs([second], last_seen=1)) == 1
        assert wallet.get_tx(str(second.compute_txid())) is not None

        root = bdk.DescriptorSecretKey(
            bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(wallet.keystores[0].mnemonic), ""
        )
        key = int.from_bytes(root.derive(bdk.DerivationPath("m/84h/1h/0h/0/0")).secret_bytes(), "big")
        parent = _signed_chain_spend(first, outpoint.vout, key)
        child = _signed_chain_spend(parent, 0, key)
        grandchild = _signed_chain_spend(child, 0, key)
        independent_parent = _signed_chain_spend(second, 0, key)
        independent_child = _signed_chain_spend(independent_parent, 0, key)
        chain = [parent, child, grandchild]
        expected = chain if reject_index is None else chain[:reject_index]
        expected = [*expected, independent_parent, independent_child]
        candidates = chain.copy()
        if reject_index is not None:
            original = chain[reject_index]
            tampered = Tx.parse(bytes(original.serialize()))
            signature = bytearray(tampered.vin[0].script_witness.stack[0])
            signature[5] ^= 1
            tampered.vin[0].script_witness = Witness(
                [bytes(signature), *tampered.vin[0].script_witness.stack[1:]]
            )
            candidates[reject_index] = bdk.Transaction(tampered.serialize(include_witness=True))
            assert candidates[reject_index].compute_txid() == original.compute_txid()

        # Even if another wallet supplies a candidate parent's output, that
        # parent must be accepted before its descendants can be submitted.
        known_prevouts = {(str(parent.compute_txid()), 0): Prevout(script, parent.output()[0].value.to_sat())}
        batch = [*candidates, independent_parent, independent_child]
        applied = wallet.apply_unconfirmed_txs(
            batch if parent_first else batch[::-1], last_seen=2, known_prevouts=known_prevouts
        )
        expected_ids = {str(tx.compute_txid()) for tx in expected}
        assert {str(entry.tx.compute_txid()) for entry in applied} == expected_ids
        for tx in batch:
            txid = str(tx.compute_txid())
            assert (wallet.get_tx(txid) is not None) == (txid in expected_ids)
        if reject_index is not None:
            assert str(chain[reject_index].compute_txid()) in caplog.text
    finally:
        wallet.close()


def test_real_bdk_rejects_unsigned_wallet_input(caplog) -> None:
    wallet, outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        spend = _create_signed_spend(wallet, outpoint)
        unsigned = Tx.parse(bytes(spend.serialize()))
        unsigned.vin[0].script_witness = Witness([])
        tx = bdk.Transaction(unsigned.serialize(include_witness=False))
        assert wallet.apply_unconfirmed_txs([tx], last_seen=2) == []
        assert wallet.get_tx(str(tx.compute_txid())) is None
        assert str(tx.compute_txid()) in caplog.text
    finally:
        wallet.close()


def test_sync_clears_wallet_caches_before_persisting_events(monkeypatch, caplog) -> None:
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/84h/1h/0h"],
        network=config.network,
    )
    wallet = Wallet.from_protowallet(protowallet=protowallet, config=config, loop_in_thread=None)
    calls: list[str] = []
    tx = _raw_tx([(b"\x41" * 32, 0)], [(2_000, b"\x51")])
    reason = bdk.TxRejectedReason.INVALID_INPUT(input_index=0)
    event = bdk.WalletEvent.TX_REJECTED(txid=tx.compute_txid(), tx=tx, reason=reason)
    monkeypatch.setattr(wallet.bdkwallet, "apply_update_events", lambda _update: [event])
    monkeypatch.setattr(wallet, "clear_cache", lambda **_kwargs: calls.append("clear_cache"))
    monkeypatch.setattr(wallet, "persist", lambda: calls.append("persist"))

    wallet._apply_update(object())

    assert calls == ["clear_cache", "persist"]
    assert str(event.txid) in caplog.text
    assert str(reason) in caplog.text
    wallet.close()


def test_signers_of_tx_inputs_attributes_real_bdk_signed_spend_to_keystore() -> None:
    wallet, outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        spend = _create_signed_spend(wallet, outpoint)

        signers = wallet.signers_of_tx_inputs(spend)

        assert len(signers) == 1
        assert signers[0] == (wallet.keystores[0].fingerprint.upper(),)
    finally:
        wallet.close()


@pytest.mark.parametrize("source", ["staged_output", "persisted_output", "graph_transaction"])
def test_taproot_spend_uses_external_prevout_from_transaction_graph(source: str) -> None:
    seed = TAPROOT_TEST_SEED
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    keystore = create_keystore(seed, "m/86h/1h/0h", "taproot", config.network)
    proto = ProtoWallet("taproot", 1, config.network, [keystore], AddressTypes.p2tr)
    wallet = Wallet.from_protowallet(protowallet=proto, config=config, loop_in_thread=None)
    try:
        wallet_outpoint = _fund_wallet_with_unconfirmed_tx(wallet)
        wallet_output = wallet.get_tx(str(wallet_outpoint.txid)).transaction.output()[0]
        external_parent = _raw_tx([(b"\x24" * 32, 0)], [(25_000, b"\x00\x14" + b"\x44" * 20)])
        external_outpoint = bdk.OutPoint(txid=external_parent.compute_txid(), vout=0)
        external_output = external_parent.output()[0]
        if source == "graph_transaction":
            wallet.serialize_persistence.change_set = bdk.ChangeSet.from_tx_graph_changeset(
                bdk.TxGraphChangeSet(
                    txs=[external_parent], txouts={}, anchors=[], last_seen={}, first_seen={}, last_evicted={}
                )
            )
        else:
            wallet.bdkwallet.insert_txout(external_outpoint, external_output)
            if source == "persisted_output":
                wallet.persist()

        spend = _build_tx(
            [(bytes.fromhex(str(wallet_outpoint.txid)), 0), (bytes.fromhex(str(external_outpoint.txid)), 0)],
            [(1_000, b"\x51")],
        )
        root = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(seed), "")
        private_key = int.from_bytes(root.derive(bdk.DerivationPath("m/86h/1h/0h/0/0")).secret_bytes(), "big")
        prevouts = [
            TxOut(output.value.to_sat(), bytes(output.script_pubkey.to_bytes()))
            for output in (wallet_output, external_output)
        ]
        message = sig_hash.taproot(spend, 0, prevouts, 0, 0, b"", b"")
        signature = ssa.sign_(message, output_prvkey_from_merkle_root(private_key, b"")).serialize()
        spend.vin[0].script_witness = Witness([signature])
        spend.vin[1].script_witness = Witness([b"external witness"])
        tx = bdk.Transaction(spend.serialize(include_witness=True))

        assert len(wallet.apply_unconfirmed_txs([tx], last_seen=2)) == 1
        assert wallet.get_tx(str(tx.compute_txid())) is not None
    finally:
        wallet.close()


def test_reported_collaborative_taproot_transaction_is_applied() -> None:
    seed = TAPROOT_TEST_SEED
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    keystore = create_keystore(seed, "m/86h/1h/0h", "taproot", config.network)
    proto = ProtoWallet("taproot", 1, config.network, [keystore], AddressTypes.p2tr)
    wallet = Wallet.from_protowallet(protowallet=proto, config=config, loop_in_thread=None)
    wallet_parent = bdk.Transaction(
        bytes.fromhex(
            "0200000003ca10217a56139ad864793f21d8a0a893e668b1718a0b275a8380e92d8c726a8e0300000000ffffffff"
            "e0f0176b6273ca73d107be2239aa999057bff47bb831c7cc3f7d4ab238259afc0100000000ffffffff"
            "b09b312989d53c38d481311768ff78a3398b0388616b582be7be82bbab8037c20000000000fdffffff"
            "01fef27b0000000000225120bd71811f07f20e24249dafc277d7e5234dd4b536ecbc3fa1b216ba249d441e89db130000"
        )
    )
    external_parent = bdk.Transaction(
        bytes.fromhex(
            "020000000001025dc3d851ca8e98ea6ba9afede5b3d40bab19cca04f983918baac3db6f867564d0000000000fdffffff"
            "26252979d4d1c0e2e0a75986ff2f11b3e50758cf182f4f33dce187709a9fe06c0000000000fdffffff"
            "021d46000000000000156a1374657374696e670a0af09fab800a0af09fab8014958e0000000000160014"
            "271ff1fa6574e88585a39acdf6f981fea2a3413b02473044022068067597ea72b466e6bffea3aa45fde629eb67dd4a91f6373f2817521ecbb1a5"
            "02200fba112edb06f3105fdb23eda8eb01cc9fecf593a86bbb54577aacd9aa27e8490121022dac24bbe155d6055e7a35d1cf70cb5ab56aea867e385136f04968d4fc34b56f"
            "02473044022034cbab0fa0e57210378ab9f3878f9ac2ccddc7a494dcd2b9713ac5ee2f0ac24202204c2482df74f1732355cde193427fb22def0011782d2c78221fcb85dfd45fe1ba"
            "012102d92621e727e018223ac6d037c97c0a1e43a67e49ae0086c4eaa28791b5d7728ad8130000"
        )
    )
    tx = bdk.Transaction(
        bytes.fromhex(
            "02000000000102b498694bb98a1583dbeddc4b58ccce741e72a17c0d7e9eebfba4e5f14e0aae8c0000000000ffffffff"
            "ca7a0377e7931ddfa14137fa47e53bb7c1997791859282b71ad4dbb8705fdf130100000000fdffffff"
            "057b7f00000000000022512097c889ad31058a264a3139dab8f2ad317de9f14c82e5d25244fbff457281a66d"
            "bd3f0000000000001976a9147a0021c1d44b801484414c536a746949c92eefbc88ac3547090100000000160014dc88e2f7247f1208106d4405130bbc796dae714b"
            "bd3f000000000000160014966ad337643b20be5ee98123ba8fb810d80c838fb44000000000000017a914facd48efdb88c9f36c44d2f9f5bc8857953ac31587"
            "014094d14c521bbac49eac158d5461798868cc279b177099c73a3beed12d1cef8681e3d1d0d91b8ccdc99b097178302f1d204d0461d2ff3d7d17419825c46b91aaa8"
            "02473044022029e19f477f6821b5d3a65a0c19149b2a07aee33d5c23a1233124c7364791bf860220709f9ab4a62bf63c5440eb588c5bc4fa57be756657ddd67a57e2eefa5442daa1"
            "012103a18fcef2fc6a068a3aacf663125720d45a9f80e86f9f7274f03c12ea95ff5a22dc130000"
        )
    )
    try:
        assert str(tx.compute_txid()) == "e5a0d3daf9bb7121d4551da2a06fa46dd31df1bcf6652069596a8a7cc89899d0"
        assert tx.input()[0].previous_output.txid == wallet_parent.compute_txid()
        assert tx.input()[1].previous_output.txid == external_parent.compute_txid()
        assert len(wallet.apply_unconfirmed_txs([wallet_parent], last_seen=1)) == 1
        prevouts, owned = wallet._prevouts_of_tx(tx)
        assert owned == [True, False]
        assert prevouts[1] is None
        assert wallet.apply_unconfirmed_txs([tx], last_seen=2) == []
        other_wallet = _GraphWallet(
            bdkwallet=SimpleNamespace(
                get_tx=lambda txid: (
                    SimpleNamespace(transaction=external_parent)
                    if txid == external_parent.compute_txid()
                    else None
                ),
                staged=lambda: None,
            ),
            serialize_persistence=SimpleNamespace(change_set=None),
        )
        shared_prevouts = prevouts_from_wallets([tx], [wallet, other_wallet])
        tampered = Tx.parse(tx.serialize())
        signature = bytearray(tampered.vin[0].script_witness.stack[0])
        signature[0] ^= 1
        tampered.vin[0].script_witness = Witness([bytes(signature)])
        assert (
            wallet.apply_unconfirmed_txs(
                [bdk.Transaction(tampered.serialize(include_witness=True))],
                last_seen=2,
                known_prevouts=shared_prevouts,
            )
            == []
        )
        assert len(wallet.apply_unconfirmed_txs([tx], last_seen=2, known_prevouts=shared_prevouts)) == 1
        assert wallet.get_tx(str(tx.compute_txid())) is not None
        external_point = tx.input()[1].previous_output
        assert (
            wallet._prevouts_of_tx(tx)[0][1]
            == shared_prevouts[(str(external_point.txid), external_point.vout)]
        )
    finally:
        wallet.close()


@pytest.mark.parametrize("reverse", [False, True])
def test_p2p_spend_uses_prevouts_from_both_open_wallets(reverse: bool) -> None:
    seed = TAPROOT_TEST_SEED
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    keystore = create_keystore(seed, "m/86h/1h/0h", "taproot", config.network)
    proto = ProtoWallet("taproot", 1, config.network, [keystore], AddressTypes.p2tr)
    taproot = Wallet.from_protowallet(protowallet=proto, config=config, loop_in_thread=None)
    other, other_outpoint = _wallet_with_funded_unconfirmed_output()
    try:
        taproot_outpoint = _fund_wallet_with_unconfirmed_tx(taproot)
        taproot_parent = taproot.get_tx(str(taproot_outpoint.txid)).transaction
        other_parent = other.get_tx(str(other_outpoint.txid)).transaction
        taproot_output = taproot_parent.output()[0]
        other_output = other_parent.output()[0]
        spend = _build_tx(
            [(bytes.fromhex(str(taproot_outpoint.txid)), 0), (bytes.fromhex(str(other_outpoint.txid)), 0)],
            [(1_000, b"\x51")],
        )
        taproot_root = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(seed), "")
        taproot_key = int.from_bytes(
            taproot_root.derive(bdk.DerivationPath("m/86h/1h/0h/0/0")).secret_bytes(), "big"
        )
        outputs = [
            TxOut(output.value.to_sat(), bytes(output.script_pubkey.to_bytes()))
            for output in (taproot_output, other_output)
        ]
        message = sig_hash.taproot(spend, 0, outputs, 0, 0, b"", b"")
        spend.vin[0].script_witness = Witness(
            [ssa.sign_(message, output_prvkey_from_merkle_root(taproot_key, b"")).serialize()]
        )
        other_root = bdk.DescriptorSecretKey(
            bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(other.keystores[0].mnemonic), ""
        )
        other_key = int.from_bytes(
            other_root.derive(bdk.DerivationPath("m/84h/1h/0h/0/0")).secret_bytes(), "big"
        )
        x, y = dsa.gen_keys(other_key)[1]
        pubkey = bytes([2 + (y & 1)]) + x.to_bytes(32, "big")
        script_code = b"\x76\xa9\x14" + hash160(pubkey) + b"\x88\xac"
        message = sig_hash.segwit_v0(script_code, spend, 1, 1, other_output.value.to_sat())
        spend.vin[1].script_witness = Witness([dsa.sign_(message, other_key).serialize() + b"\x01", pubkey])
        tx = bdk.Transaction(spend.serialize(include_witness=True))

        # Each wallet has only its own parent; the Taproot signature commits to both.
        assert taproot.apply_unconfirmed_txs([tx], last_seen=2) == []
        shared_prevouts = prevouts_from_wallets([tx], [taproot, other])
        altered = Tx.parse(tx.serialize())
        signature = bytearray(altered.vin[1].script_witness.stack[0])
        signature[5] ^= 1
        altered.vin[1].script_witness = Witness([bytes(signature), pubkey])
        invalid = bdk.Transaction(altered.serialize(include_witness=True))
        assert other.apply_unconfirmed_txs([invalid], last_seen=2, known_prevouts=shared_prevouts) == []
        assert other.get_tx(str(tx.compute_txid())) is None

        def qt_wallet(wallet: Wallet) -> SimpleNamespace:
            wrapper = SimpleNamespace(wallet=wallet, refresh_caches_and_ui_lists=Mock())
            wrapper.apply_txs = lambda txs, last_seen, known_prevouts: QTWallet.apply_txs(
                wrapper, txs, last_seen, known_prevouts
            )
            return wrapper

        wrappers = [qt_wallet(taproot), qt_wallet(other)]
        if reverse:
            wrappers.reverse()
        window = SimpleNamespace(
            qt_wallets={wallet.wallet.id: wallet for wallet in wrappers},
            config=SimpleNamespace(
                network=bdk.Network.REGTEST,
                network_config=SimpleNamespace(server_type=BlockchainType.CompactBlockFilter),
            ),
        )
        window.apply_txs_to_wallets = lambda txs, last_seen: MainWindow.apply_txs_to_wallets(
            window, txs, last_seen
        )
        MainWindow.p2p_listening_on_tx(window, tx)

        assert all(wallet.get_tx(str(tx.compute_txid())) is not None for wallet in (taproot, other))
        # The supporting data survives the other wallet closing and later sync verification.
        assert (
            taproot._prevouts_of_tx(tx)[0][1]
            == shared_prevouts[(str(other_outpoint.txid), other_outpoint.vout)]
        )
        assert all(wrapper.refresh_caches_and_ui_lists.call_count == 1 for wrapper in wrappers)
    finally:
        taproot.close()
        other.close()


@pytest.mark.parametrize("parent_first", [True, False])
@pytest.mark.parametrize("provide_known_prevouts", [True, False])
def test_taproot_batch_retains_external_candidate_parent_output(
    parent_first: bool, provide_known_prevouts: bool
) -> None:
    seed = TAPROOT_TEST_SEED
    config = _TestConfig()
    config.network = bdk.Network.REGTEST
    keystore = create_keystore(seed, "m/86h/1h/0h", "taproot", config.network)
    proto = ProtoWallet("taproot", 1, config.network, [keystore], AddressTypes.p2tr)
    wallet = Wallet.from_protowallet(protowallet=proto, config=config, loop_in_thread=None)
    try:
        wallet_outpoint = _fund_wallet_with_unconfirmed_tx(wallet)
        wallet_parent = wallet.get_tx(str(wallet_outpoint.txid))
        assert wallet_parent is not None
        wallet_output = wallet_parent.transaction.output()[0]
        external_parent = _raw_tx([(b"\x24" * 32, 0)], [(25_000, b"\x00\x14" + b"\x44" * 20)])
        external_output = external_parent.output()[0]
        external_outpoint = bdk.OutPoint(txid=external_parent.compute_txid(), vout=0)
        spend = _build_tx(
            [(bytes.fromhex(str(wallet_outpoint.txid)), 0), (bytes.fromhex(str(external_outpoint.txid)), 0)],
            [(1_000, b"\x00\x14" + b"\x55" * 20)],
        )
        root = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(seed), "")
        key = int.from_bytes(root.derive(bdk.DerivationPath("m/86h/1h/0h/0/0")).secret_bytes(), "big")
        prevouts = [
            TxOut(output.value.to_sat(), bytes(output.script_pubkey.to_bytes()))
            for output in (wallet_output, external_output)
        ]
        message = sig_hash.taproot(spend, 0, prevouts, 0, 0, b"", b"")
        spend.vin[0].script_witness = Witness(
            [ssa.sign_(message, output_prvkey_from_merkle_root(key, b"")).serialize()]
        )
        spend.vin[1].script_witness = Witness([b"external witness"])
        child = bdk.Transaction(spend.serialize(include_witness=True))
        batch = [external_parent, child] if parent_first else [child, external_parent]
        known_prevouts = (
            {
                (str(wallet_outpoint.txid), wallet_outpoint.vout): Prevout(
                    bytes(wallet_output.script_pubkey.to_bytes()), wallet_output.value.to_sat()
                )
            }
            if provide_known_prevouts
            else None
        )

        applied = wallet.apply_unconfirmed_txs(batch, last_seen=2, known_prevouts=known_prevouts)

        assert {entry.tx.compute_txid() for entry in applied} == {
            external_parent.compute_txid(),
            child.compute_txid(),
        }
        assert wallet.get_tx(str(child.compute_txid())) is not None
        assert wallet.get_graph_transaction(external_parent.compute_txid()) is None
        assert wallet._prevouts_of_tx(child)[0][1] == Prevout(
            bytes(external_output.script_pubkey.to_bytes()), external_output.value.to_sat()
        )
        restored = Wallet.from_dump(
            wallet.dump(),
            class_kwargs={"Wallet": {"config": config, "loop_in_thread": wallet.loop_in_thread}},
        )
        try:
            assert restored._prevouts_of_tx(child)[0][1] == Prevout(
                bytes(external_output.script_pubkey.to_bytes()), external_output.value.to_sat()
            )
            assert len(restored.apply_unconfirmed_txs([child], last_seen=3)) == 1
            assert restored.get_tx(str(child.compute_txid())) is not None
        finally:
            restored.close()
    finally:
        wallet.close()
