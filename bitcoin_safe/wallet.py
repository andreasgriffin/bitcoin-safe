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


import logging
import os
import random
from collections import defaultdict
from time import time
from typing import (
    Any,
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
)

import bdkpython as bdk
import numpy as np
from bdkpython import Network
from bdkpython.bdk import Connection, Descriptor
from bitcoin_qr_tools.multipath_descriptor import (
    address_descriptor_from_multipath_descriptor,
    convert_to_multipath_descriptor,
)
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.tx_util import hex_to_serialized, serialized_to_hex
from bitcoin_safe_lib.util import (
    clean_list,
    hash_string,
    replace_non_alphanumeric,
    time_logger,
)
from bitcoin_usb.address_types import DescriptorInfo
from bitcoin_usb.software_signer import derive as software_signer_derive
from packaging import version

from bitcoin_safe.client import Client
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.psbt_util import FeeInfo, FeeRate
from bitcoin_safe.wallet_util import (
    WalletDifference,
    WalletDifferences,
    WalletDifferenceType,
    signer_name,
)

from .config import MIN_RELAY_FEE, UserConfig
from .descriptors import (
    AddressType,
    bdk,
    descriptor_from_keystores,
    get_default_address_type,
)
from .i18n import translate
from .keystore import KeyStore
from .labels import Labels, LabelType
from .pythonbdk_types import *
from .signals import Signals, UpdateFilter
from .storage import BaseSaveableClass, filtered_for_init
from .tx import TxBuilderInfos, TxUiInfos
from .util import CacheManager, calculate_ema, instance_lru_cache

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
    def to_str(cls, status: "TxConfirmationStatus") -> str:
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
    return (
        isinstance(chain_position, bdk.ChainPosition.UNCONFIRMED)
        and chain_position.timestamp == LOCAL_TX_LAST_SEEN
    )


def is_in_mempool(chain_position: bdk.ChainPosition | None) -> bool:
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
        self.tx = tx
        self.get_height = get_height
        self.chain_position = chain_position

        self.confirmation_status = fallback_confirmation_status
        if isinstance(chain_position, bdk.ChainPosition.CONFIRMED):
            self.confirmation_status = TxConfirmationStatus.CONFIRMED

        if self.confirmation_status.value <= TxConfirmationStatus.UNCONFIRMED.value and self.is_in_mempool():
            self.confirmation_status = TxConfirmationStatus.UNCONFIRMED

    def is_in_mempool(self):
        return is_in_mempool(self.chain_position)

    @classmethod
    def from_wallet(cls, txid: str, wallet: "Wallet") -> "TxStatus":
        # TODO: remove get_height callback entirely
        txdetails = wallet.get_tx(txid)

        if not txdetails:
            return TxStatus(tx=None, chain_position=None, get_height=wallet.get_height)

        return TxStatus(
            tx=txdetails.transaction,
            chain_position=txdetails.chain_position,
            get_height=wallet.get_height,
        )

    def sort_id(self) -> int:
        return confirmations if (confirmations := self.confirmations()) else self.confirmation_status.value

    def confirmations(self) -> int:
        return (
            self.get_height() - self.chain_position.confirmation_block_time.block_id.height + 1
            if self.chain_position and isinstance(self.chain_position, bdk.ChainPosition.CONFIRMED)
            else 0
        )

    def is_confirmed(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.CONFIRMED

    def is_unconfirmed(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.UNCONFIRMED

    def can_do_initial_broadcast(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.LOCAL

    def is_local(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.LOCAL

    def can_rbf(self) -> bool:
        return self.is_unconfirmed()

    def can_cpfp(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.UNCONFIRMED

    def can_edit(self) -> bool:
        return self.confirmation_status.value <= TxConfirmationStatus.LOCAL.value

    def do_icon_check_on_chain_height_change(self) -> bool:
        return self.confirmations() <= 6


def locked(func) -> Any:
    def wrapper(self, *args, **kwargs) -> Any:
        with self.lock:
            return func(self, *args, **kwargs)

    return wrapper


def filename_clean(id: str, file_extension: str = ".wallet", replace_spaces_by=None) -> str:
    import os
    import string

    def create_valid_filename(filename) -> str:
        basename = os.path.basename(filename)
        if replace_spaces_by is not None:
            basename = basename.replace(" ", replace_spaces_by)
        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
        return "".join(c for c in basename if c in valid_chars) + file_extension

    return create_valid_filename(id)


# a wallet  during setup phase, with partial information
class ProtoWallet(BaseSaveableClass):
    def __init__(
        self,
        wallet_id: str,
        threshold: int,
        network: bdk.Network,
        keystores: List[Optional[KeyStore]],
        address_type: Optional[AddressType] = None,
        gap=20,
    ) -> None:
        super().__init__()

        self.id = wallet_id
        self.threshold = threshold
        self.network = network

        self.gap = gap

        initial_address_type: AddressType = (
            address_type if address_type else get_default_address_type(len(keystores) > 1)
        )
        self.keystores: List[Optional[KeyStore]] = keystores

        self.set_address_type(initial_address_type)

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.threshold, len(self.keystores)

    def get_differences(self, other_wallet: "ProtoWallet") -> WalletDifferences:
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
                        type=WalletDifferenceType.NoImpactOnAddresses,
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

        for keystore, other_keystore in zip(self.keystores, other_wallet.keystores):
            if type(keystore) != type(other_keystore):
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
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None) -> "ProtoWallet":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        return super().from_dump_migration(dct=dct)

    def dump(self) -> Any:
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
    ) -> "ProtoWallet":
        "creates a ProtoWallet from the xpub (not xpriv)"
        info = DescriptorInfo.from_str(descriptor)
        keystores: List[Optional[KeyStore]] = [
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
        self.address_type = address_type

    def signer_name(self, i: int) -> str:
        return signer_name(self.threshold, i)

    def sticker_name(self, i: int | str) -> str:
        number = i if isinstance(i, str) else f"{i+1}"
        name = f"{self.id} {number}" if len(self.keystores) > 1 else f"{self.id}"
        return name.strip()

    def set_gap(self, gap: int) -> None:
        self.gap = gap

    def to_multipath_descriptor(self) -> Optional[bdk.Descriptor]:
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

        if n > len(self.keystores):
            for i in range(len(self.keystores), n):
                self.keystores.append(None)
        elif n < len(self.keystores):
            for i in range(n, len(self.keystores)):
                self.keystores.pop()  # removes the last item

    def set_threshold(self, threshold: int) -> None:
        self.threshold = threshold

    def is_multisig(self) -> bool:
        return len(self.keystores) > 1


class DeltaCacheListTransactions:
    def __init__(self) -> None:
        super().__init__()
        self.old_state: List[TransactionDetails] = []
        self.appended: List[TransactionDetails] = []
        self.removed: List[TransactionDetails] = []
        self.new_state: List[TransactionDetails] = []
        self.modified: List[TransactionDetails] = []

    def was_changed(self) -> Dict[str, List[TransactionDetails]]:
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


class BdkWallet(bdk.Wallet, CacheManager):
    """This is a caching wrapper around bdk.Wallet. It should not provide any
    logic. Only wrapping existing methods and minimal new methods useful for
    caching.

    The exception is list_delta_transactions, which provides also deltas
    to a previous state, and is in a wider sense also caching.
    """

    def __init__(
        self, descriptor: Descriptor, change_descriptor: Descriptor, network: Network, connection: Connection
    ):
        bdk.Wallet.__init__(self, descriptor, change_descriptor, network, connection=connection)
        CacheManager.__init__(self)
        self._delta_cache: Dict[str, DeltaCacheListTransactions] = {}
        logger.info(f"Created bdk.Wallet for network {network}")

    @instance_lru_cache(always_keep=True)
    def peek_address(self, keychain: bdk.KeychainKind, index: int) -> bdk.AddressInfo:
        return super().peek_address(keychain=keychain, index=index)

    @instance_lru_cache(always_keep=True)
    def peek_address_str(
        self,
        index: int,
        is_change=False,
    ) -> str:
        return str(
            self.peek_address(
                index=index, keychain=AddressInfoMin.is_change_to_keychain(is_change=is_change)
            ).address
        )

    @instance_lru_cache()
    @time_logger
    def list_output(self) -> List[bdk.LocalOutput]:
        start_time = time()
        result = super().list_output()
        logger.debug(f"self.bdkwallet.list_output {len(result)} results in { time()-start_time}s")

        return result

    @instance_lru_cache()
    @time_logger
    def list_unspent_outpoints(self, include_spent=False) -> List[str]:
        start_time = time()
        result = [
            str(OutPoint.from_bdk(output.outpoint))
            for output in super().list_output()
            if include_spent or not output.is_spent
        ]
        logger.debug(f"self.bdkwallet.list_output {len(result)} results in { time()-start_time}s")
        return result

    def get_tx_details(self, canonical_tx: bdk.CanonicalTx) -> TransactionDetails:
        tx = canonical_tx.transaction
        txid = tx.compute_txid()

        # Calculate the fee:
        # For coinbase transactions, we set fee to None;
        # otherwise, we calculate the fee using the wallet's calculate_fee method.
        if tx.is_coinbase():
            fee = None
        else:
            try:
                fee_amount = self.calculate_fee(tx)  # returns an Amount
                fee = fee_amount.to_sat()  # convert Amount to satoshis (int)
            except:
                fee = None

        sent_receive = self.sent_and_received(tx)

        return TransactionDetails(
            transaction=tx,
            fee=fee,
            received=sent_receive.received.to_sat(),
            sent=sent_receive.sent.to_sat(),
            txid=txid,
            chain_position=canonical_tx.chain_position,
        )

    @instance_lru_cache()
    def list_transactions(self, include_raw=True) -> List[TransactionDetails]:
        start_time = time()
        res = super().transactions()

        logger.debug(f"list_transactions {len(res)} results in { time()-start_time}s")
        return [self.get_tx_details(tx) for tx in res]

    def list_delta_transactions(self, access_marker: str, include_raw=True) -> DeltaCacheListTransactions:
        """access_marker is a unique key, that the history can be stored
        relative to this.

        to call however only the minimal amount of times the underlying
        function, list_transactions is cached. When list_transactions is
        reset, the delta depends on the access_marker
        """

        key = "list_delta_transactions" + str(access_marker)
        entry = self._delta_cache[key] = self._delta_cache.get(key, DeltaCacheListTransactions())
        entry.old_state = entry.new_state

        # start_time = time()
        entry.new_state = self.list_transactions(include_raw=include_raw)

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
            if old.fee != new.fee:
                entry.modified.append(old)
                continue
            if type(old.chain_position) != type(new.chain_position):
                entry.modified.append(old)
                continue
            if (
                (is_local(old.chain_position) or is_local(new.chain_position))
                and isinstance(old.chain_position, bdk.ChainPosition.UNCONFIRMED)
                and isinstance(new.chain_position, bdk.ChainPosition.UNCONFIRMED)
                and old.chain_position.timestamp != new.chain_position.timestamp
            ):
                entry.modified.append(old)
                continue
        logger.info(entry.modified)
        return entry

    @instance_lru_cache(always_keep=True)
    def network(self) -> bdk.Network:
        return super().network()

    @instance_lru_cache(always_keep=True)
    def get_address_of_txout(self, txout: TxOut) -> Optional[str]:
        res = robust_address_str_from_script(
            txout.script_pubkey, network=self.network(), on_error_return_hex=False
        )
        return res if res else None


class WalletInputsInconsistentError(Exception):
    pass


class ProgressLogger:
    def update(self, progress: "float", message: "Optional[str]"):
        logger.info(str((progress, message)))


class Wallet(BaseSaveableClass, CacheManager):
    """If any bitcoin logic (ontop of bdk) has to be done, then here is the
    place."""

    VERSION = "0.3.2"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "KeyStore": KeyStore,
        "UserConfig": UserConfig,
        "Labels": Labels,
        "Balance": Balance,
        "LabelType": LabelType,
    }

    def __init__(
        self,
        id,
        descriptor_str: str,
        keystores: List[KeyStore],
        network: bdk.Network,
        config: UserConfig,
        gap=20,
        labels: Labels | None = None,
        _blockchain_height: int | None = None,
        initialization_tips: List[int] | None = None,
        refresh_wallet=False,
        default_category="default",
        initial_txs: List[bdk.Transaction] | None = None,
        **kwargs,
    ) -> None:
        super().__init__()
        CacheManager.__init__(self)
        self.check_consistency(keystores, descriptor_str, network=network)

        self.id = id
        self.network = network if network else config.network
        # prevent loading a wallet into different networks
        assert (
            self.network == config.network
        ), f"Cannot load a wallet for {self.network}, when the network {config.network} is configured"
        self.gap = gap
        self.keystores = keystores
        self.config: UserConfig = config
        self.labels: Labels = labels if labels else Labels(default_category=default_category)
        # refresh dependent values
        self._initialization_tips = (
            initialization_tips if initialization_tips and not refresh_wallet else [0, 0]
        )
        self._blockchain_height = _blockchain_height if _blockchain_height and not refresh_wallet else 0

        if refresh_wallet and os.path.isfile(self._db_file()):
            os.remove(self._db_file())
        self.refresh_wallet = False
        # end refresh dependent values

        self.create_bdkwallet(convert_to_multipath_descriptor(descriptor_str, self.network))

        self.client: Optional[Client] = None
        self.exclude_tx_ids_in_saving: Set[str] = set()
        self._initial_txs = initial_txs if initial_txs else []
        if initial_txs:
            self.apply_unconfirmed_txs(txs=initial_txs)
        self.clear_cache()
        self.mark_all_labeled_addresses_used(include_receiving_addresses=False)

    def persist(self) -> None:
        self.bdkwallet.persist(self.connection)
        self.clear_cache()

    @staticmethod
    def check_consistency(keystores: List[KeyStore], descriptor_str: str, network: bdk.Network):
        def get_keystore(fingerprint) -> Optional[KeyStore]:
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

    def mark_labeled_addresses_used(self, address_infos: List[AddressInfoMin]):
        for address_info in address_infos:
            label = self.labels.get_label(address_info.address)
            if not label:
                continue
            self.bdkwallet.mark_used(keychain=address_info.keychain, index=address_info.index)

    def mark_all_labeled_addresses_used(self, include_receiving_addresses=False):
        self.mark_labeled_addresses_used(self._get_addresses_infos(is_change=True))
        if include_receiving_addresses:
            self.mark_labeled_addresses_used(self._get_addresses_infos(is_change=False))

    def clear_cache(self, clear_always_keep=False) -> None:
        self.cache_dict_fulltxdetail: Dict[str, FullTxDetail] = {}  # txid:FullTxDetail
        self.cache_address_to_txids: Dict[str, Set[str]] = defaultdict(set)  # address:[txid]

        self.clear_instance_cache(clear_always_keep=clear_always_keep)
        self.bdkwallet.clear_instance_cache(clear_always_keep=clear_always_keep)

    @instance_lru_cache()
    def _get_addresses_infos(
        self,
        is_change=False,
    ) -> List[AddressInfoMin]:
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
    ) -> List[str]:
        addresses_infos = self._get_addresses_infos(is_change=is_change)
        return [addresses_info.address for addresses_info in addresses_infos]

    @instance_lru_cache(always_keep=True)
    def get_mn_tuple(self) -> Tuple[int, int]:
        info = DescriptorInfo.from_str(str(self.multipath_descriptor))
        return info.threshold, len(info.spk_providers)

    def as_protowallet(self) -> ProtoWallet:
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
        labels: Labels | None = None,
        _blockchain_height: int | None = None,
        initialization_tips: List[int] | None = None,
        refresh_wallet=False,
        default_category="default",
    ) -> "Wallet":

        keystores = []
        for keystore in protowallet.keystores:
            # dissallow None
            assert keystore is not None, "Cannot create wallet with None"

            if keystore.key_origin != protowallet.address_type.key_origin(config.network):
                logger.warning(f"Warning: {keystore.key_origin=} is not the default")

            keystores.append(keystore.clone())

        multipath_descriptor = protowallet.to_multipath_descriptor()
        assert (
            multipath_descriptor is not None
        ), "Cannot create wallet, because no descriptor could be generated"

        return Wallet(
            protowallet.id,
            multipath_descriptor.to_string_with_secret(),
            keystores=keystores,
            gap=protowallet.gap,
            network=protowallet.network,
            config=config,
            labels=labels,
            _blockchain_height=_blockchain_height,
            initialization_tips=initialization_tips,
            refresh_wallet=refresh_wallet,
            default_category=default_category,
        )

    def get_differences(self, other_wallet: "Wallet") -> WalletDifferences:
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
                logger.error(f"This should not happen!!! Please fix")
                continue
            if this[k] != other[k]:
                differences.append(
                    WalletDifference(
                        type=WalletDifferenceType.NoImpactOnAddresses,
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
                    type=WalletDifferenceType.NoImpactOnAddresses,
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

        for keystore, other_keystore in zip(self.keystores, other_wallet.keystores):
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

    def derives_identical_addresses(self, other_wallet: "Wallet") -> bool:
        return self.bdkwallet.peek_address_str(0) == other_wallet.bdkwallet.peek_address_str(0)

    def dump(self) -> Dict[str, Any]:
        d = super().dump()

        keys = [
            "id",
            "gap",
            "network",
            "keystores",
            "labels",
            "_blockchain_height",
            "refresh_wallet",
        ]
        for k in keys:
            d[k] = self.__dict__[k]

        d["initialization_tips"] = self.tips
        d["descriptor_str"] = self.multipath_descriptor.to_string_with_secret()
        d["initial_txs"] = [
            serialized_to_hex(tx.transaction.serialize())
            for tx in self.sorted_delta_list_transactions()
            if tx.transaction.compute_txid() not in self.exclude_tx_ids_in_saving
        ]
        return d

    @classmethod
    def from_file(cls, filename: str, config: UserConfig, password: str | None = None) -> "Wallet":
        return super()._from_file(
            filename=filename,
            password=password,
            class_kwargs={"Wallet": {"config": config}},
        )

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.0"):
            if "labels" in dct:
                # no real migration. Just delete old data
                del dct["labels"]

            labels = Labels()
            for k, v in dct.get("category", {}).items():
                labels.set_addr_category(k, v)

            del dct["category"]
            dct["labels"] = labels

        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.1"):
            if dct.get("sync_tab_dump"):
                del dct["sync_tab_dump"]

        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.3"):
            if dct.get("sync_tab_dump"):
                dct["data_dump"] = {"SyncTab": dct["sync_tab_dump"]}

        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.4"):
            if dct.get("data_dump"):
                if "SyncTab" in dct["data_dump"]:
                    del dct["data_dump"]["SyncTab"]

        if version.parse(str(dct["VERSION"])) <= version.parse("0.2.0"):
            if dct.get("data_dump"):
                del dct["data_dump"]

        if version.parse(str(dct["VERSION"])) < version.parse("0.3.0"):
            if dct.get("auto_opportunistic_coin_select"):
                dct["auto_opportunistic_coin_select"] = False

        if version.parse(str(dct["VERSION"])) < version.parse("0.3.1"):
            if _tips := dct.get("_tips"):
                dct["initialization_tips"] = _tips

        return super().from_dump_migration(dct=dct)

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None) -> "Wallet":
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        if initial_txs := dct.get("initial_txs"):
            dct["initial_txs"] = [bdk.Transaction(list(hex_to_serialized(tx))) for tx in initial_txs]

        return cls(**filtered_for_init(dct, cls))

    def set_gap(self, gap: int) -> None:
        self.gap = gap

    def set_wallet_id(self, id: str) -> None:
        self.id = id

    def _db_file(self) -> str:
        return f"{os.path.join(self.config.wallet_dir, filename_clean(self.id, file_extension='.db'))}"

    def create_bdkwallet(self, multipath_descriptor: bdk.Descriptor) -> None:
        self.multipath_descriptor = multipath_descriptor
        assert multipath_descriptor.is_multipath()
        self.connection = bdk.Connection.new_in_memory()

        descriptor, change_descriptor = self.multipath_descriptor.to_single_descriptors()
        self.bdkwallet = BdkWallet(
            descriptor=descriptor,
            change_descriptor=change_descriptor,
            network=self.config.network,
            connection=self.connection,
            # database_config=bdk.DatabaseConfig.SQLITE(
            #     bdk.SqliteDbConfiguration(self._db_file())
            # ),
        )
        for is_change, tip in enumerate(self._initialization_tips):
            self.bdkwallet.reveal_addresses_to(
                keychain=AddressInfoMin.is_change_to_keychain(is_change=bool(is_change)), index=tip
            )

    def is_multisig(self) -> bool:
        return len(self.keystores) > 1

    def init_blockchain(self) -> Client:
        logger.info(f"Creating blockchain connection for {self.config.network_config=}")

        if self.config.network == bdk.Network.BITCOIN:
            start_height = 0  # segwit block 481824
        elif self.config.network in [
            bdk.Network.REGTEST,
            bdk.Network.SIGNET,
        ]:
            pass
        elif self.config.network == bdk.Network.TESTNET:
            pass
        elif self.config.network == bdk.Network.TESTNET4:
            pass

        if self.config.network_config.server_type == BlockchainType.Electrum:
            client = Client.from_electrum(
                url=self.config.network_config.electrum_url,
                use_ssl=self.config.network_config.electrum_use_ssl,
                proxy_info=(
                    ProxyInfo.parse(self.config.network_config.proxy_url)
                    if self.config.network_config.proxy_url
                    else None
                ),
            )
        elif self.config.network_config.server_type == BlockchainType.Esplora:
            client = Client.from_esplora(
                url=self.config.network_config.esplora_url,
                proxy_info=(
                    ProxyInfo.parse(self.config.network_config.proxy_url)
                    if self.config.network_config.proxy_url
                    else None
                ),
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
        else:
            raise ValueError(f"{self.config.network_config.server_type=} not allowed")

        if not client:
            raise Exception("Could not find a blockchain_config.")
        self.client = client
        return client

    def _get_uniquie_wallet_id(self) -> str:
        return f"{replace_non_alphanumeric(self.id)}-{hash_string(str(self.multipath_descriptor))}"

    def sync(self) -> None:
        if not self.bdkwallet:
            logger.warning("Wallet not initialized; cannot sync.")
            return
        if not self.client:
            logger.info("No blockchain client yet; creating now...")
            self.init_blockchain()
            if not self.client:
                return

        try:
            start_time = time()

            update = self.client.full_scan(self.bdkwallet.start_full_scan().build(), stop_gap=self.gap)

            self.bdkwallet.apply_update(update)

            self.persist()

            elapsed = time() - start_time
            logger.debug(f"{self.id} wallet sync in {elapsed:.2f}s")

            logger.info("Wallet balance retrieved successfully.")

        except Exception as e:
            logger.error(f"{self.id} error syncing wallet: {e}")
            raise

    def forward_search_unused_address(
        self, category: Optional[str] = None, is_change=False
    ) -> Optional[bdk.AddressInfo]:

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
        category: Optional[str] = None,
        is_change=False,
    ) -> Optional[bdk.AddressInfo]:

        result: Optional[bdk.AddressInfo] = None
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

    def get_unused_category_address(self, category: Optional[str], is_change=False) -> bdk.AddressInfo:
        if category is None:
            category = self.labels.get_default_category()

        address_info = self.reverse_search_unused_address(category=category, is_change=is_change)
        if not address_info:
            address_info = self.get_address(force_new=True, is_change=is_change)

        self.labels.set_addr_category(str(address_info.address), category, timestamp="old")
        return address_info

    def get_force_new_address(self, is_change) -> bdk.AddressInfo:
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

    def get_output_addresses(self, transaction: bdk.Transaction) -> List[str]:
        # print(f'Getting output addresses for txid {transaction.txid}')
        output_addresses = [
            self.bdkwallet.get_address_of_txout(TxOut.from_bdk(output)) for output in transaction.output()
        ]
        return [a for a in output_addresses if a]

    @time_logger
    def fill_commonly_used_caches(self) -> None:
        # you have to repeat fetching new tx when you start watching new addresses
        # And you can only start watching new addresses once you detected transactions on them.
        # Thas why this fetching has to be done in a loop
        self.clear_cache()
        addresses = self.get_addresses()
        self.get_height()
        self.bdkwallet.list_output()
        self.get_dict_fulltxdetail()
        self.get_all_txos_dict()
        self.set_categories_of_used_addresses()
        if addresses:
            self.is_my_address_with_peek(addresses[-1])

    @instance_lru_cache()
    def get_txs(self) -> Dict[str, TransactionDetails]:
        "txid:TransactionDetails"
        return {tx.txid: tx for tx in self.sorted_delta_list_transactions()}

    @instance_lru_cache()
    def get_tx(self, txid: str) -> TransactionDetails | None:
        return self.get_txs().get(txid)

    def list_input_bdk_addresses(self, transaction: bdk.Transaction) -> List[str]:
        addresses = []
        for tx_in in transaction.input():
            address = self.get_address_of_outpoint(OutPoint.from_bdk(tx_in.previous_output))
            if address:
                addresses.append(address)
        return addresses

    def list_tx_addresses(self, transaction: bdk.Transaction) -> Dict[str, List[str]]:
        return {
            "in": self.list_input_bdk_addresses(transaction),
            "out": self.get_output_addresses(transaction),
        }

    def transaction_related_to_my_addresses(self, transaction: bdk.Transaction) -> bool:
        addresses = self.get_addresses()
        for tx_addresses in self.list_tx_addresses(transaction).values():
            if set(addresses).intersection(set([a for a in tx_addresses if a])):
                return True

        return False

    def used_address_tip(self, is_change: bool) -> int:
        def reverse_search_used(tip_index) -> int:
            for i in reversed(range(tip_index)):
                addresses = self._get_addresses(is_change=is_change)
                if len(addresses) - 1 < i:
                    continue
                if self.address_is_used(addresses[i]):
                    return i
            return 0

        return reverse_search_used(self.tips[int(is_change)])

    def get_tip(self, is_change: bool) -> int:
        keychain_kind = AddressInfoMin.is_change_to_keychain(is_change=is_change)
        derivation_index = self.bdkwallet.derivation_index(keychain=keychain_kind)
        if derivation_index is None:
            self.advance_tip_if_necessary(is_change=is_change, target=0)
            return 0
        return derivation_index

    def advance_tip_if_necessary(self, is_change: bool, target: int) -> List[bdk.AddressInfo]:
        revealed_addresses: List[bdk.AddressInfo] = []
        keychain_kind = AddressInfoMin.is_change_to_keychain(is_change=is_change)
        max_derived_index = self.bdkwallet.derivation_index(keychain=keychain_kind)

        if max_derived_index is None or max_derived_index < target:
            revealed_addresses += self.bdkwallet.reveal_addresses_to(keychain=keychain_kind, index=target)
            self.persist()
            logger.info(f"{self.id} Revealed addresses up to {keychain_kind=} {target=}")
        return revealed_addresses

    def advance_tip_to_address(self, address: str, forward_search=1000) -> Optional[AddressInfoMin]:
        """Looks for the address and advances the tip to this address"""
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
    def tips(self) -> List[int]:
        return [self.get_tip(b) for b in [False, True]]

    def get_receiving_addresses(self) -> List[str]:
        return self._get_addresses(is_change=False)

    def get_change_addresses(self) -> List[str]:
        return self._get_addresses(is_change=True)

    # do not cach this!!! it will lack behind when a psbt extends the change tip
    def get_addresses(self) -> List[str]:
        "Gets the combined list of receiving and change addresses"
        # note: overridden so that the history can be cleared.
        # addresses are ordered based on derivation
        out = self.get_receiving_addresses().copy()
        out += self.get_change_addresses().copy()
        return out

    def is_change(self, address: str) -> bool:
        return address in self.get_change_addresses()

    def is_receive(self, address: str) -> bool:
        return address in self.get_receiving_addresses()

    def _get_address_info_min(self, address: str, keychain: bdk.KeychainKind) -> Optional[AddressInfoMin]:
        "(is_change, index)"
        if keychain == bdk.KeychainKind.EXTERNAL:
            addresses = self.get_receiving_addresses()
            if address in addresses:
                return AddressInfoMin(keychain=keychain, index=addresses.index(address), address=address)
        else:
            addresses = self.get_change_addresses()
            if address in addresses:
                return AddressInfoMin(keychain=keychain, index=addresses.index(address), address=address)
        return None

    def get_address_info_min(self, address: str) -> Optional[AddressInfoMin]:
        info_min = self._get_address_info_min(address, bdk.KeychainKind.EXTERNAL)
        if info_min:
            return info_min

        info_min = self._get_address_info_min(address, bdk.KeychainKind.INTERNAL)
        if info_min:
            return info_min

        return None

    def txo_of_outpoint(self, outpoint: bdk.OutPoint) -> Optional[PythonUtxo]:
        txo_dict = self.get_all_txos_dict()
        outpoint_str = str(OutPoint.from_bdk(outpoint))
        if outpoint_str in txo_dict:
            return txo_dict[outpoint_str]
        return None

    @instance_lru_cache()
    def get_address_balances(self) -> defaultdict[str, Balance]:
        """Converts the known utxos into
        a dict of addresses and their balance
        """

        utxos = self.bdkwallet.list_output()

        balances: defaultdict[str, Balance] = defaultdict(Balance)
        for i, utxo in enumerate(utxos):
            if utxo.is_spent:
                continue
            outpoint = OutPoint.from_bdk(utxo.outpoint)
            txout = self.get_txout_of_outpoint(outpoint)
            if not txout:
                logger.warning(f"This should not happen. Most likely it is due to outdated caches.")
                # this way of handeling this special case is suboptimal.
                # Better would be to handle the caches such that the caches are always consistent
                self.clear_instance_cache()
                txout = self.get_txout_of_outpoint(outpoint)
                if not txout:
                    raise InconsistentBDKState(f"{outpoint.txid} not present in transaction details")

            address = self.bdkwallet.get_address_of_txout(txout)
            if address is None:
                continue

            outpoint_tx_details = self.get_tx(outpoint.txid)
            if outpoint_tx_details and isinstance(
                outpoint_tx_details.chain_position, bdk.ChainPosition.CONFIRMED
            ):
                balances[address].confirmed += txout.value
            else:
                balances[address].untrusted_pending += txout.value

        return balances

    @instance_lru_cache()
    def get_addr_balance(self, address: str) -> Balance:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]

    def get_involved_txids(self, address: str) -> Set[str]:
        # this also fills self.cache_address_to_txids
        self.get_dict_fulltxdetail()
        return self.cache_address_to_txids.get(address, set())

    def set_categories_of_used_addresses(self):
        for utxo in self.get_all_txos_dict(include_not_mine=False).values():
            if not self.labels.get_category_raw(utxo.address):
                categories = self.get_categories_for_txid(utxo.outpoint.txid)
                if not categories:
                    continue
                category = categories[0]
                self.labels.set_addr_category(ref=utxo.address, category=category, timestamp="old")
                logger.info(f"Set {category=} for {utxo.address=}")

    @instance_lru_cache()
    @time_logger
    def get_dict_fulltxdetail(self) -> Dict[str, FullTxDetail]:
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
            txs = delta_txs.appended

        def append_dicts(txid, python_utxos: List[Optional[PythonUtxo]]) -> None:
            for python_utxo in python_utxos:
                if not python_utxo:
                    continue
                self.cache_address_to_txids[python_utxo.address].add(txid)

        def process_outputs(tx: TransactionDetails) -> Tuple[str, FullTxDetail]:
            fulltxdetail = FullTxDetail.fill_received(tx, self.bdkwallet.get_address_of_txout)
            if fulltxdetail.txid in cache_dict_fulltxdetail:
                if not tx.transaction.is_coinbase():
                    logger.error(f"Trying to add a tx with txid {fulltxdetail.txid} twice.")
            return fulltxdetail.txid, fulltxdetail

        def process_inputs(tx: TransactionDetails) -> Tuple[str, FullTxDetail]:
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
        # threadtable_batched: 4.1 s , this should perform best, however bdk is probably the bottleneck and not-multithreading capable
        key_value_pairs = list(map(process_inputs, txs))
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, list(fulltxdetail.inputs.values()))

        if txs:
            logger.debug(f"get_dict_fulltxdetail  with {len(txs)} txs in {time()-  start_time}")

        self.cache_dict_fulltxdetail = cache_dict_fulltxdetail
        return self.cache_dict_fulltxdetail

    @instance_lru_cache(always_keep=False)
    def get_all_txos_dict(self, include_not_mine=False) -> Dict[str, PythonUtxo]:
        "Returns {str(outpoint) : python_utxo}"
        dict_fulltxdetail = self.get_dict_fulltxdetail()
        my_addresses = self.get_addresses()

        txos: Dict[str, PythonUtxo] = {}
        for fulltxdetail in dict_fulltxdetail.values():
            for python_utxo in fulltxdetail.outputs.values():
                if include_not_mine or (python_utxo.address in my_addresses):
                    if str(python_utxo.outpoint) in txos:
                        logger.error(
                            f"{str(python_utxo.outpoint)} already present in txos, meaning dict_fulltxdetail has outpoints occuring multiple times"
                        )
                    txos[str(python_utxo.outpoint)] = python_utxo
        return txos

    def get_all_utxos(self, include_not_mine=False) -> List[PythonUtxo]:
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
        address_info = self.get_address_info_min(address)
        if not address_info:
            return ""

        return address_descriptor_from_multipath_descriptor(
            descriptor=self.multipath_descriptor, kind=address_info.keychain, address_index=address_info.index
        )

    def get_input_and_output_txo_dict(self, txid: str) -> Dict[TxoType, List[PythonUtxo]]:
        result: Dict[TxoType, List[PythonUtxo]] = {TxoType.OutputTxo: [], TxoType.InputTxo: []}

        fulltxdetail = self.get_dict_fulltxdetail().get(txid)
        if not fulltxdetail:
            return result

        result[TxoType.OutputTxo] = [python_utxo for python_utxo in fulltxdetail.outputs.values()]
        result[TxoType.InputTxo] = [
            python_utxo for python_utxo in fulltxdetail.inputs.values() if python_utxo
        ]
        return result

    def get_output_txos(self, txid: str) -> List[PythonUtxo]:
        return self.get_input_and_output_txo_dict(txid)[TxoType.OutputTxo]

    def get_input_txos(self, txid: str) -> List[PythonUtxo]:
        return self.get_input_and_output_txo_dict(txid)[TxoType.InputTxo]

    def get_categories_for_txid(self, txid: str) -> List[str]:
        input_and_output_txo_dict = self.get_input_and_output_txo_dict(txid)
        python_txos = sum(input_and_output_txo_dict.values(), [])
        if not python_txos:
            return []

        categories: List[str] = np.unique(
            clean_list([self.labels.get_category_raw(python_utxo.address) for python_utxo in python_txos])
        ).tolist()  # type: ignore

        if not categories:
            categories = [self.labels.get_default_category()]
        return categories

    def get_label_for_address(self, address: str, autofill_from_txs=True, verbose_label=False) -> str:
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
        return Balance.from_bdk(balance=self.bdkwallet.balance())

    def get_txo_name(self, utxo: PythonUtxo) -> str:
        tx = self.get_tx(utxo.outpoint.txid)
        txid = tx.txid if tx else translate("wallet", "Unknown")
        return f"{txid}:{utxo.outpoint.vout}"

    def get_height_no_cache(self) -> int:
        if self.client:
            # update the cached height
            try:
                self._blockchain_height = self.client.get_height()
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
                logger.error(f"Could not fetch self.blockchain.get_height()")
        return self._blockchain_height

    @instance_lru_cache()
    # caching is crucial, because this function is called vor every row in the hist table
    def get_height(self) -> int:
        return self.get_height_no_cache()

    def opportunistic_coin_select(
        self, utxos: List[PythonUtxo], total_sent_value: int, opportunistic_merge_utxos: bool
    ) -> UtxosForInputs:
        def utxo_value(utxo: PythonUtxo) -> int:
            return utxo.txout.value

        def is_outpoint_in_list(outpoint, utxos) -> bool:
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
            selected_value += utxo.txout.value
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
                f"Selected {len(opportunistic_merging_utxos)} additional opportunistic outpoints with small values (so total ={len(selected_utxos)+len(opportunistic_merging_utxos)})"
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

        total_sent_value = sum([recipient.amount for recipient in txinfos.recipients])

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
        return address in self.get_addresses()

    @instance_lru_cache()
    def get_address_dict_with_peek(
        self, peek_receive_ahead: int, peek_change_ahead: int
    ) -> Dict[str, AddressInfoMin]:
        start_time = time()
        addresses: Dict[str, AddressInfoMin] = {}
        for _is_change, _peek_ahead in [(False, peek_receive_ahead), (True, peek_change_ahead)]:
            address_infos = self._get_addresses_infos(is_change=_is_change)
            addresses.update({address_info.address: address_info for address_info in address_infos})
            tip = address_infos[-1].index if address_infos else 0

            for index in range(tip + 1, tip + 1 + _peek_ahead):
                address_info = self.bdkwallet.peek_address(
                    keychain=AddressInfoMin.is_change_to_keychain(is_change=_is_change), index=index
                )
                addresses[str(address_info.address)] = AddressInfoMin.from_bdk_address_info(address_info)
        logger.debug(f"{self.id} get_address_dict_with_peek  in { time()-start_time}s")
        return addresses

    def is_my_address_with_peek(
        self, address: str, peek_receive_ahead: int = 1000, peek_change_ahead: int = 1000
    ) -> AddressInfoMin | None:
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
                [list(self.get_categories_for_txid(utxo.outpoint.txid)) for utxo in utxos],
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

        logger.warning(f"determine_recipient_category returns  default category")
        return self.labels.get_default_category()

    def create_bump_fee_psbt(self, txinfos: TxUiInfos) -> TxBuilderInfos:
        if txinfos.replace_tx is None:
            raise Exception("Cannot replace tx without txid")
        if txinfos.fee_rate is None:
            raise Exception("Cannot bump tx without feerate")

        # check inputs consistent
        prev_outpoints = [
            str(OutPoint.from_bdk(prev_out.previous_output)) for prev_out in txinfos.replace_tx.input()
        ]
        utxos = [utxo for utxo in txinfos.utxo_dict.values() if str(utxo.outpoint) in prev_outpoints]
        assert len(prev_outpoints) == len(
            utxos
        ), f"Inconsistent TxUiInfos:Not all utxos could be found for the {len(prev_outpoints)} inputs"
        utxos_for_input = UtxosForInputs(utxos=utxos, spend_all_utxos=txinfos.spend_all_utxos)

        # check recipients    consistent
        recipient_addresses = [r.address for r in txinfos.recipients]
        assert len(txinfos.replace_tx.output()) >= len(
            txinfos.recipients
        ), "Inconsistent TxUiInfos:too many recipients"
        for output in txinfos.replace_tx.output():
            output_address = str(bdk.Address.from_script(script=output.script_pubkey, network=self.network))
            if output_address in self.get_receiving_addresses():
                assert (
                    output_address in recipient_addresses
                ), "Inconsistent TxUiInfos: Outpoint Address not in recipient list"

        try:
            tx_builder = bdk.BumpFeeTxBuilder(
                txid=txinfos.replace_tx.compute_txid(), fee_rate=FeeRate.from_float_sats_vB(txinfos.fee_rate)
            )
            # if the fee is too low bdk will throw an exception here
            psbt = tx_builder.finish(self.bdkwallet)
        except bdk.CreateTxError.FeeRateTooLow as e:
            raise Exception(
                f"Fee below the allowed minimum fee = {Satoshis(value= int(e.required), network=self.network).str_with_unit(color_formatting=None)}"
            )
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
                if OutPoint.from_bdk(utxo.outpoint) not in selected_outpoints
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
        logger.debug(f"{self.id} tx_builder.finish  in { time()-start_time}s")

        # inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()

        logger.info(f"Created PSBT {psbt.extract_tx().compute_txid()[:4]=}")
        fee_rate = self.bdkwallet.calculate_fee_rate(psbt.extract_tx())
        if fee_rate is not None:
            logger.info(f"psbt fee after finalized { FeeRate.from_fee_rate( fee_rate).to_sats_per_vb()}")

        recipient_category = self.determine_recipient_category(utxos_for_input.utxos)

        builder_infos = TxBuilderInfos(
            recipients=recipients,
            utxos_for_input=utxos_for_input,
            psbt=psbt,
            recipient_category=recipient_category,
            fee_rate=txinfos.fee_rate,
        )

        self.set_addresses_category_if_unused(
            recipient_category=recipient_category,
            addresses=[
                self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
                for txout in builder_infos.psbt.extract_tx().output()
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
    ) -> List[str]:
        assigned_addresses: List[str] = []
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

    def _set_recipient_address_labels(self, recipients: List[Recipient]) -> None:
        # set label for the recipient output
        for recipient in recipients:
            # this does not include the change output
            if recipient.label:  # it doesnt have to be my address (in fact most often it is not)
                self.labels.set_addr_label(recipient.address, recipient.label, timestamp="now")

    def _set_labels_for_change_outputs(self, infos: TxBuilderInfos) -> None:
        # add a label for the change output
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        if not labels:
            return
        for txout in infos.psbt.extract_tx().output():
            address = self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
            if not address:
                continue
            if not self.is_my_address(address):
                continue
            if self.is_change(address):
                change_label = translate("wallet", "Change of:") + " " + ", ".join(labels)
                self.labels.set_addr_label(address, change_label, timestamp="now")

    def _label_txid_by_recipient_labels(self, infos: TxBuilderInfos) -> None:
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        if labels:
            tx_label = translate("wallet", "Send to:") + " " + ",".join(labels)
            self.labels.set_tx_label(infos.psbt.extract_tx().compute_txid(), tx_label, timestamp="now")

    def on_addresses_updated(self, update_filter: UpdateFilter) -> None:
        """Checks if the tip reaches the addresses and updated the tips if
        necessary (This is especially relevant if a psbt creates a new change
        address)"""
        self.clear_method(self._get_addresses)
        self.clear_method(self._get_addresses_infos)
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        not_indexed_addresses = set(update_filter.addresses) - set(self.get_addresses())
        for not_indexed_address in not_indexed_addresses:
            self.advance_tip_to_address(not_indexed_address)

    def get_txout_of_outpoint(self, outpoint: OutPoint) -> Optional[TxOut]:
        tx_details = self.get_tx(outpoint.txid)
        if not tx_details or not tx_details.transaction:
            return None

        txouts = list(tx_details.transaction.output())
        if outpoint.vout > len(txouts) - 1:
            return None

        txout = txouts[outpoint.vout]
        return TxOut.from_bdk(txout)

    def get_address_of_outpoint(self, outpoint: OutPoint) -> Optional[str]:
        txout = self.get_txout_of_outpoint(outpoint)
        if not txout:
            return None
        return self.bdkwallet.get_address_of_txout(txout)

    def get_python_txo(self, outpoint_str: str) -> Optional[PythonUtxo]:
        all_txos_dict = self.get_all_txos_dict()
        return all_txos_dict.get(outpoint_str)

    def get_conflicting_python_txos(self, input_outpoints: Iterable[OutPoint]) -> List[PythonUtxo]:
        conflicting_python_utxos = []

        txos_dict = self.get_all_txos_dict()
        for input_outpoint in input_outpoints:
            if str(input_outpoint) in txos_dict:
                python_utxo = txos_dict[str(input_outpoint)]
                if python_utxo.is_spent_by_txid:
                    conflicting_python_utxos.append(python_utxo)
        return conflicting_python_utxos

    @instance_lru_cache()
    def sorted_delta_list_transactions(self, access_marker=None) -> List[TransactionDetails]:
        """
        Returns TransactionDetails sorted such that:
        1) All confirmed transactions come first, ordered by block height (oldest to newest).
           Within each block, parent transactions precede their children.
        2) All unconfirmed transactions follow, grouped by dependency chains so that each parent
           immediately precedes its children (and descendants).
        """
        # Fetch full transaction details mapping
        dict_full: Dict[str, FullTxDetail] = self.get_dict_fulltxdetail()

        # 1) Split into confirmed vs. unconfirmed using helper
        confirmed, unconfirmed, initial_transactions, local = self._split_by_confirmation(dict_full)

        # 2) Sort confirmed: by height + intra-block parent→child order
        sorted_confirmed: List[FullTxDetail] = self._sort_confirmed_transactions(confirmed)

        # 3) Sort unconfirmed: group dependency chains via DFS-topo
        sorted_unconfirmed: List[FullTxDetail] = self._sort_unconfirmed_transactions(unconfirmed)

        # 4) initial_transactions: sort according to their original order
        sorted_initial_transactions = self._sort_initial_transactions(initial_transactions)

        # 5) Sort local: group dependency chains via DFS-topo
        sorted_local: List[FullTxDetail] = self._sort_unconfirmed_transactions(local)

        # 6) Merge: confirmed first, then unconfirmed
        all_sorted: List[FullTxDetail] = (
            sorted_confirmed + sorted_unconfirmed + sorted_initial_transactions + sorted_local
        )
        return [fx.tx for fx in all_sorted]

    def _split_by_confirmation(
        self, dict_full: Dict[str, FullTxDetail]
    ) -> Tuple[List[FullTxDetail], List[FullTxDetail], List[FullTxDetail], List[FullTxDetail]]:
        """
        Splits the full-detail mapping into two lists:
        - confirmed: with a confirmed chain position
        - mempool: awaiting confirmation
        - local: local transactions
        """
        initial_transation_ids = [tx.compute_txid() for tx in self._initial_txs]

        confirmed: List[FullTxDetail] = []
        unconfirmed: List[FullTxDetail] = []
        initial_transactions: List[FullTxDetail] = []
        local: List[FullTxDetail] = []
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

    def _sort_confirmed_transactions(self, confirmed: List[FullTxDetail]) -> List[FullTxDetail]:
        """
        Orders confirmed transactions by block height, and within the same block,
        ensures parent transactions precede their children.
        """
        # Bucket confirmed txs by their block height
        conf_by_height: Dict[int, List[FullTxDetail]] = defaultdict(list)
        for fx in confirmed:
            assert isinstance(fx.tx.chain_position, bdk.ChainPosition.CONFIRMED)
            height: int = fx.tx.chain_position.confirmation_block_time.block_id.height  # type: ignore
            conf_by_height[height].append(fx)

        sorted_list: List[FullTxDetail] = []
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

    def _sort_unconfirmed_transactions(self, unconfirmed: List[FullTxDetail]) -> List[FullTxDetail]:
        """
        Topologically sorts unconfirmed transactions so that each parent precedes
        its children and deeper descendants.
        """
        # Mypy narrowing: all entries must be unconfirmed
        for fx in unconfirmed:
            assert not isinstance(fx.tx.chain_position, bdk.ChainPosition.CONFIRMED)
        return self._dfs_topo_sort(unconfirmed)

    def _sort_initial_transactions(self, initial_transactions: List[FullTxDetail]) -> List[FullTxDetail]:
        initial_transation_id_order = {tx.compute_txid(): i for i, tx in enumerate(self._initial_txs)}

        def sort_key(tx: FullTxDetail) -> int:
            return initial_transation_id_order.get(tx.txid, 0)

        return sorted(initial_transactions, key=sort_key)

    def _dfs_topo_sort(self, tx_list: List[FullTxDetail]) -> List[FullTxDetail]:
        """
        Return a *full* topological ordering of the given transactions.

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
        tx_map: Dict[str, FullTxDetail] = {fx.tx.txid: fx for fx in tx_list}
        children: DefaultDict[str, List[str]] = defaultdict(list)
        indegree: Dict[str, int] = {txid: 0 for txid in tx_map}

        for fx in tx_list:
            for inp in fx.inputs.values():
                if not inp:
                    continue
                parent_id = inp.outpoint.txid
                if parent_id in tx_map:  # dependency inside list
                    children[parent_id].append(fx.tx.txid)
                    indegree[fx.tx.txid] += 1

        roots: List[str] = [txid for txid, deg in indegree.items() if deg == 0]

        # ───────────────────── sort roots by lock-time (cluster order) ──────────────
        roots.sort(
            key=lambda tid: (
                tx_map[tid].tx.transaction.lock_time(),  # ➊ primary key
                tid,  # ➋ deterministic tiebreaker
            ),
            reverse=True,
        )

        # ──────────────────────── depth-first post-order walk ───────────────────────
        sorted_order: List[FullTxDetail] = []
        visited: Set[str] = set()

        def dfs(txid: str) -> None:
            """
            Post-order DFS that appends *after* visiting descendants,
            yielding a valid topological ordering once the list is reversed.

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
        return TxStatus.from_wallet(txid, self).is_in_mempool()

    def get_fulltxdetail_and_dependents(self, txid: str, include_root_tx=True) -> List[FullTxDetail]:
        result: List[FullTxDetail] = []
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
        """
        Calculate Exponential Moving Average (EMA) of the fee_rate of all transactions.

        It weights the outgoing transactions heavier than the incoming transactions,
        because Exchanges typically overpay fees.
        """
        all_txs = self.sorted_delta_list_transactions()
        weight_sent = 10
        weight_incoming = 1
        all_weights = [(weight_sent if tx.sent else weight_incoming) for tx in all_txs]

        fee_rates: List[float] = []
        weights: List[float] = []
        for weight, txdetail in zip(all_weights, all_txs):
            if fee_info := FeeInfo.from_txdetails(txdetail):
                fee_rates.append(fee_info.fee_rate())
                weights.append(weight)

        if not fee_rates:
            return default

        return calculate_ema(fee_rates, n=min(n, len(all_txs)), weights=weights)

    def get_category_python_txo_dict(self, include_spent=False) -> Dict[str, List[PythonUtxo]]:
        category_python_utxo_dict: Dict[str, List[PythonUtxo]] = {}

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
        """
        returns the first unspent output that can be used for cpfp

        If no unspent utxo is found it returns the first spent utxo
        """
        txid = tx.compute_txid()
        for vout, output in enumerate(tx.output()):
            python_utxo = self.get_python_txo(str(OutPoint(txid=txid, vout=vout)))
            if not python_utxo:
                continue
            if exclude_spent_utxos and python_utxo.is_spent_by_txid:
                continue
            return python_utxo
        return None

    def get_local_txs(self) -> Dict[str, TransactionDetails]:
        return {key: tx for key, tx in self.get_txs().items() if is_local(tx.chain_position)}

    def apply_unconfirmed_txs(self, txs: List[bdk.Transaction], last_seen: int = LOCAL_TX_LAST_SEEN):
        self.bdkwallet.apply_unconfirmed_txs([bdk.UnconfirmedTx(tx=tx, last_seen=last_seen) for tx in txs])
        self.persist()

    def close(self) -> None:
        pass


###########
# Functions that operatate on signals.get_wallets().values()


def get_wallets(signals: Signals) -> List[Wallet]:
    return list(signals.get_wallets().values())


def get_wallet(wallet_id: str, signals: Signals) -> Optional[Wallet]:
    return signals.get_wallets().get(wallet_id)


def get_wallet_of_address(address: str, signals: Signals) -> Optional[Wallet]:
    if not address:
        return None
    for wallet in get_wallets(signals):
        if wallet.is_my_address_with_peek(address):
            return wallet
    return None


def get_wallet_of_outpoints(outpoints: List[OutPoint], signals: Signals) -> Optional[Wallet]:
    wallets = get_wallets(signals)
    if not wallets:
        return None

    number_intersections = []
    for wallet in wallets:
        python_utxos = wallet.get_all_txos_dict().values()
        wallet_outpoints: List[OutPoint] = [utxo.outpoint for utxo in python_utxos]
        number_intersections.append(len(set(outpoints).intersection(set(wallet_outpoints))))

    if not any(number_intersections):
        # no intersections at all
        return None

    i = np.argmax(number_intersections)
    return wallets[i]


def get_label_from_any_wallet(
    label_type: LabelType,
    ref: str,
    signals: Signals,
    autofill_from_txs: bool,
    autofill_from_addresses: bool = False,
    wallets: List[Wallet] | None = None,
    verbose_label=False,
) -> Optional[str]:
    wallets = wallets if wallets is not None else get_wallets(signals)
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


def get_tx_details(txid: str, signals: Signals) -> Tuple[TransactionDetails, Wallet] | Tuple[None, None]:
    for wallet in get_wallets(signals):
        tx = wallet.get_tx(txid=txid)
        if tx:
            return tx, wallet
    return None, None


###########


class ToolsTxUiInfo:
    @staticmethod
    def fill_txo_dict_from_outpoints(
        txuiinfos: TxUiInfos, outpoints: List[OutPoint], wallets: List[Wallet]
    ) -> None:
        "Will include the txo even if it is spent already  (useful for rbf)"

        outpoint_dict = {
            outpoint_str: (python_utxo, wallet)
            for wallet in wallets
            for outpoint_str, python_utxo in wallet.get_all_txos_dict().items()
        }
        for outpoint in outpoints:
            if not str(outpoint) in outpoint_dict:
                logger.warning(f"no python_utxo found for outpoint {outpoint} ")
                continue
            python_utxo, wallet = outpoint_dict[str(outpoint)]
            txuiinfos.main_wallet_id = wallet.id
            txuiinfos.utxo_dict[outpoint] = python_utxo

    @staticmethod
    def fill_utxo_dict_from_categories(
        txuiinfos: TxUiInfos, categories: List[str], wallets: List[Wallet]
    ) -> None:
        "Will only include UTXOs, (not usefull for rbf)"
        for wallet in wallets:
            for utxo in wallet.get_all_utxos():
                address = utxo.address
                if wallet.labels.get_category(address) in categories:
                    txuiinfos.utxo_dict[utxo.outpoint] = utxo

    @staticmethod
    def get_likely_source_wallet(txuiinfos: TxUiInfos, signals: Signals) -> Optional[Wallet]:
        wallet_dict: Dict[str, Wallet] = signals.get_wallets()

        # trying to identitfy the wallet , where i should fill the send tab
        wallet = None
        if txuiinfos.main_wallet_id:
            wallet = wallet_dict.get(txuiinfos.main_wallet_id)
            if wallet:
                return wallet

        input_outpoints = [outpoint for outpoint in txuiinfos.utxo_dict.keys()]
        return get_wallet_of_outpoints(input_outpoints, signals)

    @staticmethod
    def pop_change_recipient(txuiinfos: TxUiInfos, wallet: Wallet) -> Optional[Recipient]:
        def get_change_address(addresses: List[str]) -> Optional[str]:
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
        fee_info: Optional[FeeInfo],
        network: bdk.Network,
        wallets: List[Wallet],
    ) -> TxUiInfos:

        outpoints = [OutPoint.from_bdk(inp.previous_output) for inp in tx.input()]

        txinfos = TxUiInfos()
        # inputs
        ToolsTxUiInfo.fill_txo_dict_from_outpoints(txinfos, outpoints, wallets=wallets)
        txinfos.spend_all_utxos = True
        # outputs
        checked_max_amount = len(tx.output()) == 1  # if there is only 1 recipient, there is no change address
        for txout in tx.output():
            out_address = robust_address_str_from_script(txout.script_pubkey, network)
            txinfos.recipients.append(
                Recipient(out_address, txout.value, checked_max_amount=checked_max_amount)
            )
        # fee rate
        txinfos.fee_rate = fee_info.fee_rate() if fee_info else None
        return txinfos
