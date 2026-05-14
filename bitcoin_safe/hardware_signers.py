#
# Bitcoin Safe
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

import enum
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from bitcoin_qr_tools.unified_encoder import QrExportType, QrExportTypes

logger = logging.getLogger(__name__)

SUPPORTED_HARDWARE_SIGNERS_URL = "https://bitcoin-safe.org/en/knowledge/supported-hardware-signers/"


def _signer_info_url(path: str | None = None) -> str:
    """Build the Bitcoin Safe knowledge URL for a supported hardware signer."""
    if not path:
        return SUPPORTED_HARDWARE_SIGNERS_URL
    return f"{SUPPORTED_HARDWARE_SIGNERS_URL}{path.strip('/')}/"


@dataclass
class DescriptorExportType:
    name: str
    display_name: str


class DescriptorExportTypes:
    coldcard = DescriptorExportType("coldcard", "Coldcard")
    default = DescriptorExportType("passport_descriptor_export", "Default")
    specterdiy = DescriptorExportType("specterdiy_descriptor_export", "Specter")
    text = DescriptorExportType("text", "Text")

    @classmethod
    def as_list(cls) -> list[DescriptorExportType]:
        """As list."""
        return [
            export_type
            for _name, export_type in cls.__dict__.items()
            if isinstance(export_type, DescriptorExportType)
        ]


class DescriptorQrExportTypes:
    coldcard_legacy = QrExportType("coldcard_legacy", "Coldcard")
    default = QrExportType("passport_descriptor_export", "Default")
    specterdiy = QrExportType("specterdiy_descriptor_export", "Specter")
    text = QrExportTypes.text

    @classmethod
    def as_list(cls) -> list[QrExportType]:
        """As list."""
        return [
            export_type
            for _name, export_type in cls.__dict__.items()
            if isinstance(export_type, type(cls.text))
        ]


class SignMessageRequestQrExportTypes:
    bbqr = QrExportType("bbqr_sign_message_request", "BBQr")
    text = QrExportType("text_sign_message_request", "Text")

    @classmethod
    def as_list(cls) -> list[QrExportType]:
        """As list."""
        return [
            export_type
            for _name, export_type in cls.__dict__.items()
            if isinstance(export_type, type(cls.text))
        ]


class FeatureLevel(enum.Enum):
    not_capable = enum.auto()
    capable = enum.auto()
    supported = enum.auto()


@dataclass
class HardwareSigner:
    id: str
    brand_name: str
    display_name: str
    usb_preferred: bool
    qr_types: list[QrExportType]
    descriptor_export_types: list[DescriptorExportType]
    usb: FeatureLevel = FeatureLevel.not_capable
    bluetooth: FeatureLevel = FeatureLevel.not_capable
    icon_filename: str = ""
    info_url: str | None = None
    screenshot_name: str = ""

    @property
    def supports_qr(self) -> bool:
        """Return whether the signer supports any QR-based workflow."""
        return bool(self.qr_types)

    @property
    def asset_name(self) -> str:
        """Return the base name used for bundled screenshots."""
        return self.screenshot_name if self.screenshot_name else self.id

    @property
    def generate_seed_png(self) -> str:
        """Generate seed png."""
        return f"{self.asset_name}-generate-seed.png"

    @property
    def wallet_export_png(self) -> str:
        """Wallet export png."""
        return f"{self.asset_name}-wallet-export.png"

    @property
    def view_seed_png(self) -> str:
        """View seed png."""
        return f"{self.asset_name}-view-seed.png"

    @property
    def register_multisig_decriptor_png(self) -> str:
        """Register multisig decriptor png."""
        return f"{self.asset_name}-register-multisig-decriptor.png"

    @property
    def icon_name(self) -> str:
        """Icon name."""
        return self.icon_filename if self.icon_filename else f"{self.id}-icon.svg"


class HardwareSigners:
    generic = HardwareSigner(
        id="generic",
        brand_name="Generic",
        display_name="Generic Signer",
        usb_preferred=False,
        qr_types=QrExportTypes.as_list(),
        descriptor_export_types=DescriptorExportTypes.as_list(),
        usb=FeatureLevel.capable,
        icon_filename="generic-hardware-wallet-icon.svg",
        info_url=SUPPORTED_HARDWARE_SIGNERS_URL,
        bluetooth=FeatureLevel.supported,
    )
    coldcard = HardwareSigner(
        id="coldcard",
        brand_name="Coinkite",
        display_name="Coldcard-Mk4/5",
        usb_preferred=False,
        qr_types=[],
        descriptor_export_types=[DescriptorExportTypes.coldcard],
        usb=FeatureLevel.supported,
        info_url=None,
        icon_filename="coldcard-icon.svg",
        screenshot_name="coldcard",
    )
    q = HardwareSigner(
        id="q",
        brand_name="Coinkite",
        display_name="Q",
        usb_preferred=False,
        qr_types=[
            QrExportTypes.bbqr,
            DescriptorQrExportTypes.coldcard_legacy,
            SignMessageRequestQrExportTypes.bbqr,
            SignMessageRequestQrExportTypes.text,
        ],
        descriptor_export_types=[DescriptorExportTypes.coldcard],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("coldcard-q"),
        icon_filename="q-icon.svg",
        screenshot_name="q",
    )
    bitbox02 = HardwareSigner(
        id="bitbox02",
        brand_name="Shift Crypto",
        display_name="BitBox02",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("bitbox02"),
        icon_filename="bitbox02-icon.svg",
        screenshot_name="bitbox02",
    )
    bitbox02_nova = HardwareSigner(
        id="bitbox02_nova",
        brand_name="Shift Crypto",
        display_name="BitBox02 Nova",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("bitbox02"),
        icon_filename="bitbox02-icon.svg",
        screenshot_name="bitbox02",
    )
    jade = HardwareSigner(
        id="jade",
        brand_name="Blockstream",
        display_name="Jade",
        usb_preferred=True,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        bluetooth=FeatureLevel.supported,
        info_url=_signer_info_url("jade"),
        icon_filename="jade-icon.svg",
        screenshot_name="jade",
    )
    jade_plus = HardwareSigner(
        id="jade_plus",
        brand_name="Blockstream",
        display_name="Jade Plus",
        usb_preferred=True,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        bluetooth=FeatureLevel.supported,
        info_url=_signer_info_url("jade-plus"),
        icon_filename="jade-plus-icon.svg",
        screenshot_name="jade",
    )
    passport = HardwareSigner(
        id="passport",
        brand_name="Foundation",
        display_name="Passport",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.default],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("passport"),
        icon_filename="passport-icon.svg",
        screenshot_name="passport",
    )
    passport_prime = HardwareSigner(
        id="passport_prime",
        brand_name="Foundation",
        display_name="Passport Prime",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.default],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("passport-prime"),
        icon_filename="passport-prime-icon.svg",
        screenshot_name="passport-prime",
    )
    keystone = HardwareSigner(
        id="keystone",
        brand_name="Keystone",
        display_name="Keystone",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.default],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("keystone"),
        icon_filename="keystone-icon.svg",
        screenshot_name="keystone",
    )
    trezor5 = HardwareSigner(
        id="trezor_safe_5",
        brand_name="Trezor",
        display_name="Safe 5",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("trezor"),
        icon_filename="trezor-icon.svg",
        screenshot_name="trezor",
    )
    trezor3 = HardwareSigner(
        id="trezor_safe_3",
        brand_name="Trezor",
        display_name="Safe 3",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("trezor"),
        icon_filename="trezor-icon.svg",
        screenshot_name="trezor",
    )
    trezor7 = HardwareSigner(
        id="trezor_safe_7",
        brand_name="Trezor",
        display_name="Safe 7",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("trezor"),
        icon_filename="trezor-icon.svg",
        screenshot_name="trezor",
    )
    ledger = HardwareSigner(
        id="ledger",
        brand_name="Ledger",
        display_name="Nano S",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("ledger"),
        icon_filename="ledgernano-icon.svg",
        screenshot_name="ledger",
    )
    ledger_nano_s_plus = HardwareSigner(
        id="ledger_nano_s_plus",
        brand_name="Ledger",
        display_name="Nano S Plus",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("ledger"),
        icon_filename="ledgernano-icon.svg",
        screenshot_name="ledger",
    )
    ledger_flex = HardwareSigner(
        id="ledger_flex",
        brand_name="Ledger",
        display_name="Flex",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("ledger"),
        icon_filename="ledgernano-icon.svg",
        screenshot_name="ledger",
    )
    ledger_x = HardwareSigner(
        id="ledger_x",
        brand_name="Ledger",
        display_name="X",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("ledger"),
        icon_filename="ledgernano-icon.svg",
        screenshot_name="ledger",
    )
    specterdiy = HardwareSigner(
        id="specterdiy",
        brand_name="Specter",
        display_name="Specter-DIY",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.specterdiy, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.specterdiy],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("specter"),
        icon_filename="specterdiy-icon.svg",
        screenshot_name="specterdiy",
    )
    seedsigner = HardwareSigner(
        id="seedsigner",
        brand_name="SeedSigner",
        display_name="SeedSigner",
        usb_preferred=False,
        qr_types=[
            QrExportTypes.ur,
        ],
        descriptor_export_types=[],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("seedsigner"),
        icon_filename="seedsigner-icon.svg",
        screenshot_name="seedsigner",
    )
    krux_diy = HardwareSigner(
        id="krux",
        brand_name="Krux",
        display_name="Krux DIY",
        usb_preferred=False,
        qr_types=[
            QrExportTypes.ur,
            QrExportTypes.bbqr,
            QrExportTypes.text,
            QrExportTypes.ur,
            DescriptorQrExportTypes.coldcard_legacy,
            DescriptorQrExportTypes.default,
            DescriptorQrExportTypes.text,
        ],
        descriptor_export_types=[],
        usb=FeatureLevel.not_capable,
        info_url=_signer_info_url("krux"),
        icon_filename="krux-icon.svg",
        screenshot_name="krux",
    )
    keepkey = HardwareSigner(
        id="keepkey",
        brand_name="KeepKey",
        display_name="KeepKey Wallet",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
        usb=FeatureLevel.supported,
        info_url=_signer_info_url("keepkey"),
        icon_filename="keepkey-icon.svg",
        screenshot_name="keepkey",
    )

    @classmethod
    def as_list(cls, include_generic: bool = True) -> list[HardwareSigner]:
        """Return the configured hardware signers in declaration order."""
        return [
            hardware_signer
            for _name, hardware_signer in cls.__dict__.items()
            if isinstance(hardware_signer, HardwareSigner)
            and (include_generic or hardware_signer.id != cls.generic.id)
        ]

    @classmethod
    def filtered_by(
        cls, allowed_types: Sequence[QrExportType | DescriptorExportType]
    ) -> list[HardwareSigner]:
        """Filtered by."""
        if not allowed_types:
            return []
        allowed_names = {export_type.name for export_type in allowed_types}
        first_entry = allowed_types[0]

        if isinstance(first_entry, DescriptorExportType):
            return [
                hardware_signer
                for hardware_signer in cls.as_list(include_generic=False)
                if allowed_names.intersection(
                    {qrtype.name for qrtype in hardware_signer.descriptor_export_types}
                )
            ]
        return [
            hardware_signer
            for hardware_signer in cls.as_list(include_generic=False)
            if allowed_names.intersection({qrtype.name for qrtype in hardware_signer.qr_types})
        ]

    @classmethod
    def from_id(cls, signer_id: str | None) -> HardwareSigner | None:
        """Resolve a signer by its persisted id."""
        if not signer_id:
            return None
        for hardware_signer in cls.as_list():
            if hardware_signer.id == signer_id:
                return hardware_signer
        return None

    @classmethod
    def list_brands(cls, include_generic: bool = True) -> list[str]:
        """Return the available brand names without duplicates."""
        brands: list[str] = []
        for hardware_signer in cls.as_list(include_generic=include_generic):
            if hardware_signer.brand_name not in brands:
                brands.append(hardware_signer.brand_name)
        return brands

    @classmethod
    def models_for_brand(cls, brand_name: str, include_generic: bool = True) -> list[HardwareSigner]:
        """Return the models belonging to a brand."""
        return [
            hardware_signer
            for hardware_signer in cls.as_list(include_generic=include_generic)
            if hardware_signer.brand_name == brand_name
        ]

    @classmethod
    def infer_from_text(cls, text: str | None) -> HardwareSigner:
        """Infer a signer from free-form text, falling back to the generic signer."""
        if not text:
            return cls.generic

        lowered = text.casefold()
        for candidates in (
            cls._match_by_token(lowered, [signer.id for signer in cls.as_list(include_generic=False)]),
            cls._match_by_token(
                lowered, [signer.display_name for signer in cls.as_list(include_generic=False)]
            ),
            cls._match_by_brand(lowered),
        ):
            if len(candidates) == 1:
                return candidates[0]

        return cls.generic

    @classmethod
    def _match_by_token(cls, lowered_text: str, values: list[str]) -> list[HardwareSigner]:
        matches: list[HardwareSigner] = []
        for value in values:
            signer = cls.from_id(value) or cls._find_by_display_name(value)
            if not signer:
                continue
            if cls._contains_token(lowered_text, value):
                matches.append(signer)
        return matches

    @classmethod
    def _match_by_brand(cls, lowered_text: str) -> list[HardwareSigner]:
        matches: list[HardwareSigner] = []
        for brand_name in cls.list_brands(include_generic=False):
            if not cls._contains_token(lowered_text, brand_name):
                continue
            brand_models = cls.models_for_brand(brand_name, include_generic=False)
            if len(brand_models) == 1:
                matches.extend(brand_models)
        return matches

    @classmethod
    def _find_by_display_name(cls, display_name: str) -> HardwareSigner | None:
        for hardware_signer in cls.as_list(include_generic=False):
            if hardware_signer.display_name == display_name:
                return hardware_signer
        return None

    @staticmethod
    def _contains_token(lowered_text: str, value: str) -> bool:
        pattern = r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)"
        return bool(re.search(pattern, lowered_text))
