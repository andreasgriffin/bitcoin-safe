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


import copy
import logging
from typing import Any, Dict, List, Literal, Optional

import bdkpython as bdk
from bitcoin_qr_tools.signer_info import SignerInfo
from bitcoin_usb.address_types import (
    AddressTypes,
    ConstDerivationPaths,
    SimplePubKeyProvider,
)
from packaging import version

from bitcoin_safe.wallet_util import (
    WalletDifference,
    WalletDifferences,
    WalletDifferenceType,
)

from .storage import BaseSaveableClass, SaveAllClass, filtered_for_init

logger = logging.getLogger(__name__)


class KeyStoreImporterType(SaveAllClass):
    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        icon_filename: str,
        networks: List[bdk.Network] | Literal["all"] = "all",
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.icon_filename = icon_filename
        self.networks = (
            [
                bdk.Network.BITCOIN,
                bdk.Network.REGTEST,
                bdk.Network.TESTNET,
                bdk.Network.TESTNET4,
                bdk.Network.SIGNET,
            ]
            if networks == "all"
            else networks
        )

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)


class KeyStoreImporterTypes:
    hwi = KeyStoreImporterType(
        "hwi", "USB hardware signer", "Connect \nUSB \nhardware signer", "bi--usb-symbol.svg"
    )
    file = KeyStoreImporterType(
        "file",
        "SD card",
        "Import signer details\nvia SD card",
        "bi--sd-card.svg",
    )
    clipboard = KeyStoreImporterType(
        "clipboard",
        "Clipboard",
        "Import signer details\nfrom text",
        "clip.svg",
    )
    qr = KeyStoreImporterType(
        "qr",
        "QR Code",
        "Import signer details\nvia QR code",
        "bi--qr-code-scan.svg",
    )
    seed = KeyStoreImporterType(
        "seed",
        "Seed",
        "Mnemonic Seed\n(Testnet only)",
        "logo-black.svg",
        networks=[bdk.Network.REGTEST, bdk.Network.TESTNET, bdk.Network.TESTNET4, bdk.Network.SIGNET],
    )  # add networks here to make the seed option visible

    @classmethod
    def list_types(cls, network: bdk.Network) -> List[KeyStoreImporterType]:
        return [v for v in [cls.hwi, cls.file, cls.qr, cls.seed] if network in v.networks]

    @classmethod
    def list_names(cls, network: bdk.Network) -> List[str]:
        return [v.name for v in cls.list_types(network)]


class KeyStore(SimplePubKeyProvider, BaseSaveableClass):
    VERSION = "0.0.2"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(
        self,
        xpub: str,
        fingerprint: str,
        key_origin: str,
        label: str,
        network: bdk.Network,
        mnemonic: Optional[str] = None,
        description: str = "",
        derivation_path: str = ConstDerivationPaths.multipath,
    ) -> None:
        super().__init__(
            xpub=xpub,
            fingerprint=fingerprint,
            key_origin=key_origin,
            derivation_path=derivation_path,
        )

        self.network = network
        if not self.is_xpub_valid(xpub=xpub, network=self.network):
            raise ValueError(f"{xpub} is not a valid xpub")

        self.label = label
        self.mnemonic = mnemonic
        self.description = description

    def get_differences(self, other_keystore: "KeyStore", prefix="") -> WalletDifferences:
        "Compares the relevant entries like keystores"
        differences = WalletDifferences()
        this = self.dump()
        other = other_keystore.dump()

        keys = [
            "xpub",
            "fingerprint",
            "key_origin",
            "network",
            "mnemonic",
            "derivation_path",
        ]
        for k in keys:
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.ImpactOnAddresses,
                        key=f"{prefix}{k}",
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        keys = [
            "label",
            "description",
        ]
        for k in keys:
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.NoImpactOnAddresses,
                        key=f"{prefix}{k}",
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        return differences

    def is_equal(self, other: "KeyStore") -> bool:
        return self.__dict__ == other.__dict__

    @classmethod
    def is_seed_valid(cls, mnemonic: str) -> bool:
        try:
            bdk.Mnemonic.from_string(mnemonic)
            return True
        except Exception as e:
            logger.debug(f"{cls.__name__}: {e}")
            return False

    @classmethod
    def is_xpub_valid(cls, xpub: str, network: bdk.Network) -> bool:
        if not AddressTypes.p2pkh.bdk_descriptor:
            return False
        try:
            AddressTypes.p2pkh.bdk_descriptor(
                bdk.DescriptorPublicKey.from_string(xpub),
                "0" * 8,
                bdk.KeychainKind.EXTERNAL,
                network,
            )

            return True
        except Exception as e:
            logger.debug(f"{cls.__name__}: {e}")
            return False

    def clone(self, class_kwargs: Dict | None = None) -> "KeyStore":
        return KeyStore(**self.__dict__)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"

    def dump(self) -> Dict[str, Any]:
        d = super().dump()

        # you must copy it, so you not't change any calues
        full_dict = self.__dict__.copy()
        # the deepcopy must be done AFTER there is no bdk type in there any more
        d.update(copy.deepcopy(full_dict))
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None) -> "KeyStore":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            if "derivation_path" in dct:
                dct["key_origin"] = dct["derivation_path"]
                del dct["derivation_path"]

        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.1"):
            if "derivation_path" in dct:
                dct["network"] = bdk.Network.REGTEST

        return super().from_dump_migration(dct=dct)

    def from_other_keystore(self, other_keystore: "KeyStore") -> None:
        for k, v in other_keystore.__dict__.items():
            setattr(self, k, v)

    def is_identical_to(self, spk_provider: SimplePubKeyProvider) -> bool:
        # fill in missing info in keystores

        return (
            self.fingerprint == spk_provider.fingerprint
            and self.xpub == spk_provider.xpub
            and self.key_origin == spk_provider.key_origin
        )

    @classmethod
    def from_signer_info(
        cls, signer_info: SignerInfo, network: bdk.Network, default_label: str, default_derivation_path: str
    ) -> "KeyStore":
        return KeyStore(
            xpub=signer_info.xpub,
            fingerprint=signer_info.fingerprint,
            key_origin=signer_info.key_origin,
            label=signer_info.name if signer_info.name else default_label,
            network=network,
            derivation_path=(
                signer_info.derivation_path if signer_info.derivation_path else default_derivation_path
            ),
        )


def sorted_keystores(keystores: List[KeyStore]) -> List[KeyStore]:
    def key(v: KeyStore) -> str:
        return v.xpub

    return sorted(keystores, key=key)
