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
from typing import Optional

import bdkpython as bdk
from bitcoin_qr_tools.data import ConverterMultisigWalletExport
from bitcoin_qr_tools.signer_info import SignerInfo
from bitcoin_usb.address_types import DescriptorInfo

from bitcoin_safe.gui.qt.util import save_file_dialog
from bitcoin_safe.hardware_signers import DescriptorExportType, DescriptorExportTypes
from bitcoin_safe.wallet import filename_clean

from .descriptors import MultipathDescriptor

logger = logging.getLogger(__name__)


class DescriptorExportTools:

    @classmethod
    def _get_coldcard_str(cls, wallet_id: str, multipath_descriptor: MultipathDescriptor) -> str:
        return f"""# Coldcard descriptor export of wallet: {filename_clean( wallet_id, file_extension='', replace_spaces_by='_')}
{ multipath_descriptor.bdk_descriptors[0].as_string() }"""

    @staticmethod
    def _get_passport_str(wallet_id: str, descriptor_str: str, hardware_signer_name="Passport") -> str:
        infos = DescriptorInfo.from_str(descriptor_str)
        signer_infos = [
            SignerInfo(
                xpub=spk_provider.xpub,
                fingerprint=spk_provider.fingerprint,
                key_origin=spk_provider.key_origin,
                derivation_path=spk_provider.derivation_path,
            )
            for spk_provider in infos.spk_providers
        ]
        return ConverterMultisigWalletExport(
            name=filename_clean(wallet_id, file_extension="", replace_spaces_by="_"),
            threshold=infos.threshold,
            address_type_short_name=infos.address_type.short_name.upper(),
            signer_infos=signer_infos,
        ).to_custom_str(hardware_signer_name=hardware_signer_name)

    @classmethod
    def _get_keystone_str(cls, wallet_id: str, descriptor_str: str, network: bdk.Network) -> str:
        return cls._get_passport_str(
            wallet_id=wallet_id, descriptor_str=descriptor_str, hardware_signer_name="Keystone"
        )

    @classmethod
    def _get_specter_diy_str(cls, wallet_id: str, descriptor_str: str) -> str:
        simplified_descriptor = (
            descriptor_str.split("#")[0].replace("/<0;1>/*", "").replace("0/*", "").replace("1/*", "")
        )
        return f"addwallet {filename_clean( wallet_id, file_extension='', replace_spaces_by='_')}&{simplified_descriptor}"

    @classmethod
    def _export_wallet(cls, wallet_id: str, s: str, descripor_type: DescriptorExportType) -> Optional[str]:
        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=filename_clean(wallet_id, file_extension=".txt", replace_spaces_by="_")[:24],
            window_title=f"Export Wallet for {descripor_type.display_name}",
        )
        if not filename:
            return None

        with open(filename, "w") as file:
            file.write(s)
        return filename

    @classmethod
    def get_export_str(
        cls,
        wallet_id: str,
        multipath_descriptor: MultipathDescriptor,
        network: bdk.Network,
        descriptor_export_type: DescriptorExportType,
    ) -> str:
        if descriptor_export_type.name == DescriptorExportTypes.text.name:
            return multipath_descriptor.as_string()
        elif descriptor_export_type.name == DescriptorExportTypes.coldcard.name:
            return cls._get_coldcard_str(wallet_id=wallet_id, multipath_descriptor=multipath_descriptor)
        elif descriptor_export_type.name == DescriptorExportTypes.passport.name:
            return cls._get_passport_str(
                wallet_id=wallet_id,
                descriptor_str=multipath_descriptor.as_string(),
            )
        elif descriptor_export_type.name == DescriptorExportTypes.keystone.name:
            return cls._get_keystone_str(
                wallet_id=wallet_id, descriptor_str=multipath_descriptor.as_string(), network=network
            )
        elif descriptor_export_type.name == DescriptorExportTypes.specterdiy.name:
            return cls._get_specter_diy_str(
                wallet_id=wallet_id, descriptor_str=multipath_descriptor.as_string()
            )
        else:
            raise NotImplementedError(f"Cannot export descritpor for type {descriptor_export_type}")

    @classmethod
    def export(
        cls,
        wallet_id: str,
        multipath_descriptor: MultipathDescriptor,
        network: bdk.Network,
        descripor_type: DescriptorExportType,
    ):
        if descripor_type.name not in [t.name for t in DescriptorExportTypes.as_list()]:
            logger.error(f"Cannot export the descriptor for {descripor_type}")
            return

        cls._export_wallet(
            wallet_id=wallet_id,
            s=cls.get_export_str(
                wallet_id=wallet_id,
                multipath_descriptor=multipath_descriptor,
                network=network,
                descriptor_export_type=descripor_type,
            ),
            descripor_type=descripor_type,
        )
