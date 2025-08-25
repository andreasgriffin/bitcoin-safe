#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import datetime
import enum
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.tx_util import hex_to_serialized, serialized_to_hex
from packaging import version
from PyQt6.QtCore import QObject

from .storage import BaseSaveableClass, SaveAllClass, filtered_for_init

logger = logging.getLogger(__name__)


def is_address(a: str, network: bdk.Network) -> bool:
    try:
        bdk.Address(a, network=network)
    except Exception as e:
        logger.debug(str(e))
        return False
    return True


@dataclass
class Recipient:
    address: str
    amount: int
    label: Optional[str] = None
    checked_max_amount: bool = False

    def clone(self) -> "Recipient":
        return Recipient(self.address, self.amount, self.label, self.checked_max_amount)


class OutPoint(bdk.OutPoint):

    def __key__(self) -> tuple[str, int]:
        return (self.txid, self.vout)

    def __hash__(self) -> int:
        "Necessary for the caching"
        return hash(self.__key__())

    def __str__(self) -> str:
        return f"{self.txid}:{self.vout}"

    def __repr__(self) -> str:
        return str(f"{self.__class__.__name__}({self.txid},{self.vout})")

    def __eq__(self, other) -> bool:
        if isinstance(other, OutPoint):
            return (self.txid, self.vout) == (other.txid, other.vout)
        return False

    @classmethod
    def from_bdk(cls, bdk_outpoint: bdk.OutPoint) -> "OutPoint":
        if isinstance(bdk_outpoint, OutPoint):
            return bdk_outpoint
        if isinstance(bdk_outpoint, str):
            return cls.from_str(bdk_outpoint)
        return OutPoint(txid=bdk_outpoint.txid, vout=bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str) -> "OutPoint":
        if isinstance(outpoint_str, OutPoint):
            return outpoint_str
        txid, vout = outpoint_str.split(":")
        return OutPoint(txid=txid, vout=int(vout))


def get_prev_outpoints(tx: bdk.Transaction) -> List[OutPoint]:
    "Returns the list of prev_outpoints"
    return [OutPoint.from_bdk(input.previous_output) for input in tx.input()]


class TxOut(bdk.TxOut):

    def _spk_bytes(self) -> bytes:
        b = getattr(self, "_spk_bytes", None)
        if b is None:
            b = bytes(self.script_pubkey.to_bytes())
            setattr(self, "_spk_bytes", b)
        return b

    def _spk_hex(self) -> str:
        h = getattr(self, "_spk_hex", None)
        if h is None:
            h = serialized_to_hex(self._spk_bytes())
            setattr(self, "_spk_hex", h)
        return h

    def __key__(self) -> tuple[str, int]:
        # use cached hex + value
        return (self._spk_hex(), self.value)

    def __hash__(self) -> int:
        # hash on bytes (fast) + value
        return hash((self.value, self._spk_bytes()))

    def seralized_tuple(self) -> tuple[str, int]:
        return (self._spk_hex(), self.value)

    def __str__(self) -> str:
        return str(self.__key__())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__key__()})"

    def __eq__(self, other) -> bool:
        return isinstance(other, TxOut) and (
            self.value == other.value and self._spk_bytes() == other._spk_bytes()
        )

    @classmethod
    def from_bdk(cls, tx_out: bdk.TxOut) -> "TxOut":
        if isinstance(tx_out, TxOut):
            return tx_out
        return TxOut(value=tx_out.value, script_pubkey=tx_out.script_pubkey)

    @classmethod
    def from_seralized_tuple(cls, seralized_tuple: Tuple[str, int]) -> "TxOut":
        script_pubkey, value = seralized_tuple
        return TxOut(script_pubkey=bdk.Script(list(hex_to_serialized(script_pubkey))), value=(value))


@dataclass
class PythonUtxo(BaseSaveableClass):
    "A wrapper around tx_builder to collect even more infos"

    VERSION = "0.0.0"
    known_classes = {**BaseSaveableClass.known_classes, OutPoint.__name__: OutPoint, TxOut.__name__: TxOut}

    address: str
    outpoint: OutPoint
    txout: TxOut
    is_spent_by_txid: Optional[str] = None

    def dump(self) -> Dict[str, Any]:
        d = super().dump()
        d["address"] = self.address
        d["outpoint"] = str(self.outpoint)
        d["txout"] = self.txout.__key__()
        d["is_spent_by_txid"] = self.is_spent_by_txid
        return d

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        dct["outpoint"] = OutPoint.from_str(dct["outpoint"])
        dct["txout"] = TxOut.from_seralized_tuple(dct["txout"])
        return cls(**filtered_for_init(dct, cls))

    def __hash__(self) -> int:
        # Leverage Python’s tuple‐hashing;
        # this requires that OutPoint and TxOut themselves be hashable
        return hash((self.address, self.outpoint, self.txout, self.is_spent_by_txid))


def python_utxo_balance(python_utxos: List[PythonUtxo]) -> int:
    return sum(python_utxo.txout.value for python_utxo in python_utxos)


class UtxosForInputs:
    def __init__(
        self,
        utxos: List[PythonUtxo],
        included_opportunistic_merging_utxos=None,
        spend_all_utxos=False,
    ) -> None:
        if included_opportunistic_merging_utxos is None:
            included_opportunistic_merging_utxos = []

        self.utxos = utxos
        self.included_opportunistic_merging_utxos = included_opportunistic_merging_utxos
        self.spend_all_utxos = spend_all_utxos


@dataclass
class TransactionDetails:
    transaction: bdk.Transaction
    fee: int | None
    received: int
    sent: int
    txid: str
    chain_position: bdk.ChainPosition

    def get_height(self, unconfirmed_height: int) -> int:
        if isinstance(self.chain_position, bdk.ChainPosition.CONFIRMED):
            return self.chain_position.confirmation_block_time.block_id.height
        if isinstance(self.chain_position, bdk.ChainPosition.UNCONFIRMED):
            return unconfirmed_height
        raise ValueError(f"self.chain_position has unnow type {type(self.chain_position)}")

    def get_datetime(self, fallback_timestamp: float = 0) -> datetime.datetime:
        if isinstance(self.chain_position, bdk.ChainPosition.CONFIRMED):

            return datetime.datetime.fromtimestamp(
                self.chain_position.confirmation_block_time.confirmation_time
            )
        if isinstance(self.chain_position, bdk.ChainPosition.UNCONFIRMED):
            return datetime.datetime.fromtimestamp(self.chain_position.timestamp or fallback_timestamp)

        raise ValueError(f"self.chain_position has unnow type {type(self.chain_position)}")


class FullTxDetail:
    """For all outputs and inputs, where it has a full PythonUtxo ."""

    def __init__(self, tx: TransactionDetails, received=None, send=None) -> None:
        self.outputs: Dict[str, PythonUtxo] = received if received else {}  # outpoint_str: PythonUtxo
        self.inputs: Dict[str, Optional[PythonUtxo]] = send if send else {}  # outpoint_str: PythonUtxo
        self.tx = tx
        self.txid = tx.txid

    def involved_addresses(self) -> Set[str]:
        input_addresses = [input.address for input in self.inputs.values() if input]
        output_addresses = [output.address for output in self.outputs.values() if output]
        return set(input_addresses).union(output_addresses)

    @classmethod
    def fill_received(
        cls, tx: TransactionDetails, get_address_of_txout: Callable[[TxOut], str | None]
    ) -> "FullTxDetail":
        res = FullTxDetail(tx)
        txid = tx.txid
        for vout, txout in enumerate(tx.transaction.output()):
            this_txout = TxOut.from_bdk(txout)
            address = get_address_of_txout(this_txout)
            if not address:
                if not tx.transaction.is_coinbase():
                    logger.error(f"Could not calculate the address of {this_txout}. This should not happen.")
                continue
            out_point = OutPoint(txid=txid, vout=vout)
            python_utxo = PythonUtxo(address=address, outpoint=out_point, txout=this_txout)
            python_utxo.is_spent_by_txid = None
            res.outputs[str(out_point)] = python_utxo
        return res

    def fill_inputs(
        self,
        lookup_dict_fulltxdetail: Dict[str, "FullTxDetail"],
    ) -> None:
        for prev_outpoint in get_prev_outpoints(self.tx.transaction):
            prev_outpoint_str = str(prev_outpoint)

            # check if I have the prev_outpoint fulltxdetail
            if prev_outpoint.txid not in lookup_dict_fulltxdetail:
                self.inputs[prev_outpoint_str] = None
                continue
            fulltxdetail = lookup_dict_fulltxdetail[prev_outpoint.txid]
            if prev_outpoint_str not in fulltxdetail.outputs:
                self.inputs[prev_outpoint_str] = None
                continue
            python_utxo = fulltxdetail.outputs[prev_outpoint_str]
            python_utxo.is_spent_by_txid = self.tx.txid
            self.inputs[prev_outpoint_str] = python_utxo

    def sum_outputs(self, address_domain: List[str]) -> int:
        return sum(
            python_utxo.txout.value
            for python_utxo in self.outputs.values()
            if python_utxo and python_utxo.address in address_domain
        )

    def sum_inputs(self, address_domain: List[str]) -> int:
        return sum(
            python_utxo.txout.value
            for python_utxo in self.inputs.values()
            if python_utxo and python_utxo.address in address_domain
        )


class AddressInfoMin(SaveAllClass):
    def __init__(self, address: str, index: int, keychain: bdk.KeychainKind) -> None:
        self.address = address
        self.index = index
        self.keychain = keychain

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.__dict__})"

    def __key__(self) -> Tuple:
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __hash__(self) -> int:
        "Necessary for the caching"
        return hash(self.__key__())

    @classmethod
    def from_bdk_address_info(cls, bdk_address_info: bdk.AddressInfo) -> "AddressInfoMin":
        return AddressInfoMin(
            str(bdk_address_info.address),
            bdk_address_info.index,
            bdk_address_info.keychain,
        )

    def is_change(self) -> bool:
        return self.keychain == bdk.KeychainKind.INTERNAL

    def address_path(self) -> Tuple[int, int]:
        return (bool(self.is_change()), self.index)

    @staticmethod
    def is_change_to_keychain(is_change: bool) -> bdk.KeychainKind:
        if is_change:
            return bdk.KeychainKind.INTERNAL
        else:
            return bdk.KeychainKind.EXTERNAL


class BlockchainType(enum.Enum):
    CompactBlockFilter = enum.auto()
    Electrum = enum.auto()
    Esplora = enum.auto()
    RPC = enum.auto()

    @classmethod
    def from_text(cls, t) -> "BlockchainType":
        if t == "Compact Block Filters":
            return cls.CompactBlockFilter
        elif t == "Electrum Server":
            return cls.Electrum
        elif t == "Esplora Server":
            return cls.Esplora
        elif t == "RPC":
            return cls.RPC

        raise ValueError(f"{t} is not a valid BlockchainType")

    @classmethod
    def to_text(cls, t) -> str:
        if t == cls.CompactBlockFilter:
            return "Compact Block Filters"
        elif t == cls.Electrum:
            return "Electrum Server"
        elif t == cls.Esplora:
            return "Esplora Server"
        elif t == cls.RPC:
            return "RPC"
        else:
            raise ValueError()

    @classmethod
    def active_types(cls) -> List["BlockchainType"]:
        return [cls.Electrum, cls.Esplora]


class Balance(QObject, SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(self, immature=0, trusted_pending=0, untrusted_pending=0, confirmed=0) -> None:
        super().__init__()
        self.immature = immature
        self.trusted_pending = trusted_pending
        self.untrusted_pending = untrusted_pending
        self.confirmed = confirmed

    @classmethod
    def from_bdk(cls, balance: bdk.Balance):
        return cls(
            immature=balance.immature.to_sat(),
            trusted_pending=balance.trusted_pending.to_sat(),
            untrusted_pending=balance.untrusted_pending.to_sat(),
            confirmed=balance.confirmed.to_sat(),
        )

    @property
    def total(self) -> int:
        return self.immature + self.trusted_pending + self.untrusted_pending + self.confirmed

    @property
    def spendable(self) -> int:
        return self.trusted_pending + self.confirmed

    def __add__(self, other: "Balance") -> "Balance":
        summed = {key: self.__dict__[key] + other.__dict__[key] for key in self.__dict__.keys()}
        return self.__class__(**summed)

    def format_long(self, network: bdk.Network) -> str:

        details = [
            f"{title}: {Satoshis(value, network=network).str_with_unit()}"
            for title, value in [
                (self.tr("Confirmed"), self.confirmed),
                (
                    self.tr("Unconfirmed"),
                    self.untrusted_pending + self.trusted_pending,
                ),
                (self.tr("Unmatured"), self.immature),
            ]
        ]
        long = "\n".join(details)
        return long

    def format_short(self, network: bdk.Network) -> str:

        short = Satoshis(value=self.total, network=network).format_as_balance()

        return short

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)


def robust_address_str_from_script(
    script_pubkey: bdk.Script, network: bdk.Network, on_error_return_hex=True
) -> str:
    try:
        return str(bdk.Address.from_script(script_pubkey, network))
    except Exception as e:
        logger.debug(str(e))
        if on_error_return_hex:
            return serialized_to_hex(script_pubkey.to_bytes())
        else:
            return ""


@lru_cache(maxsize=200_000)
def robust_address_str_from_txout(txout: TxOut, network: bdk.Network, on_error_return_hex=True) -> str:
    return robust_address_str_from_script(
        script_pubkey=txout.script_pubkey, network=network, on_error_return_hex=on_error_return_hex
    )


if __name__ == "__main__":
    testdict = {}

    def test_hashing(v) -> None:
        testdict[v] = v.__hash__()
        print(testdict[v])

    test_hashing(OutPoint(txid="txid", vout=0))
    test_hashing(AddressInfoMin("ssss", 4, bdk.KeychainKind.EXTERNAL))
