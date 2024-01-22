import logging

logger = logging.getLogger(__name__)
import threading
from typing import Callable, Dict, List, Optional, Set, Union

import bdkpython as bdk
from PySide2.QtCore import QObject, Signal


class UpdateFilter:
    def __init__(
        self,
        addresses: Union[Set[str], List[str]] = None,
        categories: Union[Set[str], List[Optional[str]]] = None,
        txids: Union[Set[str], List[str]] = None,
        refresh_all=False,
    ) -> None:
        self.addresses = set(addresses) if addresses else set()
        self.categories = set(categories) if categories else set()
        self.txids = set(txids) if txids else set()
        self.refresh_all = refresh_all

    def __key__(self):
        return tuple(self.__dict__.items())

    def __str__(self) -> str:
        return str(self.__key__())


class SignalFunction:
    def __init__(self, name: Optional[str] = None):
        self.name = name
        self.slots: Dict[str, Callable] = {}
        self.lock = threading.Lock()

    def connect(self, slot: Callable, slot_name=None):
        with self.lock:
            key = slot_name if slot_name and (slot_name not in self.slots) else str(slot)
            self.slots[key] = slot

    def disconnect(self, slot):
        with self.lock:
            keys, values = zip(*list(self.slots.items()))
            idx = values.index(slot)
            del self.slots[keys[idx]]

    def __call__(self, *args, **kwargs):
        return self.emit(*args, **kwargs)

    def emit(self, *args, slot_name=None, **kwargs):
        allow_list = [slot_name] if isinstance(slot_name, str) else slot_name

        responses = {}
        if not self.slots:
            logger.debug(
                f"SignalFunction {self.name if self.name else ''}.emit() was called, but no listeners {self.slots} are listening."
            )

        delete_slots = []
        with self.lock:
            for key, slot in self.slots.items():
                if allow_list and key not in allow_list:
                    continue

                name = f"{slot.__self__.__class__.__name__}." if hasattr(slot, "__self__") else ""
                name += f"{slot.__name__}{args, kwargs}"
                name += f" with key={key}" if key else ""
                try:
                    responses[key] = slot(*args, **kwargs)
                except:
                    logger.warning(f"{slot} with key {key} could not be called. The slot will be deleted.")
                    delete_slots.append(slot)
                    continue
            logger.debug(
                f"SignalFunction {self.name if self.name else ''}.emit() --> Got {len(responses)} responses"
            )

        for slot in delete_slots:
            self.disconnect(slot)

        return responses


class SingularSignalFunction(SignalFunction):
    def connect(self, slot: Callable, slot_name=None):
        if not self.slots:
            super().connect(slot, slot_name=slot_name)
        else:
            raise Exception("Not allowed to add a second listener to this signal.")

    def emit(self, *args, **kwargs):
        responses = super().emit(*args, **kwargs)
        return list(responses.values())[0] if responses else responses


class Signals(QObject):
    """The idea here is to define events that might need to trigger updates of
    the UI or other events  (careful of circular loops)

    State what happended, NOT the intention:

        Good signal:
            utxos_changed
        And to this signal a listener might be triggered:
            utxo_list.update()

        A bad signal is:
            need_utxo_list_update


    I immediately break the rule however for Signal, which is a function call
    """

    open_tx_like = Signal(object)
    utxos_updated = Signal(UpdateFilter)
    addresses_updated = Signal(UpdateFilter)
    labels_updated = Signal(UpdateFilter)
    category_updated = Signal(UpdateFilter)
    completions_updated = Signal()
    event_wallet_tab_closed = Signal()
    event_wallet_tab_added = Signal()

    update_all_in_qt_wallet = Signal()

    show_utxo = Signal(object)
    show_address = Signal(str)
    show_private_key = Signal(str)

    chain_data_changed = Signal(str)  # the string is the reason

    notification = Signal(object)  # should be a Message instance

    cpfp_dialog = Signal(bdk.TransactionDetails)
    dscancel_dialog = Signal()
    bump_fee_dialog = Signal()
    show_onchain_invoice = Signal()
    save_transaction_into_wallet = Signal(object)

    get_wallets = SignalFunction(name="get_wallets")
    get_network = SingularSignalFunction(name="get_network")

    show_network_settings = Signal()
    export_bip329_labels = Signal(str)  # str= wallet_id
    import_bip329_labels = Signal(str)  # str= wallet_id
    open_wallet = Signal(str)  # str= filepath
    finished_open_wallet = Signal(str)  # str= wallet_id

    signal_broadcast_tx = Signal(bdk.Transaction)
