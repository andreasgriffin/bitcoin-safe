import logging

logger = logging.getLogger(__name__)

import bdkpython as bdk
from typing import Dict, List, Tuple
import re
from bitcoin_qrreader.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)
from bitcoin_qrreader.multipath_descriptor import add_checksum_to_descriptor
from bitcoin_usb.address_types import (
    AddressType,
    AddressTypes,
    get_address_types,
    SimplePubKeyProvider,
    ConstDerivationPaths,
    DescriptorInfo,
)


def get_default_address_type(is_multisig) -> AddressType:
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh


class MultipathDescriptor(BitcoinQRMultipathDescriptor):
    @classmethod
    def from_keystores(
        cls,
        threshold: int,
        spk_providers: List[SimplePubKeyProvider],
        address_type: AddressType,
        network: bdk.Network,
    ) -> "MultipathDescriptor":

        # sanity checks
        assert threshold <= len(spk_providers)
        is_multisig = len(spk_providers) > 1
        assert address_type.is_multisig == is_multisig

        receive_spk_providers = [p.clone() for p in spk_providers]
        for p in receive_spk_providers:
            p.derivation_path = ConstDerivationPaths.receive
        change_spk_providers = [p.clone() for p in spk_providers]
        for p in change_spk_providers:
            p.derivation_path = ConstDerivationPaths.change

        return MultipathDescriptor(
            DescriptorInfo(
                address_type=address_type,
                spk_providers=receive_spk_providers,
                threshold=threshold,
            ).get_bdk_descriptor(network),
            DescriptorInfo(
                address_type=address_type,
                spk_providers=change_spk_providers,
                threshold=threshold,
            ).get_bdk_descriptor(network),
        )
