from collections import defaultdict
import bdkpython as bdk 
from typing import Sequence, Set, Tuple
from .util import balance_dict, OrderedDictWithIndex, Satoshis, timestamp_to_datetime, TxMinedInfo, format_fee_satoshis, format_time
from .util import TX_HEIGHT_FUTURE, TX_HEIGHT_INF, TX_HEIGHT_LOCAL, TX_HEIGHT_UNCONF_PARENT, TX_HEIGHT_UNCONFIRMED, TX_STATUS, THOUSANDS_SEP, cache_method
import time 
from decimal import Decimal
from .i18n import _
from typing import TYPE_CHECKING, List, Optional, Tuple, Union, NamedTuple, Sequence, Dict, Any, Set, Iterable
from .keystore import KeyStore, KeyStoreType, KeyStoreTypes
import bdkpython as bdk
import html
from bitcoin_safe import keystore
from .pythonbdk_types import *
from .storage import Storage
from threading import Lock
from .descriptors import AddressType, AddressTypes, get_default_address_type, generate_bdk_descriptors, descriptor_infos, generate_output_descriptors_from_keystores
import json
import enum


def locked(func):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return func(self, *args, **kwargs)
    return wrapper

class BlockchainType(enum.Enum):
    CompactBlockFilter = enum.auto()
    Electrum = enum.auto()
            
            
class Wallet():
    """
    If any bitcoin logic (ontop of bdk) has to be done, then here is the place
    """
    def __init__(self, id, threshold:int, signers:int = 1, network=bdk.Network.REGTEST, blockchain_choice=BlockchainType.CompactBlockFilter, keystores:List[KeyStore]=None, address_type:AddressType=None, gap=200, gap_change=20, descriptors=None):
        self.bdkwallet = None
        self.network = network
        self.id = id
        self.threshold = threshold
        self.blockchain = None
        self.gap = gap
        self.gap_change = gap_change
        self.descriptors :List[bdk.Descriptor] = [] if descriptors is None else descriptors 
        self.blockchain_choice = blockchain_choice
        self.cache = {}
        self.write_lock = Lock()
        
        initial_address_type = address_type if address_type else get_default_address_type(signers>1)
        self.keystores: List[KeyStore] = keystores if keystores is not None else [
                                            KeyStore(None, None, 
                                                     initial_address_type.derivation_path(self.network), 
                                                     label=self.signer_names(threshold, i), 
                                                     type=KeyStoreTypes.watch_only) 
                                            for i in range(signers)
                                        ]
        self.set_address_type( initial_address_type)
    
    
    def temporary_descriptors(self, use_html=False):
        """
        These is a descriptor that can be generated without having all keystore information.
        This is useful for UI 
        """        
        return generate_output_descriptors_from_keystores(self.threshold,
                                                          self.address_type,
                                                          self.keystores,
                                                          self.network,
                                                            replace_keystore_with_dummy=False,
                                                            use_html=use_html,
                                                            combined_descriptors=True
                                                            )        
    
    def serialize(self):
        d = {}

        keys = ['id', 'threshold', 'gap', 'gap_change', 'blockchain_choice', 'keystores', 'network']
        full_dict = self.__dict__
        for k in keys:            
            d[k] = full_dict[k]

        d['descriptors'] = [descriptor.as_string() for descriptor in self.descriptors]
        d['tips'] = self.tips

        d["__class__"] = self.__class__.__name__
        return d
        
    @classmethod
    def deserialize(cls, dct):
        assert dct.get("__class__") == cls.__name__
        dct['descriptors'] = [bdk.Descriptor(descriptor, network=dct['network'])  for descriptor in dct['descriptors']]
        del dct["__class__"]

        tips = dct['tips']
        del dct['tips']
                
        wallet = Wallet(**dct)
        
        wallet.create_descriptor_wallet(wallet.descriptors[0], wallet.descriptors[1])                
        wallet.tips = tips
                
        return wallet
        
            
    def save(self, password, filename):
        human_readable = not bool(password)
        # special json
        def general_serializer(obj):
            if isinstance(obj, enum.Enum):
                return {"__enum__": True, "name": obj.__class__.__name__, "value": obj.name}
            if hasattr(obj, 'serialize'):
                return obj.serialize()
            # Fall back to the default JSON serializer
            return json.JSONEncoder().default(obj)                            
        
        storage = Storage()
        storage.save(json.dumps(self, default=general_serializer, 
                                indent=4 if human_readable else None,
                                sort_keys=bool(human_readable),                                
                                ), password, filename)
        
    
    @classmethod
    def load(cls, password, filename): # returns a Wallet instance
        def general_deserializer(dct):
            cls_string = dct.get("__class__")  # e.g. KeyStore
            if cls_string and cls_string in globals():
                obj_cls = globals()[cls_string]
                if hasattr(obj_cls, 'deserialize'):  # is there KeyStore.deserialize ? 
                    return obj_cls.deserialize(dct)  # do: KeyStore.deserialize(**dct)
            if dct.get("__enum__"):
                obj_cls = globals().get(dct["name"])                
                if not obj_cls:
                    obj_cls = getattr(bdk, dct["name"])  # if the class name is not imported directly, then try bdk
                if obj_cls:
                    return getattr(obj_cls, dct["value"])
            # For normal cases, json.loads will handle default JSON data types
            # No need to use json.Decoder here, just return the dictionary as-is
            return dct

        storage = Storage()
        json_string = storage.load(password, filename)
        return json.loads(json_string, object_hook=general_deserializer)
        
    def basename(self):
        import string, os
        def create_valid_filename(filename):
            basename = os.path.basename(filename)
            valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
            return ''.join(c for c in basename if c in valid_chars)      
        return create_valid_filename(self.id)  
    
    def clone(self): 
        return Wallet(self.id, self.threshold, len(self.keystores), self.network, self.blockchain_choice,
                        keystores=[keystore.clone() for keystore in self.keystores],
                        address_type=self.address_type.clone())
        
    
    def reset_cache(self):
        self.cache = {}
    
    def signer_names(self, threshold:int, i:int):
        i += 1
        if i <= threshold:
            return f'Signer {i}'
        else:
            return f'Recovery Signer {i}'
    
    
    def __repr__(self) -> str:
        return str(self.__dict__)
    
    def calculate_descriptors(self)->bdk.Descriptor:        
        return generate_bdk_descriptors(self.threshold, self.address_type, self.keystores, self.network)
    
    
    

    def set_wallet_from_descriptor(self, string_descriptor, recreate_bdk_wallet=True):
                                        
        infos = descriptor_infos(string_descriptor, self.network)                
                        
        self.set_number_of_keystores(len(infos['keystores']), cloned_reference_keystores=[k.clone() for k in infos['keystores']] )
        for self_keystore, descriptor_keystore in zip(self.keystores, infos['keystores']):
            self_keystore.from_other_keystore(descriptor_keystore)
        
        self.set_address_type(infos['address_type'])
        self.set_threshold(infos['threshold'])
        
        
        for i, keystore in enumerate(self.keystores):
                keystore.label = self.signer_names(self.threshold, i)
                
        if recreate_bdk_wallet:
            self.recreate_bdk_wallet()
        
        # print([k.serialize() for k in wallet.keystores])
        # print([k.serialize() for k in self.wallet.keystores])    
    
    
    def recreate_bdk_wallet(self):
        self.create_wallet(self.threshold, self.keystores, self.address_type)
    
    def set_keystores(self, keystores):
        self.keystores = keystores
    
    def set_threshold(self, threshold):
        self.threshold = threshold 
            
    def set_number_of_keystores(self, n, cloned_reference_keystores=None):
        if cloned_reference_keystores is None:
            cloned_reference_keystores = []
        if len(cloned_reference_keystores) < n:
            cloned_reference_keystores += [KeyStore(None, None, 
                                    self.address_type.derivation_path(self.network), 
                                    label=self.signer_names(self.threshold, i), 
                                    type=KeyStoreTypes.watch_only) 
                                   for i in range(n-len(cloned_reference_keystores))]
        
        if n > len(self.keystores):
            for i in range(len(self.keystores), n):
                self.keystores.append(cloned_reference_keystores[i])
        elif n < len(self.keystores):
            for i in range(n, len(self.keystores)):
                self.keystores.pop() # removes the last item
            
    
    def set_gap(self, gap):
        self.gap = gap
    
    def set_wallet_id(self, id):
        self.id = id
    
    def set_address_type(self, address_type:AddressType):
        self.address_type = address_type
        for keystore in self.keystores:
            keystore.set_derivation_path(address_type.derivation_path(self.network))
    
    def create_seed_wallet(self, seed):
        assert self.network != bdk.Network.BITCOIN # do not allow seeds on mainnet
        
        self.seed = seed
        mnemonic = bdk.Mnemonic.from_string(seed)

        descriptor = bdk.Descriptor.new_bip84(
                    secret_key=bdk.DescriptorSecretKey(self.network, mnemonic, ''),
                    keychain=bdk.KeychainKind.EXTERNAL,
                    network=self.network,
        )
        change_descriptor = bdk.Descriptor.new_bip84(
                    secret_key=bdk.DescriptorSecretKey(self.network, mnemonic, ''),
                    keychain=bdk.KeychainKind.INTERNAL,
                    network=self.network,
        )
        self.create_descriptor_wallet(descriptor=descriptor, change_descriptor=change_descriptor)
    

    
    def create_wallet(self, threshold:int, keystores:List[KeyStore], address_type:AddressType):
        # sanity checks
        assert threshold <= len(keystores) 
        is_multisig = len(keystores) >1
        assert address_type.is_multisig == is_multisig

        # check if the desc_template is in bdk and prevent unsafe templates
        if self.network == bdk.Network.BITCOIN and  address_type.desc_template.__name__ not  in dir(bdk.Descriptor):
            raise NotImplementedError
        
        if address_type.bdk_descriptor:
            # ensure that the desc_template is called from bdk.Descriptor itself, not from this_address_type            
            self.descriptors = [
                                address_type.bdk_descriptor(bdk.DescriptorPublicKey.from_string(keystores[0].xpub), 
                                                            keystores[0].fingerprint, 
                                                            keychainkind, 
                                                            self.network)
                            for keychainkind in [bdk.KeychainKind.EXTERNAL, bdk.KeychainKind.INTERNAL]]
        else:
            self.descriptors = generate_bdk_descriptors(threshold,address_type, keystores, self.network)
        
        self.create_descriptor_wallet(descriptor=self.descriptors[0], change_descriptor=self.descriptors[1])
        self.threshold = threshold
        self.address_type = address_type

    
    def create_descriptor_wallet(self, descriptor, change_descriptor=None):
        self.descriptors = [bdk.Descriptor(descriptor, network=self.network) if isinstance(descriptor, str) else descriptor,
                            bdk.Descriptor(change_descriptor, network=self.network) if isinstance(change_descriptor, str) else change_descriptor]
        

        self.bdkwallet = bdk.Wallet(
                    descriptor=self.descriptors[0],
                    change_descriptor=self.descriptors[1],
                    network=self.network,
                    database_config=bdk.DatabaseConfig.MEMORY(),
                )        
        # print(f"Wallet created successfully {self.bdkwallet}")
        
        


    def is_multisig(self):
            return len(self.keystores)>1

    def get_address_types(self, is_multisig=None) -> List[AddressType]:
            if is_multisig is None:
                    is_multisig = self.is_multisig()
            return [v for k,v in AddressTypes.__dict__.items() if (not k.startswith('_')) and  v.is_multisig==is_multisig]



    def _init_blockchain(self):
        """
        https://github.com/BitcoinDevelopersAcademy/bit-container
        
        
        alias rt-start='sudo docker run -d --rm -p 127.0.0.1:18443-18444:18443-18444/tcp -p 127.0.0.1:60401:60401/tcp --name electrs bitcoindevkit/electrs'
        alias rt-stop='sudo docker kill electrs'
        alias rt-logs='sudo docker container logs electrs'
        alias rt-cli='sudo docker exec -it electrs /root/bitcoin-cli -regtest  '        
        """
        if self.blockchain_choice == BlockchainType.Electrum:
            if self.network == bdk.Network.REGTEST:
                blockchain_config = bdk.BlockchainConfig.ELECTRUM(
                    bdk.ElectrumConfig(
                        "127.0.0.1:60401", 
                        None,
                        10,
                        100,
                        100,
                        False
                    )
                ) 
            
            
        if self.blockchain_choice == BlockchainType.CompactBlockFilter:
            folder = f"./compact-filters-{self.id}-{self.network.name}"
            if self.network == bdk.Network.BITCOIN:
                raise Exception('Mainnet not allowed')
            elif self.network == bdk.Network.REGTEST:
                blockchain_config = bdk.BlockchainConfig.COMPACT_FILTERS(
                    bdk.CompactFiltersConfig(
                        ['127.0.0.1:18444']*5,
                        self.network,
                        folder,
                        0
                    )
                )
            elif self.network == bdk.Network.TESTNET:
                blockchain_config = bdk.BlockchainConfig.COMPACT_FILTERS(
                    bdk.CompactFiltersConfig(
                        ['127.0.0.1:18333']*5,
                        self.network,
                        folder,
                        2000000
                    )
                )

        self.blockchain = bdk.Blockchain(blockchain_config)
        return self.blockchain
        
        
    def sync(self):
        if self.blockchain is None:
            self._init_blockchain()

        def update(progress:float, message:str):
            print(progress, message)
        progress = bdk.Progress()
        progress.update = update        
                
        print(self.bdkwallet)
        self.bdkwallet.sync(self.blockchain, progress) 
        print(f"Wallet balance is: { balance_dict(self.bdkwallet.get_balance()) }")        
        
    def get_address(self):        
        # print new receive address
        address_info = self.bdkwallet.get_address(bdk.AddressIndex.LAST_UNUSED())
        address = address_info.address
        index = address_info.index
        print(f"New address: {address.as_string()} at index {index}")
        return address_info

    def output_addresses(self, transaction):
        #print(f'Getting output addresses for txid {transaction.txid}')
        addresses = []
        for output in transaction.transaction.output(): 
            add = bdk.Address.from_script(output.script_pubkey, self.network) if output.value != 0 else None
            addresses.append(add)
        return addresses
            
    
    def get_bdk_tx(self, txid):
        txs = list(self.get_list_transactions())
        txids = [tx.txid for tx in txs]
        if txid in txids:
            return txs[txids.index(txid)]


    def get_tx_parents(self, txid) -> Dict:
        """
        recursively calls itself and returns a flat dict:
        txid -> list of parent txids
        """
        if not self.is_up_to_date():
            return {}
        
        all_transactions = self.get_list_transactions()
        
        result = {}
        parents = []
        uncles = []
        tx = self.get_bdk_tx(txid)
        assert tx, f"cannot find {txid}"
        for i, txin in enumerate(tx.transaction.input()):
            _txid = txin.previous_output.txid 
            parents.append(_txid)
            # detect address reuse
            addr = self.get_txin_address(txin)
            received, sent = self.bdk_received_and_send_involving_address(addr)
            # if len(sent) > 1:
            #     my_txid, my_height, my_pos = sent[txin.prevout.to_str()]
            #     assert my_txid == txid
            #     for k, v in sent.items():
            #         if k != txin.prevout.to_str():
            #             reuse_txid, reuse_height, reuse_pos = v
            #             if (reuse_height, reuse_pos) < (my_height, my_pos):
            #                 uncle_txid, uncle_index = k.split(':')
            #                 uncles.append(uncle_txid)

        for _txid in parents + uncles:
            if _txid in [tx.txid for tx in all_transactions]:
                result.update(self.get_tx_parents(_txid))
        result[txid] = parents, uncles
        return result

    def get_txin_address(self, txin):
        previous_output = txin.previous_output
        tx = self.get_bdk_tx(previous_output.txid)
        if tx:        
            output_for_input = tx.transaction.output()[previous_output.vout]
            return bdk.Address.from_script(output_for_input.script_pubkey, self.network)
        else:
            return None

    def fill_commonly_used_caches(self):
        self.get_addresses()
        self.get_list_transactions()
        self.get_utxos()
        self.get_received_send_maps()

    def list_input_addresses(self, transaction):         
        addresses = []
        for tx_in in transaction.transaction.input():
            previous_output = tx_in.previous_output
            tx = self.get_tx(previous_output.txid)     
            if tx:        
                output_for_input = tx.transaction.output()[previous_output.vout]

                add = bdk.Address.from_script(output_for_input.script_pubkey, self.network)
            else:
                add = None
                
            addresses.append(add)
        return addresses
                
    def list_tx_addresses(self, transaction):
        in_addresses = self.list_input_addresses(transaction)
        out_addresses = self.output_addresses(transaction)
        print(f'{transaction.txid}: {[(a.as_string() if a else None) for a in in_addresses]} --> {[(a.as_string() if a else None) for a in out_addresses]}')
        return {'in':in_addresses, 'out':out_addresses}
        

    def _get_tip(self, is_change):
        bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address
        return bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index
    def _set_tip(self, value, is_change):
        with self.write_lock:
            bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address
            
            current_tip = self._get_tip(is_change=is_change)
            print(f'current_tip = {current_tip},  value = {value}')
            if value >  current_tip:         
                print(f'indexing {value - current_tip} new addresses')   
                [bdk_get_address(bdk.AddressIndex.NEW()) for i in range(current_tip, value) ]   # NEW addess them to the watch list            

            new_tip = self._get_tip(is_change=is_change)
            print(f'new_tip = {new_tip},  value = {value}')
            assert new_tip == value


    @property
    def tips(self):
        return [self._get_tip(b) for b in [False, True]]
    @tips.setter
    def tips(self, value):
        [self._set_tip(v, b) for v, b in zip(value, [False, True])] 

    @cache_method
    def get_bdk_address_infos(self, is_change=False, slice_start=None, slice_stop=None) -> Sequence[bdk.AddressInfo]:
        if (not is_change) and (not self.descriptors):
            return []        
        
        if slice_start is None:
            slice_start = 0
        if slice_stop is None:
            slice_stop =  self.gap_change if is_change else self.gap

        if is_change:
            slice_stop = max(slice_stop, self.tips[1])            
            self.tip = (self.tips[0], slice_stop)
        else:
            slice_stop = max(slice_stop, self.tips[0])            
            self.tip = (slice_stop, self.tips[1])
            
        bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address
        result = [bdk_get_address(bdk.AddressIndex.PEEK(i)) for i in range(slice_start, slice_stop ) ]
        return result
        

    def get_addresses(self) -> Sequence[str]:
        # note: overridden so that the history can be cleared.
        # addresses are ordered based on derivation
        out = self.get_receiving_addresses()
        out += self.get_change_addresses()
        return out

    
    @cache_method
    def get_receiving_addresses(self, slice_start=None, slice_stop=None) -> Sequence[str]:
        return [address_info.address.as_string() 
                for address_info in self.get_bdk_address_infos(is_change=False, slice_start=slice_start, slice_stop=slice_stop)]        
        
    @cache_method
    def get_change_addresses(self, slice_start=None, slice_stop=None) -> Sequence[str]:
        addresses = [address_info.address.as_string() 
                for address_info in self.get_bdk_address_infos(is_change=True, slice_start=slice_start, slice_stop=slice_stop)]
        return addresses        

    def is_change(self, address):
        return    address in  self.get_change_addresses()  

    def get_address_index_tuple(self, address:str, keychain:bdk.KeychainKind) -> Tuple[bool, int]:
        "(is_change, index)"
        if keychain == bdk.KeychainKind.EXTERNAL:
            addresses = self.get_receiving_addresses()
            if address in addresses:
                return (0, addresses.index(address))
        else:
            addresses = self.get_change_addresses()
            if address in addresses:
                return (1, addresses.index(address))
        
    def address_info_min(self, address:str) -> AddressInfoMin:
        keychain = bdk.KeychainKind.EXTERNAL
        index_tuple = self.get_address_index_tuple(address, keychain)
        if index_tuple is None:
            keychain = bdk.KeychainKind.INTERNAL
            index_tuple = self.get_address_index_tuple(address, keychain)
        
        if  index_tuple is not None:
            return AddressInfoMin(address, index_tuple[1], keychain)    

    def get_all_known_addresses_beyond_gap_limit(self):
        return []
        
    def get_address_of_output(self, output) -> str:
        if output.value == 0: 
            return None
        else:
            return bdk.Address.from_script(output.script_pubkey, self.network).as_string()
    

    @cache_method
    def get_address_balances(self) -> Dict[AddressInfoMin, Tuple[int, int, int]]:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        def zero_balances():
            return [0,0,0]
        
        utxos = self.bdkwallet.list_unspent()
        balances : Dict[str, Tuple[int, int, int]] = defaultdict(zero_balances)
        
        for i, utxo in enumerate(utxos):
            tx = self.get_bdk_tx(utxo.outpoint.txid)

            for output in tx.transaction.output():
                address = self.get_address_of_output(output)
                if address is None:
                    continue
                balances[address][0] += output.value
                balances[address][1] += 0
                balances[address][2] += 0
                
        return balances
        
    def get_addr_balance(self, address):
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]
    
    @cache_method
    def get_list_transactions(self):
        return self.bdkwallet.list_transactions(True)
    
    @cache_method
    def get_received_send_maps(self):
        addresses_funded: Dict[OutPoint, str]     = {}
        received:  Dict[AddressInfoMin, Dict[OutPoint, bdk.Transaction]] = defaultdict(dict)   #  address: txid: tx
        send:      Dict[AddressInfoMin, Dict[OutPoint, bdk.Transaction]] = defaultdict(dict)   #  address: txid: tx
        
        # build the received dict
        for tx in self.get_list_transactions():
            for vout, output in enumerate(tx.transaction.output()):
                out_point = OutPoint(tx.txid, vout)
                address_info = self.address_info_min(self.get_address_of_output(output))
                if address_info is None:
                    continue
                received[address_info][out_point] = tx
                addresses_funded[out_point] = address_info
                
        # check if any input tx is in transactions_involving_address
        for tx in self.get_list_transactions():
            for input in tx.transaction.input():
                out_point = OutPoint.from_bdk_outpoint(input.previous_output)
                if out_point in addresses_funded:
                    address = addresses_funded[out_point]
                    send[address][out_point] = tx
                    
        return received, send
        
        
        
    def bdk_received_and_send_involving_address(self, address):
        received, send = self.get_received_send_maps()                        
        return received[address], send[address]
        
    def bdk_txs_involving_address(self, address):   
        received, send = self.bdk_received_and_send_involving_address(address)
        received.update(send)
        return received
        

    def get_utxos(self):
        return self.bdkwallet.list_unspent() 
        
    def address_is_used(self, address):
        """
        Check if any tx had this address as an output
        """
        return bool(self.bdk_txs_involving_address(address))

    def get_address_history_len(self, address): 
        return len(self.bdk_txs_involving_address(address))

    @cache_method
    def get_addresses_and_address_infos(self) -> Tuple[List[str], List[bdk.AddressInfo]]:
        addresses_infos = self.get_bdk_address_infos()
        addresses = [address_info.address.as_string() for address_info in addresses_infos]
        return addresses, addresses_infos

    def get_address_path_str(self, address) -> str:
        addresses, addresses_infos = self.get_addresses_and_address_infos()
        
        if address in addresses:
            return str(addresses_infos[addresses.index(address)].index)
        return ''
    
    def get_redeem_script(self, address):
        # TODO:         
        return None    
    
    def get_witness_script(self, address):
        return None
        
        
    def get_label_for_address(self, address):
        return ''
    
    def get_label_for_txid(self, txid):
        return ''
    
    def is_frozen_address(self, address):
        return False
    def is_frozen_coin(self, utxo):
        return False
    
    
    
    def is_up_to_date(self):
        return True
    
    
    def get_balances_for_piechart(self):
        """
        (_('Frozen'), COLOR_FROZEN, frozen),
        (_('Unmatured'), COLOR_UNMATURED, unmatured),
        (_('Unconfirmed'), COLOR_UNCONFIRMED, unconfirmed),
        (_('On-chain'), COLOR_CONFIRMED, confirmed),
        """
        
        balance = self.bdkwallet.get_balance() 
        return [0, balance.immature, balance.trusted_pending + balance.untrusted_pending , balance.confirmed]
        
        
        
        
    def get_utxo_name(self, utxo):
        tx = self.get_bdk_tx( utxo.outpoint.txid)
        return f'{tx.txid}:{utxo.outpoint.vout}'

    def get_utxo_address(self, utxo):
        tx = self.get_bdk_tx( utxo.outpoint.txid)
        return self.output_addresses(tx)[utxo.outpoint.vout]

        
    def get_full_history(self):  
        transactions = []
        balance = 0
                        
        monotonic_timestamp = 0
        for tx in self.get_list_transactions(): 
            value_delta = tx.received - tx .sent
            balance += value_delta
            timestamp = tx.confirmation_time.timestamp if tx.confirmation_time else 100
            height = tx.confirmation_time.height if tx.confirmation_time else 0
            
            monotonic_timestamp = max(monotonic_timestamp, timestamp)
            d = {
                'txid': tx.txid,
                'fee_sat': tx.fee,
                'height': height,
                'confirmations': self.blockchain.get_height() - height +1,
                'timestamp': timestamp,
                'monotonic_timestamp': monotonic_timestamp,
                'incoming': True if value_delta>0 else False,
                'bc_value': Satoshis(value_delta),
                'value': Satoshis(value_delta),
                'bc_balance': Satoshis(balance),
                'balance': Satoshis(balance),
                'date': timestamp_to_datetime(timestamp),
                'label': self.get_label_for_txid(tx.txid),
                'txpos_in_block': None, # not in bdk
            }
            transactions.append( d)
        return transactions
                
                

    def get_tx_status(self, txid, tx_mined_info: TxMinedInfo):
        extra = []
        height = tx_mined_info.height
        conf = tx_mined_info.conf
        timestamp = tx_mined_info.timestamp
        if height == TX_HEIGHT_FUTURE:
            num_blocks_remainining = tx_mined_info.wanted_height - self.blockchain.get_height()
            num_blocks_remainining = max(0, num_blocks_remainining)
            return 2, f'in {num_blocks_remainining} blocks'
        if conf == 0:
            tx = self.get_bdk_tx(txid)
            if not tx:
                return 2, 'unknown'
            is_final =  True # TODO: tx and tx.is_final()
            fee = tx.fee
            if fee is not None:
                size = tx.transaction.size()
                fee_per_byte = fee / size
                extra.append(format_fee_satoshis(fee_per_byte) + ' sat/b')
            # if fee is not None and height in (TX_HEIGHT_UNCONF_PARENT, TX_HEIGHT_UNCONFIRMED) \
            #    and self.config.has_fee_mempool():
            #     exp_n = self.config.fee_to_depth(fee_per_byte)
            #     if exp_n is not None:
            #         extra.append(self.config.get_depth_mb_str(exp_n))
            if height == TX_HEIGHT_LOCAL:
                status = 3
            elif height == TX_HEIGHT_UNCONF_PARENT:
                status = 1
            elif height == TX_HEIGHT_UNCONFIRMED:
                status = 0
            else:
                status = 2  # not SPV verified
        else:
            status = 3 + min(conf, 6)
        time_str = format_time(timestamp) if timestamp else _("unknown")
        status_str = TX_STATUS[status] if status < 4 else time_str
        if extra:
            status_str += ' [%s]'%(', '.join(extra))
        return status, status_str
    