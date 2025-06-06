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

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.gui.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_safe_lib.tx_util import tx_of_psbt_to_hex, tx_to_hex
from bitcoin_usb.software_signer import SoftwareSigner
from bitcoin_usb.usb_gui import USBGui
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.util import Message, MessageType, caught_exception_message
from bitcoin_safe.i18n import translate
from bitcoin_safe.psbt_util import PubKeyInfo
from bitcoin_safe.typestubs import TypedPyQtSignal, TypedPyQtSignalNo

from .gui.qt.dialog_import import ImportDialog
from .keystore import KeyStoreImporterTypes
from .wallet import Wallet

logger = logging.getLogger(__name__)


class AbstractSignatureImporter(QObject):
    signal_signature_added: TypedPyQtSignal[bdk.Psbt] = pyqtSignal(bdk.Psbt)  # type: ignore
    signal_final_tx_received: TypedPyQtSignal[bdk.Transaction] = pyqtSignal(bdk.Transaction)  # type: ignore
    keystore_type = KeyStoreImporterTypes.clipboard

    def __init__(
        self,
        network: bdk.Network,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature: List[PubKeyInfo] | None = None,
    ) -> None:
        super().__init__()
        self.network = network
        self.signature_available = signature_available
        self.key_label = key_label
        self.pub_keys_without_signature = pub_keys_without_signature

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
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
        psbt1: bdk.Psbt,
        psbt2: bdk.Psbt,
    ) -> bool:
        return bool(psbt1.extract_tx().compute_txid() == psbt2.extract_tx().compute_txid())

    def handle_data_input(self, original_psbt: bdk.Psbt, data: Data):
        logger.debug(f"handle_data_input {data.data_type=}")
        if data.data_type == DataType.PSBT:
            scanned_psbt: bdk.Psbt = data.data

            if not self.txids_match(scanned_psbt, original_psbt):
                Message(
                    self.tr("The txid of the signed psbt doesnt match the original txid"),
                    type=MessageType.Error,
                )
                return

            logger.debug(f"{str(scanned_psbt.serialize())[:4]=}")
            psbt2 = original_psbt.combine(scanned_psbt)

            if not self.txids_match(psbt2, original_psbt):
                Message(
                    self.tr("The txid of the signed psbt doesnt match the original txid"),
                    type=MessageType.Error,
                )
                return

            if psbt2.serialize() == original_psbt.serialize():
                Message(
                    self.tr("No additional signatures were added"),
                    type=MessageType.Error,
                )
                return

            # check if the tx can be finalized:
            finalize_result = psbt2.finalize()
            if finalize_result.could_finalize:
                finalized_tx = finalize_result.psbt.extract_tx()
                assert finalized_tx.compute_txid() == original_psbt.extract_tx().compute_txid(), self.tr(
                    "bdk libary error. The txid should not be changed during finalizing"
                )
                self.signal_final_tx_received.emit(finalized_tx)
                return

            logger.debug(f"psbt updated {psbt2.extract_tx().compute_txid()[:4]=}")
            self.signal_signature_added.emit(psbt2)

        elif data.data_type == DataType.Tx:
            scanned_tx: bdk.Transaction = data.data
            if scanned_tx.compute_txid() != original_psbt.extract_tx().compute_txid():
                Message(
                    self.tr("The txid of the signed psbt doesnt match the original txid"),
                    type=MessageType.Error,
                )
                return
            if tx_to_hex(scanned_tx) == tx_to_hex(original_psbt.extract_tx()):
                Message(
                    self.tr("No additional signatures were added"),
                    type=MessageType.Error,
                )
                return

            # TODO: Actually check if the tx is fully signed
            self.signal_final_tx_received.emit(scanned_tx)
        else:
            logger.warning(f"Datatype {data.data_type} is not valid for importing signatures")


class SignatureImporterWallet(AbstractSignatureImporter):
    keystore_type = KeyStoreImporterTypes.seed

    def __init__(
        self, wallet: Wallet, network: bdk.Network, signature_available: bool = False, key_label: str = ""
    ) -> None:
        super().__init__(
            network=network,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=[
                PubKeyInfo(keystore.fingerprint, label=keystore.label)
                for keystore in wallet.keystores
                if keystore.mnemonic
            ],
        )

        receive_descriptor, change_descriptor = wallet.multipath_descriptor.to_single_descriptors()
        self.software_signers = [
            SoftwareSigner(
                mnemonic=keystore.mnemonic,
                network=self.network,
                receive_descriptor=receive_descriptor.to_string_with_secret(),
                change_descriptor=change_descriptor.to_string_with_secret(),
            )
            for keystore in wallet.keystores
            if keystore.mnemonic
        ]

    def can_sign(self) -> bool:
        return bool(self.software_signers)

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
        original_psbt = psbt
        original_serialized_tx = tx_of_psbt_to_hex(psbt)
        for software_signer in self.software_signers:
            new_psbt = software_signer.sign_psbt(psbt)
            if new_psbt:
                psbt = new_psbt

        if not self.txids_match(original_psbt, psbt):
            Message(self.tr("The txid of the signed psbt doesnt match the original txid. Aborting"))
            return

        logger.debug(f"psbt before signing: {tx_of_psbt_to_hex(psbt)[:4]=}")

        signing_was_successful: bool = original_serialized_tx != tx_of_psbt_to_hex(psbt)

        if signing_was_successful:
            logger.debug(f"psbt after signing: {tx_of_psbt_to_hex(psbt)[:4]=}")

        else:
            logger.debug(f"signing not completed")
        self.signal_signature_added.emit(psbt)

    @property
    def label(self) -> str:
        return self.tr("Sign with seed")


class SignatureImporterQR(AbstractSignatureImporter):
    keystore_type = KeyStoreImporterTypes.qr

    def __init__(
        self,
        network: bdk.Network,
        close_all_video_widgets: TypedPyQtSignalNo,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str | None = None,
    ) -> None:
        super().__init__(
            network=network,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
        )
        self._label = label if label else self.tr("Scan QR code")
        self._temp_bitcoin_video_widget: BitcoinVideoWidget | None = None
        self.close_all_video_widgets = close_all_video_widgets

        self.close_all_video_widgets.connect(self.close_video_widget)

    def close_video_widget(self):
        if self._temp_bitcoin_video_widget:
            self._temp_bitcoin_video_widget.close()

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
        self.close_all_video_widgets.emit()
        self._temp_bitcoin_video_widget = BitcoinVideoWidget(network=self.network)
        self._temp_bitcoin_video_widget.signal_data.connect(lambda data: self.handle_data_input(psbt, data))
        self._temp_bitcoin_video_widget.show()

    @property
    def label(self) -> str:
        return f"{self._label}"


class SignatureImporterFile(SignatureImporterQR):
    keystore_type = KeyStoreImporterTypes.file

    def __init__(
        self,
        network: bdk.Network,
        close_all_video_widgets: TypedPyQtSignalNo,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = translate("importer", "Import file"),
    ) -> None:
        super().__init__(
            network=network,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
            close_all_video_widgets=close_all_video_widgets,
        )

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
        tx_dialog = ImportDialog(
            network=self.network,
            window_title=self.tr("Import signed PSBT"),
            on_open=lambda s: self.handle_data_input(psbt, Data.from_str(s, network=self.network)),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr("Please paste your PSBT in here, or drop a file"),
            text_placeholder=self.tr("Paste your PSBT in here or drop a file"),
            close_all_video_widgets=self.close_all_video_widgets,
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
        close_all_video_widgets: TypedPyQtSignalNo,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str = translate("importer", "Import Signature"),
    ) -> None:
        super().__init__(
            network=network,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
            close_all_video_widgets=close_all_video_widgets,
        )

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
        tx_dialog = ImportDialog(
            network=self.network,
            window_title=self.tr("Import signed PSBT"),
            on_open=lambda s: self.handle_data_input(psbt, Data.from_str(s, network=self.network)),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr("Please paste your PSBT in here, or drop a file"),
            text_placeholder=self.tr("Paste your PSBT in here or drop a file"),
            close_all_video_widgets=self.close_all_video_widgets,
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
        close_all_video_widgets: TypedPyQtSignalNo,
        signature_available: bool = False,
        key_label: str = "",
        pub_keys_without_signature=None,
        label: str | None = None,
    ) -> None:
        label = label if label else self.tr("USB Signing")
        super().__init__(
            network=network,
            signature_available=signature_available,
            key_label=key_label,
            pub_keys_without_signature=pub_keys_without_signature,
            label=label,
            close_all_video_widgets=close_all_video_widgets,
        )
        self.usb_gui = USBGui(self.network)

    def sign(self, psbt: bdk.Psbt, sign_options: bdk.SignOptions | None = None):
        try:
            signed_psbt = self.usb_gui.sign(psbt, slow_hwi_listing=False)
            if signed_psbt:
                self.handle_data_input(psbt, Data.from_psbt(signed_psbt, network=self.network))
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
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
