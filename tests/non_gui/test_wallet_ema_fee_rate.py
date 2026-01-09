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
import math
from collections.abc import Generator
from pathlib import Path

import pytest
from bitcoin_usb.address_types import AddressTypes, DescriptorInfo, SimplePubKeyProvider
from bitcoin_usb.software_signer import SoftwareSigner
from pytestqt.qtbot import QtBot

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.wallet import Wallet

from ..faucet import Faucet
from ..helpers import TestConfig
from ..non_gui.test_wallet import create_test_seed_keystores
from ..util import make_psbt, wait_for_sync
from ..wallet_factory import create_test_wallet
from .test_wallet_coin_select import TestWalletConfig

logger = logging.getLogger(__name__)


@pytest.fixture(
    scope="session",
    params=[
        TestWalletConfig(utxo_value_private=1_000_000, num_private=1, utxo_value_kyc=2_000_000, num_kyc=1)
    ],
)
def test_wallet_config_seed(request) -> TestWalletConfig:
    """Test wallet config seed."""
    return request.param


@pytest.fixture(scope="session")
def test_funded_seed_wallet_session(
    test_config_session: TestConfig,
    backend: str,
    bitcoin_core: Path,
    loop_in_thread,
    wallet_name="test_tutorial_wallet_setup",
) -> Generator[Wallet, None, None]:
    """Test funded seed wallet."""
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=test_config_session.network,
        test_seed_offset=20,
    )[0]

    descriptor_info = DescriptorInfo(
        address_type=AddressTypes.p2wpkh,
        spk_providers=[SimplePubKeyProvider.from_hwi(keystore.to_hwi_pubkey_provider())],
        threshold=1,
    )
    wallet_handle = create_test_wallet(
        wallet_id=wallet_name,
        descriptor_str=descriptor_info.get_descriptor_str(test_config_session.network),
        keystores=[keystore],
        backend=backend,
        config=test_config_session,
        is_new_wallet=True,
        bitcoin_core=bitcoin_core,
        loop_in_thread=loop_in_thread,
    )
    yield wallet_handle.wallet
    wallet_handle.close()


@pytest.fixture()
def test_funded_seed_wallet(
    test_funded_seed_wallet_session: Wallet,
    faucet: Faucet,
    test_wallet_config_seed: TestWalletConfig,
    qtbot: QtBot,
) -> Generator[Wallet, None, None]:
    wallet = test_funded_seed_wallet_session
    # fund the wallet
    addresses_private = [
        str(wallet.get_address(force_new=True).address) for i in range(test_wallet_config_seed.num_private)
    ]
    for address in addresses_private:
        wallet.labels.set_addr_category(address, "Private")
        faucet.send(address, amount=test_wallet_config_seed.utxo_value_private, qtbot=qtbot)

    faucet.mine(qtbot=qtbot)

    wait_for_sync(
        wallet=wallet,
        minimum_funds=test_wallet_config_seed.utxo_value_private * len(addresses_private),
        qtbot=qtbot,
    )

    yield wallet


def _override_tx_fees(wallet: Wallet, fee_map: dict[str, float]) -> None:
    """Force wallet txdetails to use the desired fee rates (sat/vbyte)."""
    txdetails = wallet.sorted_delta_list_transactions()
    for txdetail in txdetails:
        rate = fee_map.get(txdetail.txid)
        if rate is None:
            continue
        txdetail.fee = int(math.ceil(rate * txdetail.vsize))


def test_ema_fee_rate_weights_recent_heavier(
    test_funded_seed_wallet: Wallet,
    qtbot: QtBot,
    faucet: Faucet,
):
    """Test that the EMA fee rate for an incoming wallet is weighted more heavily
    towards recent transactions."""

    wallet = test_funded_seed_wallet
    desired_fee_rates: dict[str, float] = {}

    def send_tx(fee_rate=100) -> str:
        """Broadcast a tx and record the intended fee rate for testing."""
        psbt_for_signing = make_psbt(
            wallet=wallet,
            destination_address=wallet.get_addresses()[0],
            amount=1000,
            fee_rate=fee_rate,
        )

        descriptor, change_descriptor = wallet.multipath_descriptor.to_single_descriptors()
        signer = SoftwareSigner(
            mnemonic=wallet.keystores[0].mnemonic,
            network=wallet.network,
            receive_descriptor=str(descriptor),
            change_descriptor=str(change_descriptor),
        )
        signed_psbt = signer.sign_psbt(psbt_for_signing)

        tx = signed_psbt.extract_tx()
        wallet.client.broadcast(tx)
        faucet.mine(qtbot=qtbot)

        txid = str(tx.compute_txid())
        wait_for_sync(wallet=wallet, txid=txid, qtbot=qtbot)
        desired_fee_rates[txid] = fee_rate
        return txid

    # incoming txs have no fee rate (rpc doesnt seem to fill the fee field)
    _override_tx_fees(wallet, desired_fee_rates)
    assert round(wallet.get_ema_fee_rate(), 1) == MIN_RELAY_FEE

    def set_unknown_fee():
        # test that it takes in account the icoming txs, if a fee is known
        txdetails = wallet.sorted_delta_list_transactions()
        txdetails[0].fee = 21 * txdetails[0].vsize
        desired_fee_rates[txdetails[0].txid] = 21

    set_unknown_fee()
    _override_tx_fees(wallet, desired_fee_rates)
    assert wallet.get_ema_fee_rate() == 21

    # send_tx clears the cache and resets the previous tx
    send_tx(100)
    _override_tx_fees(wallet, desired_fee_rates)

    # test the outgoing is weighted more than
    set_unknown_fee()
    _override_tx_fees(wallet, desired_fee_rates)
    ema_after_100 = wallet.get_ema_fee_rate()
    assert ema_after_100 == pytest.approx(73, abs=1)

    for _ in range(5):
        send_tx(1)
    _override_tx_fees(wallet, desired_fee_rates)

    set_unknown_fee()
    _override_tx_fees(wallet, desired_fee_rates)
    ema_after_lows = wallet.get_ema_fee_rate()
    assert ema_after_lows == pytest.approx(10, abs=1)

    for _ in range(1):
        send_tx(40)
    _override_tx_fees(wallet, desired_fee_rates)

    set_unknown_fee()
    _override_tx_fees(wallet, desired_fee_rates)
    ema_after_mid = wallet.get_ema_fee_rate()
    assert ema_after_mid == pytest.approx(18, abs=1)


def test_address_balance(
    test_funded_seed_wallet: Wallet,
):
    """Test that the EMA fee rate for an incoming wallet is weighted more heavily
    towards recent transactions."""

    wallet = test_funded_seed_wallet

    # check that spent utxos do not count into the address balance
    addresses = wallet.get_addresses()
    assert addresses
    total = 0
    for address in addresses:
        total += wallet.get_addr_balance(address).total

    assert total == wallet.get_balance().total
