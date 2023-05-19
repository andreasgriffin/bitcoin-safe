from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *



from .i18n import _
from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.balance_dialog import COLOR_FROZEN, COLOR_CONFIRMED, COLOR_FROZEN_LIGHTNING, COLOR_LIGHTNING, COLOR_UNCONFIRMED, COLOR_UNMATURED
from .gui.qt.util import add_tab_to_tabs, read_QIcon
from .signals import Signals,   QTWalletSignals
import bdkpython as bdk

class KeyStoreType():
    def __init__(self, id, name, description, icon_filename, networks='all') -> None:
        self.id = id
        self.name = name
        self.description = description
        self.icon_filename = icon_filename
        self.networks = [bdk.Network.BITCOIN, bdk.Network.REGTEST, bdk.Network.TESTNET, bdk.Network.SIGNET] if networks == 'all' else networks
        
        
    def serialize(self):
        d = self.__dict__
        d["__class__"] = self.__class__.__name__
        return d
        
    @classmethod
    def deserialize(cls, dct):        
        assert dct.get("__class__") == cls.__name__
        if "__class__" in dct:
            del dct["__class__"]
        return cls(**dct)
            
    
    
    
class KeyStoreTypes:
    hwi = KeyStoreType('hwi', 'USB Hardware Wallet', "Connect \nUSB \nHardware Wallet", ["usb.svg"])
    psbt = KeyStoreType('psbp', "SD or QR Code", "Import signer details\nvia SD card or QR code", ["qr-code.svg", "sd-card.svg"])
    watch_only = KeyStoreType('watch_only', "Watch-Only", "xPub / Public Key\nInformation", ["key-hole-icon.svg"])
    seed = KeyStoreType('seed', "Seed", "Mnemonic Seed\n(Testnet only)", ["seed-plate.svg"], networks=[bdk.Network.REGTEST,bdk.Network.TESTNET, bdk.Network.SIGNET]) # add networks here to make the seed option visible
    
    @classmethod
    def list_types(cls, network:bdk.Network):
        return [v for v in [cls.hwi, cls.psbt, cls.watch_only, cls.seed] if    network in v.networks]

    @classmethod
    def list_names(cls, network:bdk.Network):
        return [v.name for v in cls.list_types(network)]


# class SignallingProperty():
#     value_changed = Signal()

#     def __init__(self, initial_value=None, value_type=str):
#         super().__init__()
#         self._value = initial_value
#         self._value_type = value_type

#     @property
#     def value(self):
#         return self._value

#     @value.setter
#     def value(self, new_value):
#         new_value = self._value_type(new_value)
#         if self._value != new_value:
#             self._value = new_value
#             self.value_changed.emit()



class KeyStore:
    def __init__(self, xpub, fingerprint, derivation_path:str, label, type:KeyStoreType, mnemonic:bdk.Mnemonic=None, description:str='') -> None:
        self.xpub = xpub
        self.fingerprint = fingerprint
        self.derivation_path = derivation_path
        self.label = label
        self.type = type
        self.mnemonic = mnemonic
        self.description = description
        
    def __repr__(self) -> str:
        return str(self.__dict__)


    def serialize(self):
        d = self.__dict__
        d['mnemonic'] = self.mnemonic.as_string() if self.mnemonic else self.mnemonic
        d["__class__"] = self.__class__.__name__
        return d
        
    @classmethod
    def deserialize(cls, dct):
        assert dct.get("__class__") == cls.__name__
        
        dct['mnemonic'] = bdk.Mnemonic.from_string(dct['mnemonic']) 
        
        if "__class__" in dct:
            del dct["__class__"]
        return KeyStore(**dct)
        

    def set_type(self, type):
        self.type = type
        
    def set_derivation_path(self, derivation_path):
        self.derivation_path = derivation_path        
        
    
    def clone(self):
        mnemonic_clone = bdk.Mnemonic.from_string(self.mnemonic.as_string()) if self.mnemonic else None
        return KeyStore(self.xpub, self.fingerprint, self.derivation_path, self.label, self.type, mnemonic_clone , self.description)
    
    
    def from_other_keystore(self, other_keystore):        
        self.xpub = other_keystore.xpub
        self.fingerprint = other_keystore.fingerprint
        self.derivation_path = other_keystore.derivation_path
        self.label = other_keystore.label
        self.type = other_keystore.type                
        self.mnemonic = other_keystore.mnemonic
        self.description = other_keystore.description
        