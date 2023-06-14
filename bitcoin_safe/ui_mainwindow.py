import logging
logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from .i18n import _
from .gui.qt.util import read_QIcon
from .gui.qt.balance_dialog import BalanceToolButton
from .config import UserConfig
from PySide2.QtCore import QLocale

            
            
class Ui_MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = UserConfig.load()
        self.setupUi(self)
                


    def setupUi(self, MainWindow:QWidget):            
        # sizePolicy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # sizePolicy.setHorizontalStretch(0)
        # sizePolicy.setVerticalStretch(0)
        # sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        # MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setWindowTitle("Bitcoin Safe")
        MainWindow.setWindowIcon(read_QIcon('logo.svg'))
        w,h = 900, 600
        MainWindow.resize(w,h)
        MainWindow.setMinimumSize(w, h)

        #####
        self.tab_wallets = tabs = QTabWidget(self)
        self.tab_wallets.setTabsClosable(True)
        tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Connect signals to slots
        tabs.tabCloseRequested.connect(self.close_tab)        
        

        # central_widget 
        central_widget = QScrollArea()
        vbox = QVBoxLayout(central_widget)
        vbox.addWidget(tabs)
        self.setCentralWidget(central_widget)

        self.setMinimumWidth(640)
        self.setMinimumHeight(400)
        if self.config.is_maximized:
            self.showMaximized()

        # self.setWindowIcon(read_QIcon("electrum.png"))
        self.init_menubar()
        ####



        
    def init_menubar(self):
        # menu
        self.menubar = QMenuBar()
        # menu wallet
        self.menu_wallet = self.menubar.addMenu(_("&Wallet"))


        self.menu_wallet.addAction(_("New Wallet"), self.new_wallet).setShortcut(QKeySequence("Ctrl+N"))
        self.menu_wallet.addAction("Open wallet", self.open_wallet).setShortcut(QKeySequence("Ctrl+O"))        
        self.menu_wallet.addAction("Save Current wallet", self.save_current_wallet).setShortcut(QKeySequence("Ctrl+S"))        
        self.menu_wallet.addAction("Find", self.toggle_search).setShortcut(QKeySequence("Ctrl+F"))                
        self.menu_wallet.addSeparator()

        self.menu_wallet.addAction(_("Sync"), self.sync).setShortcut(QKeySequence("F5"))


        # menu transaction
        self.menu_transaction = self.menubar.addMenu(_("&Transaction"))
        self.menu_transaction.addAction("Load Transaction from file", self.open_tx_file).setShortcut(QKeySequence("Ctrl+L"))        

        # menu settings
        self.menu_transaction = self.menubar.addMenu(_("&Settings"))
        self.menu_transaction.addAction("Network Settings", self.open_network_settings).setShortcut(QKeySequence("Ctrl+I"))        


        # assigne menu bar
        self.setMenuBar(self.menubar)
        



    def new_wallet(self):                   
        pass
    def open_wallet(self):                   
        pass
    def close_tab(self, index):
        pass
    def save_current_wallet(self):
        pass
    def toggle_search(self):
        pass
    def sync(self):
        pass

    def open_tx_file(self):                   
        pass

    def open_network_settings(self):                   
        pass
