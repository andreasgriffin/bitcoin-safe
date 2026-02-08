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

import bdkpython as bdk
import pytest

from bitcoin_safe.wallet import Wallet, WalletInputsInconsistentError
from bitcoin_safe.wallet_util import WalletDifferenceType

from ..helpers import TestConfig
from .utils import create_multisig_protowallet


def _make_config() -> TestConfig:
    """Make config."""
    config = TestConfig()
    config.network = bdk.Network.REGTEST
    return config


def test_check_consistency_errors() -> None:
    """Test check consistency errors."""
    config = _make_config()
    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/84h/1h/0h"],
        network=config.network,
    )
    descriptor = protowallet.to_multipath_descriptor().to_string_with_secret()
    keystores = [ks for ks in protowallet.keystores if ks]

    # Empty keystores should raise.
    with pytest.raises(WalletInputsInconsistentError):
        Wallet.check_consistency([], descriptor, network=config.network)

    # Network mismatch should raise.
    with pytest.raises(WalletInputsInconsistentError):
        Wallet.check_consistency(keystores, descriptor, network=bdk.Network.BITCOIN)

    # Duplicate keystores should raise.
    with pytest.raises(WalletInputsInconsistentError):
        Wallet.check_consistency(keystores * 2, descriptor, network=config.network)


def test_check_self_consistency(test_funded_wallet_session: Wallet) -> None:
    """Test check self consistency."""
    wallet = test_funded_wallet_session
    descriptor = "wpkh([41c5c760/84'/1'/0']tpubDDRVgaxjgMghgZzWSG4NL6D7M5wL1CXM3x98prqjmqU9zs2wfRZmYXWWamk4sxsQEQMX6Rmkc1i6G74zTD7xUxoojmijJiA3QPdJyyrWFKz/<0;1>/*)"

    # A matching descriptor should pass consistency checks.
    Wallet.check_consistency(wallet.keystores, descriptor, network=bdk.Network.REGTEST)


def test_check_protowallet_consistency_valid() -> None:
    """Test check protowallet consistency valid."""
    config = _make_config()
    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/84h/1h/0h"],
        network=config.network,
    )
    descriptor = protowallet.to_multipath_descriptor().to_string_with_secret()
    keystores = [ks for ks in protowallet.keystores if ks]

    # Valid keystores and descriptor should be consistent.
    Wallet.check_consistency(keystores, descriptor, network=config.network)


def test_get_mn_tuple_single_sig(test_funded_wallet_session: Wallet) -> None:
    """Test get mn tuple single sig."""
    wallet = test_funded_wallet_session
    # Single-sig wallets should return (1, 1).
    assert wallet.get_mn_tuple() == (1, 1)


def test_mark_all_labeled_addresses_used(test_funded_wallet_session: Wallet) -> None:
    """Test mark all labeled addresses used."""
    wallet = test_funded_wallet_session
    addr_info = wallet.get_address(force_new=True)
    address_str = str(addr_info.address)
    # ensure address appears in the list of unused addresses first
    unused_before = [str(a) for a in wallet.bdkwallet.list_unused_addresses(bdk.KeychainKind.EXTERNAL)]
    assert any(address_str in entry for entry in unused_before)

    # Label the address and mark labeled addresses as used.
    wallet.labels.set_addr_label(address_str, "lbl")
    wallet.mark_all_labeled_addresses_used(include_receiving_addresses=True)

    unused_after = [str(a) for a in wallet.bdkwallet.list_unused_addresses(bdk.KeychainKind.EXTERNAL)]
    assert all(address_str not in entry for entry in unused_after)


def test_as_protowallet_roundtrip(test_funded_wallet_session: Wallet) -> None:
    """Test as protowallet roundtrip."""
    wallet = test_funded_wallet_session
    # Convert to protowallet and back, then compare key fields.
    proto = wallet.as_protowallet()
    restored = Wallet.from_protowallet(
        proto,
        config=_make_config(),
        loop_in_thread=wallet.loop_in_thread,
    )
    assert restored.id == wallet.id
    assert restored.network == wallet.network
    assert restored.get_mn_tuple() == wallet.get_mn_tuple()
    Wallet.check_consistency(
        wallet.keystores, str(restored.multipath_descriptor), network=bdk.Network.REGTEST
    )


def test_get_differences_descriptor_change() -> None:
    """Test get differences descriptor change."""
    config = _make_config()
    key_origins = [f"m/{i + 41}h/1h/0h/2h" for i in range(2)]
    protowallet1 = create_multisig_protowallet(
        threshold=2,
        signers=2,
        key_origins=key_origins,
        network=config.network,
    )
    protowallet2 = create_multisig_protowallet(
        threshold=1,
        signers=2,
        key_origins=key_origins,
        network=config.network,
    )

    wallet1 = Wallet.from_protowallet(protowallet=protowallet1, config=config, loop_in_thread=None)
    wallet2 = Wallet.from_protowallet(protowallet=protowallet2, config=config, loop_in_thread=None)

    # Descriptor change should be flagged as impacting addresses.
    diffs = wallet1.get_differences(wallet2)
    assert any(
        d.key == "descriptor changed" and d.type == WalletDifferenceType.ImpactOnAddresses for d in diffs
    )
    assert diffs.has_impact_on_addresses()


def test_get_differences_gap_change() -> None:
    """Test get differences gap change."""
    config = _make_config()
    protowallet = create_multisig_protowallet(
        threshold=1,
        signers=1,
        key_origins=["m/84h/1h/0h"],
        network=config.network,
    )
    descriptor = protowallet.to_multipath_descriptor().to_string_with_secret()
    keystores = [ks for ks in protowallet.keystores if ks]

    wallet1 = Wallet(
        id="id",
        descriptor_str=descriptor,
        keystores=keystores,
        network=config.network,
        config=config,
        gap=20,
        loop_in_thread=None,
    )
    wallet2 = Wallet(
        id="id",
        descriptor_str=descriptor,
        keystores=keystores,
        network=config.network,
        config=config,
        gap=42,
        loop_in_thread=None,
    )

    # Gap change should require rescan but not change addresses.
    diffs = wallet1.get_differences(wallet2)
    assert any(d.key == "gap" and d.type == WalletDifferenceType.NeedsRescan for d in diffs)
    assert not diffs.has_impact_on_addresses()


def test_get_mn_tuple() -> None:
    """Test get mn tuple."""
    config = _make_config()
    key_origins = [f"m/{i + 41}h/1h/0h/2h" for i in range(3)]
    protowallet = create_multisig_protowallet(
        threshold=2,
        signers=3,
        key_origins=key_origins,
        network=config.network,
    )
    wallet = Wallet.from_protowallet(protowallet=protowallet, config=config, loop_in_thread=None)

    # Multisig should return (m, n).
    assert wallet.get_mn_tuple() == (2, 3)
