#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging

import bdkpython as bdk
from bitcoin_qr_tools.signer_info import SignerInfo
from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.keystore import KeyStore, sorted_keystores
from bitcoin_safe.wallet_util import WalletDifferenceType

from ..helpers import TestConfig
from .test_signers import test_seeds
from .utils import create_test_seed_keystores

logger = logging.getLogger(__name__)


def test_dump(test_config: TestConfig) -> None:
    """Tests if dump works correctly."""
    network = bdk.Network.REGTEST

    # Create a keystore, dump it, and ensure round-trip equality.
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i + 41}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]

    keystore_restored = KeyStore.from_dump(keystore.dump())
    assert keystore.is_equal(keystore_restored)


def test_is_equal() -> None:
    """Test is equal."""
    network = bdk.Network.REGTEST

    # Base keystore used for comparison.
    keystore = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]

    # xpub
    # Modifying xpub should break equality.
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    # blank out xpub
    keystore2.xpub += " "
    assert not keystore.is_equal(keystore2)

    # fingerprint
    # Fingerprint normalization should restore equality.
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
    # Key origin formatting differences should be normalized.
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.key_origin = keystore2.key_origin.replace("h", "'")
    assert not keystore.is_equal(keystore2)
    keystore2.key_origin = keystore2.format_key_origin(keystore2.key_origin)
    assert keystore.is_equal(keystore2)

    # network
    # Network differences should break equality.
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.network = bdk.Network.BITCOIN
    assert not keystore.is_equal(keystore2)

    # mnemonic
    # Different mnemonic should break equality.
    keystore2 = create_test_seed_keystores(
        signers=2,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[1]
    assert not keystore.is_equal(keystore2)

    # description
    # Description changes should break equality.
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.description = "ddd"
    assert not keystore.is_equal(keystore2)

    # derivation_path
    # Derivation path differences should break equality.
    keystore2 = create_test_seed_keystores(
        signers=1,
        key_origins=[f"m/{i}h/1h/0h/2h" for i in range(5)],
        network=network,
    )[0]
    keystore2.derivation_path = " "
    assert not keystore.is_equal(keystore2)


def test_get_differences_address_fields() -> None:
    """Test get differences address fields."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore2 = keystore.clone()
    keystore2.xpub += " "
    # xpub changes should require address rescan.
    diffs = keystore.get_differences(keystore2)
    assert len(diffs) == 1
    assert diffs[0].key == "xpub"
    assert diffs[0].type == WalletDifferenceType.ImpactOnAddresses


def test_get_differences_description_field() -> None:
    """Test description changes are metadata-only."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore2 = keystore.clone()
    keystore2.description = "new"
    # Description changes should not require rescan.
    diffs = keystore.get_differences(keystore2)
    assert len(diffs) == 1
    assert diffs[0].key == "description"
    assert diffs[0].type == WalletDifferenceType.NoRescan


def test_get_differences_hardware_signer_id() -> None:
    """Test hardware signer id differences are metadata-only."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore2 = keystore.clone()
    keystore2.hardware_signer_id = HardwareSigners.krux_diy.id
    diffs = keystore.get_differences(keystore2)
    assert len(diffs) == 1
    assert diffs[0].key == "hardware_signer_id"
    assert diffs[0].type == WalletDifferenceType.NoRescan


def test_hardware_signer_label_uses_device_name_when_known() -> None:
    """Test concrete hardware signers use their display name."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore.hardware_signer_id = HardwareSigners.passport.id
    assert keystore.hardware_signer_label(fallback_name="Signer 1") == HardwareSigners.passport.display_name


def test_hardware_signer_label_uses_fallback_for_generic_signer() -> None:
    """Test generic signers use the provided fallback label."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    assert keystore.hardware_signer_label(fallback_name="Signer 1") == "Signer 1"


def test_technical_hardware_signer_label_appends_fingerprint() -> None:
    """Test the technical label includes the fingerprint when available."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    keystore.hardware_signer_id = HardwareSigners.passport.id
    assert (
        keystore.technical_hardware_signer_label()
        == f"{HardwareSigners.passport.display_name} - {keystore.fingerprint}"
    )


def test_is_seed_valid() -> None:
    """Test is seed valid."""
    # Known valid test seed should pass.
    assert KeyStore.is_seed_valid(test_seeds[0])
    # Obvious invalid seed should fail.
    assert not KeyStore.is_seed_valid("not a valid seed")


def test_is_xpub_valid() -> None:
    """Test is xpub valid."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    # Correct xpub should validate for the given network.
    assert KeyStore.is_xpub_valid(keystore.xpub, keystore.network)
    # Truncated xpub should fail validation.
    assert not KeyStore.is_xpub_valid(keystore.xpub[:-4], keystore.network)


def test_clone_creates_equal_object() -> None:
    """Test clone creates equal object."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    # Clone should be equal but not the same object.
    clone = keystore.clone()
    assert keystore.is_equal(clone)
    assert keystore is not clone


def test_from_other_keystore_copies_attributes() -> None:
    """Test from other keystore copies attributes."""
    ks1 = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    ks2 = create_test_seed_keystores(
        signers=1,
        key_origins=["m/42h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
        test_seed_offset=1,
    )[0]
    # from_other_keystore should replace all relevant fields.
    ks1.from_other_keystore(ks2)
    assert ks1.is_equal(ks2)


def test_from_dump_migration_uses_signer_name_from_description() -> None:
    """Test legacy migration infers by signer name first."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    dump = keystore.dump()
    dump["VERSION"] = "0.0.2"
    dump["description"] = "passport kept in the safe"
    del dump["hardware_signer_id"]

    restored = KeyStore.from_dump(dump)
    assert restored.hardware_signer_id == HardwareSigners.passport.id


def test_from_dump_migration_uses_display_name_from_description() -> None:
    """Test legacy migration infers by display name."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    dump = keystore.dump()
    dump["VERSION"] = "0.0.2"
    dump["description"] = "Krux App at home"
    del dump["hardware_signer_id"]

    restored = KeyStore.from_dump(dump)
    assert restored.hardware_signer_id == HardwareSigners.krux_diy.id


def test_from_dump_migration_falls_back_to_generic_for_unknown_description() -> None:
    """Test legacy migration falls back to the generic signer."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    dump = keystore.dump()
    dump["VERSION"] = "0.0.2"
    dump["description"] = "device in drawer"
    del dump["hardware_signer_id"]

    restored = KeyStore.from_dump(dump)
    assert restored.hardware_signer_id == HardwareSigners.generic.id


def test_from_dump_migration_falls_back_to_generic_for_ambiguous_brand() -> None:
    """Test legacy migration does not guess across multiple models in a brand."""
    keystore = create_test_seed_keystores(
        signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST
    )[0]
    dump = keystore.dump()
    dump["VERSION"] = "0.0.2"
    dump["description"] = "Coinkite signer"
    del dump["hardware_signer_id"]

    restored = KeyStore.from_dump(dump)
    assert restored.hardware_signer_id == HardwareSigners.generic.id


def test_is_identical_to_simple_pubkey_provider() -> None:
    """Test is identical to simple pubkey provider."""
    ks = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[0]
    # Same fields should be identical.
    spk = SimplePubKeyProvider(ks.xpub, ks.fingerprint, ks.key_origin)
    assert ks.is_identical_to(spk)
    # Different fingerprint should not match.
    spk2 = SimplePubKeyProvider(ks.xpub, "FFFFFFFF", ks.key_origin)
    assert not ks.is_identical_to(spk2)


def test_from_signer_info_defaults() -> None:
    """Test from signer info defaults."""
    base = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    signer = SignerInfo(base.fingerprint, base.key_origin, base.xpub)
    # Defaults should apply when signer does not override fields.
    ks = KeyStore.from_signer_info(
        signer,
        network=base.network,
        default_derivation_path="/<0;1>/*",
    )
    assert ks.derivation_path == "/<0;1>/*"


def test_from_signer_info_overrides() -> None:
    """Test from signer info overrides."""
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
        default_derivation_path="/<0;1>/*",
    )
    # Signer-supplied derivation path should override the default.
    assert ks.derivation_path == "/1/*"
    assert ks.hardware_signer_id == HardwareSigners.generic.id


def test_from_signer_info_infers_hardware_signer_id_from_name() -> None:
    """Test signer names are used to infer the hardware signer id when possible."""
    base = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    signer = SignerInfo(base.fingerprint, base.key_origin, base.xpub, name="Passport")
    ks = KeyStore.from_signer_info(
        signer,
        network=base.network,
        default_derivation_path="/<0;1>/*",
    )
    assert ks.hardware_signer_id == HardwareSigners.passport.id


def test_sorted_keystores_orders_by_xpub() -> None:
    """Test sorted keystores orders by xpub."""
    ks1 = create_test_seed_keystores(signers=1, key_origins=["m/41h/1h/0h/2h"], network=bdk.Network.REGTEST)[
        0
    ]
    ks2 = create_test_seed_keystores(
        signers=1,
        key_origins=["m/42h/1h/0h/2h"],
        network=bdk.Network.REGTEST,
        test_seed_offset=1,
    )[0]
    # Sorting should order by xpub string.
    ordered = sorted_keystores([ks2, ks1])
    assert [k.xpub for k in ordered] == sorted([ks1.xpub, ks2.xpub])


def test_network_consistent() -> None:
    """Test network consistent."""
    bacon_xpub = "xpub6DEzNop46vmxR49zYWFnMwmEfawSNmAMf6dLH5YKDY463twtvw1XD7ihwJRLPRGZJz799VPFzXHpZu6WdhT29WnaeuChS6aZHZPFmqczR5K"
    # Mainnet xpub should only match mainnet.
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(bacon_xpub), bdk.Network.BITCOIN)
    assert not KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(bacon_xpub), bdk.Network.TESTNET4
    )

    testnet_tpub = "tpubDDyGGnd9qGbDsccDSe2imVHJPd96WysYkMVAf95PWzbbCmmKHSW7vLxvrTW3HsAau9MWirkJsyaALGJwqwcReu3LZVMg6XbRgBNYTtKXeuD"
    # Testnet tpub should be valid on testnet-like networks only.
    assert KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.TESTNET4
    )
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.REGTEST)
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.TESTNET)
    assert KeyStore.network_consistent(bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.SIGNET)
    assert not KeyStore.network_consistent(
        bdk.DescriptorPublicKey.from_string(testnet_tpub), bdk.Network.BITCOIN
    )
