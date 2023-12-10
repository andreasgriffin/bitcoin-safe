import bdkpython as bdk
import enum
from .util import serialized_to_hex
from .storage import SaveAllClass


class Recipient:
    def __init__(self, address, amount, label=None, checked_max_amount=False) -> None:
        self.address = address
        self.amount = amount
        self.label = label
        self.checked_max_amount = checked_max_amount

    def clone(self):
        return Recipient(self.address, self.amount, self.label, self.checked_max_amount)


class OutPoint(bdk.OutPoint):
    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __hash__(self):
        return hash(self.__key__())

    def __str__(self):
        return f"{self.txid}:{self.vout}"

    @classmethod
    def from_bdk(cls, bdk_outpoint: bdk.OutPoint):
        if isinstance(bdk_outpoint, OutPoint):
            return bdk_outpoint
        return OutPoint(bdk_outpoint.txid, bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str):
        txid, vout = outpoint_str.split(":")
        return OutPoint(txid, int(vout))

    def __eq__(self, other):
        if isinstance(other, OutPoint):
            return (self.txid, self.vout) == (other.txid, other.vout)
        return False


class TxOut(bdk.TxOut):
    def __key__(self):
        return (serialized_to_hex(self.script_pubkey.to_bytes()), self.value)

    def __hash__(self):
        return hash(self.__key__())

    def __str__(self):
        return str(self.__key__())

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


class AddressInfoMin(SaveAllClass):
    def __init__(self, address, index, keychain):
        self.address = address
        self.index = index
        self.keychain = keychain

    def __repr__(self) -> str:
        return str(self.__dict__)

    def __key__(self):
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __hash__(self):
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


def robust_address_str_from_script(script_pubkey, network):
    try:
        return bdk.Address.from_script(script_pubkey, network).as_string()
    except:

        return serialized_to_hex(script_pubkey.to_bytes())


if __name__ == "__main__":
    testdict = {}

    def test_hashing(v):
        testdict[v] = v.__hash__()
        print(testdict[v])

    test_hashing(OutPoint("txid", 0))
    test_hashing(AddressInfoMin("ssss", 4, bdk.KeychainKind.EXTERNAL))
