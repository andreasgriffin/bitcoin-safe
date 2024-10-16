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

logger = logging.getLogger(__name__)

from typing import Sequence

import bdkpython as bdk
from bitcoin_qr_tools.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)
from bitcoin_usb.address_types import (
    AddressType,
    AddressTypes,
    ConstDerivationPaths,
    DescriptorInfo,
    SimplePubKeyProvider,
)


def get_default_address_type(is_multisig) -> AddressType:
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh


class MultipathDescriptor(BitcoinQRMultipathDescriptor):
    @classmethod
    def from_keystores(
        cls,
        threshold: int,
        spk_providers: Sequence[SimplePubKeyProvider],
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

        return cls(
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

    def __str__(self) -> str:
        return self.as_string()
