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


import functools
import logging
import os
from time import time

from bitcoin_safe.psbt_util import FeeInfo

from .signals import Signals, UpdateFilter

logger = logging.getLogger(__name__)

import json
from collections import defaultdict
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import bdkpython as bdk
import numpy as np
from bitcoin_usb.address_types import DescriptorInfo
from bitcoin_usb.software_signer import derive as software_signer_derive
from packaging import version

from .config import MIN_RELAY_FEE, UserConfig
from .descriptors import AddressType, MultipathDescriptor, get_default_address_type
from .i18n import translate
from .keystore import KeyStore
from .labels import Labels
from .pythonbdk_types import *
from .storage import BaseSaveableClass, filtered_for_init
from .tx import TxBuilderInfos, TxUiInfos
from .util import (
    CacheManager,
    Satoshis,
    calculate_ema,
    clean_list,
    hash_string,
    instance_lru_cache,
    replace_non_alphanumeric,
)


class InconsistentBDKState(Exception):
    pass


class TxConfirmationStatus(enum.Enum):
    CONFIRMED = 1
    UNCONFIRMED = 0
    UNCONF_PARENT = -1  # this implies UNCONFIRMED
    LOCAL = -2  # this implies UNCONFIRMED

    @classmethod
    def to_str(cls, status: "TxConfirmationStatus") -> str:
        if status == cls.CONFIRMED:
            return translate("wallet", "Confirmed")
        if status == cls.UNCONFIRMED:
            return translate("wallet", "Unconfirmed")
        if status == cls.UNCONF_PARENT:
            return translate("wallet", "Unconfirmed parent")
        if status == cls.LOCAL:
            return translate("wallet", "Local")


class TxStatus:
    def __init__(
        self,
        tx: bdk.Transaction,
        confirmation_time: bdk.BlockTime,
        get_height: Callable,
        is_in_mempool: bool,
        confirmation_status: Optional[TxConfirmationStatus] = None,
    ) -> None:
        self.tx = tx
        self.get_height = get_height
        self.confirmation_time = confirmation_time
        self.is_in_mempool = is_in_mempool

        # from .util import (
        #     TX_HEIGHT_FUTURE,
        #     TX_HEIGHT_INF,
        #     TX_HEIGHT_LOCAL,
        #     TX_HEIGHT_UNCONF_PARENT,
        #     TX_HEIGHT_UNCONFIRMED,
        # )

        # upgrade/increase the status based on conditions
        self.confirmation_status = (
            TxConfirmationStatus.LOCAL if not confirmation_status else confirmation_status
        )
        if is_in_mempool:
            self.confirmation_status = TxConfirmationStatus.UNCONFIRMED
        if confirmation_time:
            self.confirmation_status = TxConfirmationStatus.CONFIRMED

    @classmethod
    def from_wallet(cls, txid: str, wallet: "Wallet") -> "TxStatus":
        txdetails = wallet.get_tx(txid)
        return TxStatus(
            txdetails.transaction,
            txdetails.confirmation_time,
            wallet.get_height,
            wallet.is_in_mempool(txid),
        )

    def sort_id(self) -> int:
        return self.confirmations() if self.confirmations() else self.confirmation_status.value

    def confirmations(self) -> int:
        return self.get_height() - self.confirmation_time.height + 1 if self.confirmation_time else 0

    def is_unconfirmed(self) -> bool:
        return self.confirmation_status != TxConfirmationStatus.CONFIRMED

    def can_do_initial_broadcast(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.LOCAL

    def can_rbf(self) -> bool:
        return self.is_unconfirmed() and self.confirmation_status != TxConfirmationStatus.LOCAL

    def can_cpfp(self) -> bool:
        return self.confirmation_status == TxConfirmationStatus.UNCONF_PARENT


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
        gap_change=5,
        tutorial_index=None,
    ) -> None:
        super().__init__()

        self.id = wallet_id
        self.threshold = threshold
        self.network = network
        self.tutorial_index = tutorial_index

        self.gap = gap
        self.gap_change = gap_change

        initial_address_type: AddressType = (
            address_type if address_type else get_default_address_type(len(keystores) > 1)
        )
        self.keystores: List[Optional[KeyStore]] = keystores

        self.set_address_type(initial_address_type)

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.threshold, len(self.keystores)

    @classmethod
    def from_dump(cls, dct, class_kwargs=None) -> "ProtoWallet":
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        if version.parse(str(dct["VERSION"])) <= version.parse("0.0.0"):
            pass

        # now the version is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

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
                label=cls.signer_names(i=i, threshold=info.threshold),
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

    @staticmethod
    def signer_names(threshold: int, i: int) -> str:
        i += 1
        if i <= threshold:
            return translate("d", "Signer {i}").format(i=i)
        else:
            return translate("d", "Recovery Signer {i}").format(i=i)

    def signer_name(self, i: int) -> str:
        return self.signer_names(self.threshold, i)

    def set_gap(self, gap: int) -> None:
        self.gap = gap

    def to_multipath_descriptor(self) -> Optional[MultipathDescriptor]:
        if not all(self.keystores):
            return None
        return MultipathDescriptor.from_keystores(
            self.threshold,
            spk_providers=self.keystores,
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
        self.old_state: List[bdk.TransactionDetails] = []
        self.appended: List[bdk.TransactionDetails] = []
        self.removed: List[bdk.TransactionDetails] = []
        self.new_state: List[bdk.TransactionDetails] = []

    def was_changed(self) -> Dict[str, List[bdk.TransactionDetails]]:
        d = {}
        if self.appended:
            d["appended"] = self.appended
        if self.removed:
            d["removed"] = self.removed
        return d


class BdkWallet(bdk.Wallet, CacheManager):
    """This is a caching wrapper around bdk.Wallet. It should not provide any
    logic. Only wrapping existing methods and minimal new methods useful for
    caching.

    The exception is list_delta_transactions, which provides also deltas
    to a previous state, and is in a wider sense also caching.
    """

    def __init__(
        self,
        descriptor: bdk.Descriptor,
        change_descriptor: bdk.Descriptor,
        network: bdk.Network,
        database_config: bdk.DatabaseConfig,
    ) -> None:
        bdk.Wallet.__init__(self, descriptor, change_descriptor, network, database_config)
        CacheManager.__init__(self)
        self._delta_cache: Dict[str, DeltaCacheListTransactions] = {}
        logger.info("Created bdk.Wallet for network {network} and database_config {database_config} ")

    @instance_lru_cache(always_keep=True)
    def peek_addressinfo(
        self,
        index: int,
        is_change=False,
    ) -> bdk.AddressInfo:
        bdk_get_address = self.get_internal_address if is_change else self.get_address
        return bdk_get_address(bdk.AddressIndex.PEEK(index))

    @instance_lru_cache(always_keep=True)
    def peek_address(
        self,
        index: int,
        is_change=False,
    ) -> str:
        return self.peek_addressinfo(index, is_change=is_change).address.as_string()

    @instance_lru_cache()
    def list_unspent(self) -> List[bdk.LocalUtxo]:
        start_time = time()
        result: List[bdk.LocalUtxo] = super().list_unspent()
        logger.debug(f"self.bdkwallet.list_unspent {len(result)} results in { time()-start_time}s")

        return result

    def partial_mitigate_fulcrum_fix_timestamps(
        self, txs: List[bdk.TransactionDetails]
    ) -> List[bdk.TransactionDetails]:
        """the timestamps are mixed up (with fulcrum), see https://github.com/cculianu/Fulcrum/issues/233

        this function at least bringt the

        Args:
            txs (_type_): _description_

        Returns:
            _type_: _description_
        """
        ""
        confirmed_txs = [tx for tx in txs if tx.confirmation_time]

        sorted_timestamps = sorted([tx.confirmation_time.timestamp for tx in confirmed_txs])
        sorted_heights = sorted([tx.confirmation_time.height for tx in confirmed_txs])

        height_to_min_timestamp = {}
        for timestamp, height in zip(sorted_timestamps, sorted_heights):
            if height not in height_to_min_timestamp:
                height_to_min_timestamp[height] = timestamp
            height_to_min_timestamp[height] = min(height_to_min_timestamp[height], timestamp)

        for tx in confirmed_txs:
            tx.confirmation_time.timestamp = height_to_min_timestamp[tx.confirmation_time.height]
        return txs

    @instance_lru_cache()
    def list_transactions(self, include_raw=True) -> List[bdk.TransactionDetails]:
        start_time = time()
        res: List[bdk.TransactionDetails] = super().list_transactions(include_raw=include_raw)

        # the timestamps are mixed up (with fulcrum), see https://github.com/cculianu/Fulcrum/issues/233
        res = self.partial_mitigate_fulcrum_fix_timestamps(res)

        logger.debug(f"list_transactions {len(res)} results in { time()-start_time}s")
        return res

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

        old_ids = [tx.txid for tx in entry.old_state]
        new_ids = [tx.txid for tx in entry.new_state]
        appended_ids = set(new_ids) - set(old_ids)
        removed_ids = set(old_ids) - set(new_ids)

        entry.appended = [tx for tx in entry.new_state if tx.txid in appended_ids]
        entry.removed = [tx for tx in entry.old_state if tx.txid in removed_ids]

        # logger.debug(
        #     f"self.bdkwallet.list_delta_transactions {len(entry.new)} results in { time()-start_time}s"
        # )
        return entry

    @instance_lru_cache(always_keep=True)
    def network(self) -> bdk.Network:
        return super().network()

    @instance_lru_cache(always_keep=True)
    def get_address_of_txout(self, txout: TxOut) -> Optional[str]:
        if txout.value == 0:
            return None
        else:
            return bdk.Address.from_script(txout.script_pubkey, self.network()).as_string()


class WalletInputsInconsistentError(Exception):
    pass


class Wallet(BaseSaveableClass, CacheManager):
    """If any bitcoin logic (ontop of bdk) has to be done, then here is the
    place."""

    VERSION = "0.1.4"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "KeyStore": KeyStore,
        "UserConfig": UserConfig,
        "Labels": Labels,
    }

    def __init__(
        self,
        id,
        descriptor_str: str,
        keystores: List[KeyStore],
        network: bdk.Network,
        config: UserConfig,
        gap=20,
        gap_change=5,
        data_dump: Dict = None,
        labels: Labels = None,
        _blockchain_height: int = None,
        _tips: List[int] = None,
        refresh_wallet=False,
        tutorial_index: Optional[int] = None,
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
        self.gap_change = gap_change
        self.keystores = keystores
        self.config: UserConfig = config
        self.write_lock = Lock()
        self.data_dump: Dict = data_dump if data_dump else {}
        self.labels: Labels = labels if labels else Labels()
        self.labels.default_category = "Friends"
        # refresh dependent values
        self._tips = _tips if _tips and not refresh_wallet else [0, 0]
        self._blockchain_height = _blockchain_height if _blockchain_height and not refresh_wallet else 0
        self.tutorial_index = tutorial_index

        if refresh_wallet and os.path.isfile(self._db_file()):
            os.remove(self._db_file())
        self.refresh_wallet = False
        # end refresh dependent values

        self.create_bdkwallet(MultipathDescriptor.from_descriptor_str(descriptor_str, self.network))
        self.blockchain = None
        self.clear_cache()

    @staticmethod
    def check_consistency(keystores: List[KeyStore], descriptor_str: str, network: bdk.Network):
        def get_keystore(fingerprint) -> Optional[KeyStore]:
            for keystore in keystores:
                if keystore.fingerprint == fingerprint:
                    return keystore
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

    def clear_cache(self, clear_always_keep=False) -> None:
        self.cache_dict_fulltxdetail: Dict[str, FullTxDetail] = {}  # txid:FullTxDetail
        self.cache_address_to_txids: Dict[str, Set[str]] = defaultdict(set)  # address:[txid]

        self.clear_instance_cache(clear_always_keep=clear_always_keep)
        self.bdkwallet.clear_instance_cache(clear_always_keep=clear_always_keep)

    @instance_lru_cache()
    def _get_addresses(
        self,
        is_change=False,
    ) -> List[str]:
        if (not is_change) and (not self.multipath_descriptor):
            return []
        return [
            self.bdkwallet.peek_address(i, is_change=is_change)
            for i in range(0, self.tips[int(is_change)] + 1)
        ]

    def get_mn_tuple(self) -> Tuple[int, int]:
        info = DescriptorInfo.from_str(self.multipath_descriptor.as_string())
        return info.threshold, len(info.spk_providers)

    def as_protowallet(self) -> ProtoWallet:
        # fill the protowallet with the xpub info
        protowallet = ProtoWallet.from_descriptor(
            self.id, self.multipath_descriptor.as_string_private(), network=self.network
        )
        protowallet.gap = self.gap
        protowallet.gap_change = self.gap_change
        protowallet.tutorial_index = self.tutorial_index
        protowallet.keystores = [keystore.clone() for keystore in self.keystores]

        return protowallet

    @classmethod
    def from_protowallet(
        cls,
        protowallet: ProtoWallet,
        config: UserConfig,
        data_dump: Dict = None,
        labels: Labels = None,
        _blockchain_height: int = None,
        _tips: List[int] = None,
        refresh_wallet=False,
    ) -> "Wallet":

        keystores = []
        for keystore in protowallet.keystores:
            # dissallow None
            assert keystore is not None, "Cannot create wallet with None"

            if keystore.key_origin != protowallet.address_type.key_origin(config.network):
                logger.warning(f"Warning: The derivation path of {keystore} is not the default")

            keystores.append(keystore.clone())

        multipath_descriptor = protowallet.to_multipath_descriptor()
        assert (
            multipath_descriptor is not None
        ), "Cannot create wallet, because no descriptor could be generated"

        return Wallet(
            protowallet.id,
            multipath_descriptor.as_string_private(),
            keystores=keystores,
            gap=protowallet.gap,
            gap_change=protowallet.gap_change,
            network=protowallet.network,
            config=config,
            tutorial_index=protowallet.tutorial_index,
            data_dump=data_dump,
            labels=labels,
            _blockchain_height=_blockchain_height,
            _tips=_tips,
            refresh_wallet=refresh_wallet,
        )

    def get_relevant_differences(self, other_wallet: "Wallet") -> Set[str]:
        "Compares the relevant entries like keystores"
        differences = set()
        this = self.dump()
        other = other_wallet.dump()

        keys = [
            "id",
            "gap",
            "gap_change",
            "network",
        ]
        for k in keys:
            if this[k] != other[k]:
                differences.add(k)

        if self.labels.export_bip329_jsonlines() != other_wallet.labels.export_bip329_jsonlines():
            differences.add("labels")

        if len(self.keystores) != len(other_wallet.keystores):
            differences.add("keystores")

        for keystore, other_keystore in zip(self.keystores, other_wallet.keystores):
            if not keystore.is_equal(other_keystore):
                differences.add("keystores")

        if (
            self.multipath_descriptor.as_string_private()
            != other_wallet.multipath_descriptor.as_string_private()
        ):
            differences.add("multipath_descriptor")

        return differences

    def is_essentially_equal(self, other_wallet: "Wallet") -> bool:
        return not self.get_relevant_differences(other_wallet)

    def dump(self) -> Dict[str, Any]:
        d = super().dump()

        keys = [
            "id",
            "gap",
            "network",
            "gap_change",
            "keystores",
            "labels",
            "_blockchain_height",
            "_tips",
            "refresh_wallet",
            "tutorial_index",
            "data_dump",
        ]
        for k in keys:
            d[k] = self.__dict__[k]

        d["descriptor_str"] = self.multipath_descriptor.as_string_private()

        return d

    @classmethod
    def from_file(cls, filename: str, config: UserConfig, password: str = None) -> "Wallet":
        return super()._from_file(
            filename=filename,
            password=password,
            class_kwargs={"Wallet": {"config": config}},
        )

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        "this class should be overwritten in child classes"
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

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    @classmethod
    def from_dump(cls, dct, class_kwargs=None) -> "Wallet":
        super()._from_dump(dct, class_kwargs=class_kwargs)
        config: UserConfig = class_kwargs[cls.__name__]["config"]  # passed via class_kwargs

        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        return cls(**filtered_for_init(dct, cls))

    def set_gap(self, gap: int) -> None:
        self.gap = gap

    def set_wallet_id(self, id: str) -> None:
        self.id = id

    def _db_file(self) -> str:
        return f"{os.path.join(self.config.wallet_dir, filename_clean(self.id, file_extension='.db'))}"

    def create_bdkwallet(self, multipath_descriptor: MultipathDescriptor) -> None:
        self.multipath_descriptor = multipath_descriptor

        self.bdkwallet = BdkWallet(
            descriptor=self.multipath_descriptor.bdk_descriptors[0],
            change_descriptor=self.multipath_descriptor.bdk_descriptors[1],
            network=self.config.network,
            database_config=bdk.DatabaseConfig.MEMORY(),
            # database_config=bdk.DatabaseConfig.SQLITE(
            #     bdk.SqliteDbConfiguration(self._db_file())
            # ),
        )

    def is_multisig(self) -> bool:
        return len(self.keystores) > 1

    def init_blockchain(self) -> bdk.Blockchain:
        logger.info(f"Creating blockchain connection for {self.config.network_config}")

        if self.config.network == bdk.Network.BITCOIN:
            start_height = 0  # segwit block 481824
        elif self.config.network in [
            bdk.Network.REGTEST,
            bdk.Network.SIGNET,
        ]:
            start_height = 0
        elif self.config.network == bdk.Network.TESTNET:
            start_height = 2000000

        if self.config.network_config.server_type == BlockchainType.Electrum:
            full_url = (
                "ssl://" if self.config.network_config.electrum_use_ssl else ""
            ) + self.config.network_config.electrum_url
            blockchain_config = bdk.BlockchainConfig.ELECTRUM(
                bdk.ElectrumConfig(
                    full_url,
                    None,
                    2,
                    10,
                    max(self.gap, self.gap_change),
                    self.config.network_config.electrum_use_ssl,
                )
            )
        elif self.config.network_config.server_type == BlockchainType.Esplora:
            blockchain_config = bdk.BlockchainConfig.ESPLORA(
                bdk.EsploraConfig(
                    self.config.network_config.esplora_url,
                    None,
                    1,
                    max(self.gap, self.gap_change),
                    10,
                )
            )
        elif self.config.network_config.server_type == BlockchainType.CompactBlockFilter:
            folder = f"./compact-filters-{self.id}-{self.config.network.name}"
            blockchain_config = bdk.BlockchainConfig.COMPACT_FILTERS(
                bdk.CompactFiltersConfig(
                    [
                        f"{self.config.network_config.compactblockfilters_ip}:{self.config.network_config.compactblockfilters_port}"
                    ]
                    * 5,
                    self.config.network,
                    folder,
                    start_height,
                )
            )
        elif self.config.network_config.server_type == BlockchainType.RPC:
            blockchain_config = bdk.BlockchainConfig.RPC(
                bdk.RpcConfig(
                    f"{self.config.network_config.rpc_ip}:{self.config.network_config.rpc_port}",
                    bdk.Auth.USER_PASS(
                        self.config.network_config.rpc_username,
                        self.config.network_config.rpc_password,
                    ),
                    self.config.network,
                    self._get_uniquie_wallet_id(),
                    bdk.RpcSyncParams(0, 0, False, 10),
                )
            )
        self.blockchain = bdk.Blockchain(blockchain_config)
        return self.blockchain

    def _get_uniquie_wallet_id(self) -> str:
        return f"{replace_non_alphanumeric(self.id)}-{hash_string(self.multipath_descriptor.as_string())}"

    def sync(self, progress_function_threadsafe=None) -> None:
        if self.blockchain is None:
            self.init_blockchain()

        if not progress_function_threadsafe:

            def progress_function_threadsafe(progress: float, message: str) -> None:
                logger.info((progress, message))

        progress = bdk.Progress()
        progress.update = progress_function_threadsafe

        try:
            start_time = time()
            self.bdkwallet.sync(self.blockchain, progress)
            logger.debug(f"{self.id} self.bdkwallet.sync in { time()-start_time}s")
            logger.info(f"Wallet balance is: { self.bdkwallet.get_balance().__dict__ }")
        except Exception as e:
            logger.debug(f"{self.id} error syncing wallet {self.id}")
            raise e

    def reverse_search_unused_address(
        self, category: Optional[str] = None, is_change=False
    ) -> bdk.AddressInfo:

        earliest_address_info = None
        for index, address_str in reversed(list(enumerate(self._get_addresses(is_change=is_change)))):

            if self.address_is_used(address_str) or self.labels.get_label(address_str):
                break
            else:
                if not category or (category and self.labels.get_category(address_str) == category):
                    earliest_address_info = self.bdkwallet.peek_addressinfo(index, is_change=is_change)
        return earliest_address_info

    def get_unused_category_address(self, category: Optional[str], is_change=False) -> bdk.AddressInfo:
        if category is None:
            category = self.labels.get_default_category()

        address_info = self.reverse_search_unused_address(category=category, is_change=is_change)
        if address_info:
            return address_info

        address_info = self.get_address(force_new=True, is_change=is_change)
        self.labels.set_addr_category(address_info.address.as_string(), category, timestamp="now")
        return address_info

    def get_address(self, force_new=False, is_change=False) -> bdk.AddressInfo:
        "Gives an unused address reverse searched from the tip"

        def get_force_new_address() -> bdk.AddressInfo:
            address_info = bdk_get_address(bdk.AddressIndex.NEW())
            index = address_info.index
            self._tips[int(is_change)] = index

            logger.info(f"advanced_tip to {self._tips}  , is_change={is_change}")
            return address_info

        bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address

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
            self.bdkwallet.get_address_of_txout(TxOut.from_bdk(output)) for output in transaction.output()
        ]

    def get_txin_address(self, txin: bdk.TxIn) -> Optional[bdk.Address]:
        previous_output = txin.previous_output
        tx = self.get_tx(previous_output.txid)
        if tx:
            output_for_input = tx.transaction.output()[previous_output.vout]
            return bdk.Address.from_script(output_for_input.script_pubkey, self.config.network)
        else:
            return None

    def fill_commonly_used_caches(self) -> None:
        i = 0
        new_addresses_were_watched = True
        # you have to repeat fetching new tx when you start watching new addresses
        # And you can only start watching new addresses once you detected transactions on them.
        # Thas why this fetching has to be done in a loop
        while new_addresses_were_watched:
            if i > 0:
                self.clear_cache()
            self.get_addresses()

            advanced_tips = self.advance_tips_by_gap()
            logger.debug(f"{self.id} tips were advanced by {advanced_tips}")
            new_addresses_were_watched = any(advanced_tips)
            i += 1
            if i > 100:
                break
        self.bdkwallet.list_unspent()
        self.get_dict_fulltxdetail()

    @instance_lru_cache()
    def get_txs(self) -> Dict[str, bdk.TransactionDetails]:
        "txid:TransactionDetails"
        return {tx.txid: tx for tx in self.sorted_delta_list_transactions()}

    @instance_lru_cache()
    def get_tx(self, txid: str) -> bdk.TransactionDetails:
        return self.get_txs().get(txid)

    def list_input_bdk_addresses(self, transaction: bdk.Transaction) -> List[str]:
        addresses = []
        for tx_in in transaction.input():
            previous_output = tx_in.previous_output
            tx = self.get_tx(previous_output.txid)
            if tx:
                output_for_input = tx.transaction.output()[previous_output.vout]

                add = bdk.Address.from_script(output_for_input.script_pubkey, self.config.network).as_string()
            else:
                add = None

            addresses.append(add)
        return addresses

    def list_tx_addresses(self, transaction: bdk.Transaction) -> Dict[str, List[str]]:
        return {
            "in": self.list_input_bdk_addresses(transaction),
            "out": self.get_output_addresses(transaction),
        }

    def transaction_involves_wallet(self, transaction: bdk.Transaction) -> bool:
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

        bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address
        return reverse_search_used(bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index)

    def _get_bdk_tip(self, is_change: bool) -> int:
        if not self.bdkwallet:
            return self._tips[int(is_change)]

        bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address
        return bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index

    def _get_tip(self, is_change: bool) -> int:
        if not self.bdkwallet:
            return self._tips[int(is_change)]

        self._advance_tip_if_necessary(is_change=is_change, target=self._tips[int(is_change)])
        return self._tips[int(is_change)]

    def _advance_tip_if_necessary(self, is_change: bool, target: int) -> None:
        with self.write_lock:
            bdk_get_address = self.bdkwallet.get_internal_address if is_change else self.bdkwallet.get_address

            # check that advancing is even necessary
            old_address_info: bdk.AddressInfo = bdk_get_address(bdk.AddressIndex.LAST_UNUSED())
            old_bdk_tip = old_address_info.index
            number = target - old_bdk_tip
            if number == 0:
                return
            if number < 0:
                self._tips[int(is_change)] = old_bdk_tip
                return

            logger.debug(f"{self.id} indexing {number} new addresses")

            def add_new_address() -> bdk.AddressInfo:
                address_info: bdk.AddressInfo = bdk_get_address(bdk.AddressIndex.NEW())
                logger.debug(
                    f"{self.id} Added {'change' if is_change else ''} address with index {address_info.index}"
                )
                return address_info

            [add_new_address() for i in range(number)]

        self.clear_cache()

    def advance_tips_by_gap(self) -> Tuple[int, int]:
        "Returns [number of added addresses, number of added change addresses]"
        tip = [0, 0]
        for is_change in [False, True]:
            gap = self.gap_change if is_change else self.gap
            used_tip = self.used_address_tip(is_change=is_change)
            self._advance_tip_if_necessary(is_change=is_change, target=used_tip + gap)
        return (tip[0], tip[1])

    def search_index_tuple(self, address, forward_search=500) -> Optional[AddressInfoMin]:
        """Looks for the address"""
        # first check if the address is already indexed
        for is_change in [False, True]:
            addresses = self._get_addresses(is_change=is_change)
            if address in addresses:
                return AddressInfoMin(
                    address, addresses.index(address), AddressInfoMin.is_change_to_keychain(is_change)
                )

        # if not then search forward
        for index in range(self.tips[int(is_change)] + 1, forward_search + self.tips[int(is_change)] + 1):
            for is_change in [False, True]:
                peek_address = self.bdkwallet.peek_address(index, is_change)
                if peek_address == address:
                    return AddressInfoMin(
                        address, index, keychain=AddressInfoMin.is_change_to_keychain(is_change)
                    )
        return None

    def advance_tip_to_address(self, address: str, forward_search=500) -> Optional[AddressInfoMin]:
        """Looks for the address and advances the tip to this address"""
        address_info_min = self.search_index_tuple(address=address, forward_search=forward_search)
        if not address_info_min:
            return None

        if address_info_min.index <= self.tips[int(address_info_min.is_change())]:
            # no need to advance tip
            return None

        is_change = address_info_min.is_change()
        self._advance_tip_if_necessary(is_change=is_change, target=address_info_min.index)

        return address_info_min

    @property
    def tips(self) -> List[int]:
        return [self._get_tip(b) for b in [False, True]]

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

    def utxo_of_outpoint(self, outpoint: bdk.OutPoint) -> Optional[PythonUtxo]:
        for python_utxo in self.get_all_txos():
            if OutPoint.from_bdk(outpoint) == OutPoint.from_bdk(python_utxo.outpoint):
                return python_utxo
        return None

    @instance_lru_cache()
    def get_address_balances(self) -> defaultdict[str, Balance]:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """

        def get_confirmation_time(txid: str) -> Optional[bdk.BlockTime]:
            tx_details = self.get_tx(txid)
            return tx_details.confirmation_time

        utxos = self.bdkwallet.list_unspent()

        balances: defaultdict[str, Balance] = defaultdict(Balance)
        for i, utxo in enumerate(utxos):
            tx = self.get_tx(utxo.outpoint.txid)
            if not tx:
                logger.warning(f"This should not happen. Most likely it is due to outdated caches.")
                # this way of handeling this special case is suboptimal.
                # Better would be to handle the caches such that the caches are always consistent
                self.clear_instance_cache()
                tx = self.get_tx(utxo.outpoint.txid)
                if not tx:
                    raise InconsistentBDKState(f"{utxo.outpoint.txid} not present in transaction details")

            txout: bdk.TxOut = tx.transaction.output()[utxo.outpoint.vout]

            address = self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
            if address is None:
                continue

            if get_confirmation_time(tx.txid):
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

    def get_dict_fulltxdetail(self) -> Dict[str, FullTxDetail]:
        """
        Createa a map of txid : to FullTxDetail

        Returns:
            FullTxDetail
        """
        start_time = time()
        delta_txs = self.bdkwallet.list_delta_transactions(access_marker="get_dict_fulltxdetail")

        # if transactions were removed (reorg or other), then recalculate everything
        if delta_txs.removed or not self.cache_dict_fulltxdetail:
            self.cache_dict_fulltxdetail = {}
            txs = delta_txs.new_state
        else:
            txs = delta_txs.appended

        def append_dicts(txid, python_utxos: List[Optional[PythonUtxo]]) -> None:
            for python_utxo in python_utxos:
                if not python_utxo:
                    continue
                self.cache_address_to_txids[python_utxo.address].add(txid)

        def process_outputs(tx: bdk.TransactionDetails) -> Tuple[str, FullTxDetail]:
            fulltxdetail = FullTxDetail.fill_received(tx, self.bdkwallet.get_address_of_txout)
            if fulltxdetail.txid in self.cache_dict_fulltxdetail:
                logger.error(f"Trying to add a tx with txid {fulltxdetail.txid} twice. ")
            return fulltxdetail.txid, fulltxdetail

        def process_inputs(tx: bdk.TransactionDetails) -> Tuple[str, FullTxDetail]:
            "this must be done AFTER process_outputs"
            txid = tx.txid
            fulltxdetail = self.cache_dict_fulltxdetail[txid]
            fulltxdetail.fill_inputs(self.cache_dict_fulltxdetail)
            return txid, fulltxdetail

        key_value_pairs = list(map(process_outputs, txs))

        self.cache_dict_fulltxdetail.update(key_value_pairs)
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, list(fulltxdetail.outputs.values()))

        # speed test for wallet 600 transactions (with many inputs each) without profiling:
        # map : 2.714s
        # for loop:  2.76464
        # multithreading : 6.3021s
        key_value_pairs = list(map(process_inputs, txs))
        for txid, fulltxdetail in key_value_pairs:
            append_dicts(txid, list(fulltxdetail.inputs.values()))

        if txs:
            logger.debug(f"get_dict_fulltxdetail  with {len(txs)} txs in {time()-  start_time}")

        return self.cache_dict_fulltxdetail

    def _get_all_txos_dict(self, include_not_mine=False) -> Dict[str, PythonUtxo]:
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

    def get_all_txos(self, include_not_mine=False) -> List[PythonUtxo]:
        return list(self._get_all_txos_dict(include_not_mine=include_not_mine).values())

    @instance_lru_cache()
    def address_is_used(self, address: str) -> bool:
        """Check if any tx had this address as an output."""
        return bool(self.get_involved_txids(address))

    def get_address_path_str(self, address: str) -> str:
        index = None
        is_change = None
        if address in self.get_receiving_addresses():
            index = self.get_receiving_addresses().index(address)
            is_change = False
        if address in self.get_change_addresses():
            index = self.get_change_addresses().index(address)
            is_change = True

        if index is None:
            return ""

        addresses_info = self.bdkwallet.peek_addressinfo(index, is_change=is_change)
        public_descriptor_string_combined: str = self.multipath_descriptor.as_string().replace(
            "<0;1>/*",
            f"{0 if  addresses_info.keychain==bdk.KeychainKind.EXTERNAL else 1}/{addresses_info.index}",
        )
        return public_descriptor_string_combined

    def get_input_and_output_utxos(self, txid: str) -> List[PythonUtxo]:
        fulltxdetail = self.get_dict_fulltxdetail().get(txid)
        if not fulltxdetail:
            return []

        l = [python_utxo for python_utxo in fulltxdetail.outputs.values() if python_utxo] + [
            python_utxo for python_utxo in fulltxdetail.inputs.values() if python_utxo
        ]

        return l

    def get_categories_for_txid(self, txid: str) -> List[str]:
        python_utxos = self.get_input_and_output_utxos(txid)
        if not python_utxos:
            return []

        l = np.unique(
            clean_list([self.labels.get_category(python_utxo.address) for python_utxo in python_utxos])
        )

        return list(l)

    def get_label_for_address(self, address: str, autofill_from_txs=True) -> str:
        maybe_label = self.labels.get_label(address, "")
        label = maybe_label if maybe_label else ""

        if not label and autofill_from_txs:
            txids = self.get_involved_txids(address)

            tx_labels = clean_list(
                [self.get_label_for_txid(txid, autofill_from_addresses=False) for txid in txids]
            )
            label = ", ".join(tx_labels)

        return label

    def get_label_for_txid(self, txid: str, autofill_from_addresses=True) -> str:
        maybe_label = self.labels.get_label(txid, "")
        label = maybe_label if maybe_label else ""

        if not label and autofill_from_addresses:
            python_utxos = self.get_input_and_output_utxos(txid)
            if not python_utxos:
                return label

            address_labels = clean_list(
                [self.get_label_for_address(python_utxo.address) for python_utxo in python_utxos]
            )
            label = ", ".join(address_labels)

        return label

    def get_balance(self) -> Balance:
        balance = self.bdkwallet.get_balance()
        return Balance(
            immature=balance.immature,
            trusted_pending=balance.trusted_pending,
            untrusted_pending=balance.untrusted_pending,
            confirmed=balance.confirmed,
        )

    def get_utxo_name(self, utxo: PythonUtxo) -> str:
        tx = self.get_tx(utxo.outpoint.txid)
        return f"{tx.txid}:{utxo.outpoint.vout}"

    def get_utxo_address(self, utxo: PythonUtxo) -> str:
        tx = self.get_tx(utxo.outpoint.txid)
        return self.get_output_addresses(tx.transaction)[utxo.outpoint.vout]

    @instance_lru_cache()
    def get_height(self) -> int:
        if self.blockchain:
            # update the cached height
            try:
                self._blockchain_height = self.blockchain.get_height()
            except:
                logger.error(f"Could not fetch self.blockchain.get_height()")
        return self._blockchain_height

    def coin_select(
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
                utxo for utxo in utxos if not is_outpoint_in_list(utxo.outpoint, selected_utxos)
            ]

            # never choose more than half of all remaining outputs
            number_of_opportunistic_outpoints = (
                np.random.randint(0, len(non_selected_utxos) // 2) if len(non_selected_utxos) // 2 > 0 else 0
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
            return self.coin_select(
                utxos=utxos_for_input.utxos,
                total_sent_value=total_sent_value,
                opportunistic_merge_utxos=txinfos.opportunistic_merge_utxos,
            )
        else:
            # otherwise let the bdk wallet decide on the minimal coins to be spent, out of the utxos
            return UtxosForInputs(utxos=utxos_for_input.utxos, spend_all_utxos=False)

    def is_my_address(self, address: str) -> bool:
        return address in self.get_addresses()

    def create_psbt(self, txinfos: TxUiInfos) -> TxBuilderInfos:
        recipients = txinfos.recipients.copy()

        tx_builder = bdk.TxBuilder()
        tx_builder = tx_builder.enable_rbf()
        if txinfos.fee_rate:
            tx_builder = tx_builder.fee_rate(txinfos.fee_rate)

        utxos_for_input = self.handle_opportunistic_merge_utxos(txinfos)
        selected_outpoints = [OutPoint.from_bdk(utxo.outpoint) for utxo in utxos_for_input.utxos]

        if utxos_for_input.spend_all_utxos:
            # spend_all_utxos requires using add_utxo
            tx_builder = tx_builder.manually_selected_only()
            # add coins that MUST be spend
            for outpoint in selected_outpoints:
                tx_builder = tx_builder.add_utxo(outpoint)
                # TODO no add_foreign_utxo yet: see https://github.com/bitcoindevkit/bdk-ffi/issues/329 https://docs.rs/bdk/latest/bdk/wallet/tx_builder/struct.TxBuilder.html#method.add_foreign_utxo
            # manually add a change output for draining all added utxos
            tx_builder = tx_builder.drain_to(self.get_address(is_change=True).address.script_pubkey())
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
                    bdk.Address(recipient.address, network=self.network).script_pubkey()
                )
            else:
                tx_builder = tx_builder.add_recipient(
                    bdk.Address(recipient.address, network=self.network).script_pubkey(), recipient.amount
                )

        start_time = time()
        builder_result: bdk.TxBuilderResult = tx_builder.finish(self.bdkwallet)
        logger.debug(f"{self.id} tx_builder.finish  in { time()-start_time}s")

        # inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()

        logger.info(json.loads(builder_result.psbt.json_serialize()))
        logger.debug(f"psbt fee after finalized {builder_result.psbt.fee_rate().as_sat_per_vb()}")

        # get category of first utxo
        categories = clean_list(
            sum(
                [list(self.get_categories_for_txid(utxo.outpoint.txid)) for utxo in utxos_for_input.utxos],
                [],
            )
        )
        recipient_category = categories[0] if categories else None
        logger.debug(f"Selecting category {recipient_category} out of {categories} for the output addresses")

        labels = [recipient.label for recipient in txinfos.recipients if recipient.label]
        if labels:
            self.labels.set_tx_label(
                builder_result.transaction_details.txid, ",".join(labels), timestamp="now"
            )

        builder_infos = TxBuilderInfos(
            recipients=recipients,
            utxos_for_input=utxos_for_input,
            builder_result=builder_result,
            recipient_category=recipient_category,
        )
        self.set_output_categories_and_labels(builder_infos)
        return builder_infos

    def on_addresses_updated(self, update_filter: UpdateFilter) -> None:
        """Checks if the tip reaches the addresses and updated the tips if
        necessary (This is especially relevant if a psbt creates a new change
        address)"""
        self.clear_method(self._get_addresses)

        not_indexed_addresses = set(update_filter.addresses) - set(self.get_addresses())
        for not_indexed_address in not_indexed_addresses:
            self.advance_tip_to_address(not_indexed_address)

    def set_output_categories_and_labels(self, infos: TxBuilderInfos) -> None:
        # set category for all outputs
        if infos.recipient_category:
            self._set_category_for_all_recipients(
                infos.builder_result.psbt.extract_tx().output(),
                infos.recipient_category,
            )

        # set label for the recipient output
        for recipient in infos.recipients:
            # this does not include the change output
            if recipient.label and self.is_my_address(recipient.address):
                self.labels.set_addr_label(recipient.address, recipient.label, timestamp="now")

        # add a label for the change output
        labels = [recipient.label for recipient in infos.recipients if recipient.label]
        for txout in infos.builder_result.psbt.extract_tx().output():
            address = self.bdkwallet.get_address_of_txout(TxOut.from_bdk(txout))
            if not self.is_change(address):
                continue
            if address and labels and self.is_my_address(address):
                self.labels.set_addr_label(address, ",".join(labels), timestamp="now")

    def _set_category_for_all_recipients(self, outputs: List[bdk.TxOut], category: str) -> None:
        "Will assign all outputs (also change) the category"

        recipients = [
            Recipient(
                address=bdk.Address.from_script(output.script_pubkey, self.network).as_string(),
                amount=output.value,
            )
            for output in outputs
        ]

        for recipient in recipients:
            if self.is_my_address(recipient.address):
                self.labels.set_addr_category(recipient.address, category, timestamp="now")
                self.labels.add_category(category)

    def get_python_utxo(self, outpoint_str: str) -> Optional[PythonUtxo]:
        all_txos_dict = self._get_all_txos_dict()
        return all_txos_dict.get(outpoint_str)

    def get_conflicting_python_utxos(self, input_outpoints: List[OutPoint]) -> List[PythonUtxo]:
        conflicting_python_utxos = []

        python_txos = self.get_all_txos()
        wallet_outpoints: List[OutPoint] = [python_utxo.outpoint for python_utxo in python_txos]

        for outpoint in input_outpoints:
            if outpoint in wallet_outpoints:
                python_utxo = python_txos[wallet_outpoints.index(outpoint)]
                if python_utxo.is_spent_by_txid:
                    conflicting_python_utxos.append(python_utxo)
        return conflicting_python_utxos

    @instance_lru_cache()
    def sorted_delta_list_transactions(self, access_marker=None) -> List[bdk.TransactionDetails]:
        "Returns a List of TransactionDetails, sorted from old to new"

        def check_relation(child: FullTxDetail, parent: FullTxDetail) -> bool:
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

        def compare_items(item1: FullTxDetail, item2: FullTxDetail) -> int:
            future_height = 1e9  # that is far in the future

            c1 = item1.tx.confirmation_time.height if item1.tx.confirmation_time else future_height
            c2 = item2.tx.confirmation_time.height if item2.tx.confirmation_time else future_height

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
                    # sort this just as if the child had a larger confirmation_time.height
                    return 1
                # now check item2 is a (distant) child of item1
                child = item2
                parent = item1
                if check_relation(child, parent):
                    return -1

            # cannot be decided
            return 0

        dict_fulltxdetail = self.get_dict_fulltxdetail()

        sorted_fulltxdetail = sorted(
            dict_fulltxdetail.values(),
            key=functools.cmp_to_key(compare_items),
        )
        return [fulltxdetail.tx for fulltxdetail in sorted_fulltxdetail]

    def is_in_mempool(self, txid: str) -> bool:
        # TODO: Currently in mempool and is in wallet is the same thing. In the future I have to differentiate here
        if txid in self.get_txs():
            return True
        return False

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

    def get_ema_fee_rate(self, alpha=0.2, default=MIN_RELAY_FEE) -> float:
        """
        Calculate Exponential Moving Average (EMA) of the fee_rate of all transactions.
        """
        fee_rates = [
            FeeInfo.from_txdetails(txdetail).fee_rate() for txdetail in self.sorted_delta_list_transactions()
        ]
        if not fee_rates:
            return default
        ema_fee_rate = calculate_ema(fee_rates, alpha=alpha)
        return ema_fee_rate


class DescriptorExportTools:
    @staticmethod
    def get_coldcard_str(wallet_id: str, descriptor: MultipathDescriptor) -> str:
        return f"""# Coldcard descriptor export of wallet: {wallet_id}\n{ descriptor.bdk_descriptors[0].as_string() }"""


###########
# Functions that operatate on signals.get_wallets().values()


def get_wallets(signals: Signals) -> List[Wallet]:
    return list(signals.get_wallets().values())


def get_wallet(wallet_id: str, signals: Signals) -> Optional[Wallet]:
    return signals.get_wallets().get(wallet_id)


def get_wallet_of_outpoints(outpoints: List[OutPoint], signals: Signals) -> Optional[Wallet]:
    wallets = get_wallets(signals)
    if not wallets:
        return None

    number_intersections = []
    for wallet in wallets:
        python_utxos = wallet.get_all_txos()
        wallet_outpoints: List[OutPoint] = [utxo.outpoint for utxo in python_utxos]
        number_intersections.append(len(set(outpoints).intersection(set(wallet_outpoints))))

    if not any(number_intersections):
        # no intersections at all
        return None

    i = np.argmax(number_intersections)
    return wallets[i]


###########


class ToolsTxUiInfo:
    @staticmethod
    def fill_utxo_dict_from_outpoints(
        txuiinfos: TxUiInfos, outpoints: List[OutPoint], wallets: List[Wallet]
    ) -> None:
        def get_utxo_and_wallet(outpoint) -> Optional[Tuple[PythonUtxo, Wallet]]:
            for wallet in wallets:
                python_utxo = wallet.utxo_of_outpoint(outpoint)
                if python_utxo:
                    return python_utxo, wallet
            logger.warning(f"{txuiinfos.__class__.__name__}: utxo for {outpoint} could not be found")
            return None

        for outpoint in outpoints:
            res = get_utxo_and_wallet(outpoint)
            if not res:
                logger.warning(f"no python_utxo found for outpoint {outpoint} ")
                continue
            python_utxo, wallet = res
            txuiinfos.main_wallet_id = wallet.id
            txuiinfos.utxo_dict[str(outpoint)] = python_utxo

    @staticmethod
    def fill_utxo_dict_from_categories(
        txuiinfos: TxUiInfos, categories: List[str], wallets: List[Wallet]
    ) -> None:
        for wallet in wallets:
            for utxo in wallet.get_all_txos():
                if utxo.is_spent_by_txid:
                    continue
                if (
                    wallet.labels.get_category(
                        wallet.bdkwallet.get_address_of_txout(TxOut.from_bdk(utxo.txout))
                    )
                    in categories
                ):
                    txuiinfos.utxo_dict[str(utxo.outpoint)] = utxo

    @staticmethod
    def get_likely_source_wallet(txuiinfos: TxUiInfos, signals: Signals) -> Optional[Wallet]:
        wallet_dict: Dict[str, Wallet] = signals.get_wallets()

        # trying to identitfy the wallet , where i should fill the send tab
        wallet = None
        if txuiinfos.main_wallet_id:
            wallet = wallet_dict.get(txuiinfos.main_wallet_id)
            if wallet:
                return wallet

        input_outpoints = [OutPoint.from_str(outpoint) for outpoint in txuiinfos.utxo_dict.keys()]
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
        ToolsTxUiInfo.fill_utxo_dict_from_outpoints(txinfos, outpoints, wallets=wallets)
        txinfos.spend_all_utxos = True
        # outputs
        checked_max_amount = len(tx.output()) == 1  # if there is only 1 recipient, there is no change address
        for txout in tx.output():
            out_address = robust_address_str_from_script(txout.script_pubkey, network)
            if out_address is None:
                logger.warning(f"No addres of {txout} could be calculated")
                continue

            txinfos.recipients.append(
                Recipient(out_address, txout.value, checked_max_amount=checked_max_amount)
            )
        # fee rate
        txinfos.fee_rate = fee_info.fee_rate() if fee_info else None
        return txinfos

    @staticmethod
    def from_wallets(
        txid: str,
        wallets: List[Wallet],
    ) -> TxUiInfos:
        def get_wallet_tx_details(txid) -> bdk.TransactionDetails:
            for wallet in wallets:
                tx_details = wallet.get_tx(txid)
                if tx_details:
                    return wallet, tx_details
            return None, None

        wallet, tx_details = get_wallet_tx_details(txid)
        fee_info = FeeInfo(tx_details.fee, tx_details.transaction.vsize(), is_estimated=False)
        return ToolsTxUiInfo.from_tx(tx_details.transaction, fee_info, wallet.network, wallets)
