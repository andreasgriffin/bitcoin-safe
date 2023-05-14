from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *


from .ui_mainwindow import Ui_MainWindow
from .wallet import BlockchainType, Wallet
import sys
import asyncio
import qasync


from .i18n import _
from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.qt_wallet import QTWallet
from .gui.qt.password_question import PasswordQuestion
from .gui.qt.balance_dialog import COLOR_FROZEN, COLOR_CONFIRMED, COLOR_FROZEN_LIGHTNING, COLOR_LIGHTNING, COLOR_UNCONFIRMED, COLOR_UNMATURED
from .gui.qt.util import add_tab_to_tabs, read_QIcon, MessageBoxMixin
from .signals import Signals,  QTWalletSignals
from bdkpython import Network
from typing import Dict



class MainWindow(Ui_MainWindow, MessageBoxMixin):
    def __init__(self):
        super().__init__()
        self.qt_wallets :Dict[QTWallet] = {}
        self.fx = None
        
        self.signals = Signals()
        #connect the listeners
        self.signals.show_address.connect(self.show_address)
        
        self.blockchain_type = BlockchainType.CompactBlockFilter
        
        self.welcome_screen = NewWalletWelcomeScreen(self.tab_wallets, network=Network.REGTEST)
        self.welcome_screen.add_new_wallet_welcome_tab()
        self.welcome_screen.set_onclick_single_signature(self.click_single_signature)
        self.welcome_screen.set_onclick_multisig_signature(self.click_multisig_signature)
        self.welcome_screen.set_onclick_custom_signature(self.click_custom_signature)
        self.welcome_screen.ui_explainer0.set_onclick_proceed(self.click_create_single_signature_wallet)
        self.welcome_screen.ui_explainer1.set_onclick_proceed(self.click_create_multisig_signature_wallet)

        self.signals.event_wallet_tab_added.connect(self.event_wallet_tab_added)
        self.signals.event_wallet_tab_closed.connect(self.event_wallet_tab_closed) 
    
    def open_wallet(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Wallet", "", "All Files (*);;Text Files (*.bitcoinsafe)")        
        if not file_path:
            print("No file selected")    
            return    

        print(f"Selected file: {file_path}")
        self.ui_password_question = PasswordQuestion()
        password = self.ui_password_question.ask_for_password()            
        try:
            wallet = Wallet.load(password, file_path)
        except:
            self.show_error('Error. Wallet could not be loaded. Please try another password.')
            raise
        qt_wallet = self.add_qt_wallet(wallet)        
        qt_wallet.password = password        
        qt_wallet.sync()
    
    def save_current_wallet(self):
        return self.get_qt_wallet().save()
        

    def click_single_signature(self):
        add_tab_to_tabs(self.tab_wallets, self.welcome_screen.ui_explainer0.tab,  read_QIcon("file.png"), 'Create new wallet', 'Create new wallet')

    
    def click_create_single_signature_wallet(self):
        qtwallet = self.next_step_after_welcome_screen((1,1))
        qtwallet.wallet_settings_ui.disable_fields()
    
    def click_multisig_signature(self):
        add_tab_to_tabs(self.tab_wallets, self.welcome_screen.ui_explainer1.tab,  read_QIcon("file.png"), 'Create new wallet', 'Create new wallet')

    def click_create_multisig_signature_wallet(self):
        qtwallet = self.next_step_after_welcome_screen((2,3))
        qtwallet.wallet_settings_ui.disable_fields()
        
    def click_custom_signature(self):     
        return self.next_step_after_welcome_screen((3,5))
        
        
        
    def new_wallet_id(self) -> str:
        return 'new'+str(len(self.qt_wallets))


    def next_step_after_welcome_screen(self, m_of_n) -> QTWallet:
        id = self.new_wallet_id()   
        m,n = m_of_n
        wallet = Wallet(id=id, threshold=m, signers=n,  blockchain_choice=self.blockchain_type, network=Network.REGTEST)         
        return self.add_qt_wallet(wallet)
        
        
    def add_qt_wallet(self, wallet:Wallet) -> QTWallet:
        qt_wallet = QTWallet(wallet, self.config, self.signals)
        
        if wallet.bdkwallet:
            qt_wallet.create_wallet_tabs()
        else:
            qt_wallet.create_pre_wallet_tab()
        self.qt_wallets[wallet.id] = qt_wallet
        add_tab_to_tabs(self.tab_wallets, qt_wallet.tab, read_QIcon("file.png"), qt_wallet.wallet.id, qt_wallet.wallet.id)
        self.tab_wallets.setCurrentIndex(self.tab_wallets.count()-1)
        return qt_wallet
        
    def import_descriptor(self):
        descriptor = self.text_descriptor.toPlainText()
        wallet = Wallet(id='import'+str(len(self.qt_wallets)),  blockchain_choice=self.blockchain_type, network=Network.REGTEST)         
        wallet.create_descriptor_wallet(descriptor)  
              
        self.add_qt_wallet(wallet) 
        self.signals.event_wallet_tab_added()

    def import_seed(self):
        seed = self.text_seed.toPlainText()
        wallet = Wallet(id='import'+str(len(self.qt_wallets)),  blockchain_choice=self.blockchain_type, network=Network.REGTEST)         
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
        if qt_wallet.wallet.id in self.signals.qt_wallet_signals:
            del self.signals.qt_wallet_signals[qt_wallet.wallet.id]


    def close_tab(self, index):        
        # if self.tab_wallets.widget(index) == self.welcome_screen.tab:
        #     return
        self.tab_wallets.removeTab(index)
        
        
        qt_wallet = self.get_qt_wallet(self.tab_wallets.widget(index))
        self.remove_qt_wallet(qt_wallet) 
        
        self.event_wallet_tab_closed()
        
        
    def import_wallet(self):
        # Handle import wallet event
        print("Import wallet")



    def sync(self):   
        for qt_wallet in self.qt_wallets.values():        
            qt_wallet.sync()     
                        


            

async def main():
    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()

    with loop:
        loop.run_forever()

if __name__ == "__main__":
    asyncio.run(main())