import logging
logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *



from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.balance_dialog import COLOR_FROZEN, COLOR_CONFIRMED, COLOR_FROZEN_LIGHTNING, COLOR_LIGHTNING, COLOR_UNCONFIRMED, COLOR_UNMATURED
from .gui.qt.util import add_tab_to_tabs, read_QIcon
from .signals import Signals
from .keystore import KeyStore
import bdkpython as bdk
from .wallet import Wallet

class AbstractSigner():
    def __init__(self, network:bdk.Network) -> None:
        self.network = network        
    
    def sign(self, psbt:bdk.PartiallySignedTransaction, sign_options:bdk.SignOptions):
        pass

    @property
    def label(self):
        pass
    
    def get_singing_options(self):
        pass
    

class SignerWallet(AbstractSigner):
    def __init__(self, wallet:Wallet, network:bdk.Network) -> None:
        super().__init__(network=network)
        self.wallet = wallet

    def sign(self, psbt:bdk.PartiallySignedTransaction, sign_options:bdk.SignOptions):
        return self.wallet.bdkwallet.sign(psbt, sign_options=sign_options)

    @property
    def label(self):
        return f"Wallet Signer {self.wallet.id}"

