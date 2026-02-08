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

import logging
import time
from pathlib import Path

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from pytestqt.qtbot import QtBot

from bitcoin_safe import wallet as wallet_module
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.wallet import InconsistentBDKState

from ..faucet import Faucet
from ..helpers import TestConfig
from ..util import wait_for_sync
from ..wallet_factory import TestWalletHandle, create_test_wallet
from .test_signers import test_seeds

logger = logging.getLogger(__name__)


def _make_single_sig_wallet(
    config: TestConfig,
    backend: str,
    bitcoin_core: Path,
    loop_in_thread: LoopInThread,
    qtbot: QtBot,
) -> TestWalletHandle:
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
    assert change_descriptor
    descriptor_str = str(descriptor)
    keystore = KeyStore(
        xpub=str(descriptor).split("]")[1].split("/0/*")[0],
        fingerprint=str(descriptor).split("[")[1].split("/")[0].upper(),
        key_origin="m/84h/1h/0h",
        label="test-seed-0",
        network=config.network,
        mnemonic=seed_str,
    )
    wallet_handle = create_test_wallet(
        wallet_id="inconsistent-bdk-state",
        descriptor_str=descriptor_str,
        keystores=[keystore],
        backend=backend,
        config=config,
        bitcoin_core=bitcoin_core,
        loop_in_thread=loop_in_thread,
        is_new_wallet=True,
    )
    return wallet_handle


def test_balance_after_replaced_receive_tx_raises(
    test_config_session: TestConfig,
    faucet: Faucet,
    bitcoin_core: Path,
    backend: str,
    qtbot: QtBot,
):  # type: ignore[annotations-typing]
    """
    Reproduce an inconsistent BDK state by:
    1) receiving an unconfirmed RBF transaction,
    2) replacing it from the sender with a higher-fee double spend that drops the receive output,
    3) syncing the wallet and querying balance.
    """
    if backend == "cbf":
        logger.info(
            "Skipped test_balance_after_replaced_receive_tx_raises because this error doesnt appear in cbf"
        )
        return
    # Create a dedicated wallet for the inconsistent-state reproduction.
    wallet_handle = _make_single_sig_wallet(
        config=test_config_session,
        backend=faucet.backend,
        bitcoin_core=bitcoin_core,
        loop_in_thread=faucet.loop_in_thread,
        qtbot=qtbot,
    )
    wallet = wallet_handle.wallet
    receive_address = str(wallet.get_address(force_new=True).address)

    # Broadcast a low-fee receive transaction to set up the eviction case.
    amount_sat = 100_000
    tx = faucet.send(receive_address, amount=amount_sat, fee_rate=1, qtbot=qtbot)

    wait_for_sync(
        wallet=wallet, minimum_funds=amount_sat, txid=str(tx.compute_txid()), timeout=20, qtbot=qtbot
    )
    assert wallet.get_addr_balance(receive_address).total == amount_sat

    # Simulate mempool eviction of the unconfirmed receive transaction
    evicted = bdk.EvictedTx(txid=tx.compute_txid(), evicted_at=int(time.time()))
    wallet.bdkwallet.apply_evicted_txs([evicted])
    wallet.bdkwallet.clear_method(wallet.bdkwallet.list_transactions)

    # Clear caches so a fresh balance query hits the inconsistent state.
    wallet.cache_dict_fulltxdetail = {}
    wallet.cache_address_to_txids.clear()
    wallet.clear_instance_cache(clear_always_keep=True)

    original_retries = wallet_module.NUM_RETRIES_get_address_balances
    try:
        # With a single retry, balance lookup should raise the inconsistency error.
        wallet_module.NUM_RETRIES_get_address_balances = 1
        with pytest.raises(InconsistentBDKState):
            _ = wallet.get_addr_balance(receive_address).total

        # With more retries, the wallet should recover and show zero.
        wallet_module.NUM_RETRIES_get_address_balances = 2
        balance = wallet.get_addr_balance(receive_address)
        assert balance.total == 0
    finally:
        # Restore global retry count and close the wallet.
        wallet_module.NUM_RETRIES_get_address_balances = original_retries
        wallet.close()
