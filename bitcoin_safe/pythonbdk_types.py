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


import enum
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import bdkpython as bdk
from packaging import version
from PyQt6.QtCore import QObject

from .storage import SaveAllClass
from .util import Satoshis, serialized_to_hex

logger = logging.getLogger(__name__)


class Recipient:
    def __init__(
        self, address: str, amount: int, label: Optional[str] = None, checked_max_amount=False
    ) -> None:
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
        if isinstance(bdk_outpoint, str):
            return cls.from_str(bdk_outpoint)
        return OutPoint(bdk_outpoint.txid, bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str):
        if isinstance(outpoint_str, OutPoint):
            return outpoint_str
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
    def __init__(self, address: str, outpoint: OutPoint, txout: TxOut) -> None:
        self.outpoint = outpoint
        self.txout = txout
        self.address = address
        self.is_spent_by_txid: Optional[str] = None


def python_utxo_balance(python_utxos: List[PythonUtxo]):
    return sum([python_utxo.txout.value for python_utxo in python_utxos])


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


class FullTxDetail:
    """For all outputs and inputs, where it has a full PythonUtxo ."""

    def __init__(self, tx: bdk.TransactionDetails, received=None, send=None) -> None:
        self.outputs: Dict[str, PythonUtxo] = received if received else {}  # outpoint_str: PythonUtxo
        self.inputs: Dict[str, Optional[PythonUtxo]] = send if send else {}  # outpoint_str: PythonUtxo
        self.tx = tx
        self.txid = tx.txid

    @classmethod
    def fill_received(
        cls, tx: bdk.TransactionDetails, get_address_of_txout: Callable[[TxOut], str]
    ) -> "FullTxDetail":
        res = FullTxDetail(tx)
        txid = tx.txid
        for vout, txout in enumerate(tx.transaction.output()):
            address = get_address_of_txout(TxOut.from_bdk(txout))
            out_point = OutPoint(txid, vout)
            if address is None:
                continue
            python_utxo = PythonUtxo(address, out_point, txout)
            python_utxo.is_spent_by_txid = None
            res.outputs[str(out_point)] = python_utxo
        return res

    def fill_inputs(
        self,
        lookup_dict_fulltxdetail: Dict[str, "FullTxDetail"],
    ):
        for input in self.tx.transaction.input():
            prev_outpoint = OutPoint.from_bdk(input.previous_output)
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


class AddressInfoMin(SaveAllClass):
    def __init__(self, address: str, index: int, keychain: bdk.KeychainKind):
        self.address = address
        self.index = index
        self.keychain = keychain

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

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

    def is_change(self):
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
    def to_text(cls, t):
        if t == cls.CompactBlockFilter:
            return "Compact Block Filters"
        elif t == cls.Electrum:
            return "Electrum Server"
        elif t == cls.Esplora:
            return "Esplora Server"
        elif t == cls.RPC:
            return "RPC"

    @classmethod
    def active_types(cls) -> List["BlockchainType"]:
        return [cls.Electrum, cls.Esplora, cls.RPC]


class CBFServerType(enum.Enum):
    Automatic = enum.auto()
    Manual = enum.auto()

    @classmethod
    def from_text(cls, t):
        return CBFServerType._member_map_[t]


class Balance(QObject):
    def __init__(self, immature=0, trusted_pending=0, untrusted_pending=0, confirmed=0):
        super().__init__()
        self.immature = immature
        self.trusted_pending = trusted_pending
        self.untrusted_pending = untrusted_pending
        self.confirmed = confirmed

    @property
    def total(self):
        return self.immature + self.trusted_pending + self.untrusted_pending + self.confirmed

    @property
    def spendable(self):
        return self.trusted_pending + self.confirmed

    def __add__(self, other: "Balance") -> "Balance":
        summed = {key: self.__dict__[key] + other.__dict__[key] for key in self.__dict__.keys()}
        return Balance(**summed)

    def format_long(self, network: bdk.Network) -> str:

        details = [
            f"{title}: {Satoshis (value, network=network).str_with_unit()}"
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


def robust_address_str_from_script(script_pubkey: bdk.Script, network, on_error_return_hex=False):
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
