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
from dataclasses import dataclass

from bitcoin_qr_tools.unified_encoder import QrExportType, QrExportTypes

logger = logging.getLogger(__name__)


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
            for name, export_type in cls.__dict__.items()
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
            export_type for name, export_type in cls.__dict__.items() if isinstance(export_type, QrExportType)
        ]


class SignMessageRequestQrExportTypes:
    bbqr = QrExportType("bbqr_sign_message_request", "BBQr")
    text = QrExportType("text_sign_message_request", "Text")

    @classmethod
    def as_list(cls) -> list[QrExportType]:
        """As list."""
        return [
            export_type for name, export_type in cls.__dict__.items() if isinstance(export_type, QrExportType)
        ]


@dataclass
class HardwareSigner:
    name: str
    display_name: str
    usb_preferred: bool
    qr_types: list[QrExportType]
    descriptor_export_types: list[DescriptorExportType]

    @property
    def generate_seed_png(self):
        """Generate seed png."""
        return f"{self.name}-generate-seed.png"

    @property
    def wallet_export_png(self):
        """Wallet export png."""
        return f"{self.name}-wallet-export.png"

    @property
    def view_seed_png(self):
        """View seed png."""
        return f"{self.name}-view-seed.png"

    @property
    def register_multisig_decriptor_png(self):
        """Register multisig decriptor png."""
        return f"{self.name}-register-multisig-decriptor.png"

    @property
    def icon_name(self):
        """Icon name."""
        return f"{self.name}-icon.svg"


class HardwareSigners:
    coldcard = HardwareSigner(
        "coldcard",
        "Coldcard-Mk4",
        usb_preferred=False,
        qr_types=[],
        descriptor_export_types=[DescriptorExportTypes.coldcard],
    )
    q = HardwareSigner(
        "q",
        "Q",
        usb_preferred=False,
        qr_types=[
            QrExportTypes.bbqr,
            DescriptorQrExportTypes.coldcard_legacy,
            SignMessageRequestQrExportTypes.bbqr,
            SignMessageRequestQrExportTypes.text,
        ],
        descriptor_export_types=[DescriptorExportTypes.coldcard],
    )
    bitbox02 = HardwareSigner(
        "bitbox02",
        "Bitbox02",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
    )
    jade = HardwareSigner(
        "jade",
        "Jade",
        usb_preferred=True,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[],
    )
    passport = HardwareSigner(
        "passport",
        "Passport",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.default],
    )
    keystone = HardwareSigner(
        "keystone",
        "Keystone",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.default, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.default],
    )
    trezor = HardwareSigner(
        "trezor",
        "Trezor",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
    )
    ledger = HardwareSigner(
        "ledger",
        "Ledger",
        usb_preferred=True,
        qr_types=[],
        descriptor_export_types=[],
    )
    specterdiy = HardwareSigner(
        "specterdiy",
        "Specter-DIY",
        usb_preferred=False,
        qr_types=[QrExportTypes.ur, DescriptorQrExportTypes.specterdiy, SignMessageRequestQrExportTypes.text],
        descriptor_export_types=[DescriptorExportTypes.specterdiy],
    )
    # seedsigner = HardwareSigner(
    #     "seedsigner",
    #     "SeedSigner",
    #     usb_preferred=False,
    #     qr_types=[
    #         QrExportTypes.ur,
    #         QrExportTypes.bbqr,
    #     ],
    #     descriptor_export_types=[],
    # )
    krux = HardwareSigner(
        "krux",
        "Krux",
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
    )

    @classmethod
    def as_list(cls) -> list[HardwareSigner]:
        """As list."""
        return [
            hardware_signer
            for name, hardware_signer in cls.__dict__.items()
            if isinstance(hardware_signer, HardwareSigner)
        ]

    @classmethod
    def filtered_by(
        cls, allowed_types: list[QrExportType] | list[DescriptorExportType]
    ) -> list[HardwareSigner]:
        """Filtered by."""
        allowed_names = set([qr_type.name for qr_type in allowed_types])
        if not allowed_types:
            return []
        first_entry = allowed_types[0]

        if isinstance(first_entry, QrExportType):
            return [
                hardware_signer
                for hardware_signer in cls.as_list()
                if allowed_names.intersection([qrtype.name for qrtype in hardware_signer.qr_types])
            ]
        elif isinstance(first_entry, DescriptorExportType):
            return [
                hardware_signer
                for hardware_signer in cls.as_list()
                if allowed_names.intersection(
                    [qrtype.name for qrtype in hardware_signer.descriptor_export_types]
                )
            ]
        raise Exception(f"{first_entry} has wrong type")
