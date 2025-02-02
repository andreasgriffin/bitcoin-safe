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
import threading
from collections import defaultdict
from enum import Enum
from typing import (
    Any,
    Callable,
    DefaultDict,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    TypeVar,
)

import bdkpython as bdk
from bitcoin_nostr_chat.signals_min import SignalsMin as NostrSignalsMin
from PyQt6.QtCore import pyqtSignal

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.pythonbdk_types import Balance, OutPoint

from .typestubs import TypedPyQtSignal, TypedPyQtSignalNo

logger = logging.getLogger(__name__)


class UpdateFilterReason(Enum):
    UserInput = enum.auto()
    UserImport = enum.auto()
    SourceLabelSyncer = enum.auto()
    Unknown = enum.auto()
    UserReplacedAddress = enum.auto()
    NewAddressRevealed = enum.auto()
    CategoryAssigned = enum.auto()
    CategoryAdded = enum.auto()
    CategoryRenamed = enum.auto()
    CategoryDeleted = enum.auto()
    GetUnusedCategoryAddress = enum.auto()
    RefreshCaches = enum.auto()
    CreatePSBT = enum.auto()
    TxCreator = enum.auto()
    TransactionChange = enum.auto()
    ForceRefresh = enum.auto()
    ChainHeightAdvanced = enum.auto()
    NewFxRates = enum.auto()


class UpdateFilter:
    def __init__(
        self,
        outpoints: Iterable[OutPoint] | None = None,
        addresses: Iterable[str] | None = None,
        categories: Iterable[Optional[str]] | None = None,
        txids: Iterable[str] | None = None,
        refresh_all=False,
        reason: UpdateFilterReason = UpdateFilterReason.Unknown,
    ) -> None:
        self.outpoints: Set[OutPoint] = set(outpoints) if outpoints else set()
        self.addresses: Set[str] = set(addresses) if addresses else set()
        self.categories = set(categories) if categories else set()
        self.txids = set(txids) if txids else set()
        self.refresh_all = refresh_all
        self.reason = reason

    def __key__(self) -> Tuple:
        return tuple(self.__dict__.items())

    def __str__(self) -> str:
        return str(self.__key__())

    def __hash__(self) -> int:
        return hash(str(self))


T = TypeVar("T")


class SignalFunction(Generic[T]):
    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name
        self.slots: Dict[str, Callable[[], T]] = {}
        self.lock = threading.Lock()

    def connect(self, slot: Callable[[], T], slot_name: str | None = None) -> None:
        with self.lock:
            key = slot_name if slot_name and (slot_name not in self.slots) else str(slot)
            self.slots[key] = slot

    def disconnect(self, slot: Callable[[], T]) -> None:
        with self.lock:
            keys, values = list(self.slots.keys()), list(self.slots.values())
            if slot in values:
                idx = values.index(slot)
                del self.slots[keys[idx]]
            else:
                logger.debug(f"Tried to disconnect {slot}. But it is not in {values}. Skipping.")

    def __call__(self, *args, **kwargs) -> Dict[str, T]:
        return self.emit(*args, **kwargs)

    def emit(self, *args, slot_name=None, **kwargs) -> Dict[str, T]:
        allow_list = [slot_name] if isinstance(slot_name, str) else slot_name

        responses = {}
        if not self.slots:
            logger.debug(
                f"SignalFunction {self.name if self.name else ''}.emit() was called, but no listeners {self.slots} are listening."
            )

        delete_slots: List[Callable[[], Any]] = []
        with self.lock:
            for key, slot in self.slots.items():
                if allow_list and key not in allow_list:
                    continue

                name = f"{slot.__self__.__class__.__name__}." if hasattr(slot, "__self__") else ""
                name += f"{slot.__name__}{args, kwargs}"
                name += f" with key={key}" if key else ""
                try:
                    responses[key] = slot(*args, **kwargs)
                except Exception as e:
                    logger.debug(f"{self.__class__.__name__}: {e}")
                    logger.warning(
                        f"{slot} with key {key} caused an exception. {slot} with key {key} could not be called, perhaps because the object doesnt exisst anymore. The slot will be deleted."
                    )
                    delete_slots.append(slot)
                    continue
            logger.debug(
                f"SignalFunction {self.name if self.name else ''}.emit() --> Got {len(responses)} responses"
            )

        for slot in delete_slots:
            self.disconnect(slot)

        return responses


class SingularSignalFunction(Generic[T]):
    def __init__(self, name: str | None = None) -> None:
        self.signal_f = SignalFunction[T](name=name)

    def connect(self, slot: Callable[[], T], slot_name=None) -> None:
        if not self.signal_f.slots:
            self.signal_f.connect(slot, slot_name=slot_name)
        else:
            raise Exception("Not allowed to add a second listener to this signal.")

    def disconnect(self, slot: Callable[[], T]) -> None:
        if not self.signal_f.slots:
            return
        else:
            self.signal_f.disconnect(slot)

    def emit(self, *args, **kwargs) -> T | None:
        responses = self.signal_f.emit(*args, **kwargs)
        if not responses:
            return None
        return list(responses.values())[0]

    def __call__(self, *args, **kwargs) -> T | None:
        return self.emit(*args, **kwargs)


class SignalsMin(NostrSignalsMin):
    close_all_video_widgets: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(self) -> None:
        super().__init__()
        self.get_current_lang_code = SingularSignalFunction[str](name="get_lang_code")


class WalletSignals(SignalsMin):
    updated: TypedPyQtSignal[UpdateFilter] = pyqtSignal(UpdateFilter)  # type: ignore
    completions_updated: TypedPyQtSignalNo = pyqtSignal()  # type: ignore  # type: ignore

    show_address: TypedPyQtSignal[str, str] = pyqtSignal(str, str)  # type: ignore   # address, wallet_id
    show_utxo: TypedPyQtSignal[OutPoint] = pyqtSignal(object)  # type: ignore

    export_bip329_labels: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    export_labels: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    import_labels: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    import_bip329_labels: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    import_electrum_wallet_labels: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    finished_psbt_creation: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(self) -> None:
        super().__init__()
        self.get_display_balance = SingularSignalFunction[Balance](name="get_display_balance")
        self.get_category_infos = SingularSignalFunction[list[CategoryInfo]](name="get_category_infos")


class Signals(SignalsMin):
    """The idea here is to define events that might need to trigger updates of
    the UI or other events  (careful of circular loops)

    State what happended, NOT the intention:

        Good signal:
            utxos_changed
        And to this signal a listener might be triggered:
            utxo_list.update()

        A bad signal is:
            need_utxo_list_update


    I immediately break the rule however for pyqtSignal, which is a function call
    """

    open_file_path: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    open_tx_like: TypedPyQtSignal[Any] = pyqtSignal(object)  # type: ignore
    event_wallet_tab_closed: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    event_wallet_tab_added: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    chain_data_changed: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore # the string is the reason
    notification: "TypedPyQtSignal[Message]" = pyqtSignal(object)  # type: ignore # should be a Message instance

    show_network_settings: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    open_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore   # str= filepath
    add_qt_wallet: "TypedPyQtSignal[QTWallet, str | None, str | None]" = pyqtSignal(object, object, object)  # type: ignore # object = qt_wallet, file_path, password
    close_qt_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore # str = wallet_id
    signal_set_tab_properties: TypedPyQtSignal[str, str, str] = pyqtSignal(str, str, str)  # type: ignore  # wallet_id, icon: icon_name, tooltip: str | None

    request_manual_sync: TypedPyQtSignalNo = pyqtSignal()  # type: ignore
    signal_broadcast_tx: TypedPyQtSignal[bdk.Transaction] = pyqtSignal(bdk.Transaction)  # type: ignore

    # this is for non-wallet bound objects like UitxViewer
    any_wallet_updated: TypedPyQtSignal[UpdateFilter] = pyqtSignal(UpdateFilter)  # type: ignore

    def __init__(self) -> None:
        super().__init__()
        self.get_wallets = SignalFunction["Wallet"](name="get_wallets")  # type: ignore
        self.get_qt_wallets = SignalFunction["QTWallet"](name="get_qt_wallets")  # type: ignore
        self.get_network = SingularSignalFunction[bdk.Network](name="get_network")
        self.get_mempool_url = SingularSignalFunction[str](name="get_mempool_url")

        self.wallet_signals: DefaultDict[str, WalletSignals] = defaultdict(WalletSignals)
