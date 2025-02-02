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
import random
from dataclasses import dataclass
from pathlib import Path

import bdkpython as bdk
import numpy as np
import pytest
from bitcoin_usb.address_types import DescriptorInfo

from bitcoin_safe.config import UserConfig
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.pythonbdk_types import Recipient
from bitcoin_safe.tx import TxUiInfos, transaction_to_dict
from bitcoin_safe.wallet import Wallet

from ..test_helpers import test_config  # type: ignore
from ..test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_signers import test_seeds  # type: ignore

logger = logging.getLogger(__name__)
import logging


def compare_dicts(d1, d2, ignore_value="value_to_be_ignored") -> bool:
    """
    Recursively compares two dictionaries (or lists), allowing for arbitrary depth.
    If a value matches `ignore_value`, the corresponding value in the other structure
    does not affect the outcome of the comparison.

    Args:
        d1 (dict | list): First structure for comparison.
        d2 (dict | list): Second structure for comparison.
        ignore_value (any): A value in either structure that should be ignored during comparison.

    Returns:
        bool: True if the structures are identical (considering ignore_value), False otherwise.
    """
    # Handle ignore_value in direct comparison
    if d1 == ignore_value or d2 == ignore_value:
        return True

    # Check the type of d1 and d2
    if type(d1) != type(d2):
        logger.debug(f"Type mismatch: {type(d1)} != {type(d2)}")
        return False

    # If both are dictionaries
    if isinstance(d1, dict):
        if d1.keys() != d2.keys():
            logger.debug(f"Dictionary keys mismatch: {d1.keys()} != {d2.keys()}")
            return False
        for key in d1:
            if not compare_dicts(d1[key], d2[key], ignore_value):
                logger.debug(f"Mismatch at key {key}: {d1[key]} != {d2[key]}")
                return False
        return True

    # If both are lists
    if isinstance(d1, list):
        if len(d1) != len(d2):
            logger.debug(f"List length mismatch: {len(d1)} != {len(d2)}")
            return False
        for i in range(len(d1)):
            if not compare_dicts(d1[i], d2[i], ignore_value):
                logger.debug(f"Mismatch at index {i}: {d1[i]} != {d2[i]}")
                return False
        return True

    # Direct value comparison
    if d1 != d2:
        logger.debug(f"Value mismatch: {d1} != {d2}")
        return False
    return True


@dataclass
class TestWalletConfig:
    utxo_value_private: int
    utxo_value_kyc: int
    num_private: int
    num_kyc: int


@dataclass
class TestCoinControlConfig:
    opportunistic_merge_utxos: bool
    python_random_seed: int = 0


@pytest.fixture(
    scope="session",
    params=[
        TestWalletConfig(utxo_value_private=1_000_000, num_private=5, utxo_value_kyc=2_000_000, num_kyc=1)
    ],
)
def test_wallet_config(request) -> TestWalletConfig:
    return request.param


@pytest.fixture(
    scope="session",
    params=[
        TestCoinControlConfig(opportunistic_merge_utxos=True),
        TestCoinControlConfig(opportunistic_merge_utxos=False),
    ],
)
def test_coin_control_config(request) -> TestCoinControlConfig:
    return request.param


# params
# [(utxo_value_private, utxo_value_kyc)]
@pytest.fixture(scope="session")
def test_funded_wallet(
    test_config: UserConfig,
    bitcoin_core: Path,
    faucet: Faucet,
    test_wallet_config: TestWalletConfig,
    wallet_name="test_tutorial_wallet_setup",
) -> Wallet:

    descriptor_str = "wpkh([5aa39a43/84'/1'/0']tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#xaf9qzlf"

    descriptor_info = DescriptorInfo.from_str(descriptor_str=descriptor_str)
    keystore = KeyStore(
        xpub=descriptor_info.spk_providers[0].xpub,
        fingerprint=descriptor_info.spk_providers[0].fingerprint,
        key_origin=descriptor_info.spk_providers[0].key_origin,
        label="test",
        network=test_config.network,
    )
    wallet = Wallet(
        id=wallet_name,
        descriptor_str=descriptor_str,
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

    addresses_kyc = [
        wallet.get_address(force_new=True).address.as_string() for i in range(test_wallet_config.num_kyc)
    ]
    for address in addresses_kyc:
        wallet.labels.set_addr_category(address, "KYC")
        faucet.send(address, amount=test_wallet_config.utxo_value_kyc)

    faucet.mine()
    wallet.sync()

    return wallet


###############################
###### Manual coin selection    ,  spend_all_utxos=True
###############################
# no max amounts
# change address must be created
def test_manual_coin_selection(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
    test_coin_control_config: TestCoinControlConfig,
) -> None:
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = True
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000, 25_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for amount in recpient_amounts]
    recipients = [
        Recipient(address=address, amount=amount) for address, amount in zip(addresses, recpient_amounts)
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1332
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1232,
            "size": 308,
            "vsize": 308,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 1


###############################
###### Manual coin selection    ,  spend_all_utxos=True
###############################
# 1 max amount
# no change address must be created
def test_manual_coin_selection_1_max(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
    test_coin_control_config: TestCoinControlConfig,
) -> None:
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = True
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for i in range(2)]
    recipients = [
        Recipient(address=addresses[0], amount=recpient_amounts[0]),
        Recipient(
            address=addresses[1],
            checked_max_amount=True,
            amount=500,  # 500 is just to stay above the dust limit
        ),
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1239
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1108,
            "size": 277,
            "vsize": 277,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private

    expected_output_values = sorted(
        recpient_amounts
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 0


###############################
###### Manual coin selection    ,  spend_all_utxos=True
###############################
# 2 max amount
# no change address must be created
def test_manual_coin_selection_2_max(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
    test_coin_control_config: TestCoinControlConfig,
) -> None:
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = True
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000]
    estimated_max_amount_of_first_max = (input_value - sum(recpient_amounts)) // 2
    addresses = [wallet.get_address(force_new=True).address.as_string() for i in range(3)]
    recipients = [
        Recipient(address=addresses[0], amount=recpient_amounts[0]),
        Recipient(
            address=addresses[1],
            checked_max_amount=True,
            amount=estimated_max_amount_of_first_max,  # bdk cant handle multiple max amounts natively
        ),
        Recipient(
            address=addresses[2],
            checked_max_amount=True,
            amount=500,  # 500 is just to stay above the dust limit
        ),
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1332
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1232,
            "size": 308,
            "vsize": 308,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected

    expected_output_values = sorted(
        recpient_amounts
        + [estimated_max_amount_of_first_max]
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
            - estimated_max_amount_of_first_max
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 0


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=False
# no max amount
# 1 change address must be created
def test_category_coin_selection(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=False)
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = False
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000, 25_000, 35_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for amount in recpient_amounts]
    recipients = [
        Recipient(address=address, amount=amount) for address, amount in zip(addresses, recpient_amounts)
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 609
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 700,
            "size": 175,
            "vsize": 175,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # only 1 input is needed
    num_inputs_needed = 1 + sum(recpient_amounts) // test_wallet_config.utxo_value_private
    assert len(tx_dict["input"]) == num_inputs_needed

    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            num_inputs_needed * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 1


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=False
# 1 max amount
# no change address must be created
def test_category_coin_selection_1_max(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=False)
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = False
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for i in range(2)]
    recipients = [
        Recipient(address=addresses[0], amount=recpient_amounts[0]),
        Recipient(
            address=addresses[1],
            checked_max_amount=True,
            amount=500,  # 500 is just to stay above the dust limit
        ),
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1239
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1108,
            "size": 277,
            "vsize": 277,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # only 1 input is needed
    assert len(tx_dict["input"]) == test_wallet_config.num_private

    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 0


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=False
# 2 max amount
# no change address must be created
def test_category_coin_selection_2_max(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=False)
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = True
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000]
    estimated_max_amount_of_first_max = (input_value - sum(recpient_amounts)) // 2
    addresses = [wallet.get_address(force_new=True).address.as_string() for i in range(3)]
    recipients = [
        Recipient(address=addresses[0], amount=recpient_amounts[0]),
        Recipient(
            address=addresses[1],
            checked_max_amount=True,
            amount=estimated_max_amount_of_first_max,  # bdk cant handle multiple max amounts natively
        ),
        Recipient(
            address=addresses[2],
            checked_max_amount=True,
            amount=500,  # 500 is just to stay above the dust limit
        ),
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1332
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1232,
            "size": 308,
            "vsize": 308,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [estimated_max_amount_of_first_max]
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
            - estimated_max_amount_of_first_max
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 0


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=False
# 6 max amount
# no change address must be created
def test_category_coin_selection_6_max(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=False)
    wallet = test_funded_wallet

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = True
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000]
    num_max_recipients = 6
    addresses = [
        wallet.get_address(force_new=True).address.as_string() for i in range(num_max_recipients + 1)
    ]
    estimated_max_amount_of_first_max = (input_value - sum(recpient_amounts)) // num_max_recipients
    recipients = [Recipient(address=addresses[0], amount=recpient_amounts[0])] + [
        Recipient(
            address=address,
            checked_max_amount=True,
            amount=estimated_max_amount_of_first_max,  # bdk cant handle multiple max amounts natively
        )
        for address in addresses[1:]
    ]

    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 1704
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 1728,
            "size": 432,
            "vsize": 432,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            test_wallet_config.num_private * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
            - estimated_max_amount_of_first_max * (num_max_recipients - 1)
        ]
        + [estimated_max_amount_of_first_max] * (num_max_recipients - 1)
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 0


#######################################################################################################################################################################################################################################################################################
##  now  opportunistic_merge_utxos=True
##################################################################################################################################################################################################################################################################################################################################################################################################################################################


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=True
# no max amount
# 1 change address must be created
def test_category_coin_selection_opportunistic(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=True, python_random_seed=1)
    wallet = test_funded_wallet

    random.seed(test_coin_control_config.python_random_seed)
    np.random.seed(test_coin_control_config.python_random_seed)

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = False
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000, 25_000, 35_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for amount in recpient_amounts]
    recipients = [
        Recipient(address=address, amount=amount) for address, amount in zip(addresses, recpient_amounts)
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 813
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 864,
            "size": 216,
            "vsize": 216,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # the python_random_seed=2 leads to 2 inputs being chosen, even though only 1 is needed
    num_inputs_chosen = 2
    assert len(tx_dict["input"]) == num_inputs_chosen

    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            num_inputs_chosen * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 1


###############################
###### Category coin selection    ,  spend_all_utxos=False
###############################
# opportunistic_merge_utxos=True
# no max amount
# 1 change address must be created
# different seed
def test_category_coin_selection_opportunistic_different_seed(
    test_funded_wallet: Wallet,
    test_wallet_config: TestWalletConfig,
) -> None:
    test_coin_control_config = TestCoinControlConfig(opportunistic_merge_utxos=True, python_random_seed=42)
    wallet = test_funded_wallet

    random.seed(test_coin_control_config.python_random_seed)
    np.random.seed(test_coin_control_config.python_random_seed)

    txinfos = TxUiInfos()
    txinfos.spend_all_utxos = False
    txinfos.utxo_dict = {
        str(utxo.outpoint): utxo
        for utxo in wallet.get_all_utxos()
        if wallet.labels.get_category(utxo.address) == "Private"
    }
    input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values()])
    assert input_value == test_wallet_config.num_private * test_wallet_config.utxo_value_private
    assert len(txinfos.utxo_dict) == test_wallet_config.num_private
    txinfos.fee_rate = 3
    txinfos.opportunistic_merge_utxos = test_coin_control_config.opportunistic_merge_utxos
    txinfos.main_wallet_id = wallet.id

    recpient_amounts = [15_000, 25_000, 35_000]
    addresses = [wallet.get_address(force_new=True).address.as_string() for amount in recpient_amounts]
    recipients = [
        Recipient(address=address, amount=amount) for address, amount in zip(addresses, recpient_amounts)
    ]
    txinfos.recipients = recipients

    builder_infos = wallet.create_psbt(txinfos)
    psbt: bdk.PartiallySignedTransaction = builder_infos.builder_result.psbt

    tx_dict = transaction_to_dict(psbt.extract_tx(), wallet.network)
    assert psbt.fee_amount() == 609
    assert compare_dicts(
        tx_dict,
        {
            "txid": "value_to_be_ignored",
            "weight": 700,
            "size": 175,
            "vsize": 175,
            "serialize": "value_to_be_ignored",
            "is_coin_base": False,
            "is_explicitly_rbf": True,
            "is_lock_time_enabled": True,
            "version": 1,
            "lock_time": "value_to_be_ignored",
            "input": "value_to_be_ignored",
            "output": "value_to_be_ignored",
        },
    )
    # the python_random_seed=42 leads to 1 inputs being chosen
    num_inputs_chosen = 1
    assert len(tx_dict["input"]) == num_inputs_chosen

    # bdk gives random sorting, so i have to compare sorted lists
    # if utxo_value_private != utxo_value_kyc, this check will implicitly
    # also check if the correct coin categories were selected
    expected_output_values = sorted(
        recpient_amounts
        + [
            num_inputs_chosen * test_wallet_config.utxo_value_private
            - psbt.fee_amount()
            - sum(recpient_amounts)
        ]
    )
    values = sorted([output["value"] for output in tx_dict["output"]])
    assert values == expected_output_values

    # check that the recipient addresses are correct
    output_addresses = [output["address"] for output in tx_dict["output"]]
    assert len(set(output_addresses) - set(addresses)) == 1
