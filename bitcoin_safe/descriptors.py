import logging

logger = logging.getLogger(__name__)

import bdkpython as bdk
from typing import Dict, List, Tuple
import re
from bitcoin_qrreader.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)
from bitcoin_qrreader.multipath_descriptor import add_checksum_to_descriptor

# https://bitcoin.design/guide/glossary/address/
# https://learnmeabitcoin.com/technical/derivation-paths
# https://github.com/bitcoin/bips/blob/master/bip-0380.mediawiki
# Safe to use are only those with a bdk desc_template
class AddressType:
    def __init__(
        self,
        name,
        is_multisig,
        derivation_path=None,
        desc_template=None,
        bdk_descriptor_secret=None,
        info_url=None,
        description=None,
        bdk_descriptor=None,
    ) -> None:
        self.name = name
        self.is_multisig = is_multisig
        self.derivation_path = derivation_path
        self.desc_template = desc_template
        self.bdk_descriptor_secret = bdk_descriptor_secret
        self.info_url = info_url
        self.description = description
        self.bdk_descriptor = bdk_descriptor

    def clone(self):
        return AddressType(
            self.name,
            self.is_multisig,
            self.derivation_path,
            self.desc_template,
            self.bdk_descriptor_secret,
            self.info_url,
            self.description,
            self.bdk_descriptor,
        )


class AddressTypes:
    p2pkh = AddressType(
        "Single Sig (Legacy/p2pkh)",
        False,
        derivation_path=lambda network: f"m/44h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
        desc_template=lambda x: f"pkh({x})",
        bdk_descriptor=bdk.Descriptor.new_bip44_public,
        bdk_descriptor_secret=bdk.Descriptor.new_bip44,
        info_url="https://learnmeabitcoin.com/technical/derivation-paths",
        description="Legacy (single sig) addresses that look like 1addresses",
    )
    p2sh_p2wpkh = AddressType(
        "Single Sig (Nested/p2sh-p2wpkh)",
        False,
        derivation_path=lambda network: f"m/49h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
        desc_template=lambda x: f"sh(wpkh({x}))",
        bdk_descriptor=bdk.Descriptor.new_bip49_public,
        bdk_descriptor_secret=bdk.Descriptor.new_bip49,
        info_url="https://learnmeabitcoin.com/technical/derivation-paths",
        description="Nested (single sig) addresses that look like 3addresses",
    )
    p2wpkh = AddressType(
        "Single Sig (SegWit/p2wpkh)",
        False,
        derivation_path=lambda network: f"m/84h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
        desc_template=lambda x: f"wpkh({x})",
        bdk_descriptor=bdk.Descriptor.new_bip84_public,
        bdk_descriptor_secret=bdk.Descriptor.new_bip84,
        info_url="https://learnmeabitcoin.com/technical/derivation-paths",
        description="SegWit (single sig) addresses that look like bc1addresses",
    )
    p2tr = AddressType(
        "Single Sig (Taproot/p2tr)",
        False,
        derivation_path=lambda network: f"m/86h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
        desc_template=lambda x: f"tr({x})",
        bdk_descriptor=bdk.Descriptor.new_bip86_public,
        bdk_descriptor_secret=bdk.Descriptor.new_bip86,
        info_url="https://github.com/bitcoin/bips/blob/master/bip-0386.mediawiki",
        description="Taproot (single sig) addresses ",
    )
    p2sh_p2wsh = AddressType(
        "Multi Sig (Nested/p2sh-p2wsh)",
        True,
        derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/1h",
        desc_template=lambda x: f"sh(wsh({x}))",
        bdk_descriptor_secret=None,
        info_url="https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki",
        description="Nested (multi sig) addresses that look like 3addresses",
    )
    p2wsh = AddressType(
        "Multi Sig (SegWit/p2wsh)",
        True,
        derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/2h",
        desc_template=lambda x: f"wsh({x})",
        bdk_descriptor_secret=None,
        info_url="https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki",
        description="SegWit (multi sig) addresses that look like bc1addresses",
    )


def get_default_address_type(is_multisig) -> AddressType:
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh


def get_address_types(is_multisig) -> List[AddressType]:
    return [
        v
        for k, v in AddressTypes.__dict__.items()
        if (not k.startswith("_")) and v.is_multisig == is_multisig
    ]


def descriptor_without_script(descriptor_str: str):
    # Regular expression pattern to match text inside parentheses
    pattern = re.compile(r"\((.*?)\)")

    # Search for the pattern in the input string
    match = pattern.search(descriptor_str)

    # If a match is found, extract and print it
    if match:
        return match.group(1)

    else:
        logger.error("Could not decode descriptor")
        return ""


def make_multisig_descriptor_string(
    address_type: AddressType, threshold: int, descriptors: List[bdk.Descriptor]
) -> str:
    # ["[189cf85e/84'/1'/0']tpubDDkYCWGii5pUuqqqvh9vRqyChQ88aEGZ7z7xpwDzAQ87SpNrii9MumksW8WSqv2aYEBssKYF5KVeY9kmoreJrvQSB2dgCz11TXu81YhyaqP/0/*", ...]
    descriptors_without_script = [
        descriptor_without_script(descriptor.as_string_private())
        for descriptor in descriptors
    ]

    descriptor_without_checksum = (
        address_type.desc_template(
            f"sortedmulti({threshold},{','.join(descriptors_without_script)})"
        )
        if len(descriptors) > 1
        else address_type.desc_template(descriptors_without_script[0])
    )
    return add_checksum_to_descriptor(descriptor_without_checksum)


def public_descriptor_info(descriptor_str: str, network: bdk.Network) -> Dict:
    "gets the xpub (not xpriv) information"

    def extract_groups(string, pattern):
        match = re.match(pattern, string)
        if match is None:
            raise ValueError(f"'{string}' does not match the required pattern!")
        return match.groups()

    def extract_keystore(keystore_string: str):
        """
        Splits 1 keystore,e.g. "[a42c6dd3/84'/1'/0']xpub/0/*"
        into fingerprint, derivation_path, xpub, wallet_path

        It also replaces the "'" into "h"

        It overwrites fingerprint, derivation_path, xpub  in default_keystore.
        """
        (
            fingerprint,
            derivation_path,
            xpub,
            further_derivation_path,
        ) = extract_groups(keystore_string, r"\[(.*?)\/(.*)\](.*?)\/(.*)")
        # TODO handle other further_derivation_path
        assert further_derivation_path in ["<0;1>/*", "0/*", "1/*"]

        return {
            "xpub": xpub,
            "fingerprint": fingerprint,
            "derivation_path": "m/" + derivation_path,
        }

    def split_string(descriptor_string_combined):
        # First split the descriptor like:
        # "wpkh"
        # "[a42c6dd3/84'/1'/0']xpub/0/*"
        groups = [
            g.rstrip(")")
            for g in extract_groups(descriptor_string_combined, r"(.*)\((.*)\)")
        ]  # remove trailing )

        # do the keystore parts
        is_multisig = "multi" in groups[0]
        threshold = 1
        if is_multisig:
            threshold, *keystore_strings = groups[1].split(",")
        else:
            assert len(groups) == 2
            keystore_strings = [groups[1]]
        return {
            "keystore_strings": keystore_strings,
            "script_prefix": groups[0],
            "is_multisig": is_multisig,
            "threshold": threshold,
        }

    descriptor_str = descriptor_str.strip()
    # these are now bdk single or multisig descriptors
    multipath_descriptor = MultipathDescriptor.from_descriptor_str(
        descriptor_str, network
    )
    # get the public descriptor string info
    public_descriptor_string_combined = multipath_descriptor.as_string()

    splitted_string = split_string(public_descriptor_string_combined)
    keystores = [
        extract_keystore(keystore_string)
        for keystore_string in splitted_string["keystore_strings"]
    ]

    descriptor_contains_keys = [
        s[1:].startswith("prv")
        for s in split_string(multipath_descriptor.as_string_private())[
            "keystore_strings"
        ]
    ]

    return {
        "threshold": int(splitted_string["threshold"]),
        "signers": len(keystores),
        "keystores": keystores,
        "network": network,
        "public_descriptor_string_combined": public_descriptor_string_combined,
        "descriptor_contains_keys": descriptor_contains_keys,
    }


class MultipathDescriptor(BitcoinQRMultipathDescriptor):
    @classmethod
    def from_keystores(
        cls,
        threshold: int,
        keystores: List["KeyStore"],
        address_type: AddressType,
        network: bdk.Network,
    ) -> "MultipathDescriptor":

        # sanity checks
        assert threshold <= len(keystores)
        is_multisig = len(keystores) > 1
        assert address_type.is_multisig == is_multisig

        # [["wpkh([189cf85e/84'/1'/0']tpubDDkYCWGii5pUuqqqvh9vRqyChQ88aEGZ7z7xpwDzAQ87SpNrii9MumksW8WSqv2aYEBssKYF5KVeY9kmoreJrvQSB2dgCz11TXu81YhyaqP/0/*)#arpc0qa2", "wpkh([189cf85e/84'/1'/0']tpubDDkYCWGii5pUuqqqvh9vRqyChQ88aEGZ7z7xpwDzAQ87SpNrii9MumksW8WSqv2aYEBssKYF5KVeY9kmoreJrvQSB2dgCz11TXu81YhyaqP/1/*)#arpc0qa2"], ...]
        if len(keystores) == 1:
            return keystores[0].to_singlesig_multipath_descriptor(address_type, network)

        # there are no bdk multisig descriptor templates yet, so I have to use a single sig template
        # the script type will be removed anyway in make_multisig_descriptor_string
        all_descriptors = [
            k.to_singlesig_multipath_descriptor(AddressTypes.p2wpkh, network)
            for k in keystores
        ]

        receive_descriptors = [d.bdk_descriptors[0] for d in all_descriptors]
        change_descriptors = [d.bdk_descriptors[1] for d in all_descriptors]

        receive_descriptor_str = make_multisig_descriptor_string(
            address_type, threshold, receive_descriptors
        )
        change_descriptor_str = make_multisig_descriptor_string(
            address_type, threshold, change_descriptors
        )

        return MultipathDescriptor(
            bdk.Descriptor(receive_descriptor_str, network=network),
            bdk.Descriptor(change_descriptor_str, network=network),
        )
