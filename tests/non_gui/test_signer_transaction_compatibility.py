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
import pytest
from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from btclib.script.witness import Witness
from btclib.tx import OutPoint, Tx, TxIn, TxOut
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.input_signature_verifier import InputVerdict, Prevout, verify_transaction
from bitcoin_safe.psbt_util import unsigned_tx_bytes
from bitcoin_safe.signals import Signals, UpdateFilter
from bitcoin_safe.signer import AbstractSignatureImporter, SignatureImporterWallet
from tests.non_gui.test_foreign_utxo import transaction

NETWORK = bdk.Network.REGTEST
SEED = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"


def _bdk_tx(tx: Tx) -> bdk.Transaction:
    return bdk.Transaction(tx.serialize(include_witness=True, check_validity=False))


def _transaction() -> Tx:
    tx = Tx.parse(transaction([b"\x51"]).serialize(), check_validity=False)
    tx.vin.append(TxIn(OutPoint(b"\x22" * 32, 1), sequence=1))
    return tx


@pytest.mark.parametrize("script_sig,witness", [(True, False), (False, True), (True, True)])
def test_unsigned_transaction_ignores_all_input_unlocking_data(script_sig: bool, witness: bool) -> None:
    unsigned = _transaction()
    signed = _transaction()
    if script_sig:
        signed.vin[0].script_sig = b"\x01\x01"
        signed.vin[1].script_sig = b"\x01\x02"
        assert _bdk_tx(unsigned).compute_txid() != _bdk_tx(signed).compute_txid()
    if witness:
        signed.vin[0].script_witness = Witness([b"signature"])
        signed.vin[1].script_witness = Witness([b"signature", b"script"])
    assert unsigned_tx_bytes(_bdk_tx(unsigned)) == unsigned_tx_bytes(_bdk_tx(signed))
    assert unsigned_tx_bytes(_bdk_tx(signed)) == unsigned.serialize(include_witness=False)


@pytest.mark.parametrize("change", ["amount", "script", "outpoint", "sequence", "version", "locktime"])
def test_unsigned_transaction_detects_changes_to_transaction_fields(change: str) -> None:
    original = _transaction()
    changed = _transaction()
    if change == "amount":
        changed.vout[0] = TxOut(changed.vout[0].value - 1, b"\x51")
    elif change == "script":
        changed.vout[0] = TxOut(changed.vout[0].value, b"\x52")
    elif change == "outpoint":
        changed.vin[1].prev_out = OutPoint(b"\x33" * 32, 1)
    elif change == "sequence":
        changed.vin[1].sequence += 1
    elif change == "version":
        changed.version += 1
    else:
        changed.lock_time += 1
    assert unsigned_tx_bytes(_bdk_tx(original)) != unsigned_tx_bytes(_bdk_tx(changed))


@pytest.fixture(params=["pkh({})", "sh(wpkh({}))", "wpkh({})"], ids=["legacy", "nested", "native"])
def signing_data(
    request: pytest.FixtureRequest,
) -> tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout]:
    key = bdk.DescriptorSecretKey(bdk.NetworkKind.TEST, bdk.Mnemonic.from_string(SEED), "")
    descriptors = [
        bdk.Descriptor(request.param.format(f"{key}/{i}/*"), bdk.NetworkKind.TEST) for i in range(2)
    ]
    wallet = bdk.Wallet(*descriptors, NETWORK, bdk.Persister.new_in_memory())
    address = wallet.reveal_next_address(bdk.KeychainKind.EXTERNAL).address
    funding = transaction([bytes(address.script_pubkey().to_bytes())])
    wallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=funding, last_seen=1)])
    original = (
        bdk.TxBuilder()
        .add_utxo(bdk.OutPoint(txid=funding.compute_txid(), vout=0))
        .manually_selected_only()
        .drain_to(address.script_pubkey())
        .finish(wallet)
    )
    signed = bdk.Psbt(original.serialize())
    options = bdk.SignOptions(
        trust_witness_utxo=False,
        assume_height=None,
        allow_all_sighashes=False,
        try_finalize=False,
        sign_with_tap_internal_key=True,
        allow_grinding=True,
    )
    wallet.sign(signed, options)
    result = signed.finalize()
    assert result.could_finalize
    final_tx = result.psbt.extract_tx()
    prevout = Prevout(bytes(funding.output()[0].script_pubkey.to_bytes()), 100_000)
    assert verify_transaction(final_tx, [prevout]).verdicts == [InputVerdict.valid]
    return wallet, original, signed, final_tx, prevout


@pytest.mark.parametrize("kind", ["psbt", "transaction"])
def test_signature_import_accepts_changed_unlocking_data(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
    kind: str,
    qtbot: QtBot,
    loop_in_thread: LoopInThread,
) -> None:
    _, original, signed, final_tx, _ = signing_data
    signals = Signals()
    importer = AbstractSignatureImporter(NETWORK, loop_in_thread, signals.close_all_video_widgets, "test", [])
    imported = Data.from_psbt(signed, NETWORK) if kind == "psbt" else Data.from_tx(final_tx, NETWORK)
    with qtbot.waitSignal(importer.signal_final_tx_received, timeout=1_000) as signal:
        importer.handle_data_input(original, imported)
    assert bytes(signal.args[0].serialize()) == bytes(final_tx.serialize())


def test_wallet_signing_accepts_changed_unlocking_data(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
    qtbot: QtBot,
    loop_in_thread: LoopInThread,
) -> None:
    wallet, original, _, final_tx, _ = signing_data
    signals = Signals()
    importer = SignatureImporterWallet.__new__(SignatureImporterWallet)
    AbstractSignatureImporter.__init__(
        importer, NETWORK, loop_in_thread, signals.close_all_video_widgets, "test", []
    )

    class WalletSigner:
        def sign_psbt(self, psbt: bdk.Psbt) -> bdk.Psbt:
            assert wallet.sign(psbt)
            return psbt

    importer.software_signers = {"TEST": WalletSigner()}
    with qtbot.waitSignal(importer.signal_signature_added, timeout=1_000) as signal:
        importer.sign(original)
    assert bytes(signal.args[0].extract_tx().serialize()) == bytes(final_tx.serialize())


def test_viewer_refresh_accepts_finalized_signature(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
) -> None:
    _, _, signed, final_tx, _ = signing_data
    viewer = SimpleNamespace(
        data=Data.from_psbt(signed, NETWORK),
        chain_position=None,
        fee_info=None,
        set_tab_properties=Mock(),
        maybe_defer_update=Mock(return_value=False),
        set_psbt=Mock(),
        set_tx=Mock(),
    )
    UITx_Viewer.reload(viewer, UpdateFilter(refresh_all=True))  # type: ignore[arg-type]
    assert bytes(viewer.set_tx.call_args.args[0].serialize()) == bytes(final_tx.serialize())


def test_import_rejects_transaction_with_changed_output(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
    monkeypatch: pytest.MonkeyPatch,
    loop_in_thread: LoopInThread,
) -> None:
    _, original, _, final_tx, _ = signing_data
    modified = Tx.parse(final_tx.serialize(), check_validity=False)
    modified.vout[0] = TxOut(modified.vout[0].value - 1, modified.vout[0].script_pub_key)
    signals = Signals()
    importer = AbstractSignatureImporter(NETWORK, loop_in_thread, signals.close_all_video_widgets, "test", [])
    message = Mock()
    monkeypatch.setattr("bitcoin_safe.signer.Message", message)
    importer.handle_data_input(original, Data.from_tx(_bdk_tx(modified), NETWORK))
    message.assert_called_once()


def test_wallet_signing_rejects_changed_transaction(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
    monkeypatch: pytest.MonkeyPatch,
    loop_in_thread: LoopInThread,
) -> None:
    _, original, _, final_tx, _ = signing_data
    modified = Tx.parse(final_tx.serialize(), check_validity=False)
    modified.vout[0] = TxOut(modified.vout[0].value - 1, modified.vout[0].script_pub_key)
    changed_psbt = Mock(spec=bdk.Psbt)
    changed_psbt.extract_tx.return_value = _bdk_tx(modified)
    signals = Signals()
    importer = SignatureImporterWallet.__new__(SignatureImporterWallet)
    AbstractSignatureImporter.__init__(
        importer, NETWORK, loop_in_thread, signals.close_all_video_widgets, "test", []
    )
    importer.software_signers = {"TEST": Mock(sign_psbt=Mock(return_value=changed_psbt))}
    received = Mock()
    importer.signal_signature_added.connect(received)
    message = Mock()
    monkeypatch.setattr("bitcoin_safe.signer.Message", message)
    importer.sign(original)
    message.assert_called_once()
    received.assert_not_called()


def test_wallet_signing_rejects_in_place_transaction_change(
    signing_data: tuple[bdk.Wallet, bdk.Psbt, bdk.Psbt, bdk.Transaction, Prevout],
    monkeypatch: pytest.MonkeyPatch,
    loop_in_thread: LoopInThread,
) -> None:
    _, original, _, final_tx, _ = signing_data
    modified = Tx.parse(final_tx.serialize(), check_validity=False)
    modified.vout[0] = TxOut(modified.vout[0].value - 1, modified.vout[0].script_pub_key)
    mutable_psbt = Mock(spec=bdk.Psbt)
    mutable_psbt.extract_tx.return_value = original.extract_tx()

    def change_psbt(psbt: Mock) -> Mock:
        psbt.extract_tx.return_value = _bdk_tx(modified)
        return psbt

    signals = Signals()
    importer = SignatureImporterWallet.__new__(SignatureImporterWallet)
    AbstractSignatureImporter.__init__(
        importer, NETWORK, loop_in_thread, signals.close_all_video_widgets, "test", []
    )
    importer.software_signers = {"TEST": Mock(sign_psbt=Mock(side_effect=change_psbt))}
    received = Mock()
    importer.signal_signature_added.connect(received)
    message = Mock()
    monkeypatch.setattr("bitcoin_safe.signer.Message", message)
    importer.sign(mutable_psbt)
    message.assert_called_once()
    received.assert_not_called()
