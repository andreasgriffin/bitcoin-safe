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
from collections.abc import Sequence

import bdkpython as bdk
from bitcoin_qr_tools.data import ConverterMultisigWalletExport
from bitcoin_qr_tools.multipath_descriptor import (
    convert_to_multipath_descriptor,
    get_all_pubkey_providers,
)
from bitcoin_usb.address_types import (
    AddressType,
    AddressTypes,
    ConstDerivationPaths,
    DescriptorInfo,
    SimplePubKeyProvider,
    get_all_address_types,
)
from hwilib.descriptor import parse_descriptor

from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.wallet_util import signer_name

logger = logging.getLogger(__name__)


def get_default_address_type(is_multisig) -> AddressType:
    """Get default address type."""
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh


def get_address_bip32_path(descriptor_str: str, kind: bdk.KeychainKind, index: int):
    """Get address bip32 path."""
    hwi_descriptor = parse_descriptor(descriptor_str)
    pubkey_providers = get_all_pubkey_providers(hwi_descriptor)

    if not len(pubkey_providers) > 1:
        logger.warning("Multiple pubkey_providers present. Choosing 1. one")

    spkp = SimplePubKeyProvider.from_hwi(pubkey_provider=pubkey_providers[0])

    return spkp.get_address_bip32_path(kind=kind, index=index)


def descriptor_from_keystores(
    threshold: int,
    spk_providers: Sequence[SimplePubKeyProvider],
    address_type: AddressType,
    network: bdk.Network,
) -> bdk.Descriptor:
    # sanity checks
    """Descriptor from keystores."""
    assert threshold <= len(spk_providers)
    is_multisig = len(spk_providers) > 1
    assert address_type.is_multisig == is_multisig

    multipath_spk_providers = [p.clone() for p in spk_providers]
    for p in multipath_spk_providers:
        p.derivation_path = ConstDerivationPaths.multipath

    return convert_to_multipath_descriptor(
        DescriptorInfo(
            address_type=address_type,
            spk_providers=multipath_spk_providers,
            threshold=threshold,
        ).get_descriptor_str(network),
        network=network,
    )


def from_multisig_wallet_export(
    multisig_wallet_export: ConverterMultisigWalletExport,
    network: bdk.Network,
) -> bdk.Descriptor:
    """From multisig wallet export."""
    matching_address_type: AddressType | None = None
    for address_type in get_all_address_types():
        if address_type.short_name == multisig_wallet_export.address_type_short_name:
            matching_address_type = address_type
    if not matching_address_type:
        raise Exception(
            f"Could not match address type {multisig_wallet_export.address_type_short_name} to {get_all_address_types()}"
        )

    keystores = [
        KeyStore.from_signer_info(
            signer_info=signer_info,
            network=network,
            default_label=signer_name(threshold=multisig_wallet_export.threshold, i=i),
            default_derivation_path=ConstDerivationPaths.multipath,
        )
        for i, signer_info in enumerate(multisig_wallet_export.signer_infos)
    ]

    return descriptor_from_keystores(
        multisig_wallet_export.threshold,
        spk_providers=keystores,
        address_type=matching_address_type,
        network=network,
    )


def is_legacy(a: AddressType):  # P2PKH
    """Is legacy."""
    return a is AddressTypes.p2pkh


def is_segwit_v0(a: AddressType):  # Any v0 segwit flavor
    """Is segwit v0."""
    return a in (
        AddressTypes.p2sh_p2wpkh,
        AddressTypes.p2wpkh,
        AddressTypes.p2sh_p2wsh,
        AddressTypes.p2wsh,
    )


def is_taproot(a: AddressType):  # P2TR (v1)
    """Is taproot."""
    return a is AddressTypes.p2tr


def get_recovery_point(address_type: AddressType, network: bdk.Network) -> bdk.RecoveryPoint:
    """Get recovery point."""
    if is_legacy(address_type):
        return bdk.RecoveryPoint.GENESIS_BLOCK
    elif is_segwit_v0(address_type):
        return bdk.RecoveryPoint.SEGWIT_ACTIVATION
    elif is_taproot(address_type):
        return bdk.RecoveryPoint.TAPROOT_ACTIVATION
    return bdk.RecoveryPoint.GENESIS_BLOCK


def min_blockheight(address_type: AddressType, network: bdk.Network) -> int:
    """Returns the minimum Bitcoin blockheight at which this address type became (or
    becomes) usable on mainnet."""

    # Mainnet
    if network == bdk.Network.BITCOIN:
        BIP141_ACTIVATION = 481_824  # SegWit v0
        BIP342_ACTIVATION = 709_632  # Taproot (v1, with BIP341/342)
        if is_legacy(address_type):
            return 0
        if is_segwit_v0(address_type):
            return BIP141_ACTIVATION
        if is_taproot(address_type):
            return BIP342_ACTIVATION
        return 0

    # Testnet3 (bdk.Network.TESTNET)
    if network == bdk.Network.TESTNET:
        BIP141_TESTNET = 834_624  # SegWit v0 activation on testnet3
        BIP342_TESTNET = 2_011_968  # Taproot activation on testnet3
        if is_legacy(address_type):
            return 0
        if is_segwit_v0(address_type):
            return BIP141_TESTNET
        if is_taproot(address_type):
            return BIP342_TESTNET
        return 0

    # Fallback
    return 0
