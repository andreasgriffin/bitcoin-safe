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

import bdkpython as bdk
from bitcoin_qr_tools.signer_info import SignerInfo
from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.config import UserConfig
from bitcoin_safe.keystore import KeyStore, sorted_keystores
from bitcoin_safe.wallet_util import WalletDifferenceType

from .test_signers import test_seeds
from .utils import create_test_seed_keystores

logger = logging.getLogger(__name__)


def test_dump(test_config: UserConfig):
    "Tests if dump works correctly"
    network = bdk.Network.REGTEST

    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i+41}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]

    keystore_restored = KeyStore.from_dump(keystore.dump())
    assert keystore.is_equal(keystore_restored)


def test_is_equal():
    network = bdk.Network.REGTEST

    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]

    # xpub
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    # blank out xpub
    keystore2.xpub += " "
    assert not keystore.is_equal(keystore2)

    # fingerprint
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.fingerprint = keystore2.fingerprint.lower()
    assert not keystore.is_equal(keystore2)
    keystore2.fingerprint = keystore2.format_fingerprint(keystore2.fingerprint)
    assert keystore.is_equal(keystore2)

    # key_origin
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.key_origin = keystore2.key_origin.replace("h", "'")
    assert not keystore.is_equal(keystore2)
    keystore2.key_origin = keystore2.format_key_origin(keystore2.key_origin)
    assert keystore.is_equal(keystore2)

    # label
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.label = "a"
    assert not keystore.is_equal(keystore2)

    # network
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.network = bdk.Network.BITCOIN
    assert not keystore.is_equal(keystore2)

    # mnemonic
    keystore2 = create_test_seed_keystores(
        signers=2,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[1]
    assert not keystore.is_equal(keystore2)

    # description
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.description = "ddd"
    assert not keystore.is_equal(keystore2)

    # derivation_path
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.derivation_path = " "
    assert not keystore.is_equal(keystore2)


def test_get_differences_address_fields():
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore2 = keystore.clone()
    keystore2.xpub += " "
    diffs = keystore.get_differences(keystore2)
    assert len(diffs) == 1
    assert diffs[0].key == "xpub"
    assert diffs[0].type == WalletDifferenceType.ImpactOnAddresses


def test_get_differences_metadata_fields():
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore2 = keystore.clone()
    keystore2.label = "new"
    diffs = keystore.get_differences(keystore2)
    assert len(diffs) == 1
    assert diffs[0].key == "label"
    assert diffs[0].type == WalletDifferenceType.NoImpactOnAddresses


def test_is_seed_valid():
    assert KeyStore.is_seed_valid(test_seeds[0])
    assert not KeyStore.is_seed_valid("not a valid seed")


def test_is_xpub_valid():
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    assert KeyStore.is_xpub_valid(keystore.xpub, keystore.network)
    assert not KeyStore.is_xpub_valid(keystore.xpub[:-4], keystore.network)


def test_clone_creates_equal_object():
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    clone = keystore.clone()
    assert keystore.is_equal(clone)
    assert keystore is not clone


def test_from_other_keystore_copies_attributes():
    ks1 = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    ks2 = create_test_seed_keystores(
        signers=1,
        key_origins=["m/42h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
        test_seed_offset=1,
    )[0]
    ks1.from_other_keystore(ks2)
    assert ks1.is_equal(ks2)


def test_is_identical_to_simple_pubkey_provider():
    ks = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[0]
    spk = SimplePubKeyProvider(ks.xpub, ks.fingerprint, ks.key_origin)
    assert ks.is_identical_to(spk)
    spk2 = SimplePubKeyProvider(ks.xpub, "FFFFFFFF", ks.key_origin)
    assert not ks.is_identical_to(spk2)


def test_from_signer_info_defaults():
    base = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    signer = SignerInfo(base.fingerprint, base.key_origin, base.xpub)
    ks = KeyStore.from_signer_info(
        signer,
        network=base.network,
        default_label="lbl",
        default_derivation_path="/<0;1>/*",
    )
    assert ks.label == "lbl"
    assert ks.derivation_path == "/<0;1>/*"


def test_from_signer_info_overrides():
    base = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    signer = SignerInfo(
        base.fingerprint,
        base.key_origin,
        base.xpub,
        derivation_path="/1/*",
        name="custom",
    )
    ks = KeyStore.from_signer_info(
        signer,
        network=base.network,
        default_label="lbl",
        default_derivation_path="/<0;1>/*",
    )
    assert ks.label == "custom"
    assert ks.derivation_path == "/1/*"


def test_sorted_keystores_orders_by_xpub():
    ks1 = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    ks2 = create_test_seed_keystores(
        signers=1,
        key_origins=["m/42h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
        test_seed_offset=1,
    )[0]
    ordered = sorted_keystores([ks2, ks1])
    assert [k.xpub for k in ordered] == sorted([ks1.xpub, ks2.xpub])


def test_network_consistent():
    bacon_xpub = "xpub6DEzNop46vmxR49zYWFnMwmEfawSNmAMf6dLH5YKDY463twtvw1XD7ihwJRLPRGZJz799VPFzXHpZu6WdhT29WnaeuChS6aZHZPFmqczR5K"
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(bacon_xpub), bdk.Network.BITCOIN)
    assert not KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(bacon_xpub), bdk.Network.TESTNET4
    )

    testnet_tpub = "tpubDDyGGnd9qGbDsccDSe2imVHJPd96WysYkMVAf95PWzbbCmmKHSW7vLxvrTW3HsAau9MWirkJsyaALGJwqwcReu3LZVMg6XbRgBNYTtKXeuD"
    assert KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.TESTNET4
    )
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.REGTEST)
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.TESTNET)
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.SIGNET)
    assert not KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.BITCOIN
    )
