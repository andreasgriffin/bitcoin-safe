import bdkpython as bdk
import enum


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

    @classmethod
    def from_bdk(cls, bdk_outpoint: bdk.OutPoint):
        return OutPoint(bdk_outpoint.txid, bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str):
        txid, vout = outpoint_str.split(":")
        return OutPoint(txid, int(vout))

    def __eq__(self, other):
        if isinstance(other, OutPoint):
            return (self.txid, self.vout) == (other.txid, other.vout)
        return False


class AddressInfoMin:
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

    def serialize(self):
        d = self.__dict__.copy()
        d["__class__"] = self.__class__.__name__
        return d

    @classmethod
    def deserialize(cls, dct):
        assert dct.get("__class__") == cls.__name__
        if "__class__" in dct:
            del dct["__class__"]
        return cls(**dct)


class BlockchainType(enum.Enum):
    CompactBlockFilter = enum.auto()
    Electrum = enum.auto()
    RPC = enum.auto()

    @classmethod
    def from_text(cls, t):
        if t == "Compact Block Filters":
            return cls.CompactBlockFilter
        elif t == "Electrum Server":
            return cls.Electrum
        elif t == "RPC":
            return cls.RPC

    @classmethod
    def to_text(cls, t):
        if t == cls.CompactBlockFilter:
            return "Compact Block Filters"
        elif t == cls.Electrum:
            return "Electrum Server"
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


class Error:
    BdkError = bdk.BdkError

    InvalidU32Bytes = bdk.BdkError.InvalidU32Bytes
    Generic = bdk.BdkError.Generic
    MissingCachedScripts = bdk.BdkError.MissingCachedScripts
    ScriptDoesntHaveAddressForm = bdk.BdkError.ScriptDoesntHaveAddressForm
    NoRecipients = bdk.BdkError.NoRecipients
    NoUtxosSelected = bdk.BdkError.NoUtxosSelected
    OutputBelowDustLimit = bdk.BdkError.OutputBelowDustLimit
    InsufficientFunds = bdk.BdkError.InsufficientFunds
    BnBTotalTriesExceeded = bdk.BdkError.BnBTotalTriesExceeded
    BnBNoExactMatch = bdk.BdkError.BnBNoExactMatch
    UnknownUtxo = bdk.BdkError.UnknownUtxo
    TransactionNotFound = bdk.BdkError.TransactionNotFound
    TransactionConfirmed = bdk.BdkError.TransactionConfirmed
    IrreplaceableTransaction = bdk.BdkError.IrreplaceableTransaction
    FeeRateTooLow = bdk.BdkError.FeeRateTooLow
    FeeTooLow = bdk.BdkError.FeeTooLow
    FeeRateUnavailable = bdk.BdkError.FeeRateUnavailable
    MissingKeyOrigin = bdk.BdkError.MissingKeyOrigin
    Key = bdk.BdkError.Key
    ChecksumMismatch = bdk.BdkError.ChecksumMismatch
    SpendingPolicyRequired = bdk.BdkError.SpendingPolicyRequired
    InvalidPolicyPathError = bdk.BdkError.InvalidPolicyPathError
    Signer = bdk.BdkError.Signer
    InvalidNetwork = bdk.BdkError.InvalidNetwork
    InvalidProgressValue = bdk.BdkError.InvalidProgressValue
    ProgressUpdateError = bdk.BdkError.ProgressUpdateError
    InvalidOutpoint = bdk.BdkError.InvalidOutpoint
    Descriptor = bdk.BdkError.Descriptor
    Encode = bdk.BdkError.Encode
    Miniscript = bdk.BdkError.Miniscript
    MiniscriptPsbt = bdk.BdkError.MiniscriptPsbt
    Bip32 = bdk.BdkError.Bip32
    Secp256k1 = bdk.BdkError.Secp256k1
    Json = bdk.BdkError.Json
    Hex = bdk.BdkError.Hex
    Psbt = bdk.BdkError.Psbt
    PsbtParse = bdk.BdkError.PsbtParse
    Electrum = bdk.BdkError.Electrum
    Esplora = bdk.BdkError.Esplora
    Sled = bdk.BdkError.Sled
    Rusqlite = bdk.BdkError.Rusqlite
    Rpc = bdk.BdkError.Rpc
    CompactFilters = bdk.BdkError.CompactFilters


if __name__ == "__main__":
    testdict = {}

    def test_hashing(v):
        testdict[v] = v.__hash__()
        print(testdict[v])

    test_hashing(OutPoint("txid", 0))
    test_hashing(AddressInfoMin("ssss", 4, bdk.KeychainKind.EXTERNAL))
