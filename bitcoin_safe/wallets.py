import logging
logger = logging.getLogger(__name__)

from collections import defaultdict
import bdkpython as bdk 
from typing import Sequence, Set, Tuple

from .tx import TXInfos
from .util import balance_dict, OrderedDictWithIndex, Satoshis, timestamp_to_datetime, TxMinedInfo, format_fee_satoshis, format_time
from .util import TX_HEIGHT_FUTURE, TX_HEIGHT_INF, TX_HEIGHT_LOCAL, TX_HEIGHT_UNCONF_PARENT, TX_HEIGHT_UNCONFIRMED, TX_STATUS, THOUSANDS_SEP, cache_method
from .i18n import _
from typing import TYPE_CHECKING, List, Optional, Tuple, Union, NamedTuple, Sequence, Dict, Any, Set, Iterable
from .keystore import KeyStore, KeyStoreType, KeyStoreTypes
import bdkpython as bdk
from .pythonbdk_types import *
from .storage import Storage
from threading import Lock
from .descriptors import AddressType, AddressTypes, get_default_address_type, generate_bdk_descriptors, descriptor_infos, generate_output_descriptors_from_keystores
from .tx import TXInfos
from .wallet import Wallet


    
    
class Wallets:
    "This class offer functions to scan all open wallets simulatenously"
    def __init__(self, get_wallets) -> None:
        self.get_wallets = get_wallets
        
    def wallet_of_address(self, address_str):
        wallets:List[Wallet] = self.get_wallets()
        for wallet in wallets:
            if address_str in wallet.get_addresses():        
                return wallet
            
    def wallet_of_outpoint(self, outpoint:bdk.OutPoint):
        def outpoint_tuple(outpoint:bdk.OutPoint):
            return (outpoint.txid, outpoint.vout)
        
        wallets:List[Wallet] = self.get_wallets()
        for wallet in wallets:            
            # check quickly via txids
            outpoints = [outpoint_tuple(utxo.outpoint) for utxo in wallet.get_utxos()]
            
            if outpoint_tuple(outpoint) in outpoints:
                return wallet
                
        

    def wallet_and_keystore_of_fingerprint(self, fingerprint):
        wallets:List[Wallet] = self.get_wallets()
        for wallet in wallets:
            for keystore in wallet.keystores:
                if fingerprint == keystore.fingerprint:
                    return wallet, keystore

    def is_change(self, address):
        return self._return_dict('is_change', address)

    def get_addresses(self):
        return self._return_dict('get_addresses')

    def get_addresses_merged(self):
        return self._return_merge('get_addresses')

    def get_change_addresses(self, slice_start=None, slice_stop=None):
        return self._return_dict('get_change_addresses', slice_start=slice_start, slice_stop=slice_stop)
        
    def get_change_addresses_merged(self, slice_start=None, slice_stop=None):
        return self._return_merge('get_change_addresses', slice_start=slice_start, slice_stop=slice_stop)
        
    def get_receiving_addresses(self, slice_start=None, slice_stop=None):
        return self._return_dict('get_receiving_addresses', slice_start=slice_start, slice_stop=slice_stop)
        
    def get_receiving_addresses_merged(self, slice_start=None, slice_stop=None):
        return self._return_merge('get_receiving_addresses', slice_start=slice_start, slice_stop=slice_stop)
        
        
        
    def _return_merge(self, name, *args, **kwargs):            
        merged = []
        for res in self._return_dict(name, *args, **kwargs).values():
            merged += res
        return merged
            
    def _return_dict(self, name, *args, **kwargs):        
        results = {}
        wallets:List[Wallet] = self.get_wallets()
        for wallet in wallets:
            result = getattr(wallet, name)(*args, **kwargs)
            if not result and not isinstance(result, (int, float)):
                # supress empty results
                continue
            results[wallet.id] = result
        return results