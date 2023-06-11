import logging
from .logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)



from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *


from .ui_mainwindow import Ui_MainWindow
from .wallet import BlockchainType, Wallet
import sys



from .i18n import _
from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.qt_wallet import QTWallet
from .gui.qt.password_question import PasswordQuestion
from .gui.qt.balance_dialog import COLOR_FROZEN, COLOR_CONFIRMED, COLOR_FROZEN_LIGHTNING, COLOR_LIGHTNING, COLOR_UNCONFIRMED, COLOR_UNMATURED
from .gui.qt.util import add_tab_to_tabs, read_QIcon, MessageBoxMixin
from .signals import Signals
from bdkpython import Network
from typing import Dict
from .storage import Storage
import json, os
import bdkpython as bdk
from .gui.qt.ui_tx import UITX_Creator, UITX_Viewer
from .gui.qt.utxo_list import UTXOList
from .config import UserConfig
from .gui.qt.network_settings import NetworkSettingsUI


class MainWindow(Ui_MainWindow, MessageBoxMixin):
    def __init__(self):
        super().__init__()


        self.qt_wallets :Dict[QTWallet] = {}
        self.fx = None

        self.signals = Signals()
        #connect the listeners
        self.signals.show_address.connect(self.show_address)
        self.signals.open_tx.connect(self.open_tx_in_tab)
        
        
        self.network_settings_ui = NetworkSettingsUI(self.config)
        self.signals.show_network_settings.connect(self.open_network_settings)
        self.network_settings_ui.signal_new_network_settings.connect(self.restart)

        self.welcome_screen = NewWalletWelcomeScreen(self.tab_wallets, network=self.config.network_settings.network)
        self.welcome_screen.signal_onclick_single_signature.connect(self.click_single_signature)
        self.welcome_screen.signal_onclick_multisig_signature.connect(self.click_multisig_signature)
        self.welcome_screen.signal_onclick_custom_signature.connect(self.click_custom_signature)
        self.welcome_screen.ui_explainer0.signal_onclick_proceed.connect(self.click_create_single_signature_wallet)
        self.welcome_screen.ui_explainer1.signal_onclick_proceed.connect(self.click_create_multisig_signature_wallet)

        self.signals.event_wallet_tab_added.connect(self.event_wallet_tab_added)
        self.signals.event_wallet_tab_closed.connect(self.event_wallet_tab_closed) 
    
        opened_qt_wallets = self.open_last_opened_wallets()
        if not opened_qt_wallets:            
            self.welcome_screen.add_new_wallet_welcome_tab()
        
        

    def open_network_settings(self):      
        self.network_settings_ui.show()

                
        
    def open_tx(self, file_path=None):                   
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, "Open Transaction/PSBT", "", "All Files (*);;Text Files (*.psbt)")        
            if not file_path:
                logger.debug("No file selected")
                return    

        logger.debug(f"Selected file: {file_path}")            
        with open(file_path, "r") as file:
            string_content = file.read()
            
        self.signals.open_tx(string_content)


    def open_tx_in_tab(self, tx):
        if isinstance(tx, bdk.TxBuilderResult):
            print('is bdk.TxBuilderResult')
        if isinstance(tx, bdk.PartiallySignedTransaction):
            print('is bdk.PartiallySignedTransaction')
        if isinstance(tx, str):
            print('tx is str. Trying to convert to psbt or raw transaction')
            tx = bdk.PartiallySignedTransaction(tx)
            
        if isinstance(tx, bdk.TransactionDetails):
            print('is bdk.TransactionDetails')
                        
                        
        viewer = UITX_Viewer(tx, self.signals, network=self.config.network_settings.network)         
        
        add_tab_to_tabs(self.tab_wallets, viewer.main_widget, read_QIcon("offline_tx.png"), "Transaction", "tx", focus=True)
        
        
        
    def open_last_opened_wallets(self):
        opened_wallets = []
        for file_path in self.config.last_wallet_files.get(str(self.config.network_settings.network), []):
            qt_wallet = self.open_wallet(file_path=file_path)
            if qt_wallet:
                opened_wallets.append(qt_wallet)        
        return opened_wallets
    
    def open_wallet(self, file_path=None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(self, "Open Wallet", self.config.wallet_dir, "All Files (*);;Text Files (*.bitcoinsafe)")        
            if not file_path:
                logger.debug("No file selected")
                return    

        logger.debug(f"Selected file: {file_path}")     
        if not os.path.isfile(file_path):
            logger.debug(f"There is no such file: {file_path}")     
            return
        password = None
        if Storage().has_password(file_path):
            self.ui_password_question = PasswordQuestion()
            password = self.ui_password_question.ask_for_password()                     
        try:
            wallet = Wallet.load(file_path, self.config, password)
        except Exception as e:
            error_type, error_value, error_traceback = sys.exc_info()
            error_message = f"Error. Wallet could not be loaded. Error: {error_type.__name__}: {error_value}"
            self.show_error(error_message)
            return

        qt_wallet = self.add_qt_wallet(wallet)        
        qt_wallet.password = password        
        qt_wallet.sync()        
        return qt_wallet
    
    def save_current_wallet(self):
        return self.get_qt_wallet().save()
        
    def save_all_wallets(self):
        for qt_wallet in self.qt_wallets.values():
            qt_wallet.save()
        

    def click_single_signature(self):
        add_tab_to_tabs(self.tab_wallets, self.welcome_screen.ui_explainer0.tab,  read_QIcon("file.png"), 'Create new wallet', 'Create new wallet', focus=True)

    
    def click_create_single_signature_wallet(self):
        qtwallet = self.next_step_after_welcome_screen((1,1))
        qtwallet.wallet_descriptor_ui.disable_fields()
    
    def click_multisig_signature(self):
        add_tab_to_tabs(self.tab_wallets, self.welcome_screen.ui_explainer1.tab,  read_QIcon("file.png"), 'Create new wallet', 'Create new wallet', focus=True)

    def click_create_multisig_signature_wallet(self):
        qtwallet = self.next_step_after_welcome_screen((2,3))
        qtwallet.wallet_descriptor_ui.disable_fields()
        
    def click_custom_signature(self):     
        return self.next_step_after_welcome_screen((3,5))
        

    def new_wallet(self):                   
        self.welcome_screen.add_new_wallet_welcome_tab()
            
    def new_wallet_id(self) -> str:
        return 'new'+str(len(self.qt_wallets))


    def next_step_after_welcome_screen(self, m_of_n) -> QTWallet:
        id = self.new_wallet_id()   
        m,n = m_of_n
        wallet = Wallet(id=id, threshold=m, signers=n,  config=self.config)         
        return self.add_qt_wallet(wallet)
        
        
    def add_qt_wallet(self, wallet:Wallet) -> QTWallet:
        qt_wallet = QTWallet(wallet, self.config, self.signals)
        
        if wallet.bdkwallet:
            qt_wallet.create_wallet_tabs()
        else:
            qt_wallet.create_pre_wallet_tab()
        self.qt_wallets[wallet.id] = qt_wallet
        add_tab_to_tabs(self.tab_wallets, qt_wallet.tab, read_QIcon("file.png"), qt_wallet.wallet.id, qt_wallet.wallet.id, focus=True)
        
        self.signals.get_wallets.connect(lambda: [qt_wallet.wallet for qt_wallet in self.qt_wallets.values()])        
        return qt_wallet
        
    def import_descriptor(self):
        descriptor = self.text_descriptor.toPlainText()
        wallet = Wallet(id='import'+str(len(self.qt_wallets)),   config=self.config)         
        wallet.create_descriptor_wallet(descriptor)  
              
        self.add_qt_wallet(wallet) 
        self.signals.event_wallet_tab_added()

    def import_seed(self):
        seed = self.text_seed.toPlainText()
        wallet = Wallet(id='import'+str(len(self.qt_wallets)),    config=self.config)         
        wallet.create_seed_wallet(seed)
        self.qt_wallets[wallet.id] = QTWallet(wallet, self.tab_wallets, self.config, self.signals)

        self.signals.event_wallet_tab_added()

    def get_qt_wallet(self, tab=None) -> QTWallet:
        wallet_tab = self.tab_wallets.currentWidget() if tab is None else tab
        for qt_wallet in self.qt_wallets.values():
            if wallet_tab == qt_wallet.tab:
                return qt_wallet
        

    def toggle_search(self):
        self.get_qt_wallet().toggle_search()



    def show_address(self, addr: str, parent=None):
        from .gui.qt import address_dialog
        d = address_dialog.AddressDialog(self.fx, self.config, self.get_qt_wallet(),  addr, parent=parent)
        d.exec_()         
            
        
    
    def event_wallet_tab_closed(self):
        if not self.tab_wallets.count():
            self.welcome_screen.add_new_wallet_welcome_tab()

        
    def event_wallet_tab_added(self):
        pass

    def remove_qt_wallet(self, qt_wallet:QTWallet):
        if not qt_wallet:
            return
        for i in range(self.tab_wallets.count()):
            if self.tab_wallets.widget(i) == qt_wallet.tab:
                self.tab_wallets.removeTab(i)

        del self.qt_wallets[qt_wallet.wallet.id]


    def close_tab(self, index):                   
        qt_wallet = self.get_qt_wallet(tab=self.tab_wallets.widget(index))
        self.tab_wallets.removeTab(index)
        if qt_wallet:
            self.remove_qt_wallet(qt_wallet) 
        
        self.event_wallet_tab_closed()
        
        
    def import_wallet(self):
        # Handle import wallet event
        logger.debug("Import wallet")



    def sync(self):   
        for qt_wallet in self.qt_wallets.values():        
            qt_wallet.sync()     

        
    def closeEvent(self, event):        
        self.config.last_wallet_files[str(self.config.network_settings.network)] = [os.path.join( self.config.wallet_dir,  qt_wallet.wallet.basename())
                                         for qt_wallet in self.qt_wallets.values()]
        self.config.save()      
        self.save_all_wallets()                  
        super().closeEvent(event)
                        
                        
    def restart(self):
        close_event = QCloseEvent()
        self.closeEvent(close_event)

        if close_event.isAccepted():
            QCoreApplication.quit()  # equivalent to QCoreApplication.exit(0)
            status = QProcess.startDetached(sys.executable, ['-m', 'bitcoin_safe'] + sys.argv[1:])
            if (not status):
                sys.exit(-1)
        else:
            # The close event was not accepted, so the application will not quit.
            pass

