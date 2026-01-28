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

from __future__ import annotations

import datetime
import enum
import ipaddress
import logging
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from functools import cached_property, lru_cache
from typing import Any

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.tx_util import hex_to_serialized, serialized_to_hex
from PyQt6.QtCore import QObject

from .storage import BaseSaveableClass, SaveAllClass, filtered_for_init
from .util import fast_version

logger = logging.getLogger(__name__)


def is_address(a: str, network: bdk.Network) -> bool:
    """Is address."""
    try:
        bdk.Address(a, network=network)
    except Exception as e:
        logger.debug(str(e))
        return False
    return True


class IpAddress(bdk.IpAddress):
    _RESOLVE_TIMEOUT_SECONDS = 5.0

    @staticmethod
    def _resolve_domain(host: str, timeout: float) -> str:
        """Resolve domain."""

        def _resolve() -> str:
            """Resolve."""
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            addresses: list[str] = []
            for family, _, _, _, sockaddr in infos:
                if family in (socket.AF_INET, socket.AF_INET6):
                    addresses.append(str(sockaddr[0]))
            if not addresses:
                raise ValueError(f"Could not resolve domain {host!r} to an IP address")
            return addresses[0]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_resolve)
            try:
                return future.result(timeout=timeout)
            except FutureTimeoutError as exc:
                raise TimeoutError(f"Timed out after {timeout} seconds resolving domain {host!r}") from exc

    @classmethod
    def from_host(cls, host: str):
        """From host."""
        try:
            host_ip = ipaddress.ip_address(host)
        except ValueError:
            resolved_host = cls._resolve_domain(host, cls._RESOLVE_TIMEOUT_SECONDS)
            host_ip = ipaddress.ip_address(resolved_host)
        host = str(host_ip.exploded)

        try:
            a1, a2, a3, a4 = host.split(".")
            return cls.from_ipv4(int(a1), int(a2), int(a3), int(a4))
        except Exception:
            pass

        try:
            a1, a2, a3, a4, a5, a6, a7, a8 = host.split(":")
            return cls.from_ipv6(
                int(a1, 16),
                int(a2, 16),
                int(a3, 16),
                int(a4, 16),
                int(a5, 16),
                int(a6, 16),
                int(a7, 16),
                int(a8, 16),
            )
        except Exception:
            pass
        raise Exception(f"{host=} could not be converted to {cls}")


@dataclass
class Recipient:
    address: str
    amount: int
    label: str | None = None
    checked_max_amount: bool = False

    def clone(self) -> Recipient:
        """Clone."""
        return Recipient(self.address, self.amount, self.label, self.checked_max_amount)


class OutPoint(bdk.OutPoint):
    def __key__(self) -> tuple[str, int]:
        """Key."""
        return (self.txid_str, self.vout)

    @cached_property
    def txid_str(self):
        """Txid str."""
        return str(self.txid)

    @cached_property
    def __hash__cached(self):
        """Hash  cached."""
        return hash(self.__key__())

    def __hash__(self) -> int:
        # Necessary for the caching
        # Attention: It has to reflect the content, not the id(self)
        """Return hash value."""
        return self.__hash__cached

    @cached_property
    def __str__cached(self):
        """Str  cached."""
        return f"{self.txid_str}:{self.vout}"

    def __str__(self) -> str:
        """Return string representation."""
        return self.__str__cached

    @cached_property
    def __repr__cached(self):
        """Repr  cached."""
        return str(f"{self.__class__.__name__}({self.txid},{self.vout})")

    def __repr__(self) -> str:
        """Return representation."""
        return self.__repr__cached

    def __eq__(self, other) -> bool:
        """Eq."""
        if isinstance(other, OutPoint):
            return hash(self) == hash(other)
        return False

    @classmethod
    def from_bdk(cls, bdk_outpoint: bdk.OutPoint) -> OutPoint:
        """From bdk."""
        if isinstance(bdk_outpoint, OutPoint):
            return bdk_outpoint
        if isinstance(bdk_outpoint, str):
            return cls.from_str(bdk_outpoint)
        return OutPoint(txid=bdk_outpoint.txid, vout=bdk_outpoint.vout)

    @classmethod
    def from_str(cls, outpoint_str: str) -> OutPoint:
        """From str."""
        if isinstance(outpoint_str, OutPoint):
            return outpoint_str
        txid, vout = outpoint_str.split(":")
        return OutPoint(txid=bdk.Txid.from_string(txid), vout=int(vout))


def get_prev_outpoints(tx: bdk.Transaction) -> list[OutPoint]:
    "Returns the list of prev_outpoints"
    return [OutPoint.from_bdk(input.previous_output) for input in tx.input()]


def _is_taproot_script(script_bytes: bytes) -> bool:
    """Is taproot script."""
    return len(script_bytes) == 34 and script_bytes[:2] == b"\x51\x20"


class TxOut(bdk.TxOut):
    @cached_property
    def spk_bytes(self) -> bytes:
        """Spk bytes."""
        return bytes(self.script_pubkey.to_bytes())

    @cached_property
    def spk_hex(self) -> str:
        """Spk hex."""
        return serialized_to_hex(self.spk_bytes)

    @cached_property
    def _key_cache(self) -> tuple[str, int]:
        """Key cache."""
        return (self.spk_hex, self.value.to_sat())

    def __key__(self) -> tuple[str, int]:
        # use cached hex + value
        """Key."""
        return self._key_cache

    @cached_property
    def __hash__cached(self):
        """Hash  cached."""
        return hash((self.value.to_sat(), self.spk_bytes))

    def __hash__(self) -> int:
        # hash on bytes (fast) + value
        # Attention: It has to reflect the content, not the id(self)
        """Return hash value."""
        return self.__hash__cached

    def seralized_tuple(self) -> tuple[str, int]:
        """Seralized tuple."""
        return (self.spk_hex, self.value.to_sat())

    @cached_property
    def __str__cached(self):
        """Str  cached."""
        return str(self.__key__())

    def __str__(self) -> str:
        """Return string representation."""
        return self.__str__cached

    @cached_property
    def _repr_cache(self):
        """Repr cache."""
        return f"{self.__class__.__name__}({self.__key__()})"

    def __repr__(self) -> str:
        """Return representation."""
        return self._repr_cache

    def __eq__(self, other) -> bool:
        """Eq."""
        return isinstance(other, TxOut) and (
            self.value.to_sat() == other.value.to_sat() and self.spk_bytes == other.spk_bytes
        )

    @classmethod
    def from_bdk(cls, tx_out: bdk.TxOut) -> TxOut:
        """From bdk."""
        if isinstance(tx_out, TxOut):
            return tx_out
        return TxOut(value=tx_out.value, script_pubkey=tx_out.script_pubkey)

    @classmethod
    def from_seralized_tuple(cls, seralized_tuple: tuple[str, int]) -> TxOut:
        """From seralized tuple."""
        script_pubkey, value = seralized_tuple
        return TxOut(
            script_pubkey=bdk.Script(hex_to_serialized(script_pubkey)), value=bdk.Amount.from_sat(value)
        )


@dataclass
class PythonUtxo(BaseSaveableClass):
    "A wrapper around tx_builder to collect even more infos"

    VERSION = "0.0.0"
    known_classes = {**BaseSaveableClass.known_classes, OutPoint.__name__: OutPoint, TxOut.__name__: TxOut}

    address: str
    outpoint: OutPoint
    txout: TxOut
    is_spent_by_txid: str | None = None

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["address"] = self.address
        d["outpoint"] = str(self.outpoint)
        d["txout"] = self.txout.__key__()
        d["is_spent_by_txid"] = self.is_spent_by_txid
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        dct["outpoint"] = OutPoint.from_str(dct["outpoint"])
        dct["txout"] = TxOut.from_seralized_tuple(dct["txout"])
        return cls(**filtered_for_init(dct, cls))

    def __hash__(self) -> int:
        # Attention: It has to reflect the content, not the id(self)
        # Leverage Python’s tuple‐hashing;
        # this requires that OutPoint and TxOut themselves be hashable
        """Return hash value."""
        return hash((self.address, self.outpoint, self.txout, self.is_spent_by_txid))

    @cached_property
    def value(self):
        """Value."""
        return self.txout.value.to_sat()


def python_utxo_balance(python_utxos: list[PythonUtxo]) -> int:
    """Python utxo balance."""
    return sum(python_utxo.value for python_utxo in python_utxos)


class UtxosForInputs:
    def __init__(
        self,
        utxos: list[PythonUtxo],
        included_opportunistic_merging_utxos=None,
        spend_all_utxos=False,
    ) -> None:
        """Initialize instance."""
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
    chain_position: bdk.ChainPosition

    @cached_property
    def bdk_txid(self):
        """Bdk txid."""
        return self.transaction.compute_txid()

    @cached_property
    def txid(self):
        """Txid."""
        return str(self.bdk_txid)

    @cached_property
    def vsize(self):
        """Vsize."""
        return self.transaction.vsize()

    def get_height(self, unconfirmed_height: int) -> int:
        """Get height."""
        if isinstance(self.chain_position, bdk.ChainPosition.CONFIRMED):
            return self.chain_position.confirmation_block_time.block_id.height
        if isinstance(self.chain_position, bdk.ChainPosition.UNCONFIRMED):
            return unconfirmed_height
        raise ValueError(f"self.chain_position has unnow type {type(self.chain_position)}")

    def get_datetime(self, fallback_timestamp: float = 0) -> datetime.datetime:
        """Get datetime."""
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
        """Initialize instance."""
        self.outputs: dict[str, PythonUtxo] = received if received else {}  # outpoint_str: PythonUtxo
        self.inputs: dict[str, PythonUtxo | None] = send if send else {}  # outpoint_str: PythonUtxo
        self.tx = tx
        self.txid = tx.txid

    def involved_addresses(self) -> set[str]:
        """Involved addresses."""
        input_addresses = [input.address for input in self.inputs.values() if input]
        output_addresses = [output.address for output in self.outputs.values() if output]
        return set(input_addresses).union(output_addresses)

    @classmethod
    def fill_received(
        cls, tx: TransactionDetails, get_address_of_txout: Callable[[str, int, TxOut], str | None]
    ) -> FullTxDetail:
        """Fill received."""
        res = FullTxDetail(tx)

        for vout, txout in enumerate(tx.transaction.output()):
            this_txout = TxOut.from_bdk(txout)
            address = get_address_of_txout(tx.txid, vout, this_txout)
            if not address:
                if not tx.transaction.is_coinbase():
                    logger.error(f"Could not calculate the address of {this_txout}. This should not happen.")
                continue
            out_point = OutPoint(txid=tx.bdk_txid, vout=vout)
            python_utxo = PythonUtxo(address=address, outpoint=out_point, txout=this_txout)
            python_utxo.is_spent_by_txid = None
            res.outputs[str(out_point)] = python_utxo
        return res

    def fill_inputs(
        self,
        lookup_dict_fulltxdetail: dict[str, FullTxDetail],
    ) -> None:
        """Fill inputs."""
        for prev_outpoint in get_prev_outpoints(self.tx.transaction):
            prev_outpoint_str = str(prev_outpoint)
            prevout_txid = prev_outpoint.txid_str

            # check if I have the prev_outpoint fulltxdetail
            if prevout_txid not in lookup_dict_fulltxdetail:
                self.inputs[prev_outpoint_str] = None
                continue
            fulltxdetail = lookup_dict_fulltxdetail[prevout_txid]
            if prev_outpoint_str not in fulltxdetail.outputs:
                self.inputs[prev_outpoint_str] = None
                continue
            python_utxo = fulltxdetail.outputs[prev_outpoint_str]
            python_utxo.is_spent_by_txid = self.tx.txid
            self.inputs[prev_outpoint_str] = python_utxo

    def sum_outputs(self, address_domain: list[str]) -> int:
        """Sum outputs."""
        return sum(
            python_utxo.value
            for python_utxo in self.outputs.values()
            if python_utxo and python_utxo.address in address_domain
        )

    def sum_inputs(self, address_domain: list[str]) -> int:
        """Sum inputs."""
        return sum(
            python_utxo.value
            for python_utxo in self.inputs.values()
            if python_utxo and python_utxo.address in address_domain
        )


class AddressInfoMin(SaveAllClass):
    def __init__(self, address: str, index: int, keychain: bdk.KeychainKind) -> None:
        """Initialize instance."""
        self.address = address
        self.index = index
        self.keychain = keychain

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)

    def __repr__(self) -> str:
        """Return representation."""
        return f"{self.__class__.__name__}({self.__dict__})"

    @cached_property
    def __key__cached(self):
        """Key  cached."""
        return tuple(v for k, v in sorted(self.__dict__.items()))

    def __key__(self) -> tuple:
        """Key."""
        return self.__key__cached

    @cached_property
    def __hash__cached(self):
        """Hash  cached."""
        return hash(self.__key__())

    def __hash__(self) -> int:
        # Necessary for the caching
        # Attention: It has to reflect the content, not the id(self)
        """Return hash value."""
        return self.__hash__cached

    @classmethod
    def from_bdk_address_info(cls, bdk_address_info: bdk.AddressInfo) -> AddressInfoMin:
        """From bdk address info."""
        return AddressInfoMin(
            str(bdk_address_info.address),
            bdk_address_info.index,
            bdk_address_info.keychain,
        )

    def is_change(self) -> bool:
        """Is change."""
        return self.keychain == bdk.KeychainKind.INTERNAL

    def address_path(self) -> tuple[int, int]:
        """Address path."""
        return (bool(self.is_change()), self.index)

    @staticmethod
    def is_change_to_keychain(is_change: bool) -> bdk.KeychainKind:
        """Is change to keychain."""
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
    def from_text(cls, t) -> BlockchainType:
        """From text."""
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
        """To text."""
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
    def active_types(cls, network: bdk.Network) -> list[BlockchainType]:
        """Active types."""
        if network == bdk.Network.TESTNET:
            return [cls.Electrum, cls.Esplora]
        return [cls.CompactBlockFilter, cls.Electrum, cls.Esplora]


class Balance(QObject, SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    def __init__(self, immature=0, trusted_pending=0, untrusted_pending=0, confirmed=0) -> None:
        """Initialize instance."""
        super().__init__()
        self.immature = immature
        self.trusted_pending = trusted_pending
        self.untrusted_pending = untrusted_pending
        self.confirmed = confirmed

    @classmethod
    def from_bdk(cls, balance: bdk.Balance):
        """From bdk."""
        return cls(
            immature=balance.immature.to_sat(),
            trusted_pending=balance.trusted_pending.to_sat(),
            untrusted_pending=balance.untrusted_pending.to_sat(),
            confirmed=balance.confirmed.to_sat(),
        )

    @property
    def total(self) -> int:
        """Total."""
        return self.immature + self.trusted_pending + self.untrusted_pending + self.confirmed

    @property
    def spendable(self) -> int:
        """Spendable."""
        return self.trusted_pending + self.confirmed

    def __add__(self, other: Balance) -> Balance:
        """Add."""
        summed = {key: self.__dict__[key] + other.__dict__[key] for key in self.__dict__.keys()}
        return self.__class__(**summed)

    def format_long(self, network: bdk.Network, btc_symbol: str) -> str:
        """Format long."""
        details = [
            f"{title}: {Satoshis(value, network=network).str_with_unit(btc_symbol=btc_symbol)}"
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

    def format_short(self, network: bdk.Network, btc_symbol: str) -> str:
        """Format short."""
        short = Satoshis(value=self.total, network=network).format_as_balance(btc_symbol=btc_symbol)

        return short

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """From dump migration."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)


def robust_address_str_from_script(
    script_pubkey: bdk.Script, network: bdk.Network, on_error_return_hex=True
) -> str:
    """Robust address str from script."""
    try:
        return str(bdk.Address.from_script(script_pubkey, network))
    except Exception as e:
        logger.debug(e.__class__.__name__)
        if on_error_return_hex:
            return serialized_to_hex(script_pubkey.to_bytes())
        else:
            return ""


@lru_cache(maxsize=200_000)
def robust_address_str_from_txout(txout: TxOut, network: bdk.Network, on_error_return_hex=True) -> str:
    """Robust address str from txout."""
    return robust_address_str_from_script(
        script_pubkey=txout.script_pubkey, network=network, on_error_return_hex=on_error_return_hex
    )


if __name__ == "__main__":
    testdict = {}

    def test_hashing(v) -> None:
        """Test hashing."""
        testdict[v] = v.__hash__()
        print(testdict[v])

    test_hashing(OutPoint(txid=bdk.Txid.from_string("txid"), vout=0))
    test_hashing(AddressInfoMin("ssss", 4, bdk.KeychainKind.EXTERNAL))
