import bdkpython as bdk
from .keystore import KeyStore
from typing import List
import html 

# https://bitcoin.design/guide/glossary/address/
# https://learnmeabitcoin.com/technical/derivation-paths
# https://github.com/bitcoin/bips/blob/master/bip-0380.mediawiki
# Safe to use are only those with a bdk desc_template  
class AddressType:
    def __init__(self, name, is_multisig, derivation_path=None, desc_template=None, desc_template_secret=None, info_url=None, description=None, bdk_descriptor=None) -> None:
        self.name = name
        self.is_multisig = is_multisig
        self.derivation_path = derivation_path
        self.desc_template = desc_template
        self.desc_template_secret = desc_template_secret
        self.info_url = info_url
        self.description = description
        self.bdk_descriptor = bdk_descriptor

    def clone(self):
        return AddressType(self.name, self.is_multisig, self.derivation_path, self.desc_template, self.desc_template_secret,
                           self.info_url, self.description, self.bdk_descriptor)

class AddressTypes:
    p2pkh = AddressType(
                'Single Sig (Legacy/p2pkh)', 
                False,
                derivation_path=lambda network: f"m/44h/{0 if network==bdk.Network.BITCOIN else 1}h/0h", 
                desc_template=lambda x: f'pkh({x})',
                bdk_descriptor=bdk.Descriptor.new_bip44_public,
                desc_template_secret=bdk.Descriptor.new_bip44,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='Legacy (single sig) addresses that look like 1addresses',
                )
    p2sh_p2wpkh= AddressType(
                'Single Sig (Nested/p2sh-p2wpkh)',
                False,
                derivation_path=lambda network: f"m/49h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
                desc_template=lambda x: f'sh(wpkh({x}))',
                bdk_descriptor=bdk.Descriptor.new_bip49_public,
                desc_template_secret=bdk.Descriptor.new_bip49,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='Nested (single sig) addresses that look like 3addresses',
            )
    p2wpkh = AddressType(
                'Single Sig (SegWit/p2wpkh)',
                False,
                derivation_path=lambda network: f"m/84h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",
                desc_template=lambda x: f'wpkh({x})',
                bdk_descriptor=bdk.Descriptor.new_bip84_public,
                desc_template_secret=bdk.Descriptor.new_bip84,
                info_url='https://learnmeabitcoin.com/technical/derivation-paths',
                description='SegWit (single sig) addresses that look like bc1addresses',
            )
    p2tr= AddressType(
                'Single Sig (Taproot/p2tr)',    
                False,
                derivation_path=lambda network: f"m/86h/{0 if network==bdk.Network.BITCOIN else 1}h/0h",    
                desc_template=lambda x: f'tr({x})',
                desc_template_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0386.mediawiki',
                description='Taproot (single sig) addresses ',
            )
    p2sh_p2wsh= AddressType(
                'Multi Sig (Nested/p2sh-p2wsh)' ,
                True,
                derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/1h",
                desc_template=lambda x: f'sh(wsh({x}))',
                desc_template_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki',
                description='Nested (multi sig) addresses that look like 3addresses',
            )
    p2wsh = AddressType(
                'Multi Sig (SegWit/p2wsh)',
                True,
                derivation_path=lambda network: f"m/48h/{0 if network==bdk.Network.BITCOIN else 1}h/0h/2h",
                desc_template=lambda x: f'wsh({x})',
                desc_template_secret=None,
                info_url='https://github.com/bitcoin/bips/blob/master/bip-0048.mediawiki',
                description='SegWit (multi sig) addresses that look like bc1addresses',
            )


def get_default_address_type(is_multisig) -> AddressType:
    return AddressTypes.p2wsh if is_multisig else AddressTypes.p2wpkh 

import colorsys

def generate_keystore_part_of_descriptor(xpubs, fingerprints, receiving_change_number, derivation_paths, use_html=False, replace_keystore_with_dummy=False):

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
    return key_parts


def generate_output_descriptors(xpubs, fingerprints, threshold:int, derivation_paths, desc_template , network, replace_keystore_with_dummy=False, use_html=False, combined_descriptors=False):    
    " combined_descriptors: see https://github.com/bitcoin/bitcoin/pull/22838 for  "
    if network==bdk.Network.BITCOIN:
        raise NotImplementedError('On mainnet are only wallet templaes from bdk suppoted.')

    if len(xpubs)>1:    
        def desc(key_parts):
            return  desc_template(f"sortedmulti({threshold},{','.join(key_parts)})")  
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


