#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import time

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.tx_util import serialized_to_hex

from bitcoin_safe.keystore import KeyStore
from bitcoin_safe import wallet as wallet_module
from bitcoin_safe.wallet import InconsistentBDKState, Wallet
from .test_signers import test_seeds

from ..setup_bitcoin_core import bitcoin_cli
from ..setup_fulcrum import Faucet
from ..util import wait_for_tx


def _make_single_sig_wallet(config) -> Wallet:
    """Create a simple single-sig wallet used for regression tests."""
    # Use a stable seed from the shared test fixtures to avoid collisions with other tests.
    seed_str = test_seeds[24]
    mnemonic = bdk.Mnemonic.from_string(seed_str)
    descriptor = bdk.Descriptor.new_bip84(
        secret_key=bdk.DescriptorSecretKey(config.network, mnemonic, ""),
        keychain_kind=bdk.KeychainKind.EXTERNAL,
        network=config.network,
    )
    change_descriptor = bdk.Descriptor.new_bip84(
        secret_key=bdk.DescriptorSecretKey(config.network, mnemonic, ""),
        keychain_kind=bdk.KeychainKind.INTERNAL,
        network=config.network,
    )
    descriptor_str = str(descriptor)
    keystore = KeyStore(
        xpub=str(descriptor).split("]")[1].split("/0/*")[0],
        fingerprint=str(descriptor).split("[")[1].split("/")[0].upper(),
        key_origin="m/84h/1h/0h",
        label="test-seed-0",
        network=config.network,
        mnemonic=seed_str,
    )
    return Wallet(
        id="inconsistent-bdk-state",
        descriptor_str=descriptor_str,
        keystores=[keystore],
        network=config.network,
        config=config,
        loop_in_thread=None,
    )


def _build_rbf_psbt(
    bdk_wallet: bdk.Wallet, utxo: bdk.LocalOutput, destination_address: str, fee_rate: float, amount_sat: int
) -> bdk.Psbt:
    """Build a PSBT that spends a specific UTXO with RBF enabled."""
    builder = bdk.TxBuilder()
    builder = builder.add_utxo(utxo.outpoint)
    builder = builder.manually_selected_only()
    builder = builder.set_exact_sequence(0xFFFFFFFD)
    builder = builder.add_recipient(
        bdk.Address(destination_address, bdk_wallet.network()).script_pubkey(),
        bdk.Amount.from_sat(amount_sat),
    )
    builder = builder.fee_rate(bdk.FeeRate.from_sat_per_vb(fee_rate))
    psbt = builder.finish(bdk_wallet)
    return bdk.Psbt(psbt.serialize())


def test_balance_after_replaced_receive_tx_raises(test_config_session, faucet: Faucet, bitcoin_core):  # type: ignore[annotations-typing]
    """
    Reproduce an inconsistent BDK state by:
    1) receiving an unconfirmed RBF transaction,
    2) replacing it from the sender with a higher-fee double spend that drops the receive output,
    3) syncing the wallet and querying balance.
    """
    wallet = _make_single_sig_wallet(test_config_session)
    receive_address = str(wallet.get_address(force_new=True).address)

    utxo = next(u for u in faucet.bdk_wallet.list_unspent() if not u.is_spent)
    amount_sat = min(100_000, utxo.txout.value.to_sat() - 5_000)

    psbt = _build_rbf_psbt(
        bdk_wallet=faucet.bdk_wallet,
        utxo=utxo,
        destination_address=receive_address,
        fee_rate=1,
        amount_sat=amount_sat,
    )

    faucet.bdk_wallet.sign(psbt, None)
    tx = psbt.extract_tx()
    bitcoin_cli(f"sendrawtransaction {serialized_to_hex(tx.serialize())}", bitcoin_core)
    faucet.sync()

    wait_for_tx(wallet, str(tx.compute_txid()))
    assert wallet.get_addr_balance(receive_address).total == amount_sat

    # Simulate mempool eviction of the unconfirmed receive transaction
    evicted = bdk.EvictedTx(txid=tx.compute_txid(), evicted_at=int(time.time()))
    wallet.bdkwallet.apply_evicted_txs([evicted])
    wallet.bdkwallet.clear_method(wallet.bdkwallet.list_transactions)

    wallet.cache_dict_fulltxdetail = {}
    wallet.cache_address_to_txids.clear()
    wallet.clear_instance_cache(clear_always_keep=True)

    original_retries = wallet_module.NUM_RETRIES_get_address_balances
    try:
        wallet_module.NUM_RETRIES_get_address_balances = 1
        with pytest.raises(InconsistentBDKState):
            wallet.get_addr_balance(receive_address).total

        wallet_module.NUM_RETRIES_get_address_balances = 2
        balance = wallet.get_addr_balance(receive_address)
        assert balance.total == 0
    finally:
        wallet_module.NUM_RETRIES_get_address_balances = original_retries
