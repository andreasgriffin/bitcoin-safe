import logging, os
from operator import ne
from time import time

from .signals import UpdateFilter

import functools

logger = logging.getLogger(__name__)

from collections import defaultdict
import bdkpython as bdk
from typing import Sequence, Set, Tuple
from .gui.qt.util import Message
import datetime
from .tx import TxBuilderInfos, TxUiInfos
from .util import (
    CacheManager,
    balance_dict,
    Satoshis,
    clear_cache,
    register_cache,
    timestamp_to_datetime,
    instance_lru_cache,
    replace_non_alphanumeric,
)
from .i18n import _
from typing import (
    TYPE_CHECKING,
    List,
    Optional,
    Tuple,
    Union,
    NamedTuple,
    Sequence,
    Dict,
    Any,
    Set,
    Iterable,
)
from .keystore import KeyStore, KeyStoreType, KeyStoreTypes
import bdkpython as bdk
from .pythonbdk_types import *
from .storage import Storage, ClassSerializer, BaseSaveableClass
from threading import Lock
from .descriptors import (
    AddressType,
    get_default_address_type,
    MultipathDescriptor,
)
import json
from .util import clean_list, Satoshis
from .config import UserConfig
import numpy as np
from .labels import Labels
from packaging import version
from .util import hash_string
from bitcoin_usb.address_types import DescriptorInfo


class TxConfirmationStatus(enum.Enum):
    CONFIRMED = 1
    UNCONFIRMED = 0
    UNCONF_PARENT = -1
    LOCAL = -2

    @classmethod
    def to_str(cls, status):
        if status == cls.CONFIRMED:
            return "Confirmed"
        if status == cls.UNCONFIRMED:
            return "Unconfirmed"
        if status == cls.UNCONF_PARENT:
            return "Unconfirmed parent"
        if status == cls.LOCAL:
            return "Local"


class TxStatus:
    def __init__(self, tx: bdk.TransactionDetails, get_height) -> None:
        self.tx = tx

        # from .util import (
        #     TX_HEIGHT_FUTURE,
        #     TX_HEIGHT_INF,
        #     TX_HEIGHT_LOCAL,
        #     TX_HEIGHT_UNCONF_PARENT,
        #     TX_HEIGHT_UNCONFIRMED,
        # )

        self.confirmation_status = TxConfirmationStatus.UNCONFIRMED
        if tx.confirmation_time:
            self.confirmation_status = TxConfirmationStatus.CONFIRMED

        self.confirmations = (
            get_height() - tx.confirmation_time.height + 1
            if tx.confirmation_time
            else 0
        )
        self.sort_id = (
            self.confirmations if self.confirmations else self.confirmation_status.value
        )


def locked(func):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return func(self, *args, **kwargs)

    return wrapper


def filename_clean(id, file_extension=".wallet"):
    import string, os

    def create_valid_filename(filename):
        basename = os.path.basename(filename)
        valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
        return "".join(c for c in basename if c in valid_chars) + file_extension

    return create_valid_filename(id)


# a wallet  during setup phase, with partial information
class ProtoWallet:
    def __init__(
        self,
        threshold: int,
        network: bdk.Network,
        signers: int = 1,
        keystores: List[KeyStore] = None,
        address_type: AddressType = None,
        gap=20,
        gap_change=5,
    ):
        super().__init__()

        self.threshold = threshold
        self.network = network

        self.gap = gap
        self.gap_change = gap_change

        initial_address_type = (
            address_type if address_type else get_default_address_type(signers > 1)
        )
        self.keystores: List[KeyStore] = (
            keystores
            if keystores is not None
            else [
                KeyStore(
                    None,
                    None,
                    initial_address_type.key_origin(network),
                    label=self.signer_names(threshold, i),
                )
                for i in range(signers)
            ]
        )

        self.set_address_type(initial_address_type)

    def get_mn_tuple(self):
        return self.threshold, len(self.keystores)

    @classmethod
    def from_descriptor(
        cls,
        string_descriptor: str,
        network: bdk.Network,
    ):
        "creates a ProtoWallet from the xpub (not xpriv)"

        info = DescriptorInfo.from_str(string_descriptor)
        keystores = [
            KeyStore(
                **spk_provider.__dict__,
                label=cls.signer_names(i=i, threshold=info.threshold),
            )
            for i, spk_provider in enumerate(info.spk_providers)
        ]
        return ProtoWallet(
            threshold=info.threshold,
            network=network,
            signers=len(info.spk_providers),
            keystores=keystores,
            address_type=info.address_type,
        )

    def set_address_type(self, address_type: AddressType):
        self.address_type = address_type

    @classmethod
    def signer_names(self, threshold: int, i: int):
        i += 1
        if i <= threshold:
            return f"Signer {i}"
        else:
            return f"Recovery Signer {i}"

    def set_gap(self, gap):
        self.gap = gap

    def to_multipath_descriptor(self):
        return MultipathDescriptor.from_keystores(
            self.threshold,
            spk_providers=self.keystores,
            address_type=self.address_type,
            network=self.network,
        )

    def set_number_of_keystores(self, n):

        if n > len(self.keystores):
            for i in range(len(self.keystores), n):
                self.keystores.append(
                    KeyStore(
                        None,
                        None,
                        self.address_type.key_origin(self.network),
                        label=self.signer_names(self.threshold, i),
                    )
                )
        elif n < len(self.keystores):
            for i in range(n, len(self.keystores)):
                self.keystores.pop()  # removes the last item

    def set_threshold(self, threshold):
        self.threshold = threshold

    def is_multisig(self):
        return len(self.keystores) > 1


class DeltaCacheEntry:
    def __init__(self) -> None:
        self.old = None
        self.appended = None
        self.removed = None
        self.new = None


class DeltaCacheListTransactions(DeltaCacheEntry):
    def __init__(self) -> None:
        super().__init__()
        self.old: List[bdk.TransactionDetails] = []
        self.appended: List[bdk.TransactionDetails] = []
        self.removed: List[bdk.TransactionDetails] = []
        self.new: List[bdk.TransactionDetails] = []


class BdkWallet(bdk.Wallet, CacheManager):
    """
    This is a caching wrapper around bdk.Wallet.
    It should not provide any logic.
    Only wrapping existing methods and minimal new methods useful for caching

    The exception is list_delta_transactions, which provides also deltas to a previous state, and is in a wider sense also caching.
    """

    def __init__(self, descriptor, change_descriptor, network, database_config):
        super().__init__(descriptor, change_descriptor, network, database_config)
        CacheManager.__init__(self)
        self._delta_cache: Dict[str, DeltaCacheEntry] = {}

    @instance_lru_cache(always_keep=True)
    def peek_addressinfo(
        self,
        index,
        is_change=False,
    ) -> bdk.AddressInfo:
        bdk_get_address = self.get_internal_address if is_change else self.get_address
        return bdk_get_address(bdk.AddressIndex.PEEK(index))

    @instance_lru_cache(always_keep=True)
    def peek_address(
        self,
        index,
        is_change=False,
    ) -> str:
        return self.peek_addressinfo(index, is_change=is_change).address.as_string()

    @instance_lru_cache()
    def list_unspent(self) -> List[bdk.LocalUtxo]:
        start_time = time()
        result = super().list_unspent()
        logger.debug(
            f"self.bdkwallet.list_unspent {len(result)} results in { time()-start_time}s"
        )

        return result

    @instance_lru_cache()
    def list_transactions(self, include_raw=True):
        start_time = time()
        res = super().list_transactions(include_raw=include_raw)
        logger.debug(f"list_transactions {len(res)} results in { time()-start_time}s")
        return res

    def list_delta_transactions(
        self, access_marker, include_raw=True
    ) -> DeltaCacheListTransactions:
        """
        access_marker is a unique key, that the history can be stored relative to this

        to call however only the minimal amount of times the underlying function, list_transactions is cached.
        When list_transactions is reset, the delta depends on the access_marker
        """

        key = "list_delta_transactions" + str(access_marker)
        entry = self._delta_cache[key] = self._delta_cache.get(
            key, DeltaCacheListTransactions()
        )
        entry.old = entry.new

        # start_time = time()
        entry.new = self.list_transactions(include_raw=include_raw)

        old_ids = [tx.txid for tx in entry.old]
        new_ids = [tx.txid for tx in entry.new]
        appended_ids = set(new_ids) - set(old_ids)
        removed_ids = set(old_ids) - set(new_ids)

        entry.appended = [tx for tx in entry.new if tx.txid in appended_ids]
        entry.removed = [tx for tx in entry.old if tx.txid in removed_ids]

        # logger.debug(
        #     f"self.bdkwallet.list_delta_transactions {len(entry.new)} results in { time()-start_time}s"
        # )
        return entry

    @instance_lru_cache(always_keep=True)
    def network(self):
        return super().network()

    @instance_lru_cache(always_keep=True)
    def get_address_of_txout(self, txout: TxOut) -> str:
        if txout.value == 0:
            return None
        else:
            return bdk.Address.from_script(
                txout.script_pubkey, self.network()
            ).as_string()


class Wallet(BaseSaveableClass, CacheManager):
    """
    If any bitcoin logic (ontop of bdk) has to be done, then here is the place
    """

    VERSION = "0.1.1"
    global_variables = globals()

    def __init__(
        self,
        id,
        descriptor_str: str,
        keystores: List[KeyStore] = None,
        gap=20,
        gap_change=20,
        labels: Labels = None,
        network: bdk.Network = None,
        config: UserConfig = None,
        _blockchain_height=None,
        _tips=None,
        refresh_wallet=False,
        tutorial_step=None,
        **kwargs,
    ):
        super().__init__()
        CacheManager.__init__(self)

        self.bdkwallet: BdkWallet = None
        self.id = id
        self.network = network if network else config.network_settings.network
        # prevent loading a wallet into different networks
        assert (
            self.network == config.network_settings.network
        ), f"Cannot load a wallet for {self.network}, when the network {config.network_settings.network} is configured"
        self.gap = gap
        self.gap_change = gap_change
        self.descriptor_str: str = descriptor_str
        self.config = config
        self.write_lock = Lock()
        self.labels: Labels = labels if labels else Labels()
        # refresh dependent values
        self._tips = _tips if _tips and not refresh_wallet else [0, 0]
        self._blockchain_height = (
            _blockchain_height if _blockchain_height and not refresh_wallet else 0
        )
        self.tutorial_step = tutorial_step

        if refresh_wallet and os.path.isfile(self._db_file()):
            os.remove(self._db_file())
        self.refresh_wallet = False
        # end refresh dependent values

        descriptor_keystores = ProtoWallet.from_descriptor(
            self.descriptor_str, network=self.network
        ).keystores
        self.keystores: List[KeyStore] = (
            keystores if keystores is not None else descriptor_keystores
        )
        for keystore, descriptor_keystore in zip(self.keystores, descriptor_keystores):
            keystore.merge_with(descriptor_keystore)

        self.create_wallet(
            MultipathDescriptor.from_descriptor_str(descriptor_str, self.network)
        )
        self.blockchain = None
        self.clear_cache()

    def clear_cache(self, clear_always_keep=False):
        self.cache_dict_fulltxdetail: Dict[str, FullTxDetail] = {}  # txid:FullTxDetail
        self.cache_address_to_txids: Dict[str, set[str]] = defaultdict(
            set
        )  # address:[txid]

        self.clear_instance_cache(clear_always_keep=clear_always_keep)
        self.bdkwallet.clear_instance_cache(clear_always_keep=clear_always_keep)

    @instance_lru_cache()
    def _get_addresses(
        self,
        is_change=False,
    ) -> Sequence[str]:
        if (not is_change) and (not self.multipath_descriptor):
            return []
        return [
            self.bdkwallet.peek_address(i, is_change=is_change)
            for i in range(0, self.tips[int(is_change)] + 1)
        ]

    def get_mn_tuple(self):
        info = DescriptorInfo.from_str(self.multipath_descriptor.as_string())
        return info.threshold, len(info.spk_providers)

    def as_protowallet(self):
        # fill the protowallet with the xpub info
        protowallet = ProtoWallet.from_descriptor(
            self.descriptor_str, network=self.network
        )
        # fill all fields that the public info doesn't contain
        if self.keystores:
            # fill the fields, that the descrioptor doesn't contain
            for own_keystore, keystore in zip(self.keystores, protowallet.keystores):
                keystore.mnemonic = own_keystore.mnemonic
                keystore.description = own_keystore.description
                keystore.label = own_keystore.label
        return protowallet

    @classmethod
    def from_protowallet(
        cls, protowallet: ProtoWallet, id: str, config: UserConfig, tutorial_step=None
    ):

        multipath_descriptor = protowallet.to_multipath_descriptor()
        for keystore in protowallet.keystores:
            if keystore.key_origin != protowallet.address_type.key_origin(
                config.network_settings.network
            ):
                logger.warning(
                    f"Warning: The derivation path of {keystore} is not the default"
                )

        return Wallet(
            id,
            multipath_descriptor.as_string_private(),
            keystores=[k.clone() for k in protowallet.keystores],
            gap=protowallet.gap,
            gap_change=protowallet.gap_change,
            network=protowallet.network,
            config=config,
            tutorial_step=tutorial_step,
        )

    def serialize(self):
        d = super().serialize()

        keys = [
            "id",
            "gap",
            "network",
            "gap_change",
            "keystores",
            "labels",
            "descriptor_str",
            "_blockchain_height",
            "_tips",
            "refresh_wallet",
            "tutorial_step",
        ]
        for k in keys:
            d[k] = self.__dict__[k]

        return d

    @classmethod
    def load(cls, filename, config: UserConfig, password=None):
        return super().load(
            filename=filename,
            password=password,
            class_kwargs={"Wallet": {"config": config}},
        )

    @classmethod
    def deserialize_migration(cls, dct: Dict):
        "this class should be oveerwritten in child classes"
        if version.parse(str(dct["VERSION"])) <= version.parse("0.1.0"):
            if "labels" in dct:
                # no real migration. Just delete old data
                del dct["labels"]

            labels = Labels()
            for k, v in dct.get("category", {}).items():
                labels.set_addr_category(k, v)

            del dct["category"]
            dct["labels"] = labels

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    @classmethod
    def deserialize(cls, dct, class_kwargs=None):
        super().deserialize(dct, class_kwargs=class_kwargs)
        config: UserConfig = class_kwargs[cls.__name__][
            "config"
        ]  # passed via class_kwargs

        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        return Wallet(**dct)

    def set_gap(self, gap):
        self.gap = gap

    def set_wallet_id(self, id):
        self.id = id

    def _db_file(self):
        return f"{os.path.join(self.config.wallet_dir, filename_clean(self.id, file_extension='.db'))}"

    def create_wallet(self, multipath_descriptor: MultipathDescriptor):
        self.multipath_descriptor = multipath_descriptor

        self.bdkwallet = BdkWallet(
            descriptor=self.multipath_descriptor.bdk_descriptors[0],
            change_descriptor=self.multipath_descriptor.bdk_descriptors[1],
            network=self.config.network_settings.network,
            database_config=bdk.DatabaseConfig.MEMORY(),
            # database_config=bdk.DatabaseConfig.SQLITE(
            #     bdk.SqliteDbConfiguration(self._db_file())
            # ),
        )

    def is_multisig(self):
        return len(self.keystores) > 1

    def get_tx_status(self, tx: bdk.TransactionDetails) -> TxStatus:
        return TxStatus(tx, self.get_height)

    def init_blockchain(self):
        if self.config.network_settings.network == bdk.Network.BITCOIN:
            start_height = 0  # segwit block 481824
        elif self.config.network_settings.network in [
            bdk.Network.REGTEST,
            bdk.Network.SIGNET,
        ]:
            start_height = 0
        elif self.config.network_settings.network == bdk.Network.TESTNET:
            start_height = 2000000

        if self.config.network_settings.server_type == BlockchainType.Electrum:
            blockchain_config = bdk.BlockchainConfig.ELECTRUM(
                bdk.ElectrumConfig(
                    self.config.network_settings.electrum_url,
                    None,
                    2,
                    10,
                    max(self.gap, self.gap_change),
                    False,
                )
            )
        elif self.config.network_settings.server_type == BlockchainType.Esplora:
            blockchain_config = bdk.BlockchainConfig.ESPLORA(
                bdk.EsploraConfig(
                    self.config.network_settings.esplora_url,
                    None,
                    1,
                    max(self.gap, self.gap_change),
                    10,
                )
            )
        elif (
            self.config.network_settings.server_type
            == BlockchainType.CompactBlockFilter
        ):
            folder = f"./compact-filters-{self.id}-{self.config.network_settings.network.name}"
            blockchain_config = bdk.BlockchainConfig.COMPACT_FILTERS(
                bdk.CompactFiltersConfig(
                    [
                        f"{self.config.network_settings.compactblockfilters_ip}:{self.config.network_settings.compactblockfilters_port}"
                    ]
                    * 5,
                    self.config.network_settings.network,
                    folder,
                    start_height,
                )
            )
        elif self.config.network_settings.server_type == BlockchainType.RPC:
            blockchain_config = bdk.BlockchainConfig.RPC(
                bdk.RpcConfig(
                    f"{self.config.network_settings.rpc_ip}:{self.config.network_settings.rpc_port}",
                    bdk.Auth.USER_PASS(
                        self.config.network_settings.rpc_username,
                        self.config.network_settings.rpc_password,
                    ),
                    self.config.network_settings.network,
                    self._get_uniquie_wallet_id(),
                    bdk.RpcSyncParams(0, 0, False, 10),
                )
            )
        self.blockchain = bdk.Blockchain(blockchain_config)
        return self.blockchain

    def _get_uniquie_wallet_id(self):
        return f"{replace_non_alphanumeric(self.id)}-{hash_string(self.descriptor_str)}"

    def sync(self, progress_function_threadsafe=None):
        if self.blockchain is None:
            self.init_blockchain()

        if not progress_function_threadsafe:

            def progress_function_threadsafe(progress: float, message: str):
                logger.info((progress, message))

        progress = bdk.Progress()
        progress.update = progress_function_threadsafe

        try:
            start_time = time()
            self.bdkwallet.sync(self.blockchain, progress)
            logger.debug(f"{self.id} self.bdkwallet.sync in { time()-start_time}s")
            logger.info(
                f"Wallet balance is: { balance_dict(self.bdkwallet.get_balance()) }"
            )
        except Exception as e:
            logger.debug(f"{self.id} error syncing wallet {self.id}")
            raise e

    def reverse_search_unused_address(
        self, category=None, is_change=False
    ) -> bdk.AddressInfo:

        earliest_address_info = None
        for index, address_str in reversed(
            list(enumerate(self._get_addresses(is_change=is_change)))
        ):

            if self.address_is_used(address_str) or self.labels.get_label(address_str):
                break
            else:
                if not category or (
                    category and self.labels.get_category(address_str) == category
                ):
                    earliest_address_info = self.bdkwallet.peek_addressinfo(
                        index, is_change=is_change
                    )
        return earliest_address_info

    def get_unused_category_address(self, category, is_change=False) -> bdk.AddressInfo:
        if category is None:
            category = self.labels.get_default_category()

        address_info = self.reverse_search_unused_address(
            category=category, is_change=is_change
        )
        if address_info:
            return address_info

        address_info = self.get_address(force_new=True, is_change=is_change)
        self.labels.set_addr_category(address_info.address.as_string(), category)
        return address_info

    def get_address(self, force_new=False, is_change=False) -> bdk.AddressInfo:
        "Gives an unused address reverse searched from the tip"

        def get_force_new_address():
            address_info = bdk_get_address(bdk.AddressIndex.NEW())
            index = address_info.index
            self._tips[int(is_change)] = index

            logger.info(f"advanced_tip to {self._tips}  , is_change={is_change}")
            return address_info

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )

        if force_new:
            return get_force_new_address()

        # try finding an unused one
        address_info = self.reverse_search_unused_address(is_change=is_change)
        if address_info:
            return address_info

        # create a new address
        return get_force_new_address()

    def get_output_addresses(self, transaction: bdk.Transaction) -> List[str]:
        # print(f'Getting output addresses for txid {transaction.txid}')
        return [
            self.bdkwallet.get_address_of_txout(TxOut.from_bdk(output))
            for output in transaction.output()
        ]

    def get_txin_address(self, txin):
        previous_output = txin.previous_output
        tx = self.get_tx(previous_output.txid)
        if tx:
            output_for_input = tx.transaction.output()[previous_output.vout]
            return bdk.Address.from_script(
                output_for_input.script_pubkey, self.config.network_settings.network
            )
        else:
            return None

    def fill_commonly_used_caches(self):
        i = 0
        new_addresses_were_watched = True
        # you have to repeat fetching new tx when you start watching new addresses
        # And you can only start watching new addresses once you detected transactions on them.
        # Thas why this fetching has to be done in a loop
        while new_addresses_were_watched:
            if i > 0:
                self.clear_cache()
            self.get_addresses()

            advanced_tips = self.extend_tips_by_gap()
            logger.debug(f"{self.id} tips were advanced by {advanced_tips}")
            new_addresses_were_watched = any(advanced_tips)
            i += 1
            if i > 100:
                break
        self.bdkwallet.list_unspent()
        self.get_dict_fulltxdetail()

    @instance_lru_cache()
    def get_txs(self) -> Dict[str, bdk.TransactionDetails]:
        return {tx.txid: tx for tx in self.sorted_delta_list_transactions()}

    @instance_lru_cache()
    def get_tx(self, txid) -> bdk.TransactionDetails:
        return self.get_txs().get(txid)

    def list_input_bdk_addresses(self, transaction: bdk.Transaction) -> List[str]:
        addresses = []
        for tx_in in transaction.input():
            previous_output = tx_in.previous_output
            tx = self.get_tx(previous_output.txid)
            if tx:
                output_for_input = tx.transaction.output()[previous_output.vout]

                add = bdk.Address.from_script(
                    output_for_input.script_pubkey, self.config.network_settings.network
                ).as_string()
            else:
                add = None

            addresses.append(add)
        return addresses

    def list_tx_addresses(self, transaction: bdk.Transaction) -> Dict[str, List[str]]:
        return {
            "in": self.list_input_bdk_addresses(transaction),
            "out": self.get_output_addresses(transaction),
        }

    def transaction_involves_wallet(self, transaction: bdk.Transaction):
        addresses = self.get_addresses()
        for tx_addresses in self.list_tx_addresses(transaction).values():
            if set(addresses).intersection(set([a for a in tx_addresses if a])):
                return True

        return False

    def used_address_tip(self, is_change):
        def reverse_search_used(tip_index):
            for i in reversed(range(tip_index)):
                addresses = self._get_addresses(is_change=is_change)
                if len(addresses) - 1 < i:
                    continue
                if self.address_is_used(addresses[i]):
                    return i
            return 0

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )
        return reverse_search_used(
            bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index
        )

    def _get_bdk_tip(self, is_change) -> int:
        if not self.bdkwallet:
            return self._tips[int(is_change)]

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )
        return bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index

    def _get_tip(self, is_change) -> int:
        if not self.bdkwallet:
            return self._tips[int(is_change)]

        bdk_tip = self._get_bdk_tip(is_change=is_change)

        if self._tips[int(is_change)] > bdk_tip:
            self._extend_tip(
                is_change=is_change, number=self._tips[int(is_change)] - bdk_tip
            )
        else:
            self._tips[int(is_change)] = bdk_tip

        return self._tips[int(is_change)]

    def _extend_tip(self, is_change, number):
        assert number >= 0, "Cannot reduce the watched addresses"
        if number == 0:
            return

        with self.write_lock:
            bdk_get_address = (
                self.bdkwallet.get_internal_address
                if is_change
                else self.bdkwallet.get_address
            )

            logger.debug(f"{self.id} indexing {number} new addresses")

            def add_new_address() -> bdk.AddressInfo:
                address_info: bdk.AddressInfo = bdk_get_address(bdk.AddressIndex.NEW())
                logger.debug(
                    f"{self.id} Added {'change' if is_change else ''} address with index {address_info.index}"
                )
                return address_info

            new_address_infos = [add_new_address() for i in range(number)]

            for address_info in new_address_infos:
                self.labels.set_addr_category_default(address_info.address.as_string())

        self.clear_cache()

    def extend_tips_by_gap(self) -> Tuple[int, int]:
        "Returns [number of added addresses, number of added change addresses]"
        change_tip = [0, 0]
        for is_change in [False, True]:
            gap = self.gap_change if is_change else self.gap
            tip = self._get_tip(is_change=is_change)
            used_tip = self.used_address_tip(is_change=is_change)
            # there is always 1 unused_addresses_dangling
            unused_addresses_dangling = tip - used_tip
            if unused_addresses_dangling < gap:
                number = gap - unused_addresses_dangling
                self._extend_tip(is_change=is_change, number=number)
                change_tip[int(is_change)] = number
        return change_tip

    @property
    def tips(self):
        return [self._get_tip(b) for b in [False, True]]

    def get_receiving_addresses(self) -> Sequence[str]:
        return self._get_addresses(is_change=False)

    def get_change_addresses(self) -> Sequence[str]:
        return self._get_addresses(is_change=True)

    # do not cach this!!! it will lack behind when a psbt extends the change tip
    def get_addresses(self) -> Sequence[str]:
        # note: overridden so that the history can be cleared.
        # addresses are ordered based on derivation
        out = self.get_receiving_addresses().copy()
        out += self.get_change_addresses().copy()
        return out

    def is_change(self, address):
        return address in self.get_change_addresses()

    def get_address_index_tuple(
        self, address: str, keychain: bdk.KeychainKind
    ) -> Tuple[bool, int]:
        "(is_change, index)"
        if keychain == bdk.KeychainKind.EXTERNAL:
            addresses = self.get_receiving_addresses()
            if address in addresses:
                return (0, addresses.index(address))
        else:
            addresses = self.get_change_addresses()
            if address in addresses:
                return (1, addresses.index(address))

    def address_info_min(self, address: str) -> AddressInfoMin:
        keychain = bdk.KeychainKind.EXTERNAL
        index_tuple = self.get_address_index_tuple(address, keychain)
        if index_tuple is None:
            keychain = bdk.KeychainKind.INTERNAL
            index_tuple = self.get_address_index_tuple(address, keychain)

        if index_tuple is not None:
            return AddressInfoMin(address, index_tuple[1], keychain)

    def utxo_of_outpoint(self, outpoint: bdk.OutPoint) -> bdk.LocalUtxo:
        for utxo in self.bdkwallet.list_unspent():
            if OutPoint.from_bdk(outpoint) == OutPoint.from_bdk(utxo.outpoint):
                return utxo

    @instance_lru_cache()
    def get_address_balances(self) -> Dict[AddressInfoMin, Tuple[int, int, int]]:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """

        def zero_balances():
            return [0, 0, 0]

        def is_confirmed(txid):
            tx_details = self.get_tx(txid)
            return tx_details.confirmation_time

        utxos = self.bdkwallet.list_unspent()

        balances: Dict[str, Tuple[int, int, int]] = defaultdict(zero_balances)
        for i, utxo in enumerate(utxos):
            tx = self.get_tx(utxo.outpoint.txid)
            txout: bdk.TxOut = tx.transaction.output()[utxo.outpoint.vout]

            address = self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
            if address is None:
                continue

            if is_confirmed(tx.txid):
                balances[address][0] += txout.value
            else:
                balances[address][1] += txout.value
            balances[address][2] += 0

        return balances

    @instance_lru_cache()
    def get_addr_balance(self, address):
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]

    def get_address_to_txids(self, address):
        # this also fills self.cache_address_to_txids
        self.get_dict_fulltxdetail()
        return self.cache_address_to_txids.get(address, set())

    def get_dict_fulltxdetail(self) -> Dict[str, FullTxDetail]:
        """
        Createa a map of txid : to FullTxDetail

        Returns:
            FullTxDetail
        """
        start_time = time()
        delta_txs = self.bdkwallet.list_delta_transactions(
            access_marker="get_dict_fulltxdetail"
        )

        # if transactions were removed (reorg or other), then recalculate everything
        if delta_txs.removed or not self.cache_dict_fulltxdetail:
            self.cache_dict_fulltxdetail = {}
            txs = delta_txs.new
        else:
            txs = delta_txs.appended

        def append_dicts(txid, python_utxos: List[PythonUtxo]):
            for python_utxo in python_utxos:
                if not python_utxo:
                    continue
                self.cache_address_to_txids[python_utxo.address].add(txid)

        def process_outputs(tx: bdk.TransactionDetails):
            fulltxdetail = FullTxDetail.fill_received(tx, self.bdkwallet)
            if fulltxdetail.txid in self.cache_dict_fulltxdetail:
                logger.error(
                    f"Trying to add a tx with txid {fulltxdetail.txid} twice. "
                )
            return fulltxdetail.txid, fulltxdetail

        def process_inputs(tx: bdk.TransactionDetails):
            "this must be done AFTER process_outputs"
            txid = tx.txid
            fulltxdetail = self.cache_dict_fulltxdetail[txid]
            fulltxdetail.fill_inputs(self.cache_dict_fulltxdetail)
            return txid, fulltxdetail

        key_value_pairs = list(map(process_outputs, txs))

        self.cache_dict_fulltxdetail.update(key_value_pairs)
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, fulltxdetail.outputs.values())

        # speed test for wallet 600 transactions (with many inputs each) without profiling:
        # map : 2.714s
        # for loop:  2.76464
        # multithreading : 6.3021s
        key_value_pairs = list(map(process_inputs, txs))
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, fulltxdetail.inputs.values())

        if txs:
            logger.debug(
                f"get_dict_fulltxdetail  with {len(txs)} txs in {time()-  start_time}"
            )

        return self.cache_dict_fulltxdetail

    @instance_lru_cache()
    def address_is_used(self, address):
        """
        Check if any tx had this address as an output
        """
        return bool(self.get_address_to_txids(address))

    def get_address_path_str(self, address) -> str:
        index = None
        is_change = None
        if address in self.get_receiving_addresses():
            index = self.get_receiving_addresses().index(address)
            is_change = False
        if address in self.get_change_addresses():
            index = self.get_change_addresses().index(address)
            is_change = True

        if not index:
            return ""

        addresses_info = self.bdkwallet.peek_addressinfo(index, is_change=is_change)
        public_descriptor_string_combined = self.multipath_descriptor.as_string().replace(
            "<0;1>/*",
            f"{0 if  addresses_info.keychain==bdk.KeychainKind.EXTERNAL else 1}/{addresses_info.index}",
        )
        return public_descriptor_string_combined

    def get_redeem_script(self, address):
        # TODO:
        return None

    def get_witness_script(self, address):
        return None

    def get_categories_for_txid(self, txid):
        fulltxdetail = self.get_dict_fulltxdetail().get(txid)
        if not fulltxdetail:
            return []

        l = np.unique(
            clean_list(
                [
                    self.labels.get_category(python_utxo.address)
                    for python_utxo in fulltxdetail.outputs.values()
                    if python_utxo
                ]
            )
        )
        return list(l)

    def get_label_for_address(self, address, autofill_from_txs=True):
        label = self.labels.get_label(address, "")

        if not label and autofill_from_txs:
            txids = self.get_address_to_txids(address)

            tx_labels = clean_list(
                [
                    self.get_label_for_txid(txid, autofill_from_addresses=False)
                    for txid in txids
                ]
            )
            label = ", ".join(tx_labels)

        return label

    def get_label_for_txid(self, txid, autofill_from_addresses=True):
        label = self.labels.get_label(txid, "")

        if not label and autofill_from_addresses:
            fulltxdetail = self.get_dict_fulltxdetail().get(txid)
            if not fulltxdetail:
                return label

            address_labels = clean_list(
                [
                    self.get_label_for_address(python_utxo.address)
                    for python_utxo in fulltxdetail.outputs.values()
                    if python_utxo
                ]
            )
            label = ", ".join(address_labels)

        return label

    def get_balances_for_piechart(self):
        """
        (_('On-chain'), COLOR_CONFIRMED, confirmed),
        (_('Unconfirmed'), COLOR_UNCONFIRMED, unconfirmed),
        (_('Unmatured'), COLOR_UNMATURED, unmatured),

        # see https://docs.rs/bdk/latest/bdk/struct.Balance.html
        """

        balance = self.bdkwallet.get_balance()
        return [
            Satoshis(balance.confirmed, self.network),
            Satoshis(balance.trusted_pending + balance.untrusted_pending, self.network),
            Satoshis(balance.immature, self.network),
        ]

    def get_utxo_name(self, utxo):
        tx = self.get_tx(utxo.outpoint.txid)
        return f"{tx.txid}:{utxo.outpoint.vout}"

    def get_utxo_address(self, utxo):
        tx = self.get_tx(utxo.outpoint.txid)
        return self.get_output_addresses(tx.transaction)[utxo.outpoint.vout]

    @instance_lru_cache()
    def get_height(self):
        if self.blockchain:
            # update the cached height
            self._blockchain_height = self.blockchain.get_height()
        return self._blockchain_height

    def minimalistic_coin_select(self, utxos, total_sent_value) -> UtxosForInputs:
        # coin selection
        utxos = list(utxos).copy()
        sorted_utxos = sorted(utxos, key=lambda utxo: utxo.txout.value, reverse=True)

        selected_utxos = []
        selected_value = 0
        for utxo in sorted_utxos:
            selected_value += utxo.txout.value
            selected_utxos.append(utxo)
            if selected_value >= total_sent_value:
                break
        logger.debug(
            f"Selected {len(selected_utxos)} outpoints with {Satoshis(selected_value, self.network).str_with_unit()}"
        )

        return UtxosForInputs(
            utxos=selected_utxos,
            spend_all_utxos=True,
        )

    def coin_select(
        self, utxos, total_sent_value, opportunistic_merge_utxos
    ) -> UtxosForInputs:
        def utxo_value(utxo: bdk.LocalUtxo):
            return utxo.txout.value

        def is_outpoint_in_list(outpoint, utxos):
            outpoint = OutPoint.from_bdk(outpoint)
            for utxo in utxos:
                if outpoint == OutPoint.from_bdk(utxo.outpoint):
                    return True
            return False

        # coin selection
        utxos = list(utxos).copy()
        np.random.shuffle(utxos)
        selected_utxos = []
        selected_value = 0
        opportunistic_merging_utxos = []
        for utxo in utxos:
            selected_value += utxo.txout.value
            selected_utxos.append(utxo)
            if selected_value >= total_sent_value:
                break
        logger.debug(
            f"Selected {len(selected_utxos)} outpoints with {Satoshis(selected_value, self.network).str_with_unit()}"
        )

        # now opportunistically  add additional outputs for merging
        if opportunistic_merge_utxos:
            non_selected_utxos = [
                utxo
                for utxo in utxos
                if not is_outpoint_in_list(utxo.outpoint, selected_utxos)
            ]

            # never choose more than half of all remaining outputs
            number_of_opportunistic_outpoints = (
                np.random.randint(0, len(non_selected_utxos) // 2)
                if len(non_selected_utxos) // 2 > 0
                else 0
            )

            opportunistic_merging_utxos = sorted(non_selected_utxos, key=utxo_value)[
                :number_of_opportunistic_outpoints
            ]
            logger.debug(
                f"Selected {len(opportunistic_merging_utxos)} additional opportunistic outpoints with small values (so total ={len(selected_utxos)+len(opportunistic_merging_utxos)}) with {Satoshis(sum([utxo.txout.value for utxo in opportunistic_merging_utxos]), self.network).str_with_unit()}"
            )

        return UtxosForInputs(
            utxos=selected_utxos + opportunistic_merging_utxos,
            included_opportunistic_merging_utxos=opportunistic_merging_utxos,
            spend_all_utxos=True,
        )

    def handle_opportunistic_merge_utxos(self, txinfos: TxUiInfos) -> UtxosForInputs:
        "This does the initial coin selection if opportunistic_merge_utxos"
        utxos_for_input = UtxosForInputs(
            txinfos.utxo_dict.values(), spend_all_utxos=txinfos.spend_all_utxos
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
            return self.coin_select(
                utxos=utxos_for_input.utxos,
                total_sent_value=total_sent_value,
                opportunistic_merge_utxos=txinfos.opportunistic_merge_utxos,
            )
        else:
            # otherwise let the bdk wallet decide on the minimal coins to be spent, out of the utxos
            return UtxosForInputs(utxos=utxos_for_input.utxos, spend_all_utxos=False)

    def is_my_address(self, address):
        return address in self.get_addresses()

    def create_psbt(self, txinfos: TxUiInfos) -> TxBuilderInfos:
        builder_infos = TxBuilderInfos()
        builder_infos.recipients = txinfos.recipients.copy()

        tx_builder = bdk.TxBuilder()
        tx_builder = tx_builder.enable_rbf()
        tx_builder = tx_builder.fee_rate(txinfos.fee_rate)

        builder_infos.utxos_for_input: UtxosForInputs = (
            self.handle_opportunistic_merge_utxos(txinfos)
        )
        selected_outpoints = [
            OutPoint.from_bdk(utxo.outpoint)
            for utxo in builder_infos.utxos_for_input.utxos
        ]

        if builder_infos.utxos_for_input.spend_all_utxos:
            # spend_all_utxos requires using add_utxo
            tx_builder = tx_builder.manually_selected_only()
            # add coins that MUST be spend
            for outpoint in selected_outpoints:
                tx_builder = tx_builder.add_utxo(outpoint)
                # TODO no add_foreign_utxo yet: see https://github.com/bitcoindevkit/bdk-ffi/issues/329 https://docs.rs/bdk/latest/bdk/wallet/tx_builder/struct.TxBuilder.html#method.add_foreign_utxo
            # manually add a change output for draining all added utxos
            tx_builder = tx_builder.drain_to(
                self.get_address(is_change=True).address.script_pubkey()
            )
        else:
            # exclude all other coins, to leave only selected_outpoints to choose from
            unspendable_outpoints = [
                utxo.outpoint
                for utxo in self.bdkwallet.list_unspent()
                if OutPoint.from_bdk(utxo.outpoint) not in selected_outpoints
            ]
            tx_builder = tx_builder.unspendable(unspendable_outpoints)

        for recipient in txinfos.recipients:
            if recipient.checked_max_amount:
                if len(txinfos.recipients) == 1:
                    tx_builder = tx_builder.drain_wallet()
                tx_builder = tx_builder.drain_to(
                    bdk.Address(recipient.address).script_pubkey()
                )
            else:
                tx_builder = tx_builder.add_recipient(
                    bdk.Address(recipient.address).script_pubkey(), recipient.amount
                )

        start_time = time()
        builder_result: bdk.TxBuilderResult = tx_builder.finish(self.bdkwallet)
        logger.debug(f"{self.id} tx_builder.finish  in { time()-start_time}s")

        # inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()

        logger.info(json.loads(builder_result.psbt.json_serialize()))
        logger.debug(
            f"psbt fee after finalized {builder_result.psbt.fee_rate().as_sat_per_vb()}"
        )

        # get category of first utxo
        categories = clean_list(
            sum(
                [
                    list(self.get_categories_for_txid(utxo.outpoint.txid))
                    for utxo in builder_infos.utxos_for_input.utxos
                ],
                [],
            )
        )
        builder_infos.recipient_category = categories[0] if categories else None
        logger.debug(
            f"Selecting category {builder_infos.recipient_category} out of {categories} for the output addresses"
        )

        labels = [
            recipient.label for recipient in txinfos.recipients if recipient.label
        ]
        if labels:
            self.labels.set_tx_label(
                builder_result.transaction_details.txid, ",".join(labels)
            )

        builder_infos.builder_result = builder_result
        self.set_output_categories_and_labels(builder_infos)
        return builder_infos

    def on_addresses_updated(self, update_filter: UpdateFilter, forward_look=20):
        """
        Checks if the tip reaches the addresses and updated the tips if necessary
        (This is especially relevant if a psbt creates a new change address)
        """
        pass
        self.clear_method(self._get_addresses)

    def set_output_categories_and_labels(self, infos: TxBuilderInfos):
        # set category for all outputs
        self._set_category_for_all_recipients(
            infos.builder_result.psbt.extract_tx().output(),
            infos.recipient_category,
        )

        # set label for the recipient output
        for recipient in infos.recipients:
            # this does not include the change output
            if recipient.label and self.is_my_address(recipient.address):
                self.labels.set_addr_label(recipient.address, recipient.label)

        # add a label for the change output
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        for txout in infos.builder_result.psbt.extract_tx().output():
            address = self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
            if not self.is_change(address):
                continue
            if address and labels and self.is_my_address(address):
                self.labels.set_addr_label(address, ",".join(labels))

    def _set_category_for_all_recipients(self, outputs: List[bdk.TxOut], category: str):
        "Will assign all outputs (also change) the category"
        if not category:
            return

        recipients = [
            Recipient(
                address=bdk.Address.from_script(
                    output.script_pubkey, self.network
                ).as_string(),
                amount=output.value,
            )
            for output in outputs
        ]

        for recipient in recipients:
            if self.is_my_address(recipient.address):
                self.labels.set_addr_category(recipient.address, category)
                self.labels.add_category(category)

    def get_category_utxo_dict(self) -> Dict[str, List[bdk.LocalUtxo]]:
        d = {}
        for utxo in self.bdkwallet.list_unspent():
            address = self.get_utxo_address(utxo)
            category = self.labels.get_category(address)
            if category not in d:
                d[category] = []
            d[category].append(utxo)
        return d

    def _get_conflicting_input_utxos(
        self, input_outpoints: List[OutPoint]
    ) -> List[bdk.LocalUtxo]:
        conflicting_input_utxos = []

        wallet_utxos = self.bdkwallet.list_unspent()
        wallet_outpoints: List[OutPoint] = [
            OutPoint.from_bdk(utxo.outpoint) for utxo in wallet_utxos
        ]

        for outpoint in input_outpoints:
            if outpoint in wallet_outpoints:
                utxo = wallet_utxos[wallet_outpoints.index(outpoint)]
                if utxo.is_spent:
                    conflicting_input_utxos.append(utxo)
        return conflicting_input_utxos

    def get_conflicting_tx_inputs(self, tx: bdk.Transaction):
        if tx.txid() in self.get_txs():
            return []

        conflicting_input_utxos = self._get_conflicting_input_utxos(
            [OutPoint.from_bdk(inp.previous_output) for inp in tx.input()],
        )
        return conflicting_input_utxos

    @instance_lru_cache()
    def sorted_delta_list_transactions(
        self, access_marker=None
    ) -> List[bdk.TransactionDetails]:
        def check_relation(child: FullTxDetail, parent: FullTxDetail):
            for inp in child.inputs.values():
                if not inp:
                    continue
                this_parent_txid = inp.outpoint.txid
                if this_parent_txid == parent.txid:
                    # if the parent is found already
                    return True
                this_parent = dict_fulltxdetail.get(this_parent_txid)
                if this_parent:
                    relation = check_relation(this_parent, parent)
                    if relation:
                        return True

            return False

        def compare_items(item1: FullTxDetail, item2: FullTxDetail):
            future_height = 1e9  # that is far in the future

            c1 = (
                item1.tx.confirmation_time.height
                if item1.tx.confirmation_time
                else future_height
            )
            c2 = (
                item2.tx.confirmation_time.height
                if item2.tx.confirmation_time
                else future_height
            )

            if c1 != c2:
                # unequal
                if c1 < c2:
                    return -1
                elif c1 > c2:
                    return 1
            else:
                # equal height

                # now check item1 is a (distant) child of item2
                child = item1
                parent = item2
                if check_relation(child, parent):
                    return -1
                # now check item2 is a (distant) child of item1
                child = item2
                parent = item1
                if check_relation(child, parent):
                    return 1

            # cannot be decided
            return 0

        dict_fulltxdetail = self.get_dict_fulltxdetail()

        sorted_fulltxdetail = sorted(
            dict_fulltxdetail.values(), key=functools.cmp_to_key(compare_items)
        )
        return [fulltxdetail.tx for fulltxdetail in sorted_fulltxdetail]
