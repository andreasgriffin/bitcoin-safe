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
from collections.abc import Callable

import bdkpython as bdk
from bitcoin_qr_tools.data import ConverterXpub
from bitcoin_qr_tools.multipath_descriptor import is_valid_descriptor
from bitcoin_usb.address_types import AddressType, SimplePubKeyProvider, get_all_address_types
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerMessage,
    AnalyzerState,
    BaseAnalyzer,
)

from ...keystore import KeyStore
from .util import Message

logger = logging.getLogger(__name__)


class KeyOriginAnalyzer(BaseAnalyzer, QObject):
    def __init__(
        self, get_expected_key_origin: Callable[[], str], network: bdk.Network, parent: QObject | None
    ) -> None:
        """Initialize instance."""
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)
        self.get_expected_key_origin = get_expected_key_origin
        self.network = network

    def _get_address_type_for_key_origin(self, key_origin: str) -> AddressType | None:
        account_number = SimplePubKeyProvider.get_account_index(key_origin)
        if account_number is None:
            return None

        for address_type in get_all_address_types():
            if address_type.key_origin(self.network, account_number=account_number) == key_origin:
                return address_type

        return None

    def _get_address_type_mismatch_message(self, key_origin: str, expected_key_origin: str) -> str | None:
        provided_address_type = self._get_address_type_for_key_origin(key_origin)
        expected_address_type = self._get_address_type_for_key_origin(expected_key_origin)
        if (
            provided_address_type is None
            or expected_address_type is None
            or provided_address_type == expected_address_type
        ):
            return None

        if provided_address_type.is_multisig != expected_address_type.is_multisig:
            provided_kind = (
                self.tr("multi-sig") if provided_address_type.is_multisig else self.tr("single-sig")
            )
            expected_kind = (
                self.tr("multi-sig") if expected_address_type.is_multisig else self.tr("single-sig")
            )
            return self.tr("This looks like a {provided_kind}. Expected: {expected_kind}.").format(
                provided_kind=provided_kind,
                expected_kind=expected_kind,
            )

        return self.tr("{given} looks like {provided_type}, but this wallet expects {expected_type}.").format(
            given=key_origin,
            provided_type=provided_address_type.name,
            expected_type=expected_address_type.name,
        )

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing Key origin"), AnalyzerState.Invalid)

        try:
            input = SimplePubKeyProvider.format_key_origin(input)
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            return AnalyzerMessage(str(e), AnalyzerState.Invalid)

        expected_key_origin = self.get_expected_key_origin()
        if input == expected_key_origin:
            return AnalyzerMessage("Expected Key Origin", AnalyzerState.Valid)
        else:
            network_index_input = SimplePubKeyProvider.get_network_index(input)
            network_index_expected = SimplePubKeyProvider.get_network_index(expected_key_origin)
            if (network_index_input is not None) and network_index_input != network_index_expected:
                return AnalyzerMessage(
                    self.tr(
                        "The provided information is for {key_origin_network}. Please provide xPub for network {network}"
                    ).format(
                        key_origin_network=(
                            bdk.Network.BITCOIN.name
                            if SimplePubKeyProvider.get_network_index(input) == 0
                            else bdk.Network.TESTNET.name
                        ),
                        network=self.network,
                    ),
                    AnalyzerState.Invalid,
                )
            elif message := self._get_address_type_mismatch_message(input, expected_key_origin):
                return AnalyzerMessage(message, AnalyzerState.Warning)
            elif SimplePubKeyProvider.key_origin_identical_disregarding_account(input, expected_key_origin):
                return AnalyzerMessage(
                    self.tr(
                        "The provided account {provided_account} differs from the default account {default_account}."
                    ).format(
                        provided_account=SimplePubKeyProvider.get_account_index(input),
                        default_account=SimplePubKeyProvider.get_account_index(expected_key_origin),
                    ),
                    AnalyzerState.Warning,
                )
            else:
                return AnalyzerMessage(
                    self.tr(
                        "The provided xpub origin {given} does not match the expectation {expected}"
                    ).format(given=input, expected=expected_key_origin),
                    AnalyzerState.Warning,
                )


class FingerprintAnalyzer(BaseAnalyzer, QObject):
    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing Fingerprint"), AnalyzerState.Invalid)

        try:
            input = SimplePubKeyProvider.format_fingerprint(input)
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            return AnalyzerMessage(str(e), AnalyzerState.Invalid)

        if KeyStore.is_fingerprint_valid(input):
            return AnalyzerMessage("Valid Fingerprint", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Fingerprint"), AnalyzerState.Invalid)


class XpubAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        """Initialize instance."""
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def normalize(self, input: str, pos: int = 0) -> tuple[str, int]:
        """Normalize."""
        if ConverterXpub.is_slip132(input):
            parent = self.parent()
            parent_widget = parent if isinstance(parent, QWidget) else None
            Message(
                self.tr("The xpub is in SLIP132 format. Converting to standard format."),
                title=self.tr("Converting format"),
                parent=parent_widget,
            )
            try:
                input = ConverterXpub.convert_slip132_to_bip32(input)
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
        return input, pos

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing xPub"), AnalyzerState.Invalid)

        if KeyStore.is_xpub_valid(input, network=self.network):
            return AnalyzerMessage("Valid xpub", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid xpub"), AnalyzerState.Invalid)


class SeedAnalyzer(BaseAnalyzer, QObject):
    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing Seed"), AnalyzerState.Valid)

        if KeyStore.is_seed_valid(input):
            return AnalyzerMessage("Valid seed", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid seed"), AnalyzerState.Invalid)


class DescriptorAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        """Initialize instance."""
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing Descriptor"), AnalyzerState.Invalid)

        if is_valid_descriptor(input, network=self.network):
            return AnalyzerMessage("Valid Descriptor", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Descriptor"), AnalyzerState.Invalid)


class AddressAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        """Initialize instance."""
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        """Analyze."""
        if not input:
            return AnalyzerMessage(self.tr("Missing Address"), AnalyzerState.Invalid)

        is_valid = False
        try:
            bdk_address = bdk.Address(input, network=self.network)
            is_valid = bool(bdk_address)
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            is_valid = False

        if is_valid:
            return AnalyzerMessage(self.tr("Valid Address"), AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Address"), AnalyzerState.Invalid)


class AmountAnalyzer(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.max_amount = 0
        self.min_amount = 0

    def analyze(self, input: float) -> AnalyzerMessage:  # type: ignore
        """Analyze."""
        if input < self.min_amount:
            return AnalyzerMessage(self.tr("Amount too small"), AnalyzerState.Invalid)
        if input > self.max_amount:
            return AnalyzerMessage(
                self.tr(
                    "Amount too large. Please click on a sufficiently funded category on the left, or select the coins in the advanced tab"
                ),
                AnalyzerState.Invalid,
            )

        return AnalyzerMessage("Amount within allowed range", AnalyzerState.Valid)
