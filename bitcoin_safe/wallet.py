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

import logging
import random
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from time import time
from typing import (
    Any,
    Final,
)
from uuid import uuid4

import bdkpython as bdk
import numpy as np
from bdkpython import Network
from bdkpython.bdk import Descriptor, Persister
from bitcoin_qr_tools.multipath_descriptor import (
    address_descriptor_from_multipath_descriptor,
    convert_to_multipath_descriptor,
)
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.tx_util import hex_to_serialized, serialized_to_hex
from bitcoin_safe_lib.util import (
    clean_list,
    hash_string,
    replace_non_alphanumeric,
    time_logger,
    unique_elements,
)
from bitcoin_usb.address_types import DescriptorInfo
from bitcoin_usb.software_signer import derive as software_signer_derive
from typing_extensions import Self

from bitcoin_safe.client import Client
from bitcoin_safe.client_helpers import UpdateInfo
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.persister.serialize_persistence import SerializePersistence
from bitcoin_safe.psbt_util import FeeInfo, FeeRate
from bitcoin_safe.wallet_util import (
    WalletDifference,
    WalletDifferences,
    WalletDifferenceType,
    signer_name,
)

from .config import UserConfig
from .constants import MIN_RELAY_FEE
from .descriptors import (
    AddressType,
    descriptor_from_keystores,
    get_default_address_type,
)
from .i18n import translate
from .keystore import KeyStore
from .labels import Labels, LabelType
from .pythonbdk_types import (
    AddressInfoMin,
    Balance,
    BlockchainType,
    FullTxDetail,
    OutPoint,
    PythonUtxo,
    Recipient,
    TransactionDetails,
    TxOut,
    UtxosForInputs,
    enum,
    robust_address_str_from_script,
    robust_address_str_from_txout,
)
from .signals import UpdateFilter, WalletFunctions
from .storage import BaseSaveableClass, filtered_for_init
from .tx import TxBuilderInfos, TxUiInfos, short_tx_id
from .util import CacheManager, calculate_ema, fast_version, instance_lru_cache, short_address

_LOOKAHEAD_SENTINEL: Final = object()  # unique marker

logger = logging.getLogger(__name__)


LOCAL_TX_LAST_SEEN = 0


class InconsistentBDKState(Exception):
    pass


class TxConfirmationStatus(enum.Enum):
    CONFIRMED = 1
    UNCONFIRMED = 0
    LOCAL = -2  # this implies UNCONFIRMED
    PSBT = -10
    DRAFT = -100

    @classmethod
    def to_str(cls, status: TxConfirmationStatus) -> str:
        """Return a localized label for a transaction confirmation status."""
        if status == cls.CONFIRMED:
            return translate("wallet", "Confirmed")
        if status == cls.UNCONFIRMED:
            return translate("wallet", "Unconfirmed")
        if status == cls.LOCAL:
            return translate("wallet", "Local")
        if status == cls.PSBT:
            return translate("wallet", "PSBT")
        if status == cls.DRAFT:
            return translate("wallet", "Draft")


def is_local(chain_position: bdk.ChainPosition | None) -> bool:
    """Return True when the chain position matches a locally stored tx."""
    return (
        isinstance(chain_position, bdk.ChainPosition.UNCONFIRMED)
        and chain_position.timestamp == LOCAL_TX_LAST_SEEN
    )


def is_in_mempool(chain_position: bdk.ChainPosition | None) -> bool:
    """Return True if the chain position reflects a mempool transaction."""
    if chain_position is None:
        return False
    if isinstance(chain_position, bdk.ChainPosition.CONFIRMED):
        return False
    local = is_local(chain_position=chain_position)
    return not local


class TxStatus:
    def __init__(
        self,
        tx: bdk.Transaction | None,
        chain_position: bdk.ChainPosition | None,
        get_height: Callable[[], int],
        fallback_confirmation_status: TxConfirmationStatus = TxConfirmationStatus.LOCAL,
    ) -> None:
        """Capture transaction data and derive the initial confirmation status."""
        self.tx = tx
        self.get_height = get_height
        self.chain_position = chain_position

        self.confirmation_status = fallback_confirmation_status
        if isinstance(chain_position, bdk.ChainPosition.CONFIRMED):
            self.confirmation_status = TxConfirmationStatus.CONFIRMED

        if self.confirmation_status.value <= TxConfirmationStatus.UNCONFIRMED.value and self.is_in_mempool():
            self.confirmation_status = TxConfirmationStatus.UNCONFIRMED

    def is_in_mempool(self):
        """Return True if the tracked transaction is currently in the mempool."""
        return is_in_mempool(self.chain_position)

    @classmethod
    def from_wallet(cls, txid: str | bdk.Txid, wallet: Wallet) -> TxStatus:
        """Construct a TxStatus helper for the given wallet transaction."""
        # TODO: remove get_height callback entirely
        txdetails = wallet.get_tx(str(txid))

        if not txdetails:
            return TxStatus(tx=None, chain_position=None, get_height=wallet.get_height)

        return TxStatus(
            tx=txdetails.transaction,
            chain_position=txdetails.chain_position,
            get_height=wallet.get_height,
        )

    def sort_id(self) -> int:
        """Return a sort key prioritizing confirmations over status order."""
        return confirmations if (confirmations := self.confirmations()) else self.confirmation_status.value

    def confirmations(self) -> int:
        """Return the number of confirmations derived from the chain position."""
        return (
            self.get_height() - self.chain_position.confirmation_block_time.block_id.height + 1
            if self.chain_position and isinstance(self.chain_position, bdk.ChainPosition.CONFIRMED)
            else 0
        )

    def is_confirmed(self) -> bool:
        """Return True if the transaction has been confirmed."""
        return self.confirmation_status == TxConfirmationStatus.CONFIRMED

    def is_unconfirmed(self) -> bool:
        """Return True if the transaction is unconfirmed."""
        return self.confirmation_status == TxConfirmationStatus.UNCONFIRMED

    def can_do_initial_broadcast(self) -> bool:
        """Return True when the transaction can be broadcast for the first time."""
        return self.confirmation_status == TxConfirmationStatus.LOCAL

    def is_local(self) -> bool:
        """Return True if the transaction is tracked locally only."""
        return self.confirmation_status == TxConfirmationStatus.LOCAL

    def can_rbf(self) -> bool:
        """Return True if the transaction is eligible for RBF."""
        return self.is_unconfirmed()

    def can_cpfp(self) -> bool:
        """Return True if the transaction can be fee bumped with CPFP."""
        return self.confirmation_status == TxConfirmationStatus.UNCONFIRMED

    def can_edit(self) -> bool:
        """Return True if the transaction details remain editable."""
        return self.confirmation_status.value <= TxConfirmationStatus.LOCAL.value

    def do_icon_check_on_chain_height_change(self) -> bool:
        """Return True if UI icons should refresh on height changes."""
        return self.confirmations() <= 6


def locked(func) -> Any:
    """Wrap a method to ensure it runs while holding the instance lock."""

    def wrapper(self, *args, **kwargs) -> Any:
        """Invoke the wrapped function with the wallet lock held."""
        with self.lock:
            return func(self, *args, **kwargs)

    return wrapper


# a wallet  during setup phase, with partial information
class ProtoWallet(BaseSaveableClass):
    def __init__(
        self,
        wallet_id: str,
        threshold: int,
        network: bdk.Network,
        keystores: list[KeyStore | None],
        address_type: AddressType | None = None,
        gap=20,
    ) -> None:
        """Create a ProtoWallet skeleton with keystore and descriptor metadata."""
        super().__init__()

        self.id = wallet_id
        self.threshold = threshold
        self.network = network

        self.gap = gap

        initial_address_type: AddressType = (
            address_type if address_type else get_default_address_type(len(keystores) > 1)
        )
        self.keystores: list[KeyStore | None] = keystores

        self.set_address_type(initial_address_type)

    def get_mn_tuple(self) -> tuple[int, int]:
        """Return the (threshold, signer count) tuple for the wallet."""
        """Return the (threshold, signer_count) tuple."""
        return self.threshold, len(self.keystores)

    def get_differences(self, other_wallet: ProtoWallet) -> WalletDifferences:
        "Compares the relevant entries like keystores"
        differences = WalletDifferences()
        this = self.__dict__
        other = other_wallet.__dict__

        keys = [
            "id",
            "gap",
        ]
        for k in keys:
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.NeedsRescan,
                        key=k,
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        keys = ["network", "threshold", "address_type"]
        for k in keys:
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.ImpactOnAddresses,
                        key=k,
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        if (this_len := len(self.keystores)) != (other_len := len(other_wallet.keystores)):
            differences.append(
                WalletDifference(
                    type=WalletDifferenceType.ImpactOnAddresses,
                    key="keystore added/removed",
                    this_value=this_len,
                    other_value=other_len,
                )
            )

        for keystore, other_keystore in zip(self.keystores, other_wallet.keystores, strict=False):
            if type(keystore) is not type(other_keystore):
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.ImpactOnAddresses,
                        key="keystore set/unset",
                        this_value=this_len,
                        other_value=other_len,
                    )
                )
            if keystore and other_keystore:
                differences += keystore.get_differences(other_keystore, prefix=f"{keystore.label} ")

        return differences

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> ProtoWallet:
        """Reconstruct a ProtoWallet instance from persisted data."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """Apply migrations required to load older ProtoWallet dumps."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)

    def dump(self) -> Any:
        """ProtoWallets cannot be dumped directly and always raise an error."""
        super().dump()

        raise NotImplementedError(
            "Dumping ProtoWallet is not implemented, since ProtoWallet is not supposed to be saved"
        )

    @classmethod
    def from_descriptor(
        cls,
        wallet_id: str,
        descriptor: str,
        network: bdk.Network,
    ) -> ProtoWallet:
        """Construct a ProtoWallet from a descriptor string and network."""
        "creates a ProtoWallet from the xpub (not xpriv)"
        info = DescriptorInfo.from_str(descriptor)
        keystores: list[KeyStore | None] = [
            KeyStore(
                **spk_provider.__dict__,
                label=signer_name(i=i, threshold=info.threshold),
                network=network,
            )
            for i, spk_provider in enumerate(info.spk_providers)
        ]
        return ProtoWallet(
            wallet_id=wallet_id,
            threshold=info.threshold,
            network=network,
            keystores=keystores,
            address_type=info.address_type,
        )

    def set_address_type(self, address_type: AddressType) -> None:
        """Update the descriptor address type used by the proto wallet."""
        self.address_type = address_type

    def signer_name(self, i: int) -> str:
        """Return a human-friendly label for the ith signer."""
        return signer_name(self.threshold, i)

    def sticker_name(self, i: int | str) -> str:
        """Return the printable sticker name for a signer index."""
        number = i if isinstance(i, str) else f"{i + 1}"
        name = f"{self.id} {number}" if len(self.keystores) > 1 else f"{self.id}"
        return name.strip()

    def set_gap(self, gap: int) -> None:
        """Set the address discovery gap for the proto wallet."""
        self.gap = gap

    def to_multipath_descriptor(self) -> bdk.Descriptor | None:
        """Return the multipath descriptor if all keystores are configured."""
        if not all(self.keystores):
            return None
        # type checking doesnt recognize that all(self.keystores)  already ensures that all are set
        cleaned_keystores = [keystore for keystore in self.keystores if keystore]
        return descriptor_from_keystores(
            self.threshold,
            spk_providers=cleaned_keystores,
            address_type=self.address_type,
            network=self.network,
        )

    def set_number_of_keystores(self, n: int) -> None:
        """Resize the keystore list to contain n entries."""
        if n > len(self.keystores):
            for _i in range(len(self.keystores), n):
                self.keystores.append(None)
        elif n < len(self.keystores):
            for _i in range(n, len(self.keystores)):
                self.keystores.pop()  # removes the last item

    def set_threshold(self, threshold: int) -> None:
        """Set the required signature threshold."""
        self.threshold = threshold

    def is_multisig(self) -> bool:
        """Return True if the proto wallet uses multiple keystores."""
        return len(self.keystores) > 1


class DeltaCacheListTransactions:
    def __init__(self) -> None:
        """Initialize the cache containers used to track history deltas."""
        super().__init__()
        self.old_state: list[TransactionDetails] = []
        self.appended: list[TransactionDetails] = []
        self.removed: list[TransactionDetails] = []
        self.new_state: list[TransactionDetails] = []
        self.modified: list[TransactionDetails] = []

    def was_changed(self) -> dict[str, list[TransactionDetails]]:
        """Return a dict of appended, removed, and modified transactions."""
        d = {}
        if self.appended:
            d["appended"] = self.appended
        if self.removed:
            d["removed"] = self.removed
        if self.modified:
            d["modified"] = self.modified
        return d


class TxoType(enum.Enum):
    InputTxo = enum.auto()
    OutputTxo = enum.auto()


BDK_DEFAULT_LOOKAHEAD = 25
NUM_RETRIES_get_address_balances = 2


class BdkWallet(bdk.Wallet, CacheManager):
    """This is a caching wrapper around bdk.Wallet. It should not provide any logic.
    Only wrapping existing methods and minimal new methods useful for caching.

    The exception is list_delta_transactions, which provides also deltas to a previous state, and is in a
    wider sense also caching.
    """

    def __init__(
        self,
        descriptor: Descriptor,
        change_descriptor: Descriptor,
        network: Network,
        persister: Persister,
        lookahead: int = BDK_DEFAULT_LOOKAHEAD,
    ):
        """Initialize the caching wrapper around the underlying bdk wallet."""
        # lookahead default see https://docs.rs/bdk_chain/0.23.1/bdk_chain/indexer/keychain_txout/constant.DEFAULT_LOOKAHEAD.html
        bdk.Wallet.__init__(
            self,
            descriptor=descriptor,
            change_descriptor=change_descriptor,
            network=network,
            persister=persister,
            lookahead=lookahead,
        )
        CacheManager.__init__(self)
        self._init_cache()
        logger.info(f"Created bdk.Wallet for network {network}")

    def _init_cache(self):
        """Reset address and transaction delta caches."""
        self._address_cache: dict[tuple[str, int], str | None] = {}
        self._delta_cache: dict[str, DeltaCacheListTransactions] = {}

    def addresses_identical(self, other_wallet: BdkWallet):
        return all(
            [
                str(self.peek_address(keychain=keychain, index=0).address)
                == str(other_wallet.peek_address(keychain=keychain, index=0).address)
                for keychain in bdk.KeychainKind
            ]
        )

    @classmethod
    def load(
        cls,
        descriptor,
        change_descriptor,
        persister,
        lookahead=_LOOKAHEAD_SENTINEL,
    ) -> BdkWallet:
        """Load a persisted wallet and initialize caching helpers."""
        wallet = super().load(
            descriptor=descriptor,
            change_descriptor=change_descriptor,
            persister=persister,
            lookahead=20 if lookahead is _LOOKAHEAD_SENTINEL else lookahead,
        )
        CacheManager.__init__(wallet)
        wallet._init_cache()
        logger.info(f"Created bdk.Wallet for network {wallet.network()}")
        return wallet

    @instance_lru_cache(always_keep=True)
    def peek_address(self, keychain: bdk.KeychainKind, index: int) -> bdk.AddressInfo:
        """Return the cached bdk address info for the given keychain index."""
        return super().peek_address(keychain=keychain, index=index)

    @instance_lru_cache(always_keep=True)
    def peek_address_str(
        self,
        index: int,
        is_change=False,
    ) -> str:
        """Return the string form of the address at the given index."""
        return str(
            self.peek_address(
                index=index, keychain=AddressInfoMin.is_change_to_keychain(is_change=is_change)
            ).address
        )

    @instance_lru_cache()
    @time_logger
    def list_output(self) -> list[bdk.LocalOutput]:
        """Return cached local outputs from the underlying bdk wallet."""
        start_time = time()
        result = super().list_output()
        logger.debug(f"self.bdkwallet.list_output {len(result)} results in {time() - start_time}s")

        return result

    @instance_lru_cache()
    @time_logger
    def list_unspent_outpoints(self, include_spent=False) -> list[str]:
        """Return a list of tracked outpoints, optionally including spent ones."""
        start_time = time()
        result = [
            str(OutPoint.from_bdk(output.outpoint))
            for output in self.list_output()
            if include_spent or not output.is_spent
        ]
        logger.debug(f"self.bdkwallet.list_output {len(result)} results in {time() - start_time}s")
        return result

    def get_tx_details(self, canonical_tx: bdk.CanonicalTx) -> TransactionDetails:
        """Return normalized transaction details including fees and amounts."""
        tx = canonical_tx.transaction

        # Calculate the fee:
        # For coinbase transactions, we set fee to None;
        # otherwise, we calculate the fee using the wallet's calculate_fee method.
        if tx.is_coinbase():
            fee = None
        else:
            try:
                fee_amount = self.calculate_fee(tx)  # returns an Amount
                fee = fee_amount.to_sat()  # convert Amount to satoshis (int)
            except bdk.CalculateFeeError.MissingTxOut:
                fee = None
                # do not log, because with Compact BlockFilters this is common
            except Exception as e:
                fee = None
                logger.debug(f"{e.__class__.__name__} occured with {short_tx_id(tx.compute_txid())}  ")

        sent_receive = self.sent_and_received(tx)

        return TransactionDetails(
            transaction=tx,
            fee=fee,
            received=sent_receive.received.to_sat(),
            sent=sent_receive.sent.to_sat(),
            chain_position=canonical_tx.chain_position,
        )

    @instance_lru_cache()
    def list_transactions(self) -> list[TransactionDetails]:
        """Return cached transaction details for the wallet history."""
        start_time = time()
        res = super().transactions()

        logger.debug(f"list_transactions {len(res)} results in {time() - start_time}s")
        return [self.get_tx_details(tx) for tx in res]

    def list_delta_transactions(self, access_marker: str) -> DeltaCacheListTransactions:
        """access_marker is a unique key, that the history can be stored relative to
        this.

        to call however only the minimal amount of times the underlying function, list_transactions is cached.
        When list_transactions is reset, the delta depends on the access_marker
        """

        key = "list_delta_transactions" + str(access_marker)
        entry = self._delta_cache[key] = self._delta_cache.get(key, DeltaCacheListTransactions())
        entry.old_state = entry.new_state

        # start_time = time()
        entry.new_state = self.list_transactions()

        old_dict = {tx.txid: tx for tx in entry.old_state}
        new_dict = {tx.txid: tx for tx in entry.new_state}
        appended_ids = set(new_dict.keys()) - set(old_dict.keys())
        removed_ids = set(old_dict.keys()) - set(new_dict.keys())

        entry.appended = [tx for tx in entry.new_state if tx.txid in appended_ids]
        entry.removed = [tx for tx in entry.old_state if tx.txid in removed_ids]

        # detect state change
        entry.modified.clear()
        for txid, old in old_dict.items():
            new = new_dict.get(txid)
            if not new:
                continue

            recognized_change = None
            if old.fee != new.fee:
                recognized_change = f"fee changed from {old.fee} to {new.fee}"
            elif type(old.chain_position) is not type(new.chain_position):
                recognized_change = (
                    f"chain position type changed from {old.chain_position} to {new.chain_position}"
                )
            elif (
                (is_local(old.chain_position) or is_local(new.chain_position))
                and isinstance(old.chain_position, bdk.ChainPosition.UNCONFIRMED)
                and isinstance(new.chain_position, bdk.ChainPosition.UNCONFIRMED)
                and old.chain_position.timestamp != new.chain_position.timestamp
            ):
                recognized_change = (
                    "unconfirmed timestamp changed from "
                    f"{old.chain_position.timestamp} to {new.chain_position.timestamp}"
                )

            if recognized_change:
                logger.info(f"Transaction {short_tx_id(txid)} {recognized_change}")
                entry.modified.append(new)

        return entry

    @instance_lru_cache(always_keep=True)
    def network(self) -> bdk.Network:
        """Return the cached bdk network for this wallet."""
        return super().network()

    def get_address_of_txout(self, txid: str, vout: int, txout: TxOut) -> str | None:
        "Cached lookup (uses (txid, vout) for lookup)"
        key = (txid, vout)

        if result := self._address_cache.get(key):
            return result

        result = self._get_address_of_txout(txout)
        self._address_cache[key] = result
        return result

    @instance_lru_cache(always_keep=True)
    def _get_address_of_txout(self, txout: TxOut) -> str | None:
        """Resolve a human-readable address for the provided txout."""
        res = robust_address_str_from_script(
            txout.script_pubkey, network=self.network(), on_error_return_hex=False
        )
        return res if res else None


class WalletInputsInconsistentError(Exception):
    pass


class ProgressLogger:
    def update(self, progress: float, message: str | None):
        """Log progress updates produced by long-running operations."""
        logger.info(str((progress, message)))


class Wallet(BaseSaveableClass, CacheManager):
    """If any bitcoin logic (ontop of bdk) has to be done, then here is the place."""

    VERSION = "0.3.3"
    known_classes = {
        **BaseSaveableClass.known_classes,
        KeyStore.__name__: KeyStore,
        UserConfig.__name__: UserConfig,
        Labels.__name__: Labels,
        Balance.__name__: Balance,
        LabelType.__name__: LabelType,
        SerializePersistence.__name__: SerializePersistence,
    }

    @staticmethod
    def cls_kwargs(
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
    ):
        return {
            "config": config,
            "loop_in_thread": loop_in_thread,
        }

    def __init__(
        self,
        id,
        descriptor_str: str,
        keystores: list[KeyStore],
        network: bdk.Network,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
        gap=20,
        labels: Labels | None = None,
        initialization_tips: list[int] | None = None,
        refresh_wallet=False,
        initial_txs: list[bdk.Transaction] | None = None,
        serialize_persistence: SerializePersistence | None = None,
        default_category: str | None = None,
        cbf_uuid: str | None = None,
        is_new_wallet=False,
        **kwargs,
    ) -> None:
        """Initialize a wallet with descriptors, keystores, and runtime context."""
        super().__init__()
        CacheManager.__init__(self)
        self.check_consistency(keystores, descriptor_str, network=network)

        self.id = id
        self.is_new_wallet = is_new_wallet
        self.network = network if network else config.network
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None
        # prevent loading a wallet into different networks
        assert self.network == config.network, (
            f"Cannot load a wallet for {self.network}, when the network {config.network} is configured"
        )
        self.gap = gap
        self.keystores = keystores
        self.config: UserConfig = config
        self.labels: Labels = labels if labels else Labels(default_category=default_category)
        # refresh dependent values
        self._initialization_tips = (
            initialization_tips if initialization_tips and not refresh_wallet else [0, 0]
        )
        self.serialize_persistence = (
            serialize_persistence if serialize_persistence else SerializePersistence()
        )
        self.cbf_uuid = cbf_uuid if cbf_uuid else uuid4().hex

        self.refresh_wallet = False
        # end refresh dependent values

        self.create_bdkwallet(convert_to_multipath_descriptor(descriptor_str, self.network))

        self.client: Client | None = None
        self._initial_txs = initial_txs if initial_txs else []
        self.clear_cache()
        if initial_txs:
            # must appear after clear_cache such that the caches are defined
            self.apply_unconfirmed_txs(txs=initial_txs)
        self.mark_all_labeled_addresses_used(include_receiving_addresses=False)

    def get_cbf_data_dir(
        self,
    ) -> Path:
        """Return the path holding Coldcard backup file data."""
        return Path(self.config.wallet_dir) / "data" / self.cbf_uuid

    def persist(self) -> None:
        """Flush wallet data to the configured persistence backend."""
        self.bdkwallet.persist(self.persister)
        self.clear_cache()

    @staticmethod
    def check_consistency(keystores: list[KeyStore], descriptor_str: str, network: bdk.Network):
        """Ensure descriptor metadata matches the provided keystore details."""

        def get_keystore(fingerprint) -> KeyStore | None:
            """Return the keystore matching the fingerprint or None."""
            for keystore in keystores:
                if keystore.fingerprint == fingerprint:
                    return keystore
                if keystore.network != network:
                    raise WalletInputsInconsistentError(
                        f"Wallet file contains different networks: {keystore.network=} != {network=}"
                    )
            return None

        if not keystores:
            raise WalletInputsInconsistentError("No keystores set")
        for _keystore in keystores:
            if not _keystore:
                raise WalletInputsInconsistentError("Keystore not set")

        descriptor_info = DescriptorInfo.from_str(descriptor_str)

        # the descriptor_info should have everything
        # except the mnemonic, label, ....
        # we check that both sources are really identical
        if len(keystores) != len(descriptor_info.spk_providers):
            raise WalletInputsInconsistentError("Length of keystore doesnt match descriptor")
        for spk_provider in descriptor_info.spk_providers:
            keystore = get_keystore(spk_provider.fingerprint)
            if not keystore:
                raise WalletInputsInconsistentError(
                    f"Keystore with fingerprint {spk_provider.fingerprint} not found"
                )
            if not keystore.is_identical_to(spk_provider):
                raise WalletInputsInconsistentError(
                    f"Keystores {keystore} is not identical to {spk_provider}"
                )

        # if mnemonic is given check derivation is correct
        for keystore in keystores:
            if keystore.mnemonic:
                xpub, fingerprint = software_signer_derive(keystore.mnemonic, keystore.key_origin, network)
                if xpub != keystore.xpub:
                    raise WalletInputsInconsistentError(
                        f"xpub {xpub} at {keystore.key_origin} doesnt match mnemonic"
                    )
                if KeyStore.format_fingerprint(fingerprint) != KeyStore.format_fingerprint(
                    keystore.fingerprint
                ):
                    raise WalletInputsInconsistentError(
                        f"fingerprint {fingerprint} at {keystore.key_origin} doesnt match mnemonic"
                    )

    def mark_labeled_addresses_used(self, address_infos: list[AddressInfoMin]):
        """Mark addresses with existing labels as used in the BDK wallet."""
        for address_info in address_infos:
            label = self.labels.get_label(address_info.address)
            if not label:
                continue
            self.bdkwallet.mark_used(keychain=address_info.keychain, index=address_info.index)

    def mark_all_labeled_addresses_used(self, include_receiving_addresses=False):
        """Mark all labeled change (and optionally receive) addresses as used."""
        self.mark_labeled_addresses_used(self._get_addresses_infos(is_change=True))
        if include_receiving_addresses:
            self.mark_labeled_addresses_used(self._get_addresses_infos(is_change=False))

    def clear_cache(self, clear_always_keep=False) -> None:
        """Reset wallet caches and propagate the clear to nested caches."""
        self.cache_dict_fulltxdetail: dict[str, FullTxDetail] = {}  # txid:FullTxDetail
        self.cache_address_to_txids: dict[str, set[str]] = defaultdict(set)  # address:[txid]

        self.clear_instance_cache(clear_always_keep=clear_always_keep)
        self.bdkwallet.clear_instance_cache(clear_always_keep=clear_always_keep)

    @instance_lru_cache()
    def _get_addresses_infos(
        self,
        is_change=False,
    ) -> list[AddressInfoMin]:
        """Return address info entries for change or receive keychains."""
        if (not is_change) and (not self.multipath_descriptor):
            return []
        return [
            AddressInfoMin(
                address=self.bdkwallet.peek_address_str(index, is_change=is_change),
                index=index,
                keychain=AddressInfoMin.is_change_to_keychain(is_change=is_change),
            )
            for index in range(0, self.tips[int(is_change)] + 1)
        ]

    @instance_lru_cache()
    def _get_addresses(
        self,
        is_change=False,
    ) -> list[str]:
        """Return the derived addresses for the selected keychain."""
        addresses_infos = self._get_addresses_infos(is_change=is_change)
        return [addresses_info.address for addresses_info in addresses_infos]

    @instance_lru_cache(always_keep=True)
    def get_mn_tuple(self) -> tuple[int, int]:
        """Return the (threshold, signer count) tuple for the wallet."""
        info = DescriptorInfo.from_str(str(self.multipath_descriptor))
        return info.threshold, len(info.spk_providers)

    def as_protowallet(self) -> ProtoWallet:
        """Return a ProtoWallet representation of the current wallet."""
        # fill the protowallet with the xpub info
        protowallet = ProtoWallet.from_descriptor(
            self.id, self.multipath_descriptor.to_string_with_secret(), network=self.network
        )
        protowallet.gap = self.gap
        protowallet.keystores = [keystore.clone() for keystore in self.keystores]

        return protowallet

    @classmethod
    def from_protowallet(
        cls,
        protowallet: ProtoWallet,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
        labels: Labels | None = None,
        initialization_tips: list[int] | None = None,
        refresh_wallet=False,
        default_category: str | None = None,
        is_new_wallet=False,
    ) -> Wallet:
        """Create a Wallet instance from a ProtoWallet definition."""
        keystores = []
        for keystore in protowallet.keystores:
            # dissallow None
            assert keystore is not None, "Cannot create wallet with None"

            if keystore.key_origin != protowallet.address_type.key_origin(config.network):
                logger.warning(f"Warning: {keystore.key_origin=} is not the default")

            keystores.append(keystore.clone())

        multipath_descriptor = protowallet.to_multipath_descriptor()
        assert multipath_descriptor is not None, (
            "Cannot create wallet, because no descriptor could be generated"
        )

        return Wallet(
            protowallet.id,
            multipath_descriptor.to_string_with_secret(),
            keystores=keystores,
            gap=protowallet.gap,
            network=protowallet.network,
            config=config,
            labels=labels,
            initialization_tips=initialization_tips,
            refresh_wallet=refresh_wallet,
            default_category=default_category,
            is_new_wallet=is_new_wallet,
            loop_in_thread=loop_in_thread,
        )

    def get_differences(self, other_wallet: Wallet) -> WalletDifferences:
        "Compares the relevant entries like keystores"
        differences = WalletDifferences()
        this = self.dump()
        other = other_wallet.dump()

        keys = [
            "id",
            "gap",
        ]
        for k in keys:
            if k not in this or k not in other:
                logger.error("This should not happen!!! Please fix")
                continue
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.NeedsRescan,
                        key=k,
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        keys = [
            "network",
        ]
        for k in keys:
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.ImpactOnAddresses,
                        key=k,
                        this_value=this[k],
                        other_value=other[k],
                    )
                )

        if (this_value := self.labels.export_bip329_jsonlines()) != (
            other_value := other_wallet.labels.export_bip329_jsonlines()
        ):
            differences.append(
                WalletDifference(
                    type=WalletDifferenceType.NoRescan,
                    key="labels",
                    this_value=this_value,
                    other_value=other_value,
                )
            )

        if (this_len := len(self.keystores)) != (other_len := len(other_wallet.keystores)):
            differences.append(
                WalletDifference(
                    type=WalletDifferenceType.ImpactOnAddresses,
                    key="keystore added/removed",
                    this_value=this_len,
                    other_value=other_len,
                )
            )

        for keystore, other_keystore in zip(self.keystores, other_wallet.keystores, strict=False):
            differences += keystore.get_differences(other_keystore, prefix=f"{keystore.label} ")

        if (this_descriptor := self.multipath_descriptor.to_string_with_secret()) != (
            other_descriptor := other_wallet.multipath_descriptor.to_string_with_secret()
        ):
            differences.append(
                WalletDifference(
                    type=WalletDifferenceType.ImpactOnAddresses,
                    key="descriptor changed",
                    this_value=this_descriptor,
                    other_value=other_descriptor,
                )
            )

        return differences

    def derives_identical_addresses(self, other_wallet: Wallet) -> bool:
        """Return True if both wallets derive the same first address."""
        return self.bdkwallet.peek_address_str(0) == other_wallet.bdkwallet.peek_address_str(0)

    def dump(self, exclude_keys: list[str] | None = None) -> dict[str, Any]:
        """Serialize the wallet state to a dictionary."""
        d = super().dump()

        keys = [
            "id",
            "gap",
            "network",
            "keystores",
            "labels",
            "refresh_wallet",
            "serialize_persistence",
            "cbf_uuid",
        ]
        for k in keys:
            if k in (exclude_keys or []):
                continue
            d[k] = self.__dict__[k]

        d["initialization_tips"] = self.tips
        d["descriptor_str"] = self.multipath_descriptor.to_string_with_secret()

        # initial_txs is a legacy way of storing transactions
        # can be removed > 1.5.0
        if (not self.serialize_persistence.change_set.tx_graph_changeset().txs) and (
            self.sorted_delta_list_transactions()
        ):
            d["initial_txs"] = [
                serialized_to_hex(tx.transaction.serialize()) for tx in self.sorted_delta_list_transactions()
            ]
        return d

    @classmethod
    def from_file(
        cls,
        filename: str,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
        password: str | None = None,
    ) -> Wallet:
        """Load a wallet from a serialized file on disk."""
        return super()._from_file(
            filename=filename,
            password=password,
            class_kwargs={"Wallet": {"config": config, "loop_in_thread": loop_in_thread}},
        )

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        """Upgrade persisted wallet data from older versions."""
        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.0"):
            if "labels" in dct:
                # no real migration. Just delete old data
                del dct["labels"]

            labels = Labels()
            for k, v in dct.get("category", {}).items():
                labels.set_addr_category(k, v)

            del dct["category"]
            dct["labels"] = labels

        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.1"):
            if dct.get("sync_tab_dump"):
                del dct["sync_tab_dump"]

        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.3"):
            if dct.get("sync_tab_dump"):
                dct["data_dump"] = {"SyncTab": dct["sync_tab_dump"]}

        if fast_version(str(dct["VERSION"])) <= fast_version("0.1.4"):
            if dct.get("data_dump"):
                if "SyncTab" in dct["data_dump"]:
                    del dct["data_dump"]["SyncTab"]

        if fast_version(str(dct["VERSION"])) <= fast_version("0.2.0"):
            if dct.get("data_dump"):
                del dct["data_dump"]

        if fast_version(str(dct["VERSION"])) < fast_version("0.3.0"):
            if dct.get("auto_opportunistic_coin_select"):
                dct["auto_opportunistic_coin_select"] = False

        if fast_version(str(dct["VERSION"])) < fast_version("0.3.1"):
            if _tips := dct.get("_tips"):
                dct["initialization_tips"] = _tips

        return super().from_dump_migration(dct=dct)

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> Self:
        """Recreate a wallet from serialized dictionary data."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        if initial_txs := dct.get("initial_txs"):
            dct["initial_txs"] = [bdk.Transaction(hex_to_serialized(tx)) for tx in initial_txs]

        return cls(**filtered_for_init(dct, cls))

    def set_gap(self, gap: int) -> None:
        """Set the wallet's address gap limit."""
        self.gap = gap

    def clone_without_peristence(
        self,
    ) -> Self:
        class_kwargs = {Wallet.__name__: {"config": self.config, "loop_in_thread": self.loop_in_thread}}
        dump = self.dump(exclude_keys=["serialize_persistence"])
        return self.from_dump(dump, class_kwargs=class_kwargs)

    def set_wallet_id(self, id: str) -> None:
        """Set the wallet id."""
        self.id = id

    def create_bdkwallet(self, multipath_descriptor: bdk.Descriptor) -> None:
        """Instantiate the underlying BDK wallet wrapper."""
        self.multipath_descriptor = multipath_descriptor
        assert multipath_descriptor.is_multipath()
        self.persister = bdk.Persister.custom(self.serialize_persistence)

        descriptor, change_descriptor = self.multipath_descriptor.to_single_descriptors()
        if self.serialize_persistence.has_descriptor():
            self.bdkwallet = BdkWallet.load(
                descriptor=descriptor,
                change_descriptor=change_descriptor,
                persister=self.persister,
                lookahead=self.calc_best_lookahead(),
            )
        else:
            self.bdkwallet = BdkWallet(
                descriptor=descriptor,
                change_descriptor=change_descriptor,
                network=self.config.network,
                persister=self.persister,
                lookahead=self.calc_best_lookahead(),
            )
        for is_change, tip in enumerate(self._initialization_tips):
            self.bdkwallet.reveal_addresses_to(
                keychain=AddressInfoMin.is_change_to_keychain(is_change=bool(is_change)), index=tip
            )
            self.persist()

    def calc_best_lookahead(self):
        """Return the preferred lookahead value for address discovery."""
        return max(BDK_DEFAULT_LOOKAHEAD, self.gap)

    def is_multisig(self) -> bool:
        """Return True if the wallet requires multiple signers."""
        return len(self.keystores) > 1

    def init_blockchain(self) -> Client | None:
        """Initialize the blockchain backend for this wallet."""
        if self.client:
            return None

        logger.info(f"Creating blockchain connection for {self.config.network_config=}")
        proxy_info = (
            ProxyInfo.parse(self.config.network_config.proxy_url)
            if self.config.network_config.proxy_url
            else None
        )

        if self.config.network_config.server_type == BlockchainType.Electrum:
            client = Client.from_electrum(
                url=self.config.network_config.electrum_url,
                use_ssl=self.config.network_config.electrum_use_ssl,
                proxy_info=proxy_info,
                loop_in_thread=self.loop_in_thread,
            )
        elif self.config.network_config.server_type == BlockchainType.Esplora:
            client = Client.from_esplora(
                url=self.config.network_config.esplora_url,
                proxy_info=proxy_info,
                loop_in_thread=self.loop_in_thread,
            )
        elif self.config.network_config.server_type == BlockchainType.RPC:
            raise NotImplementedError("RPC is not available")
            # blockchain_config = bdk.BlockchainConfig.RPC(
            #     bdk.RpcConfig(
            #         url=f"{self.config.network_config.rpc_ip}:{self.config.network_config.rpc_port}",
            #         auth=bdk.Auth.USER_PASS(
            #             username=self.config.network_config.rpc_username,
            #             password=self.config.network_config.rpc_password,
            #         ),
            #         network=self.config.network,
            #         wallet_name=self._get_uniquie_wallet_id(),
            #         sync_params=bdk.RpcSyncParams(
            #             start_script_count=0, start_time=0, force_start_time=False, poll_rate_sec=10
            #         ),
            #     )
            # )
        elif self.config.network_config.server_type == BlockchainType.CompactBlockFilter:
            client = Client.from_cbf(
                manual_peers=self.config.network_config.get_manual_peers(),
                bdkwallet=self.bdkwallet,
                gap=self.gap,
                proxy_info=proxy_info,
                data_dir=self.get_cbf_data_dir(),
                cbf_connections=self.config.network_config.cbf_connections,
                wallet_id=self.id,
                is_new_wallet=self.is_new_wallet,
                loop_in_thread=self.loop_in_thread,
            )
        else:
            raise ValueError(f"{self.config.network_config.server_type=} not allowed")

        if not client:
            raise Exception("Could not find a blockchain_config.")
        self.client = client
        return client

    def _get_uniquie_wallet_id(self) -> str:
        """Return the uniquie wallet id."""
        return f"{replace_non_alphanumeric(self.id)}-{hash_string(str(self.multipath_descriptor))}"

    def _more_than_gap_revealed_addresses(self) -> bool:
        """More than gap revealed addresses."""
        for is_change in [False, True]:
            address_info = self.reverse_search_unused_address(is_change=is_change)
            if not address_info:
                continue
            tip = self.get_tip(is_change=is_change)
            if tip >= address_info.index + self.gap:
                return True
        return False

    def trigger_sync(self) -> None:
        """Starts the update (if applicable to the client)

        At some later time (or independently of this) you have to do await update() to fetch and apply the
        update to the wallet
        """
        if not self.bdkwallet:
            logger.warning("Wallet not initialized; cannot sync.")
            return None
        if not self.client:
            logger.error(
                "This should never be called. Because init_blockchain  should be called before by qt_wallet"
            )
            self.init_blockchain()
            if not self.client:
                return None

        try:
            start_time = time()

            self.client.full_scan(self.bdkwallet.start_full_scan().build(), stop_gap=self.gap)

            elapsed = time() - start_time
            logger.debug(f"{self.id} wallet sync in {elapsed:.2f}s")
            return None
        except Exception as e:
            logger.error(f"{self.id} error syncing wallet: {e}")
            raise

    async def update(self) -> UpdateInfo | None:
        """Update the wallet using the provided update information."""
        if not self.client:
            return None
        update_info = await self.client.update()
        if not update_info:
            return None
        self._apply_update(update=update_info.update)
        return update_info

    def _apply_update(self, update: bdk.Update):
        """Apply a client update to the local wallet caches."""
        if update:
            self.bdkwallet.apply_update(update)

        self.persist()

        logger.info("Applied update")

    def forward_search_unused_address(
        self, category: str | None = None, is_change=False
    ) -> bdk.AddressInfo | None:
        """Iterate forward to find the next unused address index."""
        for index, address_str in enumerate(self._get_addresses(is_change=is_change)):
            if self.address_is_used(address_str) or self.labels.get_label(address_str):
                continue
            else:
                if (
                    not category
                    or (not self.labels.get_category_raw(address_str))
                    or (category and self.labels.get_category(address_str) == category)
                ):
                    return self.bdkwallet.peek_address(
                        index=index, keychain=AddressInfoMin.is_change_to_keychain(is_change=is_change)
                    )
        return None

    def reverse_search_unused_address(
        self,
        category: str | None = None,
        is_change=False,
    ) -> bdk.AddressInfo | None:
        """Iterate backward to find the last unused address index."""
        result: bdk.AddressInfo | None = None
        bdk_unused_addresses = self.bdkwallet.list_unused_addresses(
            AddressInfoMin.is_change_to_keychain(is_change=is_change)
        )
        bdk_unused_addresses_str = [str(a.address) for a in bdk_unused_addresses]

        for index, address_str in reversed(list(enumerate(self._get_addresses(is_change=is_change)))):
            if self.address_is_used(address_str) or self.labels.get_label(address_str):
                break
            else:
                if (
                    not category
                    or (not self.labels.get_category_raw(address_str))
                    or (
                        category
                        and (self.labels.get_category(address_str) == category)
                        and (address_str in bdk_unused_addresses_str)
                    )
                ):
                    result = self.bdkwallet.peek_address(
                        index=index,
                        keychain=AddressInfoMin.is_change_to_keychain(is_change=is_change),
                    )

        return result

    def get_unused_category_address(self, category: str | None, is_change=False) -> bdk.AddressInfo:
        """Return an unused address and record its category."""
        if category is None:
            category = self.labels.get_default_category()

        address_info = self.reverse_search_unused_address(category=category, is_change=is_change)
        if not address_info:
            address_info = self.get_address(force_new=True, is_change=is_change)

        self.labels.set_addr_category(str(address_info.address), category, timestamp="old")
        return address_info

    def get_force_new_address(self, is_change) -> bdk.AddressInfo:
        """Force creation of a new receiving address entry."""
        keychain_kind = AddressInfoMin.is_change_to_keychain(is_change=is_change)
        address_info = self.bdkwallet.reveal_next_address(keychain=keychain_kind)
        self.persist()

        logger.info(f"advanced_tip to {address_info.index}  , is_change={is_change}")
        address = str(address_info.address)
        if address in self.labels.data:
            # if the address is already labeled/categorized, then advance forward
            return self.get_force_new_address(is_change=is_change)

        return address_info

    def get_address(self, force_new=False, is_change=False) -> bdk.AddressInfo:
        "Gives an unused address reverse searched from the tip"
        if force_new:
            return self.get_force_new_address(is_change=is_change)

        # try finding an unused one
        address_info = self.reverse_search_unused_address(is_change=is_change)
        if address_info:
            return address_info

        # create a new address
        return self.get_force_new_address(is_change=is_change)

    def get_output_addresses(self, transaction: bdk.Transaction) -> list[str]:
        # print(f'Getting output addresses for txid {transaction.txid}')
        """Return destination addresses for the given transaction."""
        txid = str(transaction.compute_txid())
        output_addresses = [
            self.bdkwallet.get_address_of_txout(txid=txid, vout=vout, txout=TxOut.from_bdk(output))
            for vout, output in enumerate(transaction.output())
        ]
        return [a for a in output_addresses if a]

    @time_logger
    def fill_commonly_used_caches_min(self) -> None:
        """Prime essential caches for quick wallet lookups."""
        self.clear_cache()
        self.get_addresses()
        self.set_categories_of_used_addresses()

    @instance_lru_cache()
    def get_txs(self) -> dict[str, TransactionDetails]:
        """Return a mapping from transaction ID to details."""
        return {tx.txid: tx for tx in self.sorted_delta_list_transactions()}

    @instance_lru_cache()
    def get_tx(self, txid: str) -> TransactionDetails | None:
        """Return transaction details for the given txid."""
        return self.get_txs().get(txid)

    def list_input_bdk_addresses(self, transaction: bdk.Transaction) -> list[str]:
        """Return a list of input BDK addresses."""
        addresses = []
        for tx_in in transaction.input():
            address = self.get_address_of_outpoint(OutPoint.from_bdk(tx_in.previous_output))
            if address:
                addresses.append(address)
        return addresses

    def list_tx_addresses(self, transaction: bdk.Transaction) -> dict[str, list[str]]:
        """Return a list of transaction addresses."""
        return {
            "in": self.list_input_bdk_addresses(transaction),
            "out": self.get_output_addresses(transaction),
        }

    def list_txids_with_change_outputs_without_wallet_inputs(self) -> list[str]:
        """Return txids where change outputs exist without wallet-controlled inputs."""

        suspicious_txids: list[str] = []

        for fulltxdetail in self.get_dict_fulltxdetail().values():
            has_change_output = False
            for python_utxo in fulltxdetail.outputs.values():
                if not python_utxo:
                    continue
                if not python_utxo.address:
                    continue
                address_info = self.is_my_address_with_peek(python_utxo.address)
                if not address_info:
                    continue
                self.advance_tip_if_necessary(is_change=address_info.is_change(), target=address_info.index)
                if address_info.is_change():
                    has_change_output = True
                    break

            if not has_change_output:
                continue

            has_wallet_input = False
            for python_utxo in fulltxdetail.inputs.values():
                if not python_utxo:
                    continue
                if not python_utxo.address:
                    continue
                address_info = self.is_my_address_with_peek(python_utxo.address)
                if address_info:
                    has_wallet_input = True
                    break

            if not has_wallet_input:
                suspicious_txids.append(fulltxdetail.txid)

        return suspicious_txids

    def transaction_related_to_my_addresses(self, transaction: bdk.Transaction) -> bool:
        """Return True if the transaction involves wallet addresses."""
        addresses = self.get_addresses()
        for tx_addresses in self.list_tx_addresses(transaction).values():
            if set(addresses).intersection(set([a for a in tx_addresses if a])):
                return True

        return False

    def used_address_tip(self, is_change: bool) -> int:
        """Return the last used index for receive and change chains."""

        def reverse_search_used(tip_index) -> int:
            """Reverse the search used."""
            for i in reversed(range(tip_index)):
                addresses = self._get_addresses(is_change=is_change)
                if len(addresses) - 1 < i:
                    continue
                if self.address_is_used(addresses[i]):
                    return i
            return 0

        return reverse_search_used(self.tips[int(is_change)])

    def get_tip(self, is_change: bool) -> int:
        """Return the discovery tip for the given keychain."""
        keychain_kind = AddressInfoMin.is_change_to_keychain(is_change=is_change)
        derivation_index = self.bdkwallet.derivation_index(keychain=keychain_kind)
        if derivation_index is None:
            self.advance_tip_if_necessary(is_change=is_change, target=0)
            return 0
        return derivation_index

    def advance_tip_if_necessary(self, is_change: bool, target: int) -> list[bdk.AddressInfo]:
        """Advance address tips when additional addresses are revealed."""
        revealed_addresses: list[bdk.AddressInfo] = []
        keychain_kind = AddressInfoMin.is_change_to_keychain(is_change=is_change)
        max_derived_index = self.bdkwallet.derivation_index(keychain=keychain_kind)

        if max_derived_index is None or max_derived_index < target:
            revealed_addresses += self.bdkwallet.reveal_addresses_to(keychain=keychain_kind, index=target)
            self.persist()
            logger.info(f"{self.id} Revealed addresses up to {keychain_kind=} {target=}")
        return revealed_addresses

    def advance_tip_to_address(self, address: str, forward_search=1000) -> AddressInfoMin | None:
        """Looks for the address and advances the tip to this address."""
        address_info_min = self.is_my_address_with_peek(
            address=address, peek_change_ahead=forward_search, peek_receive_ahead=forward_search
        )
        if not address_info_min:
            return None

        if address_info_min.index <= self.tips[int(address_info_min.is_change())]:
            # no need to advance tip
            return None

        is_change = address_info_min.is_change()
        self.advance_tip_if_necessary(is_change=is_change, target=address_info_min.index)

        return address_info_min

    @property
    def tips(self) -> list[int]:
        """Return cached address tips for receive and change chains."""
        return [self.get_tip(b) for b in [False, True]]

    def get_receiving_addresses(self) -> list[str]:
        """Return derived receiving addresses up to the discovery tip."""
        return self._get_addresses(is_change=False)

    def get_change_addresses(self) -> list[str]:
        """Return derived change addresses up to the discovery tip."""
        return self._get_addresses(is_change=True)

    # do not cach this!!! it will lack behind when a psbt extends the change tip
    def get_addresses(self) -> list[str]:
        "Gets the combined list of receiving and change addresses"
        # note: overridden so that the history can be cleared.
        # addresses are ordered based on derivation
        out = self.get_receiving_addresses().copy()
        out += self.get_change_addresses().copy()
        return out

    def is_change(self, address: str) -> bool:
        """Return True if the address belongs to the change keychain."""
        return address in self.get_change_addresses()

    def is_receive(self, address: str) -> bool:
        """Return True if the address belongs to the receive keychain."""
        return address in self.get_receiving_addresses()

    def _get_address_info_min(self, address: str, keychain: bdk.KeychainKind) -> AddressInfoMin | None:
        """Return the change flag and index for a known address."""
        if keychain == bdk.KeychainKind.EXTERNAL:
            addresses = self.get_receiving_addresses()
            if address in addresses:
                return AddressInfoMin(keychain=keychain, index=addresses.index(address), address=address)
        else:
            addresses = self.get_change_addresses()
            if address in addresses:
                return AddressInfoMin(keychain=keychain, index=addresses.index(address), address=address)
        return None

    def get_address_info_min(self, address: str) -> AddressInfoMin | None:
        """Return minimal address information for the given string."""
        info_min = self._get_address_info_min(address, bdk.KeychainKind.EXTERNAL)
        if info_min:
            return info_min

        info_min = self._get_address_info_min(address, bdk.KeychainKind.INTERNAL)
        if info_min:
            return info_min

        return None

    def txo_of_outpoint(self, outpoint: bdk.OutPoint) -> PythonUtxo | None:
        """Return a PythonUtxo for the provided outpoint."""
        txo_dict = self.get_all_txos_dict()
        outpoint_str = str(OutPoint.from_bdk(outpoint))
        if outpoint_str in txo_dict:
            return txo_dict[outpoint_str]
        return None

    @instance_lru_cache()
    def get_address_balances(self) -> defaultdict[str, Balance]:
        """Converts the known utxos into a dict of addresses and their balance."""

        balances: defaultdict[str, Balance] = defaultdict(Balance)
        utxos = self.bdkwallet.list_output()
        missing_outpoint: OutPoint | None = None

        for _ in range(NUM_RETRIES_get_address_balances):  # initial attempt + retries with cleared caches
            for utxo in utxos:
                if utxo.is_spent:
                    continue
                outpoint = OutPoint.from_bdk(utxo.outpoint)
                txout = self.get_txout_of_outpoint(outpoint)
                if not txout:
                    # Stale caches (e.g. after mempool eviction) – refresh once and re-fetch.
                    logger.warning("This should not happen. Most likely it is due to outdated caches.")
                    missing_outpoint = outpoint
                    self.clear_cache(clear_always_keep=True)
                    utxos = self.bdkwallet.list_output()
                    break

                address = self.bdkwallet.get_address_of_txout(
                    txout=txout, txid=outpoint.txid_str, vout=outpoint.vout
                )
                if address is None:
                    continue

                outpoint_tx_details = self.get_tx(outpoint.txid_str)
                if outpoint_tx_details and isinstance(
                    outpoint_tx_details.chain_position, bdk.ChainPosition.CONFIRMED
                ):
                    balances[address].confirmed += txout.value.to_sat()
                else:
                    balances[address].untrusted_pending += txout.value.to_sat()
            else:
                return balances

        txid = missing_outpoint.txid if missing_outpoint else "unknown"
        raise InconsistentBDKState(f"{txid} not present in transaction details")

    @instance_lru_cache()
    def get_addr_balance(self, address: str) -> Balance:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]

    def get_involved_txids(self, address: str) -> set[str]:
        # this also fills self.cache_address_to_txids
        """Return transaction IDs that involve the provided addresses."""
        self.get_dict_fulltxdetail()
        return self.cache_address_to_txids.get(address, set())

    def set_categories_of_used_addresses(self):
        """Set address categories for used outputs."""
        for utxo in self.get_all_txos_dict(include_not_mine=False).values():
            if not self.labels.get_category_raw(utxo.address):
                categories = self.get_categories_for_txid(utxo.outpoint.txid_str)
                if not categories:
                    continue
                category = categories[0]
                self.labels.set_addr_category(ref=utxo.address, category=category, timestamp="old")
                logger.info(f"Set {category=} for address {short_address(utxo.address)}")

    @instance_lru_cache()
    @time_logger
    def get_dict_fulltxdetail(self) -> dict[str, FullTxDetail]:
        """
        Createa a map of txid : to FullTxDetail

        Returns:
            FullTxDetail
        """
        start_time = time()
        delta_txs = self.bdkwallet.list_delta_transactions(access_marker="get_dict_fulltxdetail")
        cache_dict_fulltxdetail = self.cache_dict_fulltxdetail.copy()

        # if transactions were removed (reorg or other), then recalculate everything
        if delta_txs.removed or not cache_dict_fulltxdetail:
            cache_dict_fulltxdetail = {}
            txs = delta_txs.new_state
        else:
            txs = delta_txs.appended + delta_txs.modified

        def append_dicts(txid, python_utxos: Iterable[PythonUtxo | None]) -> None:
            """Append transaction data into the accumulation dictionaries."""
            for python_utxo in python_utxos:
                if not python_utxo:
                    continue
                self.cache_address_to_txids[python_utxo.address].add(txid)

        def process_outputs(tx: TransactionDetails) -> tuple[str, FullTxDetail]:
            """Process outputs while compiling transaction details."""
            fulltxdetail = FullTxDetail.fill_received(tx, self.bdkwallet.get_address_of_txout)
            if fulltxdetail.txid in cache_dict_fulltxdetail:
                if not tx.transaction.is_coinbase():
                    logger.error(f"Trying to add a tx with txid {fulltxdetail.txid} twice.")
            return fulltxdetail.txid, fulltxdetail

        def process_inputs(tx: TransactionDetails) -> tuple[str, FullTxDetail]:
            "this must be done AFTER process_outputs"
            txid = tx.txid
            fulltxdetail = cache_dict_fulltxdetail[txid]
            fulltxdetail.fill_inputs(cache_dict_fulltxdetail)
            return txid, fulltxdetail

        key_value_pairs = list(map(process_outputs, txs))

        cache_dict_fulltxdetail.update(key_value_pairs)
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, list(fulltxdetail.outputs.values()))

        # speed test for wallet 600 transactions (with many inputs each) without profiling:
        # map : 2.714s
        # for loop:  2.76464
        # multithreading : 6.3021s
        # threadtable_batched: 4.1 s , this should perform best, however bdk is
        #                           probably the bottleneck and not-multithreading capable
        key_value_pairs = list(map(process_inputs, txs))
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, fulltxdetail.inputs.values())

        if txs:
            logger.debug(f"get_dict_fulltxdetail  with {len(txs)} txs in {time() - start_time}")

        self.cache_dict_fulltxdetail = cache_dict_fulltxdetail
        return self.cache_dict_fulltxdetail

    @instance_lru_cache(always_keep=False)
    def get_all_txos_dict(self, include_not_mine=False) -> dict[str, PythonUtxo]:
        "Returns {str(outpoint) : python_utxo}"
        dict_fulltxdetail = self.get_dict_fulltxdetail()
        my_addresses = self.get_addresses()

        txos: dict[str, PythonUtxo] = {}
        for fulltxdetail in dict_fulltxdetail.values():
            for python_utxo in fulltxdetail.outputs.values():
                if include_not_mine or (python_utxo.address in my_addresses):
                    if str(python_utxo.outpoint) in txos:
                        logger.error(
                            f"{str(python_utxo.outpoint)} already present in txos, "
                            "meaning dict_fulltxdetail has outpoints occuring multiple times"
                        )
                    txos[str(python_utxo.outpoint)] = python_utxo
        return txos

    def get_all_utxos(self, include_not_mine=False) -> list[PythonUtxo]:
        """Return all spendable UTXOs from the wallet."""
        return [
            txo
            for txo in self.get_all_txos_dict(include_not_mine=include_not_mine).values()
            if not txo.is_spent_by_txid
        ]

    @instance_lru_cache()
    def address_is_used(self, address: str) -> bool:
        """Check if any tx had this address as an output."""
        return bool(self.get_involved_txids(address))

    def get_address_path_str(self, address: str) -> str:
        """Return the descriptor path string for an address."""
        address_info = self.get_address_info_min(address)
        if not address_info:
            return ""

        return address_descriptor_from_multipath_descriptor(
            descriptor=self.multipath_descriptor, kind=address_info.keychain, address_index=address_info.index
        )

    def get_input_and_output_txo_dict(self, txid: str) -> dict[TxoType, list[PythonUtxo]]:
        """Return dictionaries of input and output TXOs for a transaction."""
        result: dict[TxoType, list[PythonUtxo]] = {TxoType.OutputTxo: [], TxoType.InputTxo: []}

        fulltxdetail = self.get_dict_fulltxdetail().get(txid)
        if not fulltxdetail:
            return result

        result[TxoType.OutputTxo] = [python_utxo for python_utxo in fulltxdetail.outputs.values()]
        result[TxoType.InputTxo] = [
            python_utxo for python_utxo in fulltxdetail.inputs.values() if python_utxo
        ]
        return result

    def get_output_txos(self, txid: str) -> list[PythonUtxo]:
        """Return TXOs created by the given transaction."""
        return self.get_input_and_output_txo_dict(txid)[TxoType.OutputTxo]

    def get_input_txos(self, txid: str) -> list[PythonUtxo]:
        """Return TXOs spent by the given transaction."""
        return self.get_input_and_output_txo_dict(txid)[TxoType.InputTxo]

    def get_categories_for_txid(self, txid: str) -> list[str]:
        """Return label categories associated with a transaction."""
        input_and_output_txo_dict = self.get_input_and_output_txo_dict(txid)
        python_txos = sum(input_and_output_txo_dict.values(), [])
        if not python_txos:
            return []

        categories: list[str] = unique_elements(
            clean_list([self.labels.get_category_raw(python_utxo.address) for python_utxo in python_txos])
        )

        if not categories:
            categories = [self.labels.get_default_category()]
        return categories

    def get_label_for_address(self, address: str, autofill_from_txs=True, verbose_label=False) -> str:
        """Return the stored label for an address."""
        stored_label = self.labels.get_label(address, "")
        if stored_label:
            return stored_label
        label = ""

        if autofill_from_txs:
            txids = self.get_involved_txids(address)

            if verbose_label:
                tx_labels = [
                    (self.get_label_for_txid(txid, autofill_from_addresses=False) or txid) for txid in txids
                ]
                label = translate("wallet", "") + "Funded by : " + ", ".join(tx_labels)
            else:
                tx_labels = clean_list(
                    [(self.get_label_for_txid(txid, autofill_from_addresses=False)) for txid in txids]
                )
                label = ", ".join(tx_labels)

        return label

    def get_label_for_txid(self, txid: str, autofill_from_addresses=True, verbose_label=False) -> str:
        """Return the stored label for a transaction."""
        stored_label = self.labels.get_label(txid, "")
        if stored_label:
            return stored_label

        label = ""

        if autofill_from_addresses:
            python_utxos = self.get_output_txos(txid)
            if not python_utxos:
                return label

            if verbose_label:
                address_labels = [
                    (
                        self.get_label_for_address(python_utxo.address, autofill_from_txs=False)
                        or python_utxo.address
                    )
                    for python_utxo in python_utxos
                ]
                label = translate("wallet", "") + "Sending to addresses: " + ", ".join(address_labels)
            else:
                address_labels = clean_list(
                    [
                        (self.get_label_for_address(python_utxo.address, autofill_from_txs=False))
                        for python_utxo in python_utxos
                    ]
                )
                label = ", ".join(address_labels)

        return label

    def get_balance(self) -> Balance:
        """Return the wallet balance summary."""
        return Balance.from_bdk(balance=self.bdkwallet.balance())

    def get_txo_name(self, utxo: PythonUtxo) -> str:
        """Return a human-readable name for a TXO."""
        tx = self.get_tx(utxo.outpoint.txid_str)
        txid = tx.txid if tx else translate("wallet", "Unknown")
        return f"{txid}:{utxo.outpoint.vout}"

    def get_height_no_cache(self) -> int:
        """Query the chain height from the blockchain backend."""
        return self.bdkwallet.latest_checkpoint().height

    @instance_lru_cache()
    # caching is crucial, because this function is called vor every row in the hist table
    def get_height(self) -> int:
        """Return the current chain height, using cache when possible."""
        return self.get_height_no_cache()

    def opportunistic_coin_select(
        self, utxos: list[PythonUtxo], total_sent_value: int, opportunistic_merge_utxos: bool
    ) -> UtxosForInputs:
        """Perform an opportunistic coin selection pass."""

        def utxo_value(utxo: PythonUtxo) -> int:
            """Return the value of a candidate UTXO."""
            return utxo.value

        def is_outpoint_in_list(outpoint, utxos) -> bool:
            """Return True if the outpoint appears in the provided list."""
            outpoint = OutPoint.from_bdk(outpoint)
            for utxo in utxos:
                if outpoint == OutPoint.from_bdk(utxo.outpoint):
                    return True
            return False

        # 1. select random utxos until >= total_sent_value
        utxos = list(utxos).copy()
        random.shuffle(utxos)
        selected_utxos = []
        selected_value = 0
        opportunistic_merging_utxos = []
        for utxo in utxos:
            selected_value += utxo.value
            selected_utxos.append(utxo)
            if selected_value >= total_sent_value:
                break
        logger.debug(f"{len(selected_utxos)=}")

        # 2. opportunistically  add additional outputs for merging
        if opportunistic_merge_utxos:
            non_selected_utxos = [
                utxo for utxo in utxos if not is_outpoint_in_list(utxo.outpoint, selected_utxos)
            ]

            # never choose more than half of all remaining outputs
            # on average this exponentially merges the utxos
            # and never more than 200 additional utoxs
            number_of_opportunistic_outpoints = min(
                200,
                (
                    np.random.randint(0, len(non_selected_utxos) // 2)
                    if len(non_selected_utxos) // 2 > 0
                    else 0
                ),
            )

            # here we choose the smalles utxos first
            # Alternatively one could also choose them from the random order
            opportunistic_merging_utxos = sorted(non_selected_utxos, key=utxo_value)[
                :number_of_opportunistic_outpoints
            ]
            logger.debug(
                f"Selected {len(opportunistic_merging_utxos)} additional opportunistic outpoints "
                f"with small values (so total ={len(selected_utxos) + len(opportunistic_merging_utxos)})"
            )

        # now shuffle again the final utxos
        final_utxo_selection = selected_utxos + opportunistic_merging_utxos
        random.shuffle(final_utxo_selection)
        return UtxosForInputs(
            utxos=final_utxo_selection,
            included_opportunistic_merging_utxos=opportunistic_merging_utxos,
            spend_all_utxos=True,
        )

    def handle_opportunistic_merge_utxos(self, txinfos: TxUiInfos) -> UtxosForInputs:
        "This does the initial coin selection if opportunistic_merge_utxos"
        utxos_for_input = UtxosForInputs(
            list(txinfos.utxo_dict.values()), spend_all_utxos=txinfos.spend_all_utxos
        )

        if not utxos_for_input.utxos:
            logger.warning("No utxos or categories for coin selection")
            return utxos_for_input

        total_sent_value = sum(recipient.amount for recipient in txinfos.recipients)

        # check if you should spend all utxos, then there is no coin selection necessary
        if utxos_for_input.spend_all_utxos:
            return utxos_for_input
        # if more opportunistic_merge should be done, than I have to use my coin selection
        elif txinfos.opportunistic_merge_utxos:
            # use my coin selection algo, which uses more utxos than needed
            return self.opportunistic_coin_select(
                utxos=utxos_for_input.utxos,
                total_sent_value=total_sent_value,
                opportunistic_merge_utxos=txinfos.opportunistic_merge_utxos,
            )
        else:
            # otherwise let the bdk wallet decide on the minimal coins to be spent, out of the utxos
            return UtxosForInputs(utxos=utxos_for_input.utxos, spend_all_utxos=False)

    def is_my_address(self, address: str) -> bool:
        """Return True if the address belongs to this wallet."""
        return address in self.get_addresses()

    @instance_lru_cache()
    def get_address_dict_with_peek(
        self, peek_receive_ahead: int = 1000, peek_change_ahead: int = 1000
    ) -> dict[str, AddressInfoMin]:
        """Return metadata for an address by peeking ahead if needed."""
        start_time = time()
        addresses: dict[str, AddressInfoMin] = {}
        for _is_change, _peek_ahead in [(False, peek_receive_ahead), (True, peek_change_ahead)]:
            address_infos = self._get_addresses_infos(is_change=_is_change)
            addresses.update({address_info.address: address_info for address_info in address_infos})
            tip = address_infos[-1].index if address_infos else 0

            for index in range(tip + 1, tip + 1 + _peek_ahead):
                address_info = self.bdkwallet.peek_address(
                    keychain=AddressInfoMin.is_change_to_keychain(is_change=_is_change), index=index
                )
                address = str(address_info.address)
                addresses[address] = AddressInfoMin(
                    address=address, index=address_info.index, keychain=address_info.keychain
                )
        logger.debug(f"{self.id} get_address_dict_with_peek  in {time() - start_time}s")
        return addresses

    def is_my_address_with_peek(
        self, address: str, peek_receive_ahead: int = 1000, peek_change_ahead: int = 1000
    ) -> AddressInfoMin | None:
        """Return True if the address belongs to this wallet using peek."""
        if not address:
            return None
        return self.get_address_dict_with_peek(
            peek_receive_ahead=peek_receive_ahead, peek_change_ahead=peek_change_ahead
        ).get(address)

    def determine_recipient_category(self, utxos: Iterable[PythonUtxo]) -> str:
        "Returns the first category it can determine from the addreses or txids"
        address_categories = clean_list(
            [self.labels.get_category_raw(utxo.address) for utxo in utxos],
        )

        if address_categories:
            category = address_categories[0]
            if len(set(address_categories)) >= 2:
                logger.warning(
                    f"Selecting category {category} out of {set(address_categories)} for the output addresses"
                )

            return category

        tx_id_categories = clean_list(
            sum(
                [list(self.get_categories_for_txid(utxo.outpoint.txid_str)) for utxo in utxos],
                [],
            )
        )
        if tx_id_categories:
            category = tx_id_categories[0]
            if len(address_categories) >= 2:
                logger.warning(
                    f"Selecting category {category} out of {tx_id_categories} for the output addresses"
                )

            return category

        logger.warning("determine_recipient_category returns  default category")
        return self.labels.get_default_category()

    def create_bump_fee_psbt(self, txinfos: TxUiInfos) -> TxBuilderInfos:
        """Create an RBF PSBT with an increased fee."""
        if txinfos.replace_tx is None:
            raise Exception("Cannot replace tx without txid")
        if txinfos.fee_rate is None:
            raise Exception("Cannot bump tx without feerate")

        # check inputs consistent
        prev_outpoints = [
            str(OutPoint.from_bdk(prev_out.previous_output)) for prev_out in txinfos.replace_tx.input()
        ]
        utxos = [utxo for utxo in txinfos.utxo_dict.values() if str(utxo.outpoint) in prev_outpoints]
        assert len(prev_outpoints) == len(utxos), (
            f"Inconsistent TxUiInfos:Not all utxos could be found for the {len(prev_outpoints)} inputs"
        )
        utxos_for_input = UtxosForInputs(utxos=utxos, spend_all_utxos=txinfos.spend_all_utxos)

        # check recipients    consistent
        recipient_addresses = [r.address for r in txinfos.recipients]
        assert len(txinfos.replace_tx.output()) >= len(txinfos.recipients), (
            "Inconsistent TxUiInfos:too many recipients"
        )
        for output in txinfos.replace_tx.output():
            output_address = str(bdk.Address.from_script(script=output.script_pubkey, network=self.network))
            if output_address in self.get_receiving_addresses():
                assert output_address in recipient_addresses, (
                    "Inconsistent TxUiInfos: Outpoint Address not in recipient list"
                )

        try:
            tx_builder = bdk.BumpFeeTxBuilder(
                txid=txinfos.replace_tx.compute_txid(), fee_rate=FeeRate.from_float_sats_vB(txinfos.fee_rate)
            )
            # if the fee is too low bdk will throw an exception here
            psbt = tx_builder.finish(self.bdkwallet)
        except bdk.CreateTxError.FeeRateTooLow as e:
            fee = Satoshis(value=int(e.required), network=self.network).str_with_unit(
                color_formatting=None, btc_symbol=self.config.bitcoin_symbol.value
            )
            raise Exception(f"Fee below the allowed minimum fee = {fee}") from e
        except Exception as e:
            raise e

        self.persist()

        recipient_category = self.determine_recipient_category(utxos_for_input.utxos)

        builder_infos = TxBuilderInfos(
            recipients=txinfos.recipients,
            utxos_for_input=utxos_for_input,
            psbt=psbt,
            recipient_category=recipient_category,
            fee_rate=txinfos.fee_rate,
        )
        return builder_infos

    def create_psbt(self, txinfos: TxUiInfos) -> TxBuilderInfos:
        """Create a PSBT from the provided builder information."""
        if txinfos.replace_tx:
            return self.create_bump_fee_psbt(txinfos=txinfos)

        recipients = txinfos.recipients.copy()

        # bdk only saves the last drained address
        # therefore we rely on the estimation of
        # recipient.amount to set the correct amount
        # the last set checked_max_amount will get what is left over.
        #  that could be a little more or a little less than the estimated recipient.amount

        # this has the positive side effect, that if spend_all_utxos was set,
        # the previously chosen drain_to(change address), because of spend_all_utxos will be overrwritten
        max_amount_recipients = [
            recipient for recipient in txinfos.recipients if recipient.checked_max_amount
        ]
        selected_max_amount_recipient = max_amount_recipients[-1] if max_amount_recipients else None

        if selected_max_amount_recipient:
            txinfos.spend_all_utxos = True

        tx_builder = bdk.TxBuilder()
        # without add_global_xpubs some Hardware signers cannot recognize that they are part of this psbt
        # https://github.com/bitcoindevkit/bdk-ffi/issues/572
        tx_builder = tx_builder.add_global_xpubs()
        if txinfos.fee_rate is not None:
            tx_builder = tx_builder.fee_rate(FeeRate.from_float_sats_vB(txinfos.fee_rate))

        utxos_for_input = self.handle_opportunistic_merge_utxos(txinfos)
        selected_outpoints = [OutPoint.from_bdk(utxo.outpoint) for utxo in utxos_for_input.utxos]
        set_selected_outpoints = set(selected_outpoints)
        # bdk doesnt seem to shuffle the inputs, so I do it here
        random.shuffle(selected_outpoints)

        if utxos_for_input.spend_all_utxos:
            # spend_all_utxos requires using add_utxo
            tx_builder = tx_builder.manually_selected_only()
            # add coins that MUST be spend
            for outpoint in selected_outpoints:
                tx_builder = tx_builder.add_utxo(outpoint)
                # TODO no add_foreign_utxo yet: see https://github.com/bitcoindevkit/bdk-ffi/issues/329 https://docs.rs/bdk/latest/bdk/wallet/tx_builder/struct.TxBuilder.html#method.add_foreign_utxo
            # ensure all utxos are spent (so we get a change address)
            tx_builder = tx_builder.drain_to(self.get_address(is_change=True).address.script_pubkey())
        else:
            # exclude all other coins, to leave only selected_outpoints to choose from
            unspendable_outpoints = [
                utxo.outpoint
                for utxo in self.bdkwallet.list_output()
                if OutPoint.from_bdk(utxo.outpoint) not in set_selected_outpoints
            ]
            tx_builder = tx_builder.unspendable(unspendable_outpoints)

        for recipient in txinfos.recipients:
            if recipient == selected_max_amount_recipient:
                tx_builder = tx_builder.drain_to(
                    bdk.Address(recipient.address, network=self.network).script_pubkey()
                )
            else:
                tx_builder = tx_builder.add_recipient(
                    bdk.Address(recipient.address, network=self.network).script_pubkey(),
                    bdk.Amount.from_sat(recipient.amount),
                )

        start_time = time()
        psbt = tx_builder.finish(self.bdkwallet)
        self.persist()
        logger.debug(f"{self.id} tx_builder.finish  in {time() - start_time}s")

        # inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()

        logger.info(f"Created PSBT {str(psbt.extract_tx().compute_txid())[:4]=}")
        fee_rate = self.bdkwallet.calculate_fee_rate(psbt.extract_tx())
        if fee_rate is not None:
            logger.info(f"psbt fee after finalized {FeeRate.from_fee_rate(fee_rate).to_sats_per_vb()}")

        recipient_category = self.determine_recipient_category(utxos_for_input.utxos)

        builder_infos = TxBuilderInfos(
            recipients=recipients,
            utxos_for_input=utxos_for_input,
            psbt=psbt,
            recipient_category=recipient_category,
            fee_rate=txinfos.fee_rate,
        )

        tx = builder_infos.psbt.extract_tx()
        self.set_addresses_category_if_unused(
            recipient_category=recipient_category,
            addresses=[
                self.bdkwallet.get_address_of_txout(
                    txout=TxOut.from_bdk(txout), txid=str(tx.compute_txid()), vout=vout
                )
                for vout, txout in enumerate(tx.output())
            ],
        )
        self._set_recipient_address_labels(builder_infos.recipients)
        self._set_labels_for_change_outputs(builder_infos)

        # self._label_txid_by_recipient_labels(builder_infos)
        return builder_infos

    def set_addr_category_if_unused(self, category: str, address: str) -> str | None:
        "sets the address category, if the category was unassigned"
        if address and self.is_my_address(address) and not self.address_is_used(address):
            # old self.labels.get_category(address, default_value="not_set_category") == "not_set_category":
            self.labels.set_addr_category(address, category=category, timestamp="old")
            return address
        return None

    def set_addresses_category_if_unused(
        self, recipient_category: str | None, addresses: Iterable[str | None]
    ) -> list[str]:
        """Assign categories to addresses when they are unused."""
        assigned_addresses: list[str] = []
        if not recipient_category:
            return assigned_addresses
        for address in addresses:
            if address and (
                assigned_address := self.set_addr_category_if_unused(
                    category=recipient_category, address=address
                )
            ):
                assigned_addresses.append(assigned_address)
        return assigned_addresses

    def _set_recipient_address_labels(self, recipients: list[Recipient]) -> None:
        # set label for the recipient output
        """Assign labels to recipient addresses on a transaction."""
        for recipient in recipients:
            # this does not include the change output
            if recipient.label:  # it doesnt have to be my address (in fact most often it is not)
                self.labels.set_addr_label(recipient.address, recipient.label, timestamp="now")

    def _set_labels_for_change_outputs(self, infos: TxBuilderInfos) -> None:
        # add a label for the change output
        """Assign labels to detected change outputs."""
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        if not labels:
            return
        tx = infos.psbt.extract_tx()
        txid = str(tx.compute_txid())
        for vout, txout in enumerate(tx.output()):
            address = self.bdkwallet.get_address_of_txout(txout=TxOut.from_bdk(txout), txid=txid, vout=vout)
            if not address:
                continue
            if not self.is_my_address(address):
                continue
            if self.config.auto_label_change_addresses and self.is_change(address):
                change_label = translate("wallet", "Change of:") + " " + ", ".join(labels)
                self.labels.set_addr_label(address, change_label, timestamp="now")

    def _label_txid_by_recipient_labels(self, infos: TxBuilderInfos) -> None:
        """Propagate recipient labels to the transaction ID."""
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        if labels:
            tx_label = translate("wallet", "Send to:") + " " + ",".join(labels)
            self.labels.set_tx_label(infos.psbt.extract_tx().compute_txid(), tx_label, timestamp="now")

    def on_addresses_updated(self, update_filter: UpdateFilter) -> None:
        """Checks if the tip reaches the addresses and updated the tips if necessary
        (This is especially relevant if a psbt creates a new change address)"""
        self.clear_method(self._get_addresses)
        self.clear_method(self._get_addresses_infos)
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        not_indexed_addresses = set(update_filter.addresses) - set(self.get_addresses())
        for not_indexed_address in not_indexed_addresses:
            self.advance_tip_to_address(not_indexed_address)

    @instance_lru_cache(always_keep=True)
    def get_txout_of_outpoint(self, outpoint: OutPoint) -> TxOut | None:
        """Return the BDK TxOut for a given outpoint."""
        tx_details = self.get_tx(outpoint.txid_str)
        if not tx_details or not tx_details.transaction:
            return None

        for i, txout in enumerate(tx_details.transaction.output()):
            if i == outpoint.vout:
                return TxOut.from_bdk(txout)
        return None

    def get_address_of_outpoint(self, outpoint: OutPoint) -> str | None:
        """Return the address referenced by the outpoint."""
        txout = self.get_txout_of_outpoint(outpoint)
        if not txout:
            return None
        return self.bdkwallet.get_address_of_txout(txout=txout, txid=outpoint.txid_str, vout=outpoint.vout)

    def get_python_txo(self, outpoint_str: str) -> PythonUtxo | None:
        """Return a PythonUtxo representation for the outpoint."""
        all_txos_dict = self.get_all_txos_dict()
        return all_txos_dict.get(outpoint_str)

    def get_conflicting_python_txos(self, input_outpoints: Iterable[OutPoint]) -> list[PythonUtxo]:
        """Return PythonUtxos that conflict with the given outpoints."""
        conflicting_python_utxos = []

        txos_dict = self.get_all_txos_dict()
        for input_outpoint in input_outpoints:
            if str(input_outpoint) in txos_dict:
                python_utxo = txos_dict[str(input_outpoint)]
                if python_utxo.is_spent_by_txid:
                    conflicting_python_utxos.append(python_utxo)
        return conflicting_python_utxos

    @instance_lru_cache()
    def sorted_delta_list_transactions(self, access_marker=None) -> list[TransactionDetails]:
        """
        Returns TransactionDetails sorted such that:
        1) All confirmed transactions come first, ordered by block height (oldest to newest).
           Within each block, parent transactions precede their children.
        2) All unconfirmed transactions follow, grouped by dependency chains so that each parent
           immediately precedes its children (and descendants).
        """
        # Fetch full transaction details mapping
        dict_full: dict[str, FullTxDetail] = self.get_dict_fulltxdetail()

        # 1) Split into confirmed vs. unconfirmed using helper
        confirmed, unconfirmed, initial_transactions, local = self._split_by_confirmation(dict_full)

        # 2) Sort confirmed: by height + intra-block parent→child order
        sorted_confirmed: list[FullTxDetail] = self._sort_confirmed_transactions(confirmed)

        # 3) Sort unconfirmed: group dependency chains via DFS-topo
        sorted_unconfirmed: list[FullTxDetail] = self._sort_unconfirmed_transactions(unconfirmed)

        # 4) initial_transactions: sort according to their original order
        sorted_initial_transactions = self._sort_initial_transactions(initial_transactions)

        # 5) Sort local: group dependency chains via DFS-topo
        sorted_local: list[FullTxDetail] = self._sort_unconfirmed_transactions(local)

        # 6) Merge: confirmed first, then unconfirmed
        all_sorted: list[FullTxDetail] = (
            sorted_confirmed + sorted_unconfirmed + sorted_initial_transactions + sorted_local
        )
        return [fx.tx for fx in all_sorted]

    def _split_by_confirmation(
        self, dict_full: dict[str, FullTxDetail]
    ) -> tuple[list[FullTxDetail], list[FullTxDetail], list[FullTxDetail], list[FullTxDetail]]:
        """
        Splits the full-detail mapping into two lists:
        - confirmed: with a confirmed chain position
        - mempool: awaiting confirmation
        - local: local transactions
        """
        initial_transation_ids = [tx.compute_txid() for tx in self._initial_txs]

        confirmed: list[FullTxDetail] = []
        unconfirmed: list[FullTxDetail] = []
        initial_transactions: list[FullTxDetail] = []
        local: list[FullTxDetail] = []
        for tx_detail in dict_full.values():
            if isinstance(tx_detail.tx.chain_position, bdk.ChainPosition.CONFIRMED):
                confirmed.append(tx_detail)
            else:
                if is_local(tx_detail.tx.chain_position):
                    if tx_detail.txid in initial_transation_ids:
                        initial_transactions.append(tx_detail)
                    else:
                        local.append(tx_detail)
                else:
                    unconfirmed.append(tx_detail)
        return confirmed, unconfirmed, initial_transactions, local

    def _sort_confirmed_transactions(self, confirmed: list[FullTxDetail]) -> list[FullTxDetail]:
        """Orders confirmed transactions by block height, and within the same block,
        ensures parent transactions precede their children."""
        # Bucket confirmed txs by their block height
        conf_by_height: dict[int, list[FullTxDetail]] = defaultdict(list)
        for fx in confirmed:
            assert isinstance(fx.tx.chain_position, bdk.ChainPosition.CONFIRMED)
            height: int = fx.tx.chain_position.confirmation_block_time.block_id.height  # type: ignore
            conf_by_height[height].append(fx)

        sorted_list: list[FullTxDetail] = []
        # Iterate heights in ascending order
        for height in sorted(conf_by_height.keys()):
            bucket = conf_by_height[height]
            if len(bucket) > 1:
                # Sort within the same block by dependency
                sorted_list.extend(self._dfs_topo_sort(bucket))
            else:
                # Single tx has no intra-block dependencies
                sorted_list.append(bucket[0])
        return sorted_list

    def _sort_unconfirmed_transactions(self, unconfirmed: list[FullTxDetail]) -> list[FullTxDetail]:
        """Topologically sorts unconfirmed transactions so that each parent precedes its
        children and deeper descendants."""
        # Mypy narrowing: all entries must be unconfirmed
        for fx in unconfirmed:
            assert not isinstance(fx.tx.chain_position, bdk.ChainPosition.CONFIRMED)
        return self._dfs_topo_sort(unconfirmed)

    def _sort_initial_transactions(self, initial_transactions: list[FullTxDetail]) -> list[FullTxDetail]:
        """Sort initial transactions deterministically."""
        initial_transation_id_order = {str(tx.compute_txid()): i for i, tx in enumerate(self._initial_txs)}

        def sort_key(tx: FullTxDetail) -> int:
            """Return the sorting key for initial transaction ordering."""
            return initial_transation_id_order.get(tx.txid, 0)

        return sorted(initial_transactions, key=sort_key)

    def _dfs_topo_sort(self, tx_list: list[FullTxDetail]) -> list[FullTxDetail]:
        """Return a *full* topological ordering of the given transactions.

        The list ``tx_list`` must be “homogeneous’’—all confirmed in the same
        block *or* all unconfirmed—so every dependency edge either points to
        another element of ``tx_list`` or to a transaction outside the list,
        never across blocks.

        Topological guarantee
        ---------------------
        In the returned list **every parent precedes *all* of its children**.
        (Parents are *not* guaranteed to be *immediately* before their children;
        sibling sub-trees can interleave.)

        Parameters
        ----------
        tx_list : List[FullTxDetail]
            Transactions to be ordered.

        Returns
        -------
        List[FullTxDetail]
            A list in topological order.
        """
        # ─────────────────────────────── build the graph ────────────────────────────
        tx_map: dict[str, FullTxDetail] = {fx.tx.txid: fx for fx in tx_list}
        children: defaultdict[str, list[str]] = defaultdict(list)
        indegree: dict[str, int] = {txid: 0 for txid in tx_map}

        for fx in tx_list:
            for inp in fx.inputs.values():
                if not inp:
                    continue
                parent_id = inp.outpoint.txid_str
                if parent_id in tx_map:  # dependency inside list
                    children[parent_id].append(fx.tx.txid)
                    indegree[fx.tx.txid] += 1

        roots: list[str] = [txid for txid, deg in indegree.items() if deg == 0]

        # ───────────────────── sort roots by lock-time (cluster order) ──────────────
        roots.sort(
            key=lambda tid: (
                tx_map[tid].tx.transaction.lock_time(),  # ➊ primary key
                tid,  # ➋ deterministic tiebreaker
            ),
            reverse=True,
        )

        # ──────────────────────── depth-first post-order walk ───────────────────────
        sorted_order: list[FullTxDetail] = []
        visited: set[str] = set()

        def dfs(txid: str) -> None:
            """Post-order DFS that appends *after* visiting descendants, yielding a
            valid topological ordering once the list is reversed.

            Steps
            -----
            1. Skip if *txid* already processed (cycle/duplicate guard).
            2. Recurse on every child in ``children[txid]``.
            3. Append the current node to ``sorted_order``.
            """
            if txid in visited:  # 1 ▸ guard
                return
            visited.add(txid)

            for child_id in children.get(txid, []):  # 2 ▸ recurse
                dfs(child_id)

            sorted_order.append(tx_map[txid])  # 3 ▸ post-order emit

        # visit each root (deterministic order is nice for testing)
        for root in roots:
            dfs(root)

        # post-order → topo order
        sorted_order.reverse()
        return sorted_order

    def is_in_mempool(self, txid: str) -> bool:
        """Return True if the transaction is seen in the mempool."""
        return TxStatus.from_wallet(txid, self).is_in_mempool()

    def get_fulltxdetail_and_dependents(self, txid: str, include_root_tx=True) -> list[FullTxDetail]:
        """Return transaction details and dependent entries."""
        result: list[FullTxDetail] = []
        fulltxdetail = self.get_dict_fulltxdetail().get(txid)
        if not fulltxdetail:
            return result

        if include_root_tx:
            result.append(fulltxdetail)

        for output in fulltxdetail.outputs.values():
            if output.is_spent_by_txid:
                result += self.get_fulltxdetail_and_dependents(output.is_spent_by_txid)

        return result

    def get_ema_fee_rate(self, n: int = 10, default=MIN_RELAY_FEE) -> float:
        """Calculate Exponential Moving Average (EMA) of the fee_rate of all
        transactions.

        It weights the outgoing transactions heavier than the incoming transactions, because Exchanges
        typically overpay fees.
        """
        all_txs = self.sorted_delta_list_transactions()
        weight_sent = 10
        weight_incoming = 1
        all_weights = [(weight_sent if tx.sent else weight_incoming) for tx in all_txs]

        fee_rates: list[float] = []
        weights: list[float] = []
        for weight, txdetail in zip(all_weights, all_txs, strict=False):
            if fee_info := FeeInfo.from_txdetails(txdetail):
                fee_rates.append(fee_info.fee_rate())
                weights.append(weight)

        if not fee_rates:
            return default

        return calculate_ema(fee_rates, n=min(n, len(all_txs)), weights=weights)

    def get_category_python_txo_dict(self, include_spent=False) -> dict[str, list[PythonUtxo]]:
        """Return TXO data filtered by category."""
        category_python_utxo_dict: dict[str, list[PythonUtxo]] = {}

        for python_utxo in self.get_all_txos_dict().values():
            if not include_spent and python_utxo.is_spent_by_txid:
                continue
            category = self.labels.get_category(python_utxo.address)
            if not category:
                continue
            if category not in category_python_utxo_dict:
                category_python_utxo_dict[category] = []
            category_python_utxo_dict[category].append(python_utxo)
        return category_python_utxo_dict

    def get_cpfp_utxos(self, tx: bdk.Transaction, exclude_spent_utxos=True) -> PythonUtxo | None:
        """Returns the first unspent output that can be used for cpfp.

        If no unspent utxo is found it returns the first spent utxo
        """
        txid = tx.compute_txid()
        for vout, _output in enumerate(tx.output()):
            python_utxo = self.get_python_txo(str(OutPoint(txid=txid, vout=vout)))
            if not python_utxo:
                continue
            if exclude_spent_utxos and python_utxo.is_spent_by_txid:
                continue
            return python_utxo
        return None

    def get_local_txs(self) -> dict[str, TransactionDetails]:
        """Return locally stored transactions that lack confirmations."""
        return {key: tx for key, tx in self.get_txs().items() if is_local(tx.chain_position)}

    def apply_evicted_txs(self, txids: list[str], evicted_at=LOCAL_TX_LAST_SEEN):
        "Evicts the txs from the mempool. It can only be applied again if last_seen>evicted_at"
        self.bdkwallet.apply_evicted_txs(
            [bdk.EvictedTx(txid=bdk.Txid.from_string(txid), evicted_at=evicted_at) for txid in txids]
        )
        self.persist()

    def get_hidden_txs_in_tx_graph(self) -> dict[str, bdk.Transaction]:
        hidden_txs: dict[str, bdk.Transaction] = {}

        visible_txids = {tx.txid for tx in self.sorted_delta_list_transactions()}
        for tx in self.serialize_persistence.change_set.tx_graph_changeset().txs:
            txid = str(tx.compute_txid())
            if txid in visible_txids:
                continue
            hidden_txs[txid] = tx
        return hidden_txs

    def apply_unconfirmed_txs(
        self, txs: list[bdk.Transaction], last_seen: int = LOCAL_TX_LAST_SEEN
    ) -> list[bdk.UnconfirmedTx]:
        """Add unconfirmed transactions to the cache and state."""

        # important is to first advance, such that bdk can detect all outputs correctly
        self.advance_tip_to_addresses([address for tx in txs for address in self.get_output_addresses(tx)])

        applied_txs: list[bdk.UnconfirmedTx] = []
        for tx in txs:
            wallet_tx = self.get_tx(str(tx.compute_txid()))
            if (
                wallet_tx
                and isinstance(wallet_tx.chain_position, bdk.ChainPosition.UNCONFIRMED)
                and wallet_tx.chain_position.timestamp
                and wallet_tx.chain_position.timestamp >= last_seen
            ):
                # no need to add txs that are already in there
                continue
            applied_txs.append(bdk.UnconfirmedTx(tx=tx, last_seen=last_seen))

        self.bdkwallet.apply_unconfirmed_txs(applied_txs)
        self.persist()

        return applied_txs

    def advance_tip_to_addresses(self, addresses: list[str]) -> list[bdk.AddressInfo]:
        """Advance tip to address info."""
        revealed_address_infos: list[bdk.AddressInfo] = []

        for address in addresses:
            address_info = self.is_my_address_with_peek(address=address)
            if not address_info:
                continue
            if address_info.index > (current_tip := self.get_tip(is_change=address_info.is_change())):
                revealed_address_infos += self.advance_tip_if_necessary(
                    is_change=address_info.is_change(), target=max(address_info.index, current_tip + self.gap)
                )

        return revealed_address_infos

    def close(self) -> None:
        """Shutdown the wallet and release background resources."""
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()
        if self.client:
            self.client.close()


###########
# Functions that operatate on signals.get_wallets().values()


def get_wallets(wallet_functions: WalletFunctions) -> list[Wallet]:
    """Return all loaded wallets."""
    return list(wallet_functions.get_wallets().values())


def get_wallet(wallet_id: str, wallet_functions: WalletFunctions) -> Wallet | None:
    """Return a wallet by identifier."""
    return wallet_functions.get_wallets().get(wallet_id)


def get_wallet_of_address(address: str, wallet_functions: WalletFunctions) -> Wallet | None:
    """Return the wallet that controls the given address."""
    if not address:
        return None
    for wallet in get_wallets(wallet_functions):
        if wallet.is_my_address_with_peek(address):
            return wallet
    return None


def get_wallet_of_outpoints(outpoints: list[OutPoint], wallet_functions: WalletFunctions) -> Wallet | None:
    """Return the wallet that controls the provided outpoints."""
    wallets = get_wallets(wallet_functions)
    if not wallets:
        return None

    number_intersections = []
    for wallet in wallets:
        python_utxos = wallet.get_all_txos_dict().values()
        wallet_outpoints: list[OutPoint] = [utxo.outpoint for utxo in python_utxos]
        number_intersections.append(len(set(outpoints).intersection(set(wallet_outpoints))))

    if not any(number_intersections):
        # no intersections at all
        return None

    i = np.argmax(number_intersections)
    return wallets[i]


def get_label_from_any_wallet(
    label_type: LabelType,
    ref: str,
    wallet_functions: WalletFunctions,
    autofill_from_txs: bool,
    autofill_from_addresses: bool = False,
    wallets: list[Wallet] | None = None,
    verbose_label=False,
) -> str | None:
    """Return the label for an address from any wallet."""
    wallets = wallets if wallets is not None else get_wallets(wallet_functions)
    for wallet in wallets:
        label = None
        if label_type == LabelType.addr:
            label = wallet.get_label_for_address(
                ref, autofill_from_txs=autofill_from_txs, verbose_label=verbose_label
            )
        elif label_type == LabelType.tx:
            label = wallet.get_label_for_txid(
                ref, autofill_from_addresses=autofill_from_addresses, verbose_label=verbose_label
            )

        if label:
            return label
    return None


def get_tx_details(
    txid: str, wallet_functions: WalletFunctions
) -> tuple[TransactionDetails, Wallet] | tuple[None, None]:
    """Return transaction details from the owning wallet."""
    for wallet in get_wallets(wallet_functions):
        tx = wallet.get_tx(txid=txid)
        if tx:
            return tx, wallet
    return None, None


def get_fulltxdetail(
    txid: str, wallet_functions: WalletFunctions
) -> tuple[FullTxDetail, Wallet] | tuple[None, None]:
    """Return the full transaction detail for the provided ID."""
    for wallet in get_wallets(wallet_functions):
        tx = wallet.get_dict_fulltxdetail().get(txid)
        if tx:
            return tx, wallet
    return None, None


###########


class ToolsTxUiInfo:
    @staticmethod
    def fill_txo_dict_from_outpoints(
        txuiinfos: TxUiInfos, outpoints: list[OutPoint], wallets: list[Wallet]
    ) -> None:
        """Populate TXO metadata for the referenced outpoints."""
        wanted = {str(op) for op in outpoints}
        for wallet in wallets:
            txos_dict = wallet.get_all_txos_dict()
            hits = wanted & txos_dict.keys()
            for op_str in hits:
                pyutxo = txos_dict[op_str]
                txuiinfos.main_wallet_id = wallet.id
                txuiinfos.utxo_dict[pyutxo.outpoint] = pyutxo
                wanted.remove(op_str)
            if not wanted:
                break
        for op_str in wanted:
            logger.warning(f"no python_utxo found for outpoint {op_str} ")

    @staticmethod
    def fill_utxo_dict_from_categories(
        txuiinfos: TxUiInfos, categories: list[str], wallets: list[Wallet]
    ) -> None:
        "Will only include UTXOs, (not usefull for rbf)"
        for wallet in wallets:
            for utxo in wallet.get_all_utxos():
                address = utxo.address
                if wallet.labels.get_category(address) in categories:
                    txuiinfos.utxo_dict[utxo.outpoint] = utxo

    @staticmethod
    def get_likely_source_wallet(txuiinfos: TxUiInfos, wallet_functions: WalletFunctions) -> Wallet | None:
        """Return the wallet most likely associated with the transaction."""
        wallet_dict: dict[str, Wallet] = wallet_functions.get_wallets()

        # trying to identitfy the wallet , where i should fill the send tab
        wallet = None
        if txuiinfos.main_wallet_id:
            wallet = wallet_dict.get(txuiinfos.main_wallet_id)
            if wallet:
                return wallet

        input_outpoints = [outpoint for outpoint in txuiinfos.utxo_dict.keys()]
        return get_wallet_of_outpoints(input_outpoints, wallet_functions)

    @staticmethod
    def pop_change_recipient(txuiinfos: TxUiInfos, wallet: Wallet) -> Recipient | None:
        """Remove and return the detected change recipient."""

        def get_change_address(addresses: list[str]) -> str | None:
            """Return an available change address."""
            for address in addresses:
                if wallet.is_change(address):
                    return address
            return None

        # remove change output if possible
        change_address = get_change_address([recipient.address for recipient in txuiinfos.recipients])
        change_recipient = None
        if change_address and len(txuiinfos.recipients) > 1:
            for i in range(len(txuiinfos.recipients)):
                if txuiinfos.recipients[i].address == change_address:
                    change_recipient = txuiinfos.recipients.pop(i)
                    break

        return change_recipient

    @staticmethod
    def from_tx(
        tx: bdk.Transaction,
        fee_info: FeeInfo | None,
        network: bdk.Network,
        wallets: list[Wallet],
    ) -> TxUiInfos:
        """Construct UI information from transaction data."""
        outpoints = [OutPoint.from_bdk(inp.previous_output) for inp in tx.input()]

        txinfos = TxUiInfos()
        # inputs
        ToolsTxUiInfo.fill_txo_dict_from_outpoints(txinfos, outpoints, wallets=wallets)
        txinfos.spend_all_utxos = True
        # outputs
        checked_max_amount = len(tx.output()) == 1  # if there is only 1 recipient, there is no change address
        for txout in tx.output():
            out_address = robust_address_str_from_txout(TxOut.from_bdk(txout), network)
            txinfos.recipients.append(
                Recipient(out_address, txout.value.to_sat(), checked_max_amount=checked_max_amount)
            )
        # fee rate
        txinfos.fee_rate = fee_info.fee_rate() if fee_info else None
        return txinfos
