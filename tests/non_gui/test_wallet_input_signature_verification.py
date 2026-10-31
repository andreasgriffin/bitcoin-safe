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

import bdkpython as bdk
from bitcoin_usb.software_signer import SoftwareSigner
from embit.script import Script
from embit.transaction import (
    Transaction,
    TransactionInput,
    TransactionOutput,
)
from embit.transaction import (
    Transaction as EmbitTransaction,
)

from bitcoin_safe.input_signature_verifier import Prevout
from bitcoin_safe.wallet import Wallet
from tests.helpers import TestConfig as _TestConfig
from tests.non_gui.utils import create_multisig_protowallet


def _taproot_script_path_tx() -> bdk.Transaction:
    tx = Transaction(
        vin=[TransactionInput(b"\xab" * 32, 0)],
        vout=[TransactionOutput(1_000, Script(b"\x51"))],
    )
    # More than one witness item is a Taproot script-path spend, which this
    # lightweight verifier deliberately reports as unchecked.
    tx.vin[0].witness.items = [b"script", b"control block"]
    return bdk.Transaction(tx.serialize())


def _fund_wallet_with_unconfirmed_tx(wallet: Wallet) -> bdk.OutPoint:
    address = wallet.bdkwallet.peek_address(keychain=bdk.KeychainKind.EXTERNAL, index=0)
    funding_tx = Transaction(
        vin=[TransactionInput(b"\x42" * 32, 0)],
        vout=[TransactionOutput(1_000_000, Script(bytes(address.address.script_pubkey().to_bytes())))],
    )
    applied = wallet.apply_unconfirmed_txs([bdk.Transaction(funding_tx.serialize())], last_seen=1)
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


def test_unchecked_known_wallet_input_is_rejected() -> None:
    transaction = _taproot_script_path_tx()
    wallet = SimpleNamespace(_prevouts_of_tx=lambda _tx: [Prevout(b"\x51\x20" + b"\x00" * 32, 2_000)])

    assert not Wallet._verify_tx_signatures(wallet, transaction)


def test_unchecked_unknown_input_does_not_reject_transaction() -> None:
    transaction = _taproot_script_path_tx()
    wallet = SimpleNamespace(_prevouts_of_tx=lambda _tx: [None])

    assert Wallet._verify_tx_signatures(wallet, transaction)


def test_known_external_parent_output_is_not_treated_as_wallet_owned() -> None:
    transaction = _taproot_script_path_tx()
    parent = bdk.Transaction(
        Transaction(
            vin=[TransactionInput(b"\xcd" * 32, 0)],
            vout=[TransactionOutput(2_000, Script(b"\x51\x20" + b"\x00" * 32))],
        ).serialize()
    )
    wallet = SimpleNamespace(
        get_tx=lambda _txid: SimpleNamespace(transaction=parent),
        bdkwallet=SimpleNamespace(is_mine=lambda _script_pubkey: False),
    )

    assert Wallet._prevouts_of_tx(wallet, transaction) == [None]


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
        tampered = EmbitTransaction.parse(spend.serialize())
        signature = bytearray(tampered.vin[0].witness.items[0])
        signature[5] ^= 1
        tampered.vin[0].witness.items[0] = bytes(signature)
        tampered_spend = bdk.Transaction(tampered.serialize())

        assert tampered_spend.compute_txid() == spend.compute_txid()
        assert wallet.apply_unconfirmed_txs([tampered_spend], last_seen=2) == []
        assert wallet.get_tx(str(tampered_spend.compute_txid())) is None
    finally:
        wallet.close()


def test_sync_clears_wallet_caches_before_verifying_events(monkeypatch) -> None:
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
    monkeypatch.setattr(wallet.bdkwallet, "apply_update_events", lambda _update: [])
    monkeypatch.setattr(wallet, "clear_cache", lambda **_kwargs: calls.append("clear_cache"))
    monkeypatch.setattr(wallet, "_evict_txs_with_invalid_signatures", lambda _events: calls.append("verify"))
    monkeypatch.setattr(wallet, "persist", lambda: calls.append("persist"))

    wallet._apply_update(object())

    assert calls == ["clear_cache", "verify", "persist"]
    wallet.close()
