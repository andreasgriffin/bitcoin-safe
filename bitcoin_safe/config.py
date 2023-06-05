import logging
logger = logging.getLogger(__name__)

import appdirs, os, json
from .storage import BaseSaveableClass, Storage
import bdkpython as bdk

FEE_ETA_TARGETS = [25, 10, 5, 2]
FEE_DEPTH_TARGETS = [10_000_000, 5_000_000, 2_000_000, 1_000_000,
                     800_000, 600_000, 400_000, 250_000, 100_000]
FEE_LN_ETA_TARGET = 2  # note: make sure the network is asking for estimates for this target

# satoshi per kbyte
FEERATE_MAX_DYNAMIC = 1500000
FEERATE_WARNING_HIGH_FEE = 600000
FEERATE_FALLBACK_STATIC_FEE = 150000
FEERATE_DEFAULT_RELAY = 1000
FEERATE_MAX_RELAY = 50000
FEERATE_STATIC_VALUES = [1000, 2000, 5000, 10000, 20000, 30000,
                         50000, 70000, 100000, 150000, 200000, 300000]
FEERATE_REGTEST_HARDCODED = 180000  # for eclair compat


FEE_RATIO_HIGH_WARNING = 0.05  # warn user if fee/amount for on-chain tx is higher than this


class UserConfig(BaseSaveableClass):
    global_variables = globals()

    version = 0.1
    app_name = 'bitcoin_safe'
    config_dir = appdirs.user_config_dir(app_name)
    config_file = os.path.join( appdirs.user_config_dir(app_name) , app_name + '.conf')

    def __init__(self):
        self.last_wallet_files = []
        self.network = bdk.Network.REGTEST
        self.data_dir = appdirs.user_data_dir(self.app_name)
        self.wallet_dir = os.path.join(self.config_dir, str(self.network))
        self.is_maximized = False


    def get(self, key, default=None):
        "For legacy reasons"
        if hasattr(self, key):
            return getattr(self, key)
        else:
            return default

    def serialize(self): 
        d = super().serialize()
        d.update(self.__dict__        )
        return d

    @classmethod
    def deserialize(cls, dct):
        super().deserialize(dct)
        u = UserConfig()
        
        for k,v in dct.items():        
            setattr(u, k, v)
        return u
            
            
    @classmethod
    def load(cls, password=None): 
        if os.path.isfile(cls.config_file):
            return super().load( cls.config_file, password=password)
        else:
            return UserConfig()
                    
    def save(self):
        super().save(self.config_file)