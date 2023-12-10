import logging
from bitcoin_safe.gui.qt.open_tx_dialog import TransactionDialog

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
from .util import psbt_to_hex


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
        self.wallet = wallet

    def can_sign(self):
        for keystore in self.wallet.keystores:
            if keystore.mnemonic:
                return True
        # in case the secret is not in a mnemonic but in the descriptor
        return (
            self.wallet.multipath_descriptor.as_string_private()
            != self.wallet.multipath_descriptor.as_string()
        )

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        # sign transaction - this method mutates transaction, so we copy it first
        psbt2 = bdk.PartiallySignedTransaction(psbt.serialize())

        logger.debug(f"psbt before signing: {psbt_to_hex(psbt2)}")

        signing_was_successful: bool = self.wallet.bdkwallet.sign(
            psbt2, sign_options=sign_options
        )

        if signing_was_successful:
            logger.debug(f"psbt after signing: {psbt_to_hex(psbt2)}")
            logger.debug(f"psbt after signing: fee  {psbt2.fee_rate().as_sat_per_vb()}")

        else:
            logger.debug(f"signign not completed")
        self.signal_signature_added.emit(psbt2)

    @property
    def label(self):
        return f"Sign with wallet {self.wallet.id}"


class QRSigner(AbstractSigner):
    keystore_type = KeyStoreTypes.qr

    def __init__(
        self, label: str, network: bdk.Network, blockchain: bdk.Blockchain
    ) -> None:
        super().__init__(network=network, blockchain=blockchain)
        self._label = label

    def scan_result_callback(
        self, original_psbt: bdk.PartiallySignedTransaction, data: bitcoin_qr.Data
    ):
        logger.debug(str(data.data))
        if data.data_type == bitcoin_qr.DataType.PSBT:
            scanned_psbt: bdk.PartiallySignedTransaction = data.data
            logger.debug(str(scanned_psbt.serialize()))
            psbt2 = original_psbt.combine(scanned_psbt)
            if psbt2.serialize() != original_psbt.serialize():
                self.signal_signature_added.emit(psbt2)
                logger.debug(f"psbt updated {psbt2.serialize()}")
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
            title="Open signed PSBT",
            on_open=lambda s: self.scan_result_callback(
                psbt, bitcoin_qr.Data.from_str(s, network=self.network)
            ),
        )
        tx_dialog.show()

    @property
    def label(self):
        return f"{self._label}"
