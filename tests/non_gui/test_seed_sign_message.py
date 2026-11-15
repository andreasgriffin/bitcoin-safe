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

from bitcoin_usb.software_signer import SoftwareSigner

from bitcoin_safe.descriptors import get_address_bip32_path
from bitcoin_safe.message_signature_verifyer import MessageSignatureVerifyer
from bitcoin_safe.pythonbdk_types import AddressInfoMin
from bitcoin_safe.signer import SeedSignOption, seed_sign_options
from bitcoin_safe.wallet import Wallet

from .utils import create_multisig_protowallet


def _wallet(signers: int, test_config, threshold: int = 1) -> Wallet:  # type: ignore[no-untyped-def]
    protowallet = create_multisig_protowallet(
        threshold=threshold,
        signers=signers,
        key_origins=[f"m/{i + 84}h/1h/0h" for i in range(signers)],
        wallet_id=f"seed signer {signers}",
        network=test_config.network,
    )
    return Wallet.from_protowallet(protowallet=protowallet, config=test_config, loop_in_thread=None)


def _address_info(wallet: Wallet, is_change: bool = False) -> AddressInfoMin:
    address = str(wallet.get_force_new_address(is_change=is_change).address)
    address_info = wallet.get_address_info_min(address)
    assert address_info
    return address_info


def test_seed_sign_options_empty_without_seed(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=1, test_config=test_config)
    for keystore in wallet.keystores:
        assert keystore
        keystore.mnemonic = None

    assert seed_sign_options(wallet, _address_info(wallet)) == []


def test_seed_sign_options_single_seed_single_sig(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=1, test_config=test_config)
    address_info = _address_info(wallet)

    options = seed_sign_options(wallet, address_info)

    assert len(options) == 1
    assert isinstance(options[0].signer, SoftwareSigner)
    assert options[0].bip32_path == get_address_bip32_path(
        descriptor_str=str(wallet.multipath_descriptor), kind=address_info.keychain, index=address_info.index
    )


def test_seed_sign_options_one_per_seed_in_multisig(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=3, test_config=test_config, threshold=2)
    address_info = _address_info(wallet, is_change=True)

    options = seed_sign_options(wallet, address_info)

    assert len(options) == 3
    assert [option.bip32_path for option in options] == [
        f"m/{i + 84}h/1h/0h/1/{address_info.index}" for i in range(3)
    ]


def test_seed_sign_options_skip_keystores_without_seed(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=3, test_config=test_config, threshold=2)
    keystore = wallet.keystores[1]
    assert keystore
    keystore.mnemonic = None

    options = seed_sign_options(wallet, _address_info(wallet))

    assert len(options) == 2


def test_seed_sign_options_dedupes_same_seed_in_two_keystores(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=2, test_config=test_config, threshold=1)
    first, second = wallet.keystores
    assert first and second
    second.fingerprint = first.fingerprint
    second.mnemonic = first.mnemonic
    first.mnemonic = None

    options = seed_sign_options(wallet, _address_info(wallet))

    assert len(options) == 1


def test_seed_sign_options_match_fingerprint_case_insensitively(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=2, test_config=test_config, threshold=1)
    for keystore in wallet.keystores:
        assert keystore
        keystore.fingerprint = keystore.fingerprint.upper()

    assert len(seed_sign_options(wallet, _address_info(wallet))) == 2


def test_seed_sign_option_label_is_signer_label_and_uppercase_fingerprint(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=1, test_config=test_config)
    keystore = wallet.keystores[0]
    assert keystore
    keystore.description = "My seed"

    options = seed_sign_options(wallet, _address_info(wallet))

    assert [option.label for option in options] == [
        f"{keystore.hardware_signer_label()} - {keystore.fingerprint.upper()}"
    ]


def test_seed_signature_verifies_against_wallet_address(test_config) -> None:  # type: ignore[no-untyped-def]
    wallet = _wallet(signers=1, test_config=test_config)
    address_info = _address_info(wallet)
    option: SeedSignOption = seed_sign_options(wallet, address_info)[0]

    message = "hello from the seed"
    signature = option.signer.sign_message(message=message, bip32_path=option.bip32_path)

    result = MessageSignatureVerifyer().verify_message(address_info.address, message, signature)
    assert result.match, result.error
