"""
This file was created once to provide  the pubkeys of a TxIn

- since it wasnt needed anywhere the functions were removed again
"""
import logging

logger = logging.getLogger(__name__)


import bdkpython as bdk

from bitcoin_safe.util import hex_to_serialized


def script_pubkey_to_address(script_pubkey: str, network: bdk.Network) -> str:
    return bdk.Address.from_script(bdk.Script(hex_to_serialized(script_pubkey)), network).as_string()
