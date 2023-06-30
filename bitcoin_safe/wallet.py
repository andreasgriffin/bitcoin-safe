import logging

logger = logging.getLogger(__name__)

from collections import defaultdict
import bdkpython as bdk
from typing import Sequence, Set, Tuple
from .pythonbdk_types import Error
from .gui.qt.util import Message

from .tx import TXInfos
from .util import (
    balance_dict,
    Satoshis,
    timestamp_to_datetime,
)
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
    AddressTypes,
    get_default_address_type,
    generate_bdk_descriptors,
    descriptor_infos,
    generate_output_descriptors_from_keystores,
)
import json
from .tx import TXInfos
from .util import clean_list, Satoshis
from .config import UserConfig
import numpy as np
from .labels import Labels
import copy
from packaging import version


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
    def __init__(self, tx: bdk.TransactionDetails, blockchain: bdk.Blockchain) -> None:
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
            blockchain.get_height() - tx.confirmation_time.height + 1
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


class OutputInfo:
    def __init__(self, outpoint: OutPoint, tx: bdk.TransactionDetails) -> None:
        self.outpoint = outpoint
        self.tx = tx


def locked(func):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return func(self, *args, **kwargs)

    return wrapper


class Wallet(BaseSaveableClass):
    """
    If any bitcoin logic (ontop of bdk) has to be done, then here is the place
    """

    VERSION = "0.1.1"
    global_variables = globals()

    def __init__(
        self,
        id,
        threshold: int,
        signers: int = 1,
        keystores: List[KeyStore] = None,
        address_type: AddressType = None,
        gap=20,
        gap_change=20,
        descriptors=None,
        categories=None,
        labels: Labels = None,
        network: bdk.Network = None,
        config: UserConfig = None,
    ):
        super().__init__()

        self.bdkwallet = None
        self.id = id
        self.threshold = threshold
        self.blockchain = None
        self.network = network if network else config.network_settings.network
        # prevent loading a wallet into different networks
        assert (
            self.network == config.network_settings.network
        ), f"Cannot load a wallet for {self.network}, when the network {config.network_settings.network} is configured"
        self.gap = gap
        self.gap_change = gap_change
        self.descriptors: List[bdk.Descriptor] = (
            [] if descriptors is None else descriptors
        )
        self.config = config
        self.cache = {}
        self.write_lock = Lock()
        self.local_txs = []
        self.max_tips = [
            0,
            0,
        ]  # this is needed because there is currently no way to get the real tip from bdkwallet
        self.categories = categories if categories else []
        self.labels: Labels = labels if labels else Labels()

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
                    initial_address_type.derivation_path(
                        self.config.network_settings.network
                    ),
                    label=self.signer_names(threshold, i),
                    type=None,
                )
                for i in range(signers)
            ]
        )
        self.set_address_type(initial_address_type)

    def temporary_descriptors(self, use_html=False):
        """
        These is a descriptor that can be generated without having all keystore information.
        This is useful for UI
        """
        return generate_output_descriptors_from_keystores(
            self.threshold,
            self.address_type,
            self.keystores,
            self.config.network_settings.network,
            replace_keystore_with_dummy=False,
            use_html=use_html,
            combined_descriptors=True,
        )

    def serialize(self):
        d = super().serialize()

        keys = [
            "id",
            "threshold",
            "gap",
            "network",
            "gap_change",
            "keystores",
            "categories",
            "labels",
        ]
        for k in keys:
            d[k] = self.__dict__[k]

        d["descriptors"] = [descriptor.as_string() for descriptor in self.descriptors]
        d["tips"] = self.tips
        return d

    @classmethod
    def load(cls, filename, config: UserConfig, password=None):
        return super().load(
            filename=filename,
            password=password,
            class_kwargs={"Wallet": {"config": config}},
        )

    def partital_clone(self):
        dct = self.serialize()
        super().deserialize(dct)

        del dct["tips"]
        wallet = Wallet(**dct, config=self.config)
        return wallet

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
        dct["descriptors"] = [
            bdk.Descriptor(descriptor, network=config.network_settings.network)
            for descriptor in dct["descriptors"]
        ]

        tips = dct["tips"]
        del dct["tips"]

        if class_kwargs:
            dct.update(class_kwargs[cls.__name__])

        wallet = Wallet(**dct)

        wallet.create_wallet(wallet.threshold, wallet.keystores, wallet.address_type)
        wallet.tips = tips

        return wallet

    def basename(self):
        import string, os

        def create_valid_filename(filename):
            basename = os.path.basename(filename)
            valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
            return "".join(c for c in basename if c in valid_chars)

        return create_valid_filename(self.id)

    def reset_cache(self):
        self.cache = {}

    def signer_names(self, threshold: int, i: int):
        i += 1
        if i <= threshold:
            return f"Signer {i}"
        else:
            return f"Recovery Signer {i}"

    def calculate_descriptors(self) -> bdk.Descriptor:
        return generate_bdk_descriptors(
            self.threshold,
            self.address_type,
            self.keystores,
            self.config.network_settings.network,
        )

    def set_wallet_from_descriptor(self, string_descriptor, recreate_bdk_wallet=True):

        infos = descriptor_infos(
            string_descriptor, self.config.network_settings.network
        )

        self.set_number_of_keystores(
            len(infos["keystores"]),
            cloned_reference_keystores=[k.clone() for k in infos["keystores"]],
        )
        for self_keystore, descriptor_keystore in zip(
            self.keystores, infos["keystores"]
        ):
            self_keystore.from_other_keystore(descriptor_keystore)

        self.set_address_type(infos["address_type"])
        self.set_threshold(infos["threshold"])

        for i, keystore in enumerate(self.keystores):
            keystore.label = self.signer_names(self.threshold, i)

        if recreate_bdk_wallet:
            self.recreate_bdk_wallet()

    def recreate_bdk_wallet(self):
        self.create_wallet(self.threshold, self.keystores, self.address_type)

    def set_keystores(self, keystores):
        self.keystores = keystores

    def set_threshold(self, threshold):
        self.threshold = threshold

    def set_number_of_keystores(self, n, cloned_reference_keystores=None):
        if cloned_reference_keystores is None:
            cloned_reference_keystores = []
        if len(cloned_reference_keystores) < n:
            cloned_reference_keystores += [
                KeyStore(
                    None,
                    None,
                    self.address_type.derivation_path(
                        self.config.network_settings.network
                    ),
                    label=self.signer_names(self.threshold, i),
                    type=KeyStoreTypes.watch_only,
                )
                for i in range(n - len(cloned_reference_keystores))
            ]

        if n > len(self.keystores):
            for i in range(len(self.keystores), n):
                self.keystores.append(cloned_reference_keystores[i])
        elif n < len(self.keystores):
            for i in range(n, len(self.keystores)):
                self.keystores.pop()  # removes the last item

    def set_gap(self, gap):
        self.gap = gap

    def set_wallet_id(self, id):
        self.id = id

    def set_address_type(self, address_type: AddressType):
        self.address_type = address_type
        for keystore in self.keystores:
            keystore.set_derivation_path(
                address_type.derivation_path(self.config.network_settings.network)
            )

    def create_seed_wallet(self, seed):
        assert (
            self.config.network_settings.network != bdk.Network.BITCOIN
        )  # do not allow seeds on mainnet

        self.seed = seed
        mnemonic = bdk.Mnemonic.from_string(seed)

        descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(
                self.config.network_settings.network, mnemonic, ""
            ),
            keychain=bdk.KeychainKind.EXTERNAL,
            network=self.config.network_settings.network,
        )
        change_descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(
                self.config.network_settings.network, mnemonic, ""
            ),
            keychain=bdk.KeychainKind.INTERNAL,
            network=self.config.network_settings.network,
        )
        self.create_descriptor_wallet(
            descriptor=descriptor, change_descriptor=change_descriptor
        )

    def create_wallet(
        self, threshold: int, keystores: List[KeyStore], address_type: AddressType
    ):
        # sanity checks
        assert threshold <= len(keystores)
        is_multisig = len(keystores) > 1
        assert address_type.is_multisig == is_multisig

        # check if the desc_template is in bdk and prevent unsafe templates
        if (
            self.config.network_settings.network == bdk.Network.BITCOIN
            and address_type.desc_template.__name__ not in dir(bdk.Descriptor)
        ):
            logger.warning("Unsafe mode!")

        if address_type.bdk_descriptor:
            # TODO: Currently only single sig implemented, since bdk only has single sig templates
            keystore = keystores[0]
            self.descriptors = [
                address_type.bdk_descriptor(
                    bdk.DescriptorPublicKey.from_string(keystore.xpub),
                    keystore.fingerprint,
                    keychainkind,
                    self.config.network_settings.network,
                )
                if not keystore.mnemonic
                else address_type.bdk_descriptor_secret(
                    bdk.DescriptorSecretKey(
                        self.config.network_settings.network, keystore.mnemonic, ""
                    ),
                    keychainkind,
                    self.config.network_settings.network,
                )
                for keychainkind in [
                    bdk.KeychainKind.EXTERNAL,
                    bdk.KeychainKind.INTERNAL,
                ]
            ]
        else:
            self.descriptors = generate_bdk_descriptors(
                threshold, address_type, keystores, self.config.network_settings.network
            )

        self.create_descriptor_wallet(
            descriptor=self.descriptors[0], change_descriptor=self.descriptors[1]
        )
        self.threshold = threshold
        self.address_type = address_type

    def create_descriptor_wallet(self, descriptor, change_descriptor=None):
        self.descriptors = [
            bdk.Descriptor(descriptor, network=self.config.network_settings.network)
            if isinstance(descriptor, str)
            else descriptor,
            bdk.Descriptor(
                change_descriptor, network=self.config.network_settings.network
            )
            if isinstance(change_descriptor, str)
            else change_descriptor,
        ]

        self.bdkwallet = bdk.Wallet(
            descriptor=self.descriptors[0],
            change_descriptor=self.descriptors[1],
            network=self.config.network_settings.network,
            database_config=bdk.DatabaseConfig.MEMORY(),
        )
        # print(f"Wallet created successfully {self.bdkwallet}")

    def is_multisig(self):
        return len(self.keystores) > 1

    def get_address_types(self, is_multisig=None) -> List[AddressType]:
        if is_multisig is None:
            is_multisig = self.is_multisig()
        return [
            v
            for k, v in AddressTypes.__dict__.items()
            if (not k.startswith("_")) and v.is_multisig == is_multisig
        ]

    def get_tx_status(self, tx: bdk.TransactionDetails) -> TxStatus:
        return TxStatus(tx, self.blockchain)

    def init_blockchain(self):
        """
        https://github.com/BitcoinDevelopersAcademy/bit-container


        alias rt-start='sudo docker run -d --rm -p 127.0.0.1:18443-18444:18443-18444/tcp -p 127.0.0.1:60401:60401/tcp --name electrs bitcoindevkit/electrs'
        alias rt-stop='sudo docker kill electrs'
        alias rt-logs='sudo docker container logs electrs'
        alias rt-cli='sudo docker exec -it electrs /root/bitcoin-cli -regtest  '
        """
        if self.config.network_settings.server_type == BlockchainType.Electrum:
            if self.config.network_settings.network == bdk.Network.REGTEST:
                blockchain_config = bdk.BlockchainConfig.ELECTRUM(
                    bdk.ElectrumConfig(
                        f"{self.config.network_settings.electrum_ip}:{self.config.network_settings.electrum_port}",
                        None,
                        10,
                        100,
                        100,
                        False,
                    )
                )

        elif (
            self.config.network_settings.server_type
            == BlockchainType.CompactBlockFilter
        ):
            folder = f"./compact-filters-{self.id}-{self.config.network_settings.network.name}"
            if self.config.network_settings.network == bdk.Network.BITCOIN:
                start_height = 481824
            elif self.config.network_settings.network in [
                bdk.Network.REGTEST,
                bdk.Network.SIGNET,
            ]:
                start_height = 0
            elif self.config.network_settings.network == bdk.Network.TESTNET:
                start_height = 2000000
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
                    self.id,
                    None,
                )
            )
        self.blockchain = bdk.Blockchain(blockchain_config)
        return self.blockchain

    def sync(self, progress_function_threadsafe=None):
        if self.blockchain is None:
            self.init_blockchain()

        if not progress_function_threadsafe:

            def progress_function_threadsafe(progress: float, message: str):
                logger.info((progress, message))

        progress = bdk.Progress()
        progress.update = progress_function_threadsafe

        self.bdkwallet.sync(self.blockchain, progress)
        logger.info(
            f"Wallet balance is: { balance_dict(self.bdkwallet.get_balance()) }"
        )

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
        self.update_tip(new_last_index=index, is_change=is_change)

        if self.labels.get_category(address) or self.labels.get_label(address):
            return self.get_address(force_new=True, is_change=is_change)

        logger.info(f"New address: {address} at index {index}")
        return address_info

    def get_output_addresses(self, transaction) -> List[bdk.Address]:
        # print(f'Getting output addresses for txid {transaction.txid}')
        addresses = [
            self.get_address_of_txout(output)
            for output in transaction.transaction.output()
        ]
        return addresses

    def get_tx(self, txid) -> bdk.TransactionDetails:
        txs = {tx.txid: tx for tx in self.get_list_transactions()}
        if txid in txs:
            return txs[txid]

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
        self.get_addresses()
        self.get_list_transactions()
        self.get_utxos()
        self.get_received_send_maps()

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

    def _get_tip(self, is_change):
        if not self.bdkwallet:
            return self.max_tips

        bdk_get_address = (
            self.bdkwallet.get_internal_address
            if is_change
            else self.bdkwallet.get_address
        )
        new_tip = max(
            bdk_get_address(bdk.AddressIndex.LAST_UNUSED()).index,
            self.max_tips[int(is_change)],
        )
        self.max_tips[int(is_change)] = new_tip
        return new_tip

    def _set_tip(self, value, is_change):
        with self.write_lock:
            bdk_get_address = (
                self.bdkwallet.get_internal_address
                if is_change
                else self.bdkwallet.get_address
            )

            current_tip = self._get_tip(is_change=is_change)
            logger.debug(f"current_tip = {current_tip},  value = {value}")
            if value > current_tip:
                logger.debug(f"indexing {value - current_tip} new addresses")
                [
                    bdk_get_address(bdk.AddressIndex.NEW())
                    for i in range(current_tip, value)
                ]  # NEW addess them to the watch list

            new_tip = self._get_tip(is_change=is_change)
            logger.debug(f"new_tip = {new_tip},  value = {value}")
            assert new_tip == value

    def update_tip(self, new_last_index=None, is_change=False):
        new_tip = [0, 0]
        new_tip[int(is_change)] = new_last_index

        self.tip = [max(old, new) for old, new in zip(self.tip, new_tip)]

    @property
    def tips(self):
        return [self._get_tip(b) for b in [False, True]]

    @tips.setter
    def tips(self, value):
        [self._set_tip(v, b) for v, b in zip(value, [False, True])]

    @cache_method
    def get_bdk_address_infos(
        self, is_change=False, slice_start=None, slice_stop=None
    ) -> Sequence[bdk.AddressInfo]:
        if (not is_change) and (not self.descriptors):
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

    def get_all_known_addresses_beyond_gap_limit(self):
        return []

    def get_address_of_txout(self, txout: bdk.TxOut) -> str:
        if txout.value == 0:
            return None
        else:
            return bdk.Address.from_script(
                txout.script_pubkey, self.config.network_settings.network
            ).as_string()

    def utxo_of_outpoint(self, outpoint: bdk.OutPoint) -> bdk.LocalUtxo:
        for utxo in self.get_utxos():
            if OutPoint.from_bdk(outpoint) == OutPoint.from_bdk(utxo.outpoint):
                return utxo

    @cache_method
    def get_utxos(self) -> List[bdk.LocalUtxo]:
        return self.bdkwallet.list_unspent()

    @cache_method
    def get_address_balances(self) -> Dict[AddressInfoMin, Tuple[int, int, int]]:
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """

        def zero_balances():
            return [0, 0, 0]

        utxos = self.get_utxos()
        balances: Dict[str, Tuple[int, int, int]] = defaultdict(zero_balances)

        for i, utxo in enumerate(utxos):
            tx = self.get_tx(utxo.outpoint.txid)
            txout = tx.transaction.output()[utxo.outpoint.vout]

            address = self.get_address_of_txout(txout)
            if address is None:
                continue
            balances[address][0] += txout.value
            balances[address][1] += 0
            balances[address][2] += 0

        return balances

    def get_addr_balance(self, address):
        """Return the balance of a set of addresses:
        confirmed and matured, unconfirmed, unmatured
        """
        return self.get_address_balances()[address]

    @cache_method
    def get_list_transactions(self) -> List[bdk.TransactionDetails]:
        return self.bdkwallet.list_transactions(True)

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
    ) -> Tuple[Dict[str, List[OutputInfo]], Dict[str, List[OutputInfo]]]:
        hash_outpoint_to_address: Dict[int, str] = {}  # hash(out_point), address
        received: Dict[str, List[OutputInfo]] = {}  #  address: OutputInfo
        send: Dict[str, List[OutputInfo]] = {}  #  address: OutputInfo

        # build the received dict
        for tx in self.get_list_transactions():
            for vout, txout in enumerate(tx.transaction.output()):
                address = self.get_address_of_txout(txout)
                out_point = OutPoint(tx.txid, vout)
                if address is None:
                    continue
                if address not in received:
                    received[address] = []
                received[address].append(OutputInfo(out_point, tx))
                hash_outpoint_to_address[hash(out_point)] = address

        # check if any input tx is in transactions_involving_address
        for tx in self.get_list_transactions():
            for input in tx.transaction.input():
                out_point = OutPoint.from_bdk(input.previous_output)
                if hash(out_point) in hash_outpoint_to_address:
                    address = hash_outpoint_to_address[hash(out_point)]
                    if address not in send:
                        send[address] = []
                    send[address].append(OutputInfo(out_point, tx))

        return received, send

    def get_received_and_send_involving_address(
        self, address
    ) -> Tuple[List[OutputInfo], List[OutputInfo]]:
        received, send = self.get_received_send_maps()
        return received.get(address, []).copy(), send.get(address, []).copy()

    def get_txs_involving_address(self, address) -> List[OutputInfo]:
        received, send = self.get_received_and_send_involving_address(address)
        return received.copy() + send.copy()

    def get_utxos(self) -> List[bdk.LocalUtxo]:
        return self.bdkwallet.list_unspent()

    def address_is_used(self, address):
        """
        Check if any tx had this address as an output
        """
        return bool(self.get_txs_involving_address(address))

    def get_address_history_len(self, address):
        return len(self.get_txs_involving_address(address))

    @cache_method
    def get_addresses_and_address_infos(
        self,
    ) -> Tuple[List[str], List[bdk.AddressInfo]]:
        addresses_infos = self.get_bdk_address_infos()
        addresses = [
            address_info.address.as_string() for address_info in addresses_infos
        ]
        return addresses, addresses_infos

    def get_address_path_str(self, address) -> str:
        addresses, addresses_infos = self.get_addresses_and_address_infos()

        if address in addresses:
            return str(addresses_infos[addresses.index(address)].index)
        return ""

    def get_redeem_script(self, address):
        # TODO:
        return None

    def get_witness_script(self, address):
        return None

    def get_categories_for_txid(self, txid):
        tx = self.get_tx(txid)
        l = [
            [self.get_address_of_txout(output), output.value]
            for output in tx.transaction.output()
        ]
        logger.debug(str((txid[:10], l)))
        l = clean_list(
            [
                self.labels.get_category(self.get_address_of_txout(output))
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
                        self.get_address_of_txout(output), autofill_from_txs=False
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
            Satoshis(balance.confirmed),
            Satoshis(balance.trusted_pending + balance.untrusted_pending),
            Satoshis(balance.immature),
        ]

    def get_utxo_name(self, utxo):
        tx = self.get_tx(utxo.outpoint.txid)
        return f"{tx.txid}:{utxo.outpoint.vout}"

    def get_utxo_address(self, utxo):
        tx = self.get_tx(utxo.outpoint.txid)
        return self.get_output_addresses(tx)[utxo.outpoint.vout]

    def get_full_history(self, address_domain=None):
        transactions = []
        balance = 0

        txid_domain = None
        if address_domain:
            # get txids that one is interested in
            txid_domain = []
            for address in address_domain:
                txid_domain += [
                    outputinfo.tx.txid
                    for outputinfo in self.get_txs_involving_address(address)
                ]

        monotonic_timestamp = 0
        for tx in self.get_list_transactions():
            if (txid_domain is not None) and (tx.txid not in txid_domain):
                continue

            value_delta = tx.received - tx.sent
            balance += value_delta
            timestamp = tx.confirmation_time.timestamp if tx.confirmation_time else 100

            # TODO: Correct this.
            height = tx.confirmation_time.height if tx.confirmation_time else None

            monotonic_timestamp = max(monotonic_timestamp, timestamp)
            d = {
                "txid": tx.txid,
                "fee_sat": tx.fee,
                "height": height
                if height is not None
                else self.blockchain.get_height() + 1,
                "confirmations": self.blockchain.get_height() - height + 1
                if height is not None
                else -1,
                "timestamp": timestamp,
                "monotonic_timestamp": monotonic_timestamp,
                "incoming": True if value_delta > 0 else False,
                "bc_value": Satoshis(value_delta),
                "value": Satoshis(value_delta),
                "bc_balance": Satoshis(balance),
                "balance": Satoshis(balance),
                "date": timestamp_to_datetime(timestamp),
                "label": self.get_label_for_txid(tx.txid),
                "categories": self.get_categories_for_txid(tx.txid),
                "txpos_in_block": None,  # not in bdk
            }
            transactions.append(d)
        return sorted(transactions, key=lambda x: x["height"])

    # def get_tx_status(self, txid, tx_mined_info: TxMinedInfo):
    #     extra = []
    #     height = tx_mined_info.height
    #     conf = tx_mined_info.conf
    #     timestamp = tx_mined_info.timestamp
    #     if height == TX_HEIGHT_FUTURE:
    #         num_blocks_remainining = (
    #             tx_mined_info.wanted_height - self.blockchain.get_height()
    #         )
    #         num_blocks_remainining = max(0, num_blocks_remainining)
    #         return 2, f"in {num_blocks_remainining} blocks"
    #     if conf == 0:
    #         tx = self.get_tx(txid)
    #         if not tx:
    #             return 2, "unknown"
    #         is_final = True  # TODO: tx and tx.is_final()
    #         fee = tx.fee
    #         if fee is not None:
    #             size = tx.transaction.size()
    #             fee_per_byte = fee / size
    #             extra.append(format_fee_satoshis(fee_per_byte) + " sat/b")
    #         # if fee is not None and height in (TX_HEIGHT_UNCONF_PARENT, TX_HEIGHT_UNCONFIRMED) \
    #         #    and self.config.has_fee_mempool():
    #         #     exp_n = self.config.fee_to_depth(fee_per_byte)
    #         #     if exp_n is not None:
    #         #         extra.append(self.config.get_depth_mb_str(exp_n))
    #         if height == TX_HEIGHT_LOCAL:
    #             status = 3
    #         elif height == TX_HEIGHT_UNCONF_PARENT:
    #             status = 1
    #         elif height == TX_HEIGHT_UNCONFIRMED:
    #             status = 0
    #         else:
    #             status = 2  # not SPV verified
    #     else:
    #         status = 3 + min(conf, 6)
    #     time_str = format_time(timestamp) if timestamp else _("unknown")
    #     status_str = TX_STATUS[status] if status < 4 else time_str
    #     if extra:
    #         status_str += " [%s]" % (", ".join(extra))
    #     return status, status_str

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
        utxos = utxos.copy()
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
            f"Selected {len(selected_utxos)} outpoints with {Satoshis(selected_value).str_with_unit()}"
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
                f"Selected {len(opportunistic_merging_utxos)} additional opportunistic outpoints with small values (so total ={len(selected_utxos)+len(opportunistic_merging_utxos)}) with {Satoshis(sum([utxo.txout.value for utxo in opportunistic_merging_utxos])).str_with_unit()}"
            )

        return UtxosForInputs(
            utxos=selected_utxos + opportunistic_merging_utxos,
            included_opportunistic_merging_utxos=opportunistic_merging_utxos,
            spend_all_utxos=True,
        )

    def get_all_input_utxos(self, txinfos: TXInfos) -> UtxosForInputs:
        if not txinfos.utxo_strings and not txinfos.categories:
            logger.warning("No inputs provided for coin selection")

        utxos = []

        if txinfos.utxo_strings:
            utxos += [
                self.utxo_of_outpoint(OutPoint.from_str(s))
                for s in txinfos.utxo_strings
            ]
        elif txinfos.categories:  # this will not be added if txinfos.utxo_strings
            utxos += [
                utxo
                for utxo in self.bdkwallet.list_unspent()
                if self.category.get(self.get_address_of_txout(utxo.txout))
                in txinfos.categories
            ]
        else:
            logger.debug("No utxos or categories for coin selection")

        return UtxosForInputs(utxos=utxos, spend_all_utxos=bool(txinfos.utxo_strings))

    def create_coin_selection_dict(self, txinfos: TXInfos) -> UtxosForInputs:
        if not txinfos.utxo_strings and not txinfos.categories:
            logger.warning("No inputs provided for coin selection")

        utxos_for_input = self.get_all_input_utxos(txinfos)
        if not utxos_for_input:
            logger.warning("No utxos or categories for coin selection")
            return UtxosForInputs(utxos=[])

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
            # manually add a change output for draining all added utxos
            tx_builder = tx_builder.drain_to(
                self.get_address(is_change=True).address.script_pubkey()
            )
        else:
            # exclude all other coins, to leave only selected_outpoints to choose from
            unspendable_outpoints = [
                utxo.outpoint
                for utxo in self.get_utxos()
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
        except Error.NoRecipients as e:
            Message(e.args[0], title="er").show_error()
            raise

        self.tips = [tip + 1 for tip in self.tips]

        inputs: List[bdk.TxIn] = builder_result.psbt.extract_tx().input()
        logger.debug(str(len(inputs)))

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
        category = categories[0] if categories else None
        logger.debug(
            f"Selecting category {category} out of {categories} for the output addresses"
        )

        # the category is automatically copied from the input(s)
        if category:
            self.set_recipient_category_from_inputs(
                builder_result.psbt.extract_tx().output(), category
            )
        # the label is not copied from the inputs
        for recipient in txinfos.recipients:
            # this does not include the change output
            if recipient.label:
                self.labels[recipient.address] = recipient.label
        # add a label for the change output
        for txout in builder_result.psbt.extract_tx().output():
            address = self.get_address_of_txout(txout)
            if not self.is_change(address):
                continue
            labels = [
                recipient.label for recipient in txinfos.recipients if recipient.label
            ]
            if address and labels:
                self.labels[address] = ",".join(labels)

        txinfos.builder_result = builder_result
        return txinfos

    def set_recipient_category_from_inputs(
        self, outputs: List[bdk.TxOut], category: str
    ):
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
            self.labels.set_addr_category(recipient.address, category)
