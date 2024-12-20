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


import logging
from pathlib import Path

import pytest
from bitcoin_usb.address_types import AddressTypes, DescriptorInfo, SimplePubKeyProvider
from bitcoin_usb.software_signer import SoftwareSigner

from bitcoin_safe.config import MIN_RELAY_FEE, UserConfig
from bitcoin_safe.wallet import Wallet
from tests.non_gui.test_wallet import create_test_seed_keystores
from tests.test_util import make_psbt

from ..test_helpers import test_config  # type: ignore
from ..test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_wallet_coin_select import (  # type: ignore
    TestWalletConfig,
    test_wallet_config,
)

logger = logging.getLogger(__name__)
import logging


# params
# [(utxo_value_private, utxo_value_kyc)]
@pytest.fixture(scope="session")
def test_funded_seed_wallet(
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    test_wallet_config: TestWalletConfig,
    wallet_name="test_tutorial_wallet_setup",
) -> Wallet:

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
        descriptor_str=descriptor_info.get_bdk_descriptor(faucet.network).as_string_private(),
        keystores=[keystore],
        network=test_config.network,
        config=test_config,
    )

    # fund the wallet
    addresses_private = [
        wallet.get_address(force_new=True).address.as_string() for i in range(test_wallet_config.num_private)
    ]
    for address in addresses_private:
        wallet.labels.set_addr_category(address, "Private")
        faucet.send(address, amount=test_wallet_config.utxo_value_private)

    faucet.mine()
    wallet.sync()

    return wallet


def test_ema_fee_rate_weights_recent_heavier(
    test_funded_seed_wallet: Wallet,
    faucet: Faucet,
) -> Wallet:
    wallet = test_funded_seed_wallet

    def send_tx(fee_rate=100):
        psbt_for_signing = make_psbt(
            bdk_wallet=wallet.bdkwallet,
            network=wallet.network,
            destination_address=wallet.get_addresses()[0],
            amount=1000,
            fee_rate=fee_rate,
        )

        signer = SoftwareSigner(mnemonic=wallet.keystores[0].mnemonic, network=wallet.network)
        signed_psbt = signer.sign_psbt(psbt_for_signing)

        tx = signed_psbt.extract_tx()
        wallet.blockchain.broadcast(tx)
        # to include the tx into a block and create a sorting of the txs
        # otherwise the order might be random and ema is random
        faucet.mine()

        wallet.sync()
        wallet.clear_cache()

    # incoming txs have no fee rate (rpc doesnt seem to fill the fee field)
    assert wallet.get_ema_fee_rate() == MIN_RELAY_FEE

    # test that it takes in account the icoming txs, if a fee is known
    txdetails = wallet.sorted_delta_list_transactions()
    txdetails[0].fee = 21 * txdetails[0].transaction.vsize()
    assert wallet.get_ema_fee_rate() == 21

    # send_tx clears the cache and removes the previous incoming fee
    send_tx(100)

    # test the outgoing is weighted more than
    assert wallet.get_ema_fee_rate() == pytest.approx(100, abs=0.1)

    for i in range(5):
        send_tx(1)

    assert wallet.get_ema_fee_rate() == pytest.approx(37.3, abs=0.1)

    for i in range(1):
        send_tx(40)

    assert wallet.get_ema_fee_rate() == pytest.approx(37.79, abs=0.1)

    return wallet
