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
from typing import List

from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.util import Message, MessageType, caught_exception_message
from bitcoin_safe.psbt_util import PubKeyInfo

from .dynamic_lib_load import setup_libsecp256k1
from .gui.qt.dialog_import import ImportDialog

setup_libsecp256k1()


logger = logging.getLogger(__name__)

import bdkpython as bdk
from bitcoin_qr_tools.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_usb.gui import USBGui
from bitcoin_usb.psbt_finalizer import PSBTFinalizer
from bitcoin_usb.software_signer import SoftwareSigner
from PyQt6.QtCore import QObject, pyqtSignal

from .keystore import KeyStoreImporterTypes
from .util import tx_of_psbt_to_hex
from .wallet import Wallet


class AbstractSignatureImporter(QObject):
    signal_signature_added = pyqtSignal(bdk.PartiallySignedTransaction)
    signal_final_tx_received = pyqtSignal(bdk.Transaction)
    keystore_type = KeyStoreImporterTypes.watch_only

    def __init__(
        self,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature: List[PubKeyInfo] = None,
    ) -> None:
        super().__init__()
        self.network = network
        self.blockchain = blockchain
        self.signature_available = signature_available
        self.key_label = key_label
        self.pub_keys_without_signature = pub_keys_without_signature

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):
        pass

    @property
    def label(self) -> str:
        return ""

    def get_singing_options(self):
        pass

    def can_sign(self) -> bool:
        return False

    def txids_match(
        self,
        psbt1: bdk.PartiallySignedTransaction,
        psbt2: bdk.PartiallySignedTransaction,
    ) -> bool:
        return bool(psbt1.txid() == psbt2.txid())


class SignatureImporterWallet(AbstractSignatureImporter):
    keystore_type = KeyStoreImporterTypes.seed

    def __init__(
        self, wallet: Wallet, network: bdk.Network, signature_available: bool = False, key_label: str = ""
    ) -> None:
        super().__init__(
            network=network,
            blockchain=wallet.blockchain,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=[
                PubKeyInfo(keystore.fingerprint, label=keystore.label)
                for keystore in wallet.keystores
                if keystore.mnemonic
            ],
        )

        self.software_signers = [
            SoftwareSigner(keystore.mnemonic, self.network)
            for keystore in wallet.keystores
            if keystore.mnemonic
        ]

    def can_sign(self) -> bool:
        return bool(self.software_signers)

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):
        original_psbt = psbt
        original_serialized_tx = tx_of_psbt_to_hex(psbt)
        for software_signer in self.software_signers:
            psbt = software_signer.sign_psbt(psbt)

        if not self.txids_match(original_psbt, psbt):
            Message(self.tr("The txid of the signed psbt doesnt match the original txid. Aborting"))
            return

        logger.debug(f"psbt before signing: {tx_of_psbt_to_hex(psbt)}")

        signing_was_successful: bool = original_serialized_tx != tx_of_psbt_to_hex(psbt)

        if signing_was_successful:
            logger.debug(f"psbt after signing: {tx_of_psbt_to_hex(psbt)}")
            logger.debug(f"psbt after signing: fee  {psbt.fee_rate().as_sat_per_vb()}")

        else:
            logger.debug(f"signign not completed")
        self.signal_signature_added.emit(psbt)

    @property
    def label(self) -> str:
        return f"Sign with mnemonic seed"


class SignatureImporterQR(AbstractSignatureImporter):
    keystore_type = KeyStoreImporterTypes.qr

    def __init__(
        self,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = None,
    ) -> None:
        super().__init__(
            network=network,
            blockchain=blockchain,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
        )
        self._label = label if label else self.tr("Scan QR code")

    def scan_result_callback(self, original_psbt: bdk.PartiallySignedTransaction, data: Data):
        logger.debug(str(data.data))
        if data.data_type == DataType.PSBT:
            scanned_psbt: bdk.PartiallySignedTransaction = data.data
            assert self.txids_match(scanned_psbt, original_psbt), self.tr(
                "The txid of the signed psbt doesnt match the original txid"
            )

            logger.debug(str(scanned_psbt.serialize()))
            psbt2 = original_psbt.combine(scanned_psbt)
            assert self.txids_match(psbt2, original_psbt), self.tr(
                "The txid of the signed psbt doesnt match the original txid"
            )

            if psbt2.serialize() == original_psbt.serialize():
                logger.debug(f"psbt unchanged {psbt2.serialize()}")
                return

            # check if the tx can be finalized:
            finalized_tx = PSBTFinalizer.finalize(psbt2)
            if finalized_tx:
                assert finalized_tx.txid() == original_psbt.txid(), self.tr(
                    "bitcoin_tx libary error. The txid should not be changed during finalizing"
                )
                self.signal_final_tx_received.emit(finalized_tx)
                return

            logger.debug(f"psbt updated {psbt2.serialize()}")
            self.signal_signature_added.emit(psbt2)

        elif data.data_type == DataType.Tx:
            scanned_tx: bdk.Transaction = data.data
            if scanned_tx.txid() != original_psbt.txid():
                Message(
                    self.tr("The txid of the signed psbt doesnt match the original txid"),
                    type=MessageType.Error,
                )
                return
            # assert (
            #     scanned_tx.txid() == original_psbt.txid()
            # ), "The txid of the signed psbt doesnt match the original txid"

            # TODO: Actually check if the tx is fully signed
            self.signal_final_tx_received.emit(scanned_tx)
        else:
            logger.warning(f"Datatype {data.data_type} is not valid for importing signatures")

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):

        window = BitcoinVideoWidget(
            result_callback=lambda data: self.scan_result_callback(psbt, data), network=self.network
        )
        window.show()

    @property
    def label(self) -> str:
        return f"{self._label}"


class SignatureImporterFile(SignatureImporterQR):
    keystore_type = KeyStoreImporterTypes.file

    def __init__(
        self,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = "Import file",
    ) -> None:
        super().__init__(
            network=network,
            blockchain=blockchain,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
        )

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):
        tx_dialog = ImportDialog(
            network=self.network,
            window_title="Import signed PSBT",
            on_open=lambda s: self.scan_result_callback(psbt, Data.from_str(s, network=self.network)),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr("Please paste your PSBT in here, or drop a file"),
            text_placeholder=self.tr("Paste your PSBT in here or drop a file"),
        )
        tx_dialog.show()
        # tx_dialog.text_edit.button_open_file.click()

    @property
    def label(self) -> str:
        return f"{self._label}"


class SignatureImporterClipboard(SignatureImporterFile):
    keystore_type = KeyStoreImporterTypes.clipboard

    def __init__(
        self,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = "Import Signature",
    ) -> None:
        super().__init__(
            network=network,
            blockchain=blockchain,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
        )

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):
        tx_dialog = ImportDialog(
            network=self.network,
            window_title=self.tr("Import signed PSBT"),
            on_open=lambda s: self.scan_result_callback(psbt, Data.from_str(s, network=self.network)),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr("Please paste your PSBT in here, or drop a file"),
            text_placeholder=self.tr("Paste your PSBT in here or drop a file"),
        )
        tx_dialog.show()

    @property
    def label(self) -> str:
        return f"{self._label}"


class SignatureImporterUSB(SignatureImporterQR):
    keystore_type = KeyStoreImporterTypes.hwi

    def __init__(
        self,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = None,
    ) -> None:
        label = label if label else self.tr("USB Signing")
        super().__init__(
            network=network,
            blockchain=blockchain,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
        )
        self.usb = USBGui(self.network)

    def sign(self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None):
        try:
            signed_psbt = self.usb.sign(psbt)
            if signed_psbt:
                self.scan_result_callback(psbt, Data.from_psbt(signed_psbt))
        except Exception as e:
            if "multisig" in str(e).lower():
                question_dialog(
                    self.tr(
                        "Please do 'Wallet --> Export --> Export for ...' and register the multisignature wallet on the hardware signer."
                    )
                )
            else:
                caught_exception_message(e)

    @property
    def label(self) -> str:
        return f"{self._label}"
