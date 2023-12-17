from typing import List
import bdkpython as bdk
import enum
from .util import serialized_to_hex
from .storage import SaveAllClass
import numpy as np


class Recipient:
    def __init__(self, address, amount, label=None, checked_max_amount=False) -> None:
        self.address = address
        self.amount = amount
        self.label = label
        self.checked_max_amount = checked_max_amount

    def __hash__(self):
        "Necessary for the caching"
        return hash(self.__dict__)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"

    def clone(self):
        return Recipient(self.address, self.amount, self.label, self.checked_max_amount)


class OutPoint(bdk.OutPoint):
    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __hash__(self):
        "Necessary for the caching"
        return hash(self.__key__())

    def __str__(self) -> str:
        return f"{self.txid}:{self.vout}"

    def __repr__(self) -> str:
        return str(f"{self.__class__.__name__}({self.txid},{self.vout})")

    def __eq__(self, other):
        if isinstance(other, OutPoint):
            return (self.txid, self.vout) == (other.txid, other.vout)
        return False

    @classmethod
    def from_bdk(cls, bdk_outpoint: bdk.OutPoint):
        if isinstance(bdk_outpoint, OutPoint):
            return bdk_outpoint
        return OutPoint(bdk_outpoint.txid, bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str):
        txid, vout = outpoint_str.split(":")
        return OutPoint(txid, int(vout))


class TxOut(bdk.TxOut):
    def __key__(self):
        return (serialized_to_hex(self.script_pubkey.to_bytes()), self.value)

    def __hash__(self):
        "Necessary for the caching"
        return hash(self.__key__())

    def __str__(self) -> str:
        return str(self.__key__())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__key__()})"

    @classmethod
    def from_bdk(cls, tx_out: bdk.TxOut):
        if isinstance(tx_out, TxOut):
            return tx_out
        return TxOut(tx_out.value, tx_out.script_pubkey)

    def __eq__(self, other):
        if isinstance(other, TxOut):
            return (self.value, serialized_to_hex(self.script_pubkey.to_bytes())) == (
                other.value,
                serialized_to_hex(other.script_pubkey.to_bytes()),
            )
        return False


class PythonUtxo:
    def __init__(self, outpoint: OutPoint, txout: TxOut) -> None:
        self.outpoint = outpoint
        self.txout = txout


class UtxosForInputs:
    def __init__(
        self, utxos, included_opportunistic_merging_utxos=None, spend_all_utxos=False
    ) -> None:
        if included_opportunistic_merging_utxos is None:
            included_opportunistic_merging_utxos = []

        self.utxos = utxos
        self.included_opportunistic_merging_utxos = included_opportunistic_merging_utxos
        self.spend_all_utxos = spend_all_utxos


class PartialTxInfo:
    "Gives a partial info of the tx, usually restricted to 1 address"

    def __init__(self, tx: bdk.TransactionDetails, received=None, send=None) -> None:
        self.received: List[PythonUtxo] = received if received else []
        self.send: List[PythonUtxo] = send if send else []
        self.tx = tx
        self.txid = tx.txid


def unique_txs(txs: List[bdk.TransactionDetails]) -> List[bdk.TransactionDetails]:
    tx_ids = []
    res = []
    for tx in txs:
        if tx.txid not in tx_ids:
            tx_ids.append(tx.txid)
            res.append(tx)
    return res


def unique_txs_from_partialtxinfos(
    partialtxinfos: List[PartialTxInfo],
) -> List[bdk.TransactionDetails]:
    return unique_txs([partialtxinfo.tx for partialtxinfo in partialtxinfos])


class AddressInfoMin(SaveAllClass):
    def __init__(self, address, index, keychain):
        self.address = address
        self.index = index
        self.keychain = keychain

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"

    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __hash__(self):
        "Necessary for the caching"
        return hash(self.__key__())

    @classmethod
    def from_bdk_address_info(cls, bdk_address_info: bdk.AddressInfo):
        return AddressInfoMin(
            bdk_address_info.address.as_string(),
            bdk_address_info.index,
            bdk_address_info.keychain,
        )


class BlockchainType(enum.Enum):
    CompactBlockFilter = enum.auto()
    Electrum = enum.auto()
    Esplora = enum.auto()
    RPC = enum.auto()

    @classmethod
    def from_text(cls, t):
        if t == "Compact Block Filters":
            return cls.CompactBlockFilter
        elif t == "Electrum Server":
            return cls.Electrum
        elif t == "Esplora Server":
            return cls.Esplora
        elif t == "RPC":
            return cls.RPC

    @classmethod
    def to_text(cls, t):
        if t == cls.CompactBlockFilter:
            return "Compact Block Filters"
        elif t == cls.Electrum:
            return "Electrum Server"
        elif t == cls.Esplora:
            return "Esplora Server"
        elif t == cls.RPC:
            return "RPC"


class CBFServerType(enum.Enum):
    Automatic = enum.auto()
    Manual = enum.auto()

    @classmethod
    def from_text(cls, t):
        if t == "Automatic":
            return cls.Automatic
        elif t == "Manual":
            return cls.Manual

    @classmethod
    def to_text(cls, t):
        if t == cls.Automatic:
            return "Automatic"
        elif t == cls.Manual:
            return "Manual"


def robust_address_str_from_script(
    script_pubkey: bdk.Script, network, on_error_return_hex=False
):
    try:
        return bdk.Address.from_script(script_pubkey, network).as_string()
    except:
        if on_error_return_hex:
            return serialized_to_hex(script_pubkey.to_bytes())


if __name__ == "__main__":
    testdict = {}

    def test_hashing(v):
        testdict[v] = v.__hash__()
        print(testdict[v])

    test_hashing(OutPoint("txid", 0))
    test_hashing(AddressInfoMin("ssss", 4, bdk.KeychainKind.EXTERNAL))
