import logging
logger = logging.getLogger(__name__)

import appdirs, os, json
from .storage import BaseSaveableClass, Storage
import bdkpython as bdk
from .pythonbdk_types import *
from typing import Dict, List
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



def get_default_port(network:bdk.Network, server_type:BlockchainType):
    if server_type == BlockchainType.CompactBlockFilter:
        d = {
            bdk.Network.BITCOIN : 8333,
            bdk.Network.REGTEST : 18444,
            bdk.Network.TESTNET : 18333,                            
            bdk.Network.SIGNET : 18333,                            
        }
        return d[network]
    elif server_type == BlockchainType.Electrum:
        d = {
            bdk.Network.BITCOIN : 50001,
            bdk.Network.REGTEST : 60401,
            bdk.Network.TESTNET : 51001,                            
            bdk.Network.SIGNET : 51001,                            
        }
        return d[network]

class NetworkConfig(BaseSaveableClass):
    def __init__(self):
        self.network = bdk.Network.REGTEST
        self.server_type = BlockchainType.CompactBlockFilter
        self.cbf_server_type = "Automatic"
        self.compactblockfilters_ip = '127.0.0.1'
        self.compactblockfilters_port = get_default_port(self.network, BlockchainType.CompactBlockFilter)
        self.electrum_ip = '127.0.0.1'
        self.electrum_port = get_default_port(self.network, BlockchainType.Electrum)
    


    def serialize(self): 
        d = super().serialize()
        d.update(self.__dict__)
        return d

    @classmethod
    def deserialize(cls, dct):
        super().deserialize(dct)
        u = cls()
        
        for k,v in dct.items():        
            if v is not None:  # only overwrite the default value, if there is a value 
                setattr(u, k, v)
        return u
                        
    


class UserConfig(BaseSaveableClass):
    global_variables = globals()

    version = 0.1
    app_name = 'bitcoin_safe'
    config_dir = appdirs.user_config_dir(app_name)
    config_file = os.path.join( appdirs.user_config_dir(app_name) , app_name + '.conf')

    def __init__(self):
        self.network_settings = NetworkConfig()
        self.last_wallet_files:Dict[str, List[str]] = {}   # network:[file_path0] 
        self.data_dir = appdirs.user_data_dir(self.app_name)
        self.wallet_dir = os.path.join(self.config_dir, str(self.network_settings.network))
        self.is_maximized = False
        self.block_explorer:str = 'mempool.space'



            
    

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
        u = cls()
        
        for k,v in dct.items():        
            if v is not None:  # only overwrite the default value, if there is a value 
                setattr(u, k, v)
        return u
            
            
    @classmethod
    def load(cls, password=None):         
        if os.path.isfile(cls.config_file):
            return super().load(cls.config_file, password=password)
        else:
            return UserConfig()
                    
    def save(self):
        super().save(self.config_file)