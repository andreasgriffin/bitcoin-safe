from distutils.util import change_root
import logging, os

logger = logging.getLogger(__name__)

from collections import defaultdict
import bdkpython as bdk
from typing import Sequence, Set, Tuple
from .gui.qt.util import Message
import datetime
from .tx import TXInfos
from .util import (
    balance_dict,
    Satoshis,
    timestamp_to_datetime,
    replace_non_alphanumeric,
)
import re
from .util import (
    TX_HEIGHT_FUTURE,
    TX_HEIGHT_INF,
    TX_HEIGHT_LOCAL,
    TX_HEIGHT_UNCONF_PARENT,
    TX_HEIGHT_UNCONFIRMED,
    TX_STATUS,
    THOUSANDS_SEP,
    cache_method,
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
    public_descriptor_info,
    MultipathDescriptor,
)
import json
from .tx import TXInfos
from .util import clean_list, Satoshis
from .config import UserConfig
import numpy as np
from .labels import Labels
from packaging import version
from .util import hash_string


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
        #     TX_STATUS,
        #     THOUSANDS_SEP,
        #     cache_method,
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


class UtxosForInputs:
    def __init__(
        self, utxos, included_opportunistic_merging_utxos=None, spend_all_utxos=False
    ) -> None:
        if included_opportunistic_merging_utxos is None:
            included_opportunistic_merging_utxos = []

        self.utxos = utxos
        self.included_opportunistic_merging_utxos = included_opportunistic_merging_utxos
        self.spend_all_utxos = spend_all_utxos


class OutPointInfo:
    def __init__(
        self, prev_outpoint: OutPoint, outpoint: OutPoint, tx: bdk.TransactionDetails
    ) -> None:
        self.prev_outpoint = prev_outpoint
        self.outpoint = outpoint
        self.tx = tx


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
                    initial_address_type.derivation_path(network),
                    label=self.signer_names(threshold, i),
                )
                for i in range(signers)
            ]
        )

        self.set_address_type(initial_address_type)

    @classmethod
    def from_descriptor(
        cls,
        string_descriptor: str,
        network: bdk.Network,
    ):
        "creates a ProtoWallet from the xpub (not xpriv)"

        info = public_descriptor_info(string_descriptor, network)

        info["keystores"] = [
            KeyStore(
                xpub=d["xpub"],
                fingerprint=d["fingerprint"],
                derivation_path=d["derivation_path"],
                label=cls.signer_names(i=i, threshold=info["threshold"]),
            )
            for i, d in enumerate(info["keystores"])
        ]
        del info["public_descriptor_string_combined"]
        del info["descriptor_contains_keys"]

        return ProtoWallet(**info)

    def set_address_type(self, address_type: AddressType):
        self.address_type = address_type
        for keystore in self.keystores:
            keystore.set_derivation_path(address_type.derivation_path(self.network))

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
            keystores=self.keystores,
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
                        self.address_type.derivation_path(self.network),
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


class Wallet(BaseSaveableClass):
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

        self.bdkwallet = None
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
        self.cache = {}
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
            if keystore.derivation_path != protowallet.address_type.derivation_path(
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
        if version.parse(str(dct["version"])) <= version.parse("0.1.0"):
            if "labels" in dct:
                # no real migration. Just delete old data
                del dct["labels"]

            labels = Labels()
            for k, v in dct.get("category", {}).items():
                labels.set_addr_category(k, v)

            del dct["category"]
            dct["labels"] = labels
            del dct["version"]
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

    def clear_cache(self):
        self.cache = {}

    def set_gap(self, gap):
        self.gap = gap

    def set_wallet_id(self, id):
        self.id = id

    def _db_file(self):
        return f"{os.path.join(self.config.wallet_dir, filename_clean(self.id, file_extension='.db'))}"

    def create_wallet(self, multipath_descriptor: MultipathDescriptor):
        self.multipath_descriptor = multipath_descriptor

        self.bdkwallet = bdk.Wallet(
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
            self.bdkwallet.sync(self.blockchain, progress)
            logger.info(
                f"Wallet balance is: { balance_dict(self.bdkwallet.get_balance()) }"
            )
        except Exception as e:
            logger.debug(f"error syncing wallet {self.id}")
            raise e

    def get_unused_category_address(self, category, is_change=False) -> bdk.AddressInfo:
        def reverse_search_unused(tip_index):
            for i in reversed(range(tip_index)):
                address_info = self.bdkwallet.get_address(bdk.AddressIndex.PEEK(i))
                address_str = address_info.address.as_string()
                if self.labels.get_category(address_str) == category and (
                    not self.address_is_used(address_str)
                ):
                    return address_info

        if category is None:
            category = self.labels.get_default_category()

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )
        # print new receive address
        tip_address_info: bdk.AddressInfo = bdk_get_address(
            bdk.AddressIndex.LAST_UNUSED()
        )
        search_result = reverse_search_unused(tip_address_info.index)
        if search_result:
            return search_result
        else:
            tip_address_info = self.get_address(force_new=True, is_change=is_change)
            self.labels.set_addr_category(
                tip_address_info.address.as_string(), category
            )
            return tip_address_info

    def get_address(self, force_new=False, is_change=False) -> bdk.AddressInfo:
        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )

        # print new receive address
        address_info = bdk_get_address(
            bdk.AddressIndex.NEW() if force_new else bdk.AddressIndex.LAST_UNUSED()
        )
        address = address_info.address.as_string()
        index = address_info.index
        advanced_tip = index > self._tips[int(is_change)]
        # update tip
        self._tips[int(is_change)] = index

        #
        # if self.labels.get_category(address) or self.labels.get_label(address):
        #     return self.get_address(force_new=True, is_change=is_change)

        logger.info(f"New address: {address} at index {index}")
        return address_info

    def get_output_addresses(self, transaction) -> List[bdk.Address]:
        # print(f'Getting output addresses for txid {transaction.txid}')
        addresses = [
            self.get_address_of_txout(TxOut.from_bdk(output))
            for output in transaction.transaction.output()
        ]
        return addresses

    @cache_method
    def get_txs(self) -> Dict[str, bdk.TransactionDetails]:
        return {tx.txid: tx for tx in self.get_list_transactions()}

    @cache_method
    def get_tx(self, txid) -> bdk.TransactionDetails:
        return self.get_txs().get(txid)

    def get_tx_parents(self, txid) -> Dict:
        """
        recursively calls itself and returns a flat dict:
        txid -> list of parent txids
        """

        all_transactions = self.get_list_transactions()

        result = {}
        parents = []
        uncles = []
        tx = self.get_tx(txid)
        assert tx, f"cannot find {txid}"
        for i, txin in enumerate(tx.transaction.input()):
            _txid = txin.previous_output.txid
            parents.append(_txid)
            # detect address reuse
            addr = self.get_txin_address(txin)
            received, sent = self.get_received_and_send_involving_address(addr)
            # if len(sent) > 1:
            #     my_txid, my_height, my_pos = sent[txin.prevout.to_str()]
            #     assert my_txid == txid
            #     for k, v in sent.items():
            #         if k != txin.prevout.to_str():
            #             reuse_txid, reuse_height, reuse_pos = v
            #             if (reuse_height, reuse_pos) < (my_height, my_pos):
            #                 uncle_txid, uncle_index = k.split(':')
            #                 uncles.append(uncle_txid)

        for _txid in parents + uncles:
            if _txid in [tx.txid for tx in all_transactions]:
                result.update(self.get_tx_parents(_txid))
        result[txid] = parents, uncles
        return result

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
            self.get_list_transactions()
            self.list_unspent_based_on_tx()
            self.get_received_send_maps()
            new_addresses_were_watched = any(self.extend_tips_by_gap())
            i += 1
            if i > 100:
                break

    def list_input_addresses(self, transaction):
        addresses = []
        for tx_in in transaction.transaction.input():
            previous_output = tx_in.previous_output
            tx = self.get_tx(previous_output.txid)
            if tx:
                output_for_input = tx.transaction.output()[previous_output.vout]

                add = bdk.Address.from_script(
                    output_for_input.script_pubkey, self.config.network_settings.network
                )
            else:
                add = None

            addresses.append(add)
        return addresses

    def list_tx_addresses(self, transaction):
        in_addresses = self.list_input_addresses(transaction)
        out_addresses = self.get_output_addresses(transaction)
        logger.debug(
            f"{transaction.txid}: {[(a.as_string() if a else None) for a in in_addresses]} --> {[(a.as_string() if a else None) for a in out_addresses]}"
        )
        return {"in": in_addresses, "out": out_addresses}

    def used_address_tip(self, is_change):
        def reverse_search_used(tip_index):
            for i in reversed(range(tip_index)):
                address_info: bdk.AddressInfo = self.bdkwallet.get_address(
                    bdk.AddressIndex.PEEK(i)
                )
                address_str = address_info.address.as_string()
                if self.address_is_used(address_str):
                    return address_info.index
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

            logger.debug(f"indexing {number} new addresses")

            def add_new_address() -> bdk.AddressInfo:
                address_info: bdk.AddressInfo = bdk_get_address(bdk.AddressIndex.NEW())
                logger.debug(f"Added address with index {address_info.index}")
                return address_info

            new_address_infos = [add_new_address() for i in range(number)]

            for address_info in new_address_infos:
                self.labels.set_addr_category_default(address_info.address.as_string())

        # refresh address cache
        for key in list(self.cache.keys()):
            if (
                key.startswith("get_receiving_addresses")
                or key.startswith("get_change_addresses")
                or key.startswith("get_bdk_address_infos")
            ):
                del self.cache[key]

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

    @cache_method
    def get_bdk_address_infos(
        self, is_change=False, slice_start=None, slice_stop=None
    ) -> Sequence[bdk.AddressInfo]:
        if (not is_change) and (not self.multipath_descriptor):
            return []

        if slice_start is None:
            slice_start = 0
        if slice_stop is None:
            slice_stop = self.gap_change if is_change else self.gap

        if is_change:
            slice_stop = max(slice_stop, self.tips[1])
            self.tip = (self.tips[0], slice_stop)
        else:
            slice_stop = max(slice_stop, self.tips[0])
            self.tip = (slice_stop, self.tips[1])

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )
        result = [
            bdk_get_address(bdk.AddressIndex.PEEK(i))
            for i in range(slice_start, slice_stop + 1)
        ]
        return result

    def get_addresses(self) -> Sequence[str]:
        # note: overridden so that the history can be cleared.
        # addresses are ordered based on derivation
        out = self.get_receiving_addresses().copy()
        out += self.get_change_addresses()
        return out

    @cache_method
    def get_receiving_addresses(
        self, slice_start=None, slice_stop=None
    ) -> Sequence[str]:
        return [
            address_info.address.as_string()
            for address_info in self.get_bdk_address_infos(
                is_change=False, slice_start=slice_start, slice_stop=slice_stop
            )
        ]

    @cache_method
    def get_change_addresses(self, slice_start=None, slice_stop=None) -> Sequence[str]:
        addresses = [
            address_info.address.as_string()
            for address_info in self.get_bdk_address_infos(
                is_change=True, slice_start=slice_start, slice_stop=slice_stop
            )
        ]
        return addresses

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

    @cache_method
    def get_address_of_txout(self, txout: TxOut) -> str:
        if txout.value == 0:
            return None
        else:
            return bdk.Address.from_script(
                txout.script_pubkey, self.config.network_settings.network
            ).as_string()

    def utxo_of_outpoint(self, outpoint: bdk.OutPoint) -> bdk.LocalUtxo:
        for utxo in self.list_unspent_based_on_tx():
            if OutPoint.from_bdk(outpoint) == OutPoint.from_bdk(utxo.outpoint):
                return utxo

    @cache_method
    def list_unspent(self) -> List[bdk.LocalUtxo]:
        raise NotImplementedError("This method is not included unconfirmed utxos")
        start = datetime.datetime.now()
        unspent = self.bdkwallet.list_unspent()
        logger.debug(
            f"call bdkwallet.list_unspent took: {datetime.datetime.now() -start}"
        )
        return unspent

    @cache_method
    def list_unspent_based_on_tx(self, include_spent=False) -> List[bdk.LocalUtxo]:
        spent_outpoints: List[OutPoint] = []
        utxos: List[bdk.LocalUtxo] = []
        txs = self.get_list_transactions()

        # build a dict of all spent outpoints
        for tx_details in txs:
            tx: bdk.Transaction = tx_details.transaction
            inputs: List[bdk.TxIn] = tx.input()
            for txin in inputs:
                prev_out = OutPoint.from_bdk(txin.previous_output)
                spent_outpoints.append(prev_out)

        for tx_details in txs:
            tx: bdk.Transaction = tx_details.transaction
            outputs: List[bdk.TxOut] = tx.output()
            for vout, txout in enumerate(outputs):
                outpoint = bdk.OutPoint(tx_details.txid, vout)

                address: bdk.AddressInfo = robust_address_str_from_script(
                    txout.script_pubkey, self.network
                )

                keychain_kind = None
                if address in self.get_receiving_addresses():
                    keychain_kind = bdk.KeychainKind.EXTERNAL
                if address in self.get_change_addresses():
                    keychain_kind = bdk.KeychainKind.INTERNAL

                # only add a utxo if the output address belongs to me
                if not keychain_kind:
                    continue

                is_spent = OutPoint.from_bdk(outpoint) in spent_outpoints

                if not include_spent and is_spent:
                    continue

                utxo = bdk.LocalUtxo(outpoint, txout, keychain_kind, is_spent)
                utxos.append(utxo)
        return utxos

    @cache_method
    def get_address_balances(self) -> Dict[AddressInfoMin, Tuple[int, int, int]]:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """

        def zero_balances():
            return [0, 0, 0]

        def is_unconfirmed(txid):
            tx_details = self.get_tx(txid)
            return tx_details.confirmation_time

        utxos = self.list_unspent_based_on_tx()

        balances: Dict[str, Tuple[int, int, int]] = defaultdict(zero_balances)
        for i, utxo in enumerate(utxos):
            tx = self.get_tx(utxo.outpoint.txid)
            txout: bdk.TxOut = tx.transaction.output()[utxo.outpoint.vout]

            address = self.get_address_of_txout(TxOut.from_bdk(txout))
            if address is None:
                continue

            if is_unconfirmed(tx.txid):
                balances[address][1] += txout.value
            else:
                balances[address][0] += txout.value
            balances[address][2] += 0

        return balances

    def get_addr_balance(self, address):
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]

    @cache_method
    def get_list_transactions(self) -> List[bdk.TransactionDetails]:
        def key(txdetails: bdk.TransactionDetails):
            return (
                txdetails.confirmation_time.timestamp
                if txdetails.confirmation_time
                else datetime.datetime.now().timestamp()
            )

        return sorted(self.bdkwallet.list_transactions(True), key=key)

    @cache_method
    def get_outpoint_dict(
        self, txs: List[bdk.TransactionDetails], must_be_mine=True
    ) -> Dict[OutPoint, bdk.TransactionDetails]:
        can_belong_to_any = not must_be_mine

        d = {}
        for txdetails in txs:
            for vout, txout in enumerate(txdetails.transaction.output()):
                if can_belong_to_any or self.bdkwallet.is_mine(txout.script_pubkey):
                    outpoint = OutPoint(txdetails.txid, vout)
                    d[outpoint] = txdetails
        return d

    @cache_method
    def get_received_send_maps(
        self,
    ) -> Tuple[Dict[str, List[OutPointInfo]], Dict[str, List[OutPointInfo]]]:
        """
        Createa a map of adddress : OutPointInfo

        Returns:
            Tuple[Dict[str, List[OutPointInfo]], Dict[str, List[OutPointInfo]]]: _description_
        """
        hash_outpoint_to_address: Dict[int, str] = {}  # hash(out_point): address
        received: Dict[str, List[OutPointInfo]] = {}  #  address: OutPointInfo
        send: Dict[str, List[OutPointInfo]] = {}  #  address: OutPointInfo

        txs = self.get_list_transactions()
        # build the received dict
        for tx in txs:
            for vout, txout in enumerate(tx.transaction.output()):
                address = self.get_address_of_txout(TxOut.from_bdk(txout))
                out_point = OutPoint(tx.txid, vout)
                if address is None:
                    continue
                if address not in received:
                    received[address] = []
                received[address].append(
                    OutPointInfo(prev_outpoint=None, outpoint=out_point, tx=tx)
                )
                hash_outpoint_to_address[hash(out_point)] = address

        # check if any input tx is in transactions_involving_address
        for tx in txs:
            for input in tx.transaction.input():
                prev_outpoint = OutPoint.from_bdk(input.previous_output)
                if hash(prev_outpoint) in hash_outpoint_to_address:
                    address = hash_outpoint_to_address[hash(prev_outpoint)]
                    if address not in send:
                        send[address] = []
                    send[address].append(
                        OutPointInfo(prev_outpoint=prev_outpoint, outpoint=None, tx=tx)
                    )

        return received, send

    def get_received_and_send_involving_address(
        self, address
    ) -> Tuple[List[OutPointInfo], List[OutPointInfo]]:
        received, send = self.get_received_send_maps()
        return received.get(address, []).copy(), send.get(address, []).copy()

    def get_txs_involving_address(self, address) -> List[OutPointInfo]:
        received, send = self.get_received_and_send_involving_address(address)
        return received.copy() + send.copy()

    def address_is_used(self, address):
        """
        Check if any tx had this address as an output
        """
        return bool(self.get_txs_involving_address(address))

    @cache_method
    def get_addresses_and_address_infos(
        self, is_change=False
    ) -> Tuple[List[str], List[bdk.AddressInfo]]:
        addresses_infos = self.get_bdk_address_infos(is_change=is_change)
        addresses = [
            address_info.address.as_string() for address_info in addresses_infos
        ]
        return addresses, addresses_infos

    def get_address_path_str(self, address) -> str:
        addresses, addresses_infos = self.get_addresses_and_address_infos(
            is_change=self.is_change(address)
        )

        if address in addresses:
            addresses_info = addresses_infos[addresses.index(address)]
            public_descriptor_string_combined = self.multipath_descriptor.as_string().replace(
                "<0;1>/*",
                f"{0 if  addresses_info.keychain==bdk.KeychainKind.EXTERNAL else 1}/{addresses_info.index}",
            )
            return public_descriptor_string_combined
        return ""

    def get_redeem_script(self, address):
        # TODO:
        return None

    def get_witness_script(self, address):
        return None

    def get_categories_for_txid(self, txid):
        tx = self.get_tx(txid)
        l = clean_list(
            [
                self.labels.get_category(
                    self.get_address_of_txout(TxOut.from_bdk(output))
                )
                for output in tx.transaction.output()
            ]
        )
        return l

    def get_label_for_address(self, address, autofill_from_txs=True):
        label = self.labels.get_label(address, "")

        if not label and autofill_from_txs:
            txs = self.get_txs_involving_address(address)

            tx_labels = clean_list(
                [
                    self.get_label_for_txid(tx.tx.txid, autofill_from_addresses=False)
                    for tx in txs
                ]
            )
            label = ", ".join(tx_labels)

        return label

    def get_label_for_txid(self, txid, autofill_from_addresses=True):
        label = self.labels.get_label(txid, "")

        if not label and autofill_from_addresses:
            tx = self.get_tx(txid)
            address_labels = clean_list(
                [
                    self.get_label_for_address(
                        self.get_address_of_txout(TxOut.from_bdk(output)),
                        autofill_from_txs=False,
                    )
                    for output in tx.transaction.output()
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
        return self.get_output_addresses(tx)[utxo.outpoint.vout]

    @cache_method
    def get_height(self):
        if self.blockchain:
            # update the cached height
            self._blockchain_height = self.blockchain.get_height()
        return self._blockchain_height

    def coin_select(
        self, utxos, total_sent_value, opportunistic_merge_utxos
    ) -> Dict[str, UtxosForInputs]:
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

    def create_coin_selection_dict(self, txinfos: TXInfos) -> UtxosForInputs:
        if not txinfos.utxo_strings and not txinfos.categories:
            logger.warning("No inputs provided for coin selection")

        utxos_for_input = UtxosForInputs(
            txinfos.utxo_dict.values(), spend_all_utxos=not bool(txinfos.categories)
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

    def create_psbt(self, txinfos: TXInfos) -> TXInfos:
        tx_builder = bdk.TxBuilder()
        tx_builder = tx_builder.enable_rbf()
        tx_builder = tx_builder.fee_rate(txinfos.fee_rate)

        txinfos.utxos_for_input = self.create_coin_selection_dict(txinfos)
        selected_outpoints = [
            OutPoint.from_bdk(utxo.outpoint) for utxo in txinfos.utxos_for_input.utxos
        ]

        if txinfos.utxos_for_input.spend_all_utxos:
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
                for utxo in self.list_unspent_based_on_tx()
                if OutPoint.from_bdk(utxo.outpoint) not in selected_outpoints
            ]
            tx_builder = tx_builder.unspendable(unspendable_outpoints)

        for recipient in txinfos.recipients:
            if recipient.checked_max_amount:
                tx_builder = tx_builder.drain_to(
                    bdk.Address(recipient.address).script_pubkey()
                )
            else:
                tx_builder = tx_builder.add_recipient(
                    bdk.Address(recipient.address).script_pubkey(), recipient.amount
                )

        try:
            builder_result: bdk.TxBuilderResult = tx_builder.finish(self.bdkwallet)
        except bdk.BdkError.NoRecipients as e:
            Message(e.args[0], title="er").show_error()
            raise

        inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()

        logger.info(json.loads(builder_result.psbt.json_serialize()))
        logger.debug(
            f"psbt fee after finalized {builder_result.psbt.fee_rate().as_sat_per_vb()}"
        )

        # get category of first utxo
        categories = clean_list(
            sum(
                [
                    list(self.get_categories_for_txid(utxo.outpoint.txid))
                    for utxo in txinfos.utxos_for_input.utxos
                ],
                [],
            )
        )
        txinfos.recipient_category = categories[0] if categories else None
        logger.debug(
            f"Selecting category {txinfos.recipient_category} out of {categories} for the output addresses"
        )

        labels = [
            recipient.label for recipient in txinfos.recipients if recipient.label
        ]
        if labels:
            self.labels.set_tx_label(
                builder_result.transaction_details.txid, ",".join(labels)
            )

        txinfos.builder_result = builder_result
        self.set_output_categories_and_labels(txinfos)
        return txinfos

    def set_output_categories_and_labels(self, txinfos: TXInfos):
        # set category for all outputs
        self._set_category_for_all_recipients(
            txinfos.builder_result.psbt.extract_tx().output(),
            txinfos.recipient_category,
        )

        # set label for the recipient output
        for recipient in txinfos.recipients:
            # this does not include the change output
            if recipient.label and self.is_my_address(recipient.address):
                self.labels.set_addr_label(recipient.address, recipient.label)

        # add a label for the change output
        labels = [
            recipient.label for recipient in txinfos.recipients if recipient.label
        ]
        for txout in txinfos.builder_result.psbt.extract_tx().output():
            address = self.get_address_of_txout(TxOut.from_bdk(txout))
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

    def get_category_utxo_dict(self):
        d = {}
        for utxo in self.list_unspent_based_on_tx():
            address = self.get_utxo_address(utxo)
            category = self.labels.get_category(address)
            if category not in d:
                d[category] = []
            d[category].append(utxo)
        return d
