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
from typing import List, Optional

import bdkpython as bdk
import pytest
from bitcoin_usb.software_signer import derive

from bitcoin_safe.config import UserConfig
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.wallet import ProtoWallet, Wallet, WalletInputsInconsistentError

from ..test_helpers import test_config, test_config_main_chain  # type: ignore
from .test_signers import bacon_seed, test_seeds

logger = logging.getLogger(__name__)


def create_keystore(seed_str: str, key_origin: str, label: str, network=bdk.Network.REGTEST) -> KeyStore:
    mnemonic = bdk.Mnemonic.from_string(seed_str).as_string()
    key_origin = key_origin
    xpub, fingerprint = derive(mnemonic, key_origin, network)

    return KeyStore(
        xpub, fingerprint, key_origin, label, network=network, mnemonic=seed_str, description=label
    )


def create_test_seed_keystores(
    signers: int, key_origins: List[str], network=bdk.Network.REGTEST, test_seed_offset=0
) -> List[KeyStore]:
    keystores: List[KeyStore] = []
    for i, seed_str in enumerate(test_seeds[test_seed_offset : test_seed_offset + signers]):
        keystores.append(
            create_keystore(seed_str=seed_str, key_origin=key_origins[i], label=f"{i}", network=network)
        )
    return keystores


def create_multisig_protowallet(
    threshold: int, signers: int, key_origins: List[str], wallet_id="some id", network=bdk.Network.REGTEST
) -> ProtoWallet:

    keystores: List[Optional[KeyStore]] = create_test_seed_keystores(signers, key_origins, network)  # type: ignore

    return ProtoWallet(
        threshold=threshold,
        keystores=keystores,
        network=network,
        wallet_id=wallet_id,
    )


def test_protowallet_import_export_keystores(test_config: UserConfig):
    "Tests if keystores are correctly handles in Wallet.from_protowallet and wallet.as_protowallet()"
    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        wallet_id="some id",
        network=test_config.network,
    )

    expected_keystores = [
        {
            "xpub": "tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA",
            "fingerprint": "5AA39A43",
            "key_origin": "m/41h/1h/0h/2h",
            "derivation_path": "/0/*",
            "network": test_config.network,
            "label": "0",
            "mnemonic": "peanut all ghost appear daring exotic choose disease bird ready love salad",
            "description": "0",
        },
        {
            "xpub": "tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX",
            "fingerprint": "5459F23B",
            "key_origin": "m/42h/1h/0h/2h",
            "derivation_path": "/0/*",
            "network": test_config.network,
            "label": "1",
            "mnemonic": "chair useful hammer word edge hat title drastic priority chalk city gentle",
            "description": "1",
        },
        {
            "xpub": "tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1",
            "fingerprint": "A302D279",
            "key_origin": "m/43h/1h/0h/2h",
            "derivation_path": "/0/*",
            "network": test_config.network,
            "label": "2",
            "mnemonic": "expand text improve perfect sponsor gesture flush wolf poem blouse kangaroo lesson",
            "description": "2",
        },
        {
            "xpub": "tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv",
            "fingerprint": "BAC81685",
            "key_origin": "m/44h/1h/0h/2h",
            "derivation_path": "/0/*",
            "network": test_config.network,
            "label": "3",
            "mnemonic": "base episode pyramid share teach degree ocean copper merit auto source noble",
            "description": "3",
        },
        {
            "xpub": "tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy",
            "fingerprint": "6627F20A",
            "key_origin": "m/45h/1h/0h/2h",
            "derivation_path": "/0/*",
            "network": test_config.network,
            "label": "4",
            "mnemonic": "scout clarify assist brain moon canvas rack memory coast gauge short child",
            "description": "4",
        },
    ]

    multipath_descriptor = protowallet.to_multipath_descriptor()
    assert multipath_descriptor
    # descriptor was compared to sparrow and is (up to ordering) identical
    assert (
        multipath_descriptor.as_string()
        == "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    )

    wallet = Wallet.from_protowallet(protowallet=protowallet, config=test_config)

    assert [keystore.__dict__ for keystore in protowallet.keystores] == expected_keystores
    assert [keystore.__dict__ for keystore in wallet.keystores] == expected_keystores
    assert [keystore.__dict__ for keystore in wallet.as_protowallet().keystores] == expected_keystores


def test_protowallet_import_export_descriptor(test_config: UserConfig):
    "Tests if keystores are correctly handles in Wallet.from_protowallet and wallet.as_protowallet()"
    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        wallet_id="some id",
        network=test_config.network,
    )

    multipath_descriptor = protowallet.to_multipath_descriptor()
    assert multipath_descriptor
    # descriptor was compared to sparrow and is (up to ordering) identical
    expected_descriptor = "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    assert multipath_descriptor.as_string() == expected_descriptor

    wallet = Wallet.from_protowallet(protowallet=protowallet, config=test_config)

    assert wallet.multipath_descriptor.as_string() == expected_descriptor


def test_create_from_protowallet_and_from_descriptor_string(test_config: UserConfig):
    "Tests if keystores are correctly handles in Wallet.from_protowallet and wallet.as_protowallet()"
    wallet_id = "some id"
    expected_descriptor = "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=test_config.network,
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )

    ## and now via protowallet

    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        wallet_id=wallet_id,
        network=test_config.network,
    )
    wallet2 = Wallet.from_protowallet(protowallet=protowallet, config=test_config)

    # compare
    assert wallet.multipath_descriptor.as_string_private() == wallet2.multipath_descriptor.as_string_private()
    assert [keystore.__dict__ for keystore in wallet.keystores] == [
        keystore.__dict__ for keystore in wallet2.keystores
    ]
    assert wallet.is_essentially_equal(wallet2)
    assert wallet2.is_essentially_equal(wallet)


def test_is_multisig(test_config: UserConfig):
    wallet_id = "some id"
    descriptor = "wpkh([5aa39a43/84'/1'/0']tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#xaf9qzlf"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/84h/1h/0h" for i in range(5)],
        network=test_config.network,
    )
    # roll keystores
    keystores = keystores[3:] + keystores[:3]

    # no exception raised
    wallet = Wallet(
        id=wallet_id,
        descriptor_str=descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )


def test_is_multisig2(test_config: UserConfig):
    wallet_id = "some id"
    expected_descriptor = "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=test_config.network,
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )

    assert wallet.is_multisig()


def test_dump(test_config: UserConfig):
    "Tests if dump works correctly"
    wallet_id = "some id"
    expected_descriptor = "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=test_config.network,
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )

    dct = wallet.dump()
    walllet_restored = Wallet.from_dump(
        dct=dct,
        class_kwargs={"Wallet": {"config": test_config}},
    )

    assert walllet_restored.is_essentially_equal(wallet)


def test_correct_addresses(test_config: UserConfig):
    wallet_id = "some id"
    expected_descriptor = "wpkh([5aa39a43/84h/1h/0h]tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#345tvr45"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/84h/1h/0h" for i in range(5)],
        network=test_config.network,
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )

    assert wallet.get_receiving_addresses()[0] == "bcrt1q3qt0n3z69sds3u6zxalds3fl67rez4u2wm4hes"
    wallet.get_address(force_new=True, is_change=False)
    wallet.clear_cache()
    assert wallet.get_receiving_addresses()[1] == "bcrt1qmx7ke6j0amadeca65xqxpwh0utju5g3uka2sj5"

    assert wallet.get_change_addresses()[0] == "bcrt1qagm6afe7xh47cvruwav37gu3ajng8pptpsag37"
    wallet.get_address(force_new=True, is_change=True)
    wallet.clear_cache()
    assert wallet.get_change_addresses()[1] == "bcrt1qgdv8n5mnwtat2ffku0m4swmcy7jmpgv4afz7rd"


def test_inconsistent_key_origins(test_config: UserConfig):
    wallet_id = "some id"
    expected_descriptor = "wpkh([5aa39a43/84h/1h/0h]tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#345tvr45"
    network = test_config.network

    # wrong derivation path
    keystores = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/24h/1h/0h" for i in range(5)],
        network=test_config.network,
    )

    with pytest.raises(WalletInputsInconsistentError) as exc_info:
        wallet = Wallet(
            id=wallet_id,
            descriptor_str=expected_descriptor,
            keystores=keystores,
            network=network,
            config=test_config,
        )


def test_inconsistent_seed_with_descriptor(test_config: UserConfig):
    wallet_id = "some id"
    expected_descriptor = "wpkh([5aa39a43/84h/1h/0h]tpubDD2ww8jti4Xc8vkaJH2yC1r7C9TVb9bG3kTi6BFm5w3aAZmtFHktK6Mv2wfyBvSPqV9QeH1QXrmHzabuNh1sgRtAsUoG7dzVjc9WvGm78PD/<0;1>/*)#345tvr45"
    network = test_config.network

    # wrong derivation path
    keystores = create_test_seed_keystores(
        signers=2,
        key_origins=[f"m/84h/1h/0h" for i in range(5)],
        network=test_config.network,
    )[1:]

    with pytest.raises(WalletInputsInconsistentError) as exc_info:
        wallet = Wallet(
            id=wallet_id,
            descriptor_str=expected_descriptor,
            keystores=keystores,
            network=network,
            config=test_config,
        )


def test_mixed_keystores_is_consistent(test_config: UserConfig):
    wallet_id = "some id"
    expected_descriptor = "wsh(sortedmulti(2,[5aa39a43/41'/1'/0'/2']tpubDDxYDzeDqFbdktXDTMAQpZPgRj3uMk784q8kHyGsC6zUNn2YUbNgZdK3GuXsPjMk8Gt7AEsAGwccd6dbcxaCWJwpRC1rKy1xPLicuNyjLaA/<0;1>/*,[5459f23b/42'/1'/0'/2']tpubDE2ECxCKZhscAKFA2NG2VGzeQow9ZnSrYz8VxmRKPvNCwNv8rg6wXE2hNuB4vdLKfBf6enmrn2zmkLTt1h1fiLEXxTt9tPSXJCTogzYmnfX/<0;1>/*,[a302d279/43'/1'/0'/2']tpubDEbicbTmJ1g9sY7KynzsrodCDp5CoFcPPnxNHpDAbJsufTLTJKrtCo4GvUdgby5NXA8xppgXzawmHYgQqDSB3R6i1YjtS1Ko774FSVqmpA1/<0;1>/*,[6627f20a/45'/1'/0'/2']tpubDEk3xNvJFZN72ikNADMXKyHzX6EEeaANeurUoyBvzxZvxufRqXH1ECSUyDK7hw6YvSYdxmnGXKfpHAxKwYyZpWdjRnDtgoXicwGWY6nujAy/<0;1>/*,[bac81685/44'/1'/0'/2']tpubDEtp92LMMkxJx7cBdUJ68LE2oLApiNYKAyrgHCewGNbWBfumnPXUYamFbGUHM7dfYkJQtSVuj3scqQhPcgy9yv9xr53JVubYQpMby137qQv/<0;1>/*))#gtzk7j0k"
    network = test_config.network

    keystores = create_test_seed_keystores(
        signers=5,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=test_config.network,
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=keystores,
        network=network,
        config=test_config,
    )

    assert wallet.is_multisig()


def test_wallet_dump_and_restore(test_config: UserConfig):
    "Tests if dump works correctly"
    network = test_config.network

    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=5,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        wallet_id="some id",
        network=network,
    )
    wallet = Wallet.from_protowallet(protowallet=protowallet, config=test_config)
    dump = wallet.dump()

    restored_wallet = Wallet.from_dump(dct=dump, class_kwargs={"Wallet": {"config": test_config}})

    assert wallet.is_essentially_equal(restored_wallet)

    assert len(wallet.keystores) == len(restored_wallet.keystores)
    for org_keystore, restored_keystore in zip(wallet.keystores, restored_wallet.keystores):
        assert org_keystore.is_equal(restored_keystore)


def test_bacon_wallet_tx_are_fetched(test_config_main_chain: UserConfig):
    wallet_id = "bacon wallet"
    expected_descriptor = "wpkh([9a6a2580/84h/0h/0h]xpub6DEzNop46vmxR49zYWFnMwmEfawSNmAMf6dLH5YKDY463twtvw1XD7ihwJRLPRGZJz799VPFzXHpZu6WdhT29WnaeuChS6aZHZPFmqczR5K/<0;1>/*)#fkxd7j3k"

    keystore = create_keystore(
        seed_str=bacon_seed, key_origin="m/84h/0h/0h", label=wallet_id, network=bdk.Network.BITCOIN
    )

    wallet = Wallet(
        id=wallet_id,
        descriptor_str=expected_descriptor,
        keystores=[keystore],
        network=test_config_main_chain.network,
        config=test_config_main_chain,
    )

    assert not wallet.is_multisig()

    assert wallet.get_addresses()[0] == "bc1qyngkwkslw5ng4v7m42s8t9j6zldmhyvrnnn9k5"
    wallet.sync()

    tx_list = wallet.sorted_delta_list_transactions()
    assert len(tx_list) >= 28
    assert tx_list[0].txid == "5d321554674865dffb7a5406002ba5d68d4819d0eff805393d4917921d68f3c5"
