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

from bitcoin_usb.address_types import SimplePubKeyProvider

from bitcoin_safe.gui.qt.custom_edits import (
    AnalyzerMessage,
    AnalyzerState,
    BaseAnalyzer,
)

logger = logging.getLogger(__name__)

from typing import Callable

import bdkpython as bdk
from bitcoin_qr_tools.data import convert_slip132_to_bip32, is_slip132
from bitcoin_qr_tools.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)
from PyQt6.QtCore import QObject

from ...keystore import KeyStore
from .util import Message


class KeyOriginAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, get_expected_key_origin: Callable[[], str], parent: QObject | None) -> None:
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)
        self.get_expected_key_origin = get_expected_key_origin

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing Key origin"), AnalyzerState.Invalid)

        try:
            input = SimplePubKeyProvider.format_key_origin(input)
        except Exception as e:
            return AnalyzerMessage(str(e), AnalyzerState.Invalid)

        if input == self.get_expected_key_origin():
            return AnalyzerMessage("Expected Key Origin", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Unexpected key origin"), AnalyzerState.Warning)


class FingerprintAnalyzer(BaseAnalyzer, QObject):
    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing Fingerprint"), AnalyzerState.Invalid)

        try:
            input = SimplePubKeyProvider.format_fingerprint(input)
        except Exception as e:
            return AnalyzerMessage(str(e), AnalyzerState.Invalid)

        if KeyStore.is_fingerprint_valid(input):
            return AnalyzerMessage("Valid Fingerprint", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Fingerprint"), AnalyzerState.Invalid)


class XpubAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing xPub"), AnalyzerState.Invalid)

        if is_slip132(input):
            Message(
                self.tr("The xpub is in SLIP132 format. Converting to standard format."),
                title=self.tr("Converting format"),
            )
            try:
                input = convert_slip132_to_bip32(input)
            except:
                pass

        if KeyStore.is_xpub_valid(input, network=self.network):
            return AnalyzerMessage("Valid xpub", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid xpub"), AnalyzerState.Invalid)


class SeedAnalyzer(BaseAnalyzer, QObject):
    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing Seed"), AnalyzerState.Valid)

        if KeyStore.is_seed_valid(input):
            return AnalyzerMessage("Valid seed", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid seed"), AnalyzerState.Invalid)


class DescriptorAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing Descriptor"), AnalyzerState.Invalid)

        if BitcoinQRMultipathDescriptor.is_valid(input, network=self.network):
            return AnalyzerMessage("Valid Descriptor", AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Descriptor"), AnalyzerState.Invalid)


class AddressAnalyzer(BaseAnalyzer, QObject):
    def __init__(self, network: bdk.Network, parent: QObject | None) -> None:
        BaseAnalyzer.__init__(self)
        QObject.__init__(self, parent=parent)

        self.network = network

    def analyze(self, input: str, pos: int = 0) -> AnalyzerMessage:
        if not input:
            return AnalyzerMessage(self.tr("Missing Address"), AnalyzerState.Invalid)

        is_valid = False
        try:
            bdk_address = bdk.Address(input, network=self.network)
            is_valid = bool(bdk_address)
        except:
            is_valid = False

        if is_valid:
            return AnalyzerMessage(self.tr("Valid Address"), AnalyzerState.Valid)
        else:
            return AnalyzerMessage(self.tr("Invalid Address"), AnalyzerState.Invalid)
