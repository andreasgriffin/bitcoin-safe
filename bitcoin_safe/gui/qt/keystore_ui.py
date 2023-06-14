import logging
logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from PySide2.QtSvg import QSvgWidget
from .util import  icon_path, center_in_widget, qresize, add_tab_to_tabs, read_QIcon
from ...wallet import AddressTypes, get_default_address_type, Wallet, generate_bdk_descriptors
from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from ...signals import Signals,   Signal
from ...util import compare_dictionaries, psbt_to_hex
from typing import List
from .keystore_ui_tabs import KeyStoreUIDefault, KeyStoreUISigner, KeyStoreUITypeChooser
from .block_change_signals import BlockChangesSignals
import bdkpython as bdk
from ...signer import AbstractSigner


def icon_for_label(label):
    return read_QIcon("key-gray.png") if label.startswith('Recovery') else read_QIcon("key.png")




class KeyStoreUI:
    def __init__(self, keystore:KeyStore, tabs:QTabWidget, network:bdk.Network) -> None:
        self.keystore = keystore
        self.tabs = tabs
        
        self.keystore_ui_default = KeyStoreUIDefault(tabs, network)
        self.keystore_ui_type_chooser = KeyStoreUITypeChooser(network)
        
        self.block_change_signals = BlockChangesSignals(
                sub_instances=[self.keystore_ui_default.block_change_signals]
        )
        

        if keystore.type is None:
            add_tab_to_tabs(self.tabs, self.keystore_ui_type_chooser.tab, icon_for_label(keystore.label), keystore.label, keystore.label,   focus=True)
        else:
            add_tab_to_tabs(self.tabs, self.keystore_ui_default.tab, icon_for_label(keystore.label), self.keystore.label, self.keystore.label, focus=True)
            
        self.set_ui_from_keystore(self.keystore)            
        self.keystore_ui_type_chooser.signal_click_watch_only.connect(self.onclick_button_watch_only)    
        self.keystore_ui_type_chooser.signal_click_seed.connect(self.onclick_button_seed)    

    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.keystore_ui_default.tab))
        self.tabs.removeTab(self.tabs.indexOf(self.keystore_ui_type_chooser.tab))
                
    def set_keystore_from_ui_values(self, keystore:KeyStore):
        ui_keystore = self.keystore_ui_default.get_ui_values_as_keystore()
        if not keystore:
            keystore = self.keystore
        keystore.from_other_keystore(ui_keystore)

    def changed_ui_values(self) -> KeyStore:
        return compare_dictionaries(self.keystore, self.keystore_ui_default.get_ui_values_as_keystore()                        )

    def set_ui_from_keystore(self, keystore:KeyStore):        
        for tab in [self.keystore_ui_default.tab, self.keystore_ui_type_chooser.tab]:
            index = self.tabs.indexOf(tab)
            if index>=0:
                self.tabs.setTabText(index,  keystore.label)
                self.tabs.setTabIcon(index,  icon_for_label(keystore.label))
                
        self.keystore_ui_default.set_ui_from_keystore(keystore)
    


    def switch_to_tab(self, tab):
        index = None
        for remove_tab in [self.keystore_ui_type_chooser.tab, self.keystore_ui_default.tab]:
            # save index to put the new tab exactly there
            index = self.tabs.indexOf(remove_tab)
            self.tabs.removeTab(index)
                        
        add_tab_to_tabs(self.tabs, tab, icon_for_label(self.keystore.label), self.keystore.label, self.keystore.label, position=index, focus=True)
    
    
    def onclick_button_watch_only(self):
        self.switch_to_tab( self.keystore_ui_default.tab) 
        
        self.keystore.set_type(KeyStoreTypes.watch_only)
        self.set_ui_from_keystore(self.keystore)

    
    def onclick_button_seed(self):
        self.switch_to_tab( self.keystore_ui_default.tab) 
        
        self.keystore.set_type(KeyStoreTypes.seed)
        self.set_ui_from_keystore(self.keystore)





class SignerUI(QObject):
    signal_signature_added = Signal(bdk.PartiallySignedTransaction)
    def __init__(self, signer:AbstractSigner, psbt:bdk.PartiallySignedTransaction, tabs:QTabWidget, network:bdk.Network) -> None:
        super().__init__()
        self.signer = signer
        self.psbt = psbt
        self.tabs = tabs
        
    
        self.ui_signer = KeyStoreUISigner(signer, network)        
        self.ui_signer.button_seed.clicked.connect(lambda: self.sign())  # with lambda function it works. But not without. No idea why

        add_tab_to_tabs(self.tabs, self.ui_signer.tab, icon_for_label(signer.label), self.signer.label, self.signer.label, focus=True)
            

        
    def remove_tab(self):
        self.tabs.removeTab(self.tabs.indexOf(self.ui_signer.tab))
        
        
    def sign(self):
        # sign transaction - this method mutates transaction, so we copy it first
        psbt2 = bdk.PartiallySignedTransaction(self.psbt.serialize())
    
        logger.debug(f'psbt before signing: {psbt_to_hex(psbt2)}')
        
        signing_was_successful:bool = self.signer.sign(psbt2, None)

        if signing_was_successful:
            logger.debug(f'psbt after signing: {psbt_to_hex(psbt2)}')
            logger.debug(f'psbt after signing: fee  {psbt2.fee_rate().as_sat_per_vb()}')

            self.signal_signature_added.emit(psbt2)
        else:
            logger.debug(f'signign failed')
    
    
    