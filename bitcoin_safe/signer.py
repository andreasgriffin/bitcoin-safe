import logging
from .gui.qt.open_tx_dialog import TransactionDialog
from .signals import Signals

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *


from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.balance_dialog import (
    COLOR_FROZEN,
    COLOR_CONFIRMED,
    COLOR_FROZEN_LIGHTNING,
    COLOR_LIGHTNING,
    COLOR_UNCONFIRMED,
    COLOR_UNMATURED,
)
from .gui.qt.util import (
    Message,
)
from .keystore import KeyStore, KeyStoreTypes
import bdkpython as bdk
from .wallet import Wallet
from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui
from bitcoin_qrreader.bitcoin_qr import Data, DataType
from .util import tx_of_psbt_to_hex
from bitcoin_usb.software_signer import SoftwareSigner
from bitcoin_usb.gui import USBGui


class AbstractSigner(QObject):
    signal_signature_added = Signal(bdk.PartiallySignedTransaction)
    keystore_type = KeyStoreTypes.watch_only

    def __init__(self, network: bdk.Network, blockchain: bdk.Blockchain) -> None:
        super().__init__()
        self.network = network
        self.blockchain = blockchain

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        pass

    @property
    def label(self):
        pass

    def get_singing_options(self):
        pass

    def can_sign(self):
        return False


class SignerWallet(AbstractSigner):
    keystore_type = KeyStoreTypes.seed

    def __init__(self, wallet: Wallet, network: bdk.Network) -> None:
        super().__init__(network=network, blockchain=wallet.blockchain)

        self.software_signers = [
            SoftwareSigner(keystore.mnemonic, self.network)
            for keystore in wallet.keystores
            if keystore.mnemonic
        ]

    def can_sign(self):
        return bool(self.software_signers)

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        original_serialized_tx = tx_of_psbt_to_hex(psbt)
        for software_signer in self.software_signers:
            psbt = software_signer.sign_psbt(psbt)

        logger.debug(f"psbt before signing: {tx_of_psbt_to_hex(psbt)}")

        signing_was_successful: bool = original_serialized_tx != tx_of_psbt_to_hex(psbt)

        if signing_was_successful:
            logger.debug(f"psbt after signing: {tx_of_psbt_to_hex(psbt)}")
            logger.debug(f"psbt after signing: fee  {psbt.fee_rate().as_sat_per_vb()}")

        else:
            logger.debug(f"signign not completed")
        self.signal_signature_added.emit(psbt)

    @property
    def label(self):
        return f"Sign with mnemonic seed"


class QRSigner(AbstractSigner):
    keystore_type = KeyStoreTypes.qr

    def __init__(
        self,
        label: str,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        dummy_wallet: Wallet,
    ) -> None:
        super().__init__(network=network, blockchain=blockchain)
        self._label = label
        self.dummy_wallet = dummy_wallet

    def scan_result_callback(
        self, original_psbt: bdk.PartiallySignedTransaction, data: bitcoin_qr.Data
    ):
        logger.debug(str(data.data))
        if data.data_type == bitcoin_qr.DataType.PSBT:
            scanned_psbt: bdk.PartiallySignedTransaction = data.data
            logger.debug(str(scanned_psbt.serialize()))
            psbt2 = original_psbt.combine(scanned_psbt)
            if psbt2.serialize() != original_psbt.serialize():
                # finalize the psbt (some hardware wallets like specter diy dont do that)
                self.dummy_wallet.bdkwallet.sign(psbt2, None)
                logger.debug(f"psbt updated {psbt2.serialize()}")
                self.signal_signature_added.emit(psbt2)
            else:
                logger.debug(f"psbt unchanged {psbt2.serialize()}")
        elif data.data_type == bitcoin_qr.DataType.Tx:
            scanned_tx: bdk.Transaction = data.data
            if scanned_tx.txid() == original_psbt.txid():
                self.signal_signature_added.emit(scanned_tx)
            else:
                Message(
                    "Scanned a transaction unrelated to the current PSBT"
                ).show_error()
                return

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):

        window = bitcoin_qr_gui.BitcoinVideoWidget(
            result_callback=lambda data: self.scan_result_callback(psbt, data)
        )
        window.show()

    @property
    def label(self):
        return f"{self._label}"


class FileSigner(QRSigner):
    keystore_type = KeyStoreTypes.file

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        tx_dialog = TransactionDialog(
            network=self.network,
            title="Import signed PSBT",
            on_open=lambda s: self.scan_result_callback(
                psbt, bitcoin_qr.Data.from_str(s, network=self.network)
            ),
        )
        tx_dialog.show()

    @property
    def label(self):
        return f"{self._label}"


class USBSigner(QRSigner):
    keystore_type = KeyStoreTypes.hwi

    def __init__(
        self,
        label: str,
        network: bdk.Network,
        blockchain: bdk.Blockchain,
        dummy_wallet: Wallet,
    ) -> None:
        super().__init__(label, network, blockchain, dummy_wallet)
        self.usb = USBGui(self.network)

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        signed_psbt = self.usb.sign(psbt)
        if signed_psbt:
            self.scan_result_callback(psbt, Data(signed_psbt, DataType.PSBT))

    @property
    def label(self):
        return f"{self._label}"
