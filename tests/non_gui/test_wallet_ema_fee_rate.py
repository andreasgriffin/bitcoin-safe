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

import pytest
from bitcoin_usb.address_types import AddressTypes, DescriptorInfo, SimplePubKeyProvider
from bitcoin_usb.software_signer import SoftwareSigner
from bitcoin_safe.config import UserConfig

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.wallet import Wallet

from ..non_gui.test_wallet import create_test_seed_keystores
from ..setup_fulcrum import Faucet
from ..util import make_psbt, wait_for_funds, wait_for_tx
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


# params
# [(utxo_value_private, utxo_value_kyc)]
@pytest.fixture(scope="session")
def test_funded_seed_wallet(
    test_config_session: UserConfig,
    faucet: Faucet,
    test_wallet_config_seed: TestWalletConfig,
    wallet_name="test_tutorial_wallet_setup",
) -> Wallet:
    """Test funded seed wallet."""
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=faucet.network,
        test_seed_offset=20,
    )[0]

    descriptor_info = DescriptorInfo(
        address_type=AddressTypes.p2wpkh,
        spk_providers=[SimplePubKeyProvider.from_hwi(keystore.to_hwi_pubkey_provider())],
        threshold=1,
    )
    wallet = Wallet(
        id=wallet_name,
        descriptor_str=descriptor_info.get_descriptor_str(faucet.network),
        keystores=[keystore],
        network=test_config_session.network,
        config=test_config_session,
    )

    # fund the wallet
    addresses_private = [
        str(wallet.get_address(force_new=True).address) for i in range(test_wallet_config_seed.num_private)
    ]
    for address in addresses_private:
        wallet.labels.set_addr_category(address, "Private")
        faucet.send(address, amount=test_wallet_config_seed.utxo_value_private)

    faucet.mine()
    wait_for_funds(wallet)

    return wallet


def test_ema_fee_rate_weights_recent_heavier(
    test_funded_seed_wallet: Wallet,
    faucet: Faucet,
) -> Wallet:
    """Test that the EMA fee rate for an incoming wallet is weighted more heavily
    towards recent transactions."""

    wallet = test_funded_seed_wallet

    def send_tx(fee_rate=100):
        """Send tx."""
        psbt_for_signing = make_psbt(
            bdk_wallet=wallet.bdkwallet,
            network=wallet.network,
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
        # to include the tx into a block and create a sorting of the txs
        # otherwise the order might be random and ema is random
        faucet.mine()

        wait_for_tx(wallet, str(tx.compute_txid()))

    # incoming txs have no fee rate (rpc doesnt seem to fill the fee field)
    assert round(wallet.get_ema_fee_rate(), 1) == MIN_RELAY_FEE

    # test that it takes in account the icoming txs, if a fee is known
    txdetails = wallet.sorted_delta_list_transactions()
    txdetails[0].fee = 21 * txdetails[0].vsize
    assert wallet.get_ema_fee_rate() == 21

    # send_tx clears the cache and resets the previous tx
    send_tx(100)

    # test the outgoing is weighted more than
    assert wallet.get_ema_fee_rate() == pytest.approx(66.7, abs=0.1)

    for i in range(5):
        send_tx(1)

    assert wallet.get_ema_fee_rate() == pytest.approx(6.8, abs=0.1)

    for i in range(1):
        send_tx(40)

    assert wallet.get_ema_fee_rate() == pytest.approx(14.5, abs=0.1)


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
