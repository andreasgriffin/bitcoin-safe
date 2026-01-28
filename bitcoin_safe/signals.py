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

import enum
import logging
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    TypeVar,
    cast,
)

if TYPE_CHECKING:
    # Import the actual class only for typing to avoid import cycles / runtime deps
    from .gui.qt.qt_wallet import (
        QTWallet,
    )
    from .gui.qt.util import (
        Message,
    )
    from .wallet import Wallet

import bdkpython as bdk
from bitcoin_nostr_chat.signals_min import SignalsMin as NostrSignalsMin
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import pyqtSignal

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.pythonbdk_types import OutPoint

logger = logging.getLogger(__name__)


class UpdateFilterReason(Enum):
    UserInput = enum.auto()
    UserImport = enum.auto()
    SourceLabelSyncer = enum.auto()
    Unknown = enum.auto()
    UserReplacedAddress = enum.auto()
    NewAddressRevealed = enum.auto()
    CategoryChange = enum.auto()
    GetUnusedCategoryAddress = enum.auto()
    RefreshCaches = enum.auto()
    CreatePSBT = enum.auto()
    UnusedAddressesCategorySet = enum.auto()
    TransactionChange = enum.auto()
    ForceRefresh = enum.auto()
    ChainHeightAdvanced = enum.auto()
    NewFxRates = enum.auto()
    RestoredSnapshot = enum.auto()
    AddressMarkedUsed = enum.auto()


class UpdateFilter:
    def __init__(
        self,
        outpoints: Iterable[OutPoint] | None = None,
        addresses: Iterable[str] | None = None,
        categories: Iterable[str | None] | None = None,
        txids: Iterable[str] | None = None,
        refresh_all=False,
        reason: UpdateFilterReason = UpdateFilterReason.Unknown,
    ) -> None:
        """Initialize instance."""
        self.outpoints: set[OutPoint] = set(outpoints) if outpoints else set()
        self.addresses: set[str] = set(addresses) if addresses else set()
        self.categories = set(categories) if categories else set()
        self.txids = set(txids) if txids else set()
        self.refresh_all = refresh_all
        self.reason = reason

    def __key__(self) -> tuple:
        """Key."""
        return tuple(self.__dict__.items())

    def __str__(self) -> str:
        """Return string representation."""
        return str(self.__key__())

    def __hash__(self) -> int:
        """Return hash value."""
        return hash(str(self))


T = TypeVar("T")


class SignalFunction(Generic[T]):
    def __init__(self, name: str | None = None) -> None:
        """Initialize instance."""
        self.name = name
        self.slots: dict[str, Callable[[], T]] = {}
        self.lock = threading.Lock()

    def connect(self, slot: Callable[[], T], slot_name: str | None = None) -> None:
        """Connect."""
        with self.lock:
            key = slot_name if slot_name and (slot_name not in self.slots) else str(slot)
            self.slots[key] = slot

    def disconnect(self, slot: Callable[[], T]) -> None:
        """Disconnect."""
        with self.lock:
            keys, values = list(self.slots.keys()), list(self.slots.values())
            if slot in values:
                idx = values.index(slot)
                del self.slots[keys[idx]]
            else:
                logger.debug(f"Tried to disconnect {slot}. But it is not in {values}. Skipping.")

    def __call__(self, *args, **kwargs) -> dict[str, T]:
        """Invoke instance as a function."""
        return self.emit(*args, **kwargs)

    def emit(self, *args, slot_name=None, **kwargs) -> dict[str, T]:
        """Emit."""
        allow_list = [slot_name] if isinstance(slot_name, str) else slot_name

        responses = {}
        if not self.slots:
            logger.debug(
                f"SignalFunction {self.name if self.name else ''}.emit() was called, "
                f"but no listeners {self.slots} are listening."
            )

        delete_slots: list[Callable[[], Any]] = []
        with self.lock:
            for key, slot in self.slots.items():
                if allow_list and key not in allow_list:
                    continue

                name = f"{slot.__self__.__class__.__name__}." if hasattr(slot, "__self__") else ""  # type: ignore
                name += f"{slot.__name__}{args, kwargs}"
                name += f" with key={key}" if key else ""
                try:
                    responses[key] = slot(*args, **kwargs)
                except Exception as e:
                    logger.debug(f"{self.__class__.__name__}: {e}")
                    logger.warning(
                        f"{slot} with key {key} caused an exception. {slot} with key {key} could "
                        f"not be called, perhaps because the object doesnt exisst anymore. "
                        "The slot will be deleted."
                    )
                    delete_slots.append(slot)
                    continue

        for slot in delete_slots:
            self.disconnect(slot)

        return responses


class SingularSignalFunction(Generic[T]):
    def __init__(self, name: str | None = None) -> None:
        """Initialize instance."""
        self.signal_f = SignalFunction[T](name=name)

    def connect(self, slot: Callable[[], T], slot_name=None) -> None:
        """Connect."""
        if not self.signal_f.slots:
            self.signal_f.connect(slot, slot_name=slot_name)
        else:
            raise Exception("Not allowed to add a second listener to this signal.")

    def disconnect(self, slot: Callable[[], T]) -> None:
        """Disconnect."""
        if not self.signal_f.slots:
            return
        else:
            self.signal_f.disconnect(slot)

    def emit(self, *args, **kwargs) -> T | None:
        """Emit."""
        responses = self.signal_f.emit(*args, **kwargs)
        if not responses:
            return None
        return list(responses.values())[0]

    def __call__(self, *args, **kwargs) -> T | None:
        """Invoke instance as a function."""
        return self.emit(*args, **kwargs)


class SignalsMin(NostrSignalsMin):
    close_all_video_widgets = cast(SignalProtocol[[]], pyqtSignal())
    currency_switch = cast(SignalProtocol[[]], pyqtSignal())


class WalletSignals(SignalsMin):
    updated = cast(SignalProtocol[[UpdateFilter]], pyqtSignal(UpdateFilter))
    completions_updated = cast(SignalProtocol[[]], pyqtSignal())

    show_address = cast(SignalProtocol[[str, str]], pyqtSignal(str, str))  # address, wallet_id
    show_utxo = cast(SignalProtocol[[OutPoint]], pyqtSignal(object))

    export_bip329_labels = cast(SignalProtocol[[]], pyqtSignal())
    export_labels = cast(SignalProtocol[[]], pyqtSignal())
    import_labels = cast(SignalProtocol[[]], pyqtSignal())
    import_bip329_labels = cast(SignalProtocol[[]], pyqtSignal())
    import_electrum_wallet_labels = cast(SignalProtocol[[]], pyqtSignal())

    finished_psbt_creation = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__()
        self.get_category_infos = SingularSignalFunction[list[CategoryInfo]](name="get_category_infos")


class Signals(SignalsMin):
    """The idea here is to define events that might need to trigger updates of the UI or
    other events  (careful of circular loops)

    State what happended, NOT the intention:

        Good signal:
            utxos_changed
        And to this signal a listener might be triggered:
            utxo_list.update()

        A bad signal is:
            need_utxo_list_update


    I immediately break the rule however for pyqtSignal, which is a function call
    """

    open_file_path = cast(SignalProtocol[[str]], pyqtSignal(str))
    open_tx_like = cast(SignalProtocol[[Any]], pyqtSignal(object))
    event_wallet_tab_closed = cast(SignalProtocol[[]], pyqtSignal())
    event_wallet_tab_added = cast(SignalProtocol[[]], pyqtSignal())

    tab_history_backward = cast(SignalProtocol[[]], pyqtSignal())
    tab_history_forward = cast(SignalProtocol[[]], pyqtSignal())

    chain_data_changed = cast(SignalProtocol[[str]], pyqtSignal(str))  # the string is the reason
    notification: SignalProtocol[[Message]] = pyqtSignal(object)  # type: ignore

    show_network_settings = cast(SignalProtocol[[]], pyqtSignal())
    open_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))  # str= filepath
    add_qt_wallet: SignalProtocol[[QTWallet, str | None, str | None]] = pyqtSignal(object, object, object)  # type: ignore  # object = qt_wallet, file_path, password
    close_qt_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))  # str = wallet_id
    signal_set_tab_properties = cast(
        SignalProtocol[[object, str, str, str]], pyqtSignal(object, str, str, str)
    )  # tab:QWidget, wallet_id, icon: icon_name, tooltip: str | None

    request_manual_sync = cast(SignalProtocol[[]], pyqtSignal())
    signal_broadcast_tx = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))
    apply_txs_to_wallets = cast(SignalProtocol[[list[bdk.Transaction], int]], pyqtSignal(object, int))
    evict_txs_from_wallet_id = cast(SignalProtocol[[list[str], str, int]], pyqtSignal(object, str, int))
    signal_close_tabs_with_txids = cast(SignalProtocol[[list[str]]], pyqtSignal(list))

    # this is for non-wallet bound objects like UitxViewer
    any_wallet_updated = cast(SignalProtocol[[UpdateFilter]], pyqtSignal(UpdateFilter))

    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__()
        self.get_network = SingularSignalFunction[bdk.Network](name="get_network")
        self.get_mempool_url = SingularSignalFunction[str](name="get_mempool_url")
        self.get_btc_symbol = SingularSignalFunction[str](name="get_btc_symbol")


class WalletFunctions:
    def __init__(self, signals: Signals) -> None:
        """Initialize instance."""
        self.signals = signals
        self.get_wallets: SignalFunction[Wallet] = SignalFunction["Wallet"](name="get_wallets")  # type: ignore
        self.get_qt_wallets: SignalFunction[QTWallet] = SignalFunction["QTWallet"](name="get_qt_wallets")  # type: ignore
        self.wallet_signals: defaultdict[str, WalletSignals] = defaultdict(WalletSignals)
