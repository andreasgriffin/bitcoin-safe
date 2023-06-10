import logging
logger = logging.getLogger(__name__)

import bdkpython as bdk
from .keystore import KeyStore, KeyStoreTypes
from typing import Dict, List, Tuple
import html 
import re

# https://bitcoin.design/guide/glossary/address/
# https://learnmeabitcoin.com/technical/derivation-paths
# https://github.com/bitcoin/bips/blob/master/bip-0380.mediawiki
# Safe to use are only those with a bdk desc_template  
class AddressType:
    def __init__(self, name, is_multisig, derivation_path=None, desc_template=None, bdk_descriptor_secret=None, info_url=None, description=None, bdk_descriptor=None) -> None:
        self.name = name
        self.is_multisig = is_multisig
        self.derivation_path = derivation_path
        self.desc_template = desc_template
        self.bdk_descriptor_secret = bdk_descriptor_secret
        self.info_url = info_url
        self.description = description
        self.bdk_descriptor = bdk_descriptor

    def clone(self):
        return AddressType(self.name, self.is_multisig, self.derivation_path, self.desc_template, self.bdk_descriptor_secret,
                           self.info_url, self.description, self.bdk_descriptor)

class AddressTypes:
    p2pkh = AddressType(
                'Single Sig (Legacy/p2pkh)', 
                False,
                derivation_path=lambda network: f"m/44h/{0 if network==bdk.Network.BITCOIN else 1}h/0h", 
                desc_template=lambda x: f'pkh({x})',
                bdk_descriptor=bdk.Descriptor.new_bip44_public,
                bdk_descriptor_secret=bdk.Descriptor.new_bip44,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='Legacy (single sig) addresses that look like 1addresses',
                )
    p2sh_p2wpkh= AddressType(
                'Single Sig (Nested/p2sh-p2wpkh)',
                False,
                derivation_path=lambda network: f"m/49h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
                desc_template=lambda x: f'sh(wpkh({x}))',
                bdk_descriptor=bdk.Descriptor.new_bip49_public,
                bdk_descriptor_secret=bdk.Descriptor.new_bip49,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='Nested (single sig) addresses that look like 3addresses',
            )
    p2wpkh = AddressType(
                'Single Sig (SegWit/p2wpkh)',
                False,
                derivation_path=lambda network: f"m/84h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
                desc_template=lambda x: f'wpkh({x})',
                bdk_descriptor=bdk.Descriptor.new_bip84_public,
                bdk_descriptor_secret=bdk.Descriptor.new_bip84,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='SegWit (single sig) addresses that look like bc1addresses',
            )
    p2tr= AddressType(
                'Single Sig (Taproot/p2tr)',    
                False,
                derivation_path=lambda network: f"m/86h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",    
                desc_template=lambda x: f'tr({x})',
                bdk_descriptor_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0386.mediawiki',
                description='Taproot (single sig) addresses ',
            )
    p2sh_p2wsh= AddressType(
                'Multi Sig (Nested/p2sh-p2wsh)' ,
                True,
                derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/1h",
                desc_template=lambda x: f'sh(wsh({x}))',
                bdk_descriptor_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki',
                description='Nested (multi sig) addresses that look like 3addresses',
            )
    p2wsh = AddressType(
                'Multi Sig (SegWit/p2wsh)',
                True,
                derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/2h",
                desc_template=lambda x: f'wsh({x})',
                bdk_descriptor_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki',
                description='SegWit (multi sig) addresses that look like bc1addresses',
            )


def get_default_address_type(is_multisig) -> AddressType:
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh 

import colorsys

def generate_keystore_part_of_descriptor(xpubs, fingerprints, receiving_change_number, derivation_paths, use_html=False, replace_keystore_with_dummy=False) -> str:
    def float_rgb_to_hex(r_float, g_float, b_float):
        r_int, g_int, b_int = [int(round(x * 255)) for x in (r_float, g_float, b_float)]
        hex_color = "#{:02X}{:02X}{:02X}".format(r_int, g_int, b_int)
        return hex_color


    def keystore(xpub, fingerprint, derivation_path, i, use_html=False):
        hue = i/len(xpubs) + 0.3
        hex_color = float_rgb_to_hex(*colorsys.hsv_to_rgb(hue,1,.7))
        if replace_keystore_with_dummy and (not xpub or not fingerprint or not derivation_path):
            s = f"Signer{i+1}"
        else:
            s = f"[{derivation_path.replace('m', fingerprint)}]{xpub}/{receiving_change_number}/*" 
        
        if use_html:
            s = f'<span style="color:{hex_color}">{html.escape(s)}</span>'
        
        return s
    
    key_parts = [
        keystore(xpub, fingerprint, derivation_path, i, use_html=use_html)
        for i, (xpub, fingerprint, derivation_path) in enumerate(zip(xpubs, fingerprints, derivation_paths))]  
    return ','.join(key_parts)


def generate_output_descriptors(xpubs, fingerprints, threshold:int, derivation_paths, desc_template , network, replace_keystore_with_dummy=False, use_html=False, combined_descriptors=False):    
    " combined_descriptors: see https://github.com/bitcoin/bitcoin/pull/22838 for  "
    # if network==bdk.Network.BITCOIN:
    #     raise NotImplementedError('On mainnet are only wallet templates from bdk suppoted.')

    if len(xpubs)>1:    
        def desc(key_parts):
            return  desc_template(f"sortedmulti({threshold},{key_parts})")  
    else:
        def desc(key_parts):
            return  desc_template(key_parts)

    if combined_descriptors:
        return [desc(generate_keystore_part_of_descriptor(xpubs, fingerprints, '<0;1>', derivation_paths, use_html=use_html, replace_keystore_with_dummy=replace_keystore_with_dummy )) ]
    else:        
        return [desc(generate_keystore_part_of_descriptor(xpubs, fingerprints, receiving_change_number, derivation_paths, use_html=use_html, replace_keystore_with_dummy=replace_keystore_with_dummy )) 
                for receiving_change_number in range(2)]

def generate_output_descriptors_from_keystores(threshold:int, address_type:AddressType, keystores:List[KeyStore], network, replace_keystore_with_dummy=False, use_html=False, combined_descriptors=False) -> str:        
        output_descriptors = generate_output_descriptors([keystore.xpub for keystore in keystores], 
                                        [keystore.fingerprint for keystore in keystores], 
                                        threshold, 
                                        [keystore.derivation_path for keystore in keystores], 
                                        address_type.desc_template, 
                                        network, 
                                        replace_keystore_with_dummy=replace_keystore_with_dummy, 
                                        use_html=use_html,
                                        combined_descriptors=combined_descriptors)
        if combined_descriptors:
            assert len(output_descriptors) == 1
        return output_descriptors
    
    
def generate_bdk_descriptors(threshold:int, address_type:AddressType, keystores:List[KeyStore], network, replace_keystore_with_dummy=False) -> bdk.Descriptor:
    if address_type.bdk_descriptor:
        # single sig currently, thats why no m_of_n goes in here
        assert len(keystores) == 1
        return [address_type.bdk_descriptor(keystores[0].xpub, keystores[0].fingerprint, keychainkind, network) for keychainkind in [bdk.KeychainKind.EXTERNAL, bdk.KeychainKind.INTERNAL]]
    else:
        # check if the desc_template is in bdk and prevent unsafe templates
        if network == bdk.Network.BITCOIN:
            raise NotImplementedError            
        
        output_descriptors = generate_output_descriptors([keystore.xpub for keystore in keystores], 
                                        [keystore.fingerprint for keystore in keystores], 
                                        threshold, 
                                        [keystore.derivation_path for keystore in keystores], 
                                        address_type.desc_template, 
                                        network, 
                                        replace_keystore_with_dummy=replace_keystore_with_dummy)
        return [bdk.Descriptor(d, network) for d in output_descriptors]


def descriptor_infos(string_descriptor:str, network=None) -> Dict:
    def extract_groups(string, pattern):
        match = re.match(pattern, string)
        if match is None:
            raise ValueError(f"'{string}' does not match the required pattern!")
        return match.groups()

    def extract_keystore(keystore_string):
        """
        Splits 1 keystore,e.g. "[a42c6dd3/84'/1'/0']xpub/0/*"
        into fingerprint, derivation_path, xpub, wallet_path
        
        It also replaces the "'" into "h"
        """
        fingerprint, derivation_path, xpub, further_derivation_path = extract_groups(keystore_string, r'\[(.*?)\/(.*)\](.*?)\/(.*)')
        # TODO handle other further_derivation_path
        assert further_derivation_path in ["<0;1>/*", "0/*", "1/*"]
        
        return KeyStore(xpub, fingerprint, 'm/'+derivation_path, label='', type=KeyStoreTypes.watch_only)
    
    
    string_descriptor = string_descriptor.strip()
    
    # First split the descriptor like:
    # "wpkh"
    # "[a42c6dd3/84'/1'/0']xpub/0/*"
    groups = [g.rstrip(')') for g in extract_groups(string_descriptor, r'(.*)\((.*)\)')] # remove trailing )
    logger.debug(f'groups {groups}')

    # do the keystore parts
    is_single_sig = len(groups) == 2
    is_multisig = 'multi' in groups[0]
    assert is_multisig != is_single_sig
    threshold = 1    
    if is_multisig:
        threshold, *keystore_strings = groups[1].split(',')
        keystores = [extract_keystore(keystore_string) for keystore_string in keystore_strings]
    elif is_single_sig:
        keystores = [extract_keystore(groups[1])]
    else:
        raise Exception('descriptor could not be matched to single or multisig')

    # address type
    used_desc_template = f'{groups[0]}()' + (')' if '(' in groups[0] else '')
    address_type = None
    for temp_address_type in AddressTypes.__dict__.values():    
        if not isinstance(temp_address_type, AddressType):
            continue
        if temp_address_type.desc_template('') == used_desc_template:
            address_type = temp_address_type
            break
        
    # warn if the derivation path deviates from the recommended
    if network:
        for keystore in keystores:
            if keystore.derivation_path != address_type.derivation_path(network):
                logger.warning(f'Warning: The derivation path of {keystore} is not the default')
    
    
    return {'threshold':threshold, 'is_multisig':is_multisig, 'keystores':keystores, 'address_type':address_type}