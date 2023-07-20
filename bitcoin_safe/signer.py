import logging

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
from .gui.qt.util import add_tab_to_tabs, read_QIcon
from .signals import Signals
from .keystore import KeyStore, KeyStoreTypes
import bdkpython as bdk
from .wallet import Wallet
from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui
from .util import compare_dictionaries, psbt_to_hex


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
        return (
            self.wallet.descriptors[0].as_string_private()
            != self.wallet.descriptors[0].as_string()
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

            self.signal_signature_added.emit(psbt2)
        else:
            logger.debug(f"signign failed")

    @property
    def label(self):
        return f"Wallet Signer {self.wallet.id}"


class QRSigner(AbstractSigner):
    keystore_type = KeyStoreTypes.qr

    def __init__(self, network: bdk.Network, blockchain: bdk.Blockchain) -> None:
        super().__init__(network=network, blockchain=blockchain)

    def sign(
        self, psbt: bdk.PartiallySignedTransaction, sign_options: bdk.SignOptions = None
    ):
        def result_callback(data: bitcoin_qr.Data):
            logger.debug(str(data.data))
            if data.data_type == bitcoin_qr.DataType.PSBT:
                scanned_psbt: bdk.PartiallySignedTransaction = data.data
                logger.debug(str(scanned_psbt.serialize()))
                psbt2 = psbt.combine(scanned_psbt)
                if psbt2.serialize() != psbt.serialize():
                    self.signal_signature_added.emit(psbt2)
                    logger.debug(f"psbt updated {psbt2.serialize()}")
                else:
                    logger.debug(f"psbt unchanged {psbt2.serialize()}")
            elif data.data_type == bitcoin_qr.DataType.Tx:
                scanned_tx: bdk.Transaction = data.data
                if scanned_tx.txid() == psbt.txid():
                    self.signal_signature_added.emit(scanned_tx)
                else:
                    logger.error("Scanned a transaction unrelated to the current PSBT")

        window = bitcoin_qr_gui.BitcoinVideoWidget(result_callback=result_callback)
        window.show()

    @property
    def label(self):
        return f"QR Signer {self.wallet.id}"
