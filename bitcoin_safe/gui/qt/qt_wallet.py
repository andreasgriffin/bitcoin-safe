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

import asyncio
import datetime
import json
import logging
import os
import shutil
from collections.abc import Callable, Coroutine, Iterable
from concurrent.futures import Future
from datetime import timedelta
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    TypeVar,
    cast,
)

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.util import time_logger
from PyQt6.QtCore import QLocale, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.client import ProgressInfo, UpdateInfo
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.category_manager.category_list import CategoryList
from bitcoin_safe.gui.qt.category_manager.category_manager import CategoryManager
from bitcoin_safe.gui.qt.my_treeview import (
    MyItemDataRole,
    SearchableTab,
    TreeViewWithToolbar,
)
from bitcoin_safe.gui.qt.qt_wallet_base import QtWalletBase, SyncStatus
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.utxo_list import UTXOList, UtxoListWithToolbar
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.labels import LabelType
from bitcoin_safe.pdf_statement import make_and_open_pdf_statement
from bitcoin_safe.plugin_framework.plugin_list_widget import PluginListWidget
from bitcoin_safe.plugin_framework.plugin_manager import PluginManager
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.pythonbdk_types import (
    Balance,
    BlockchainType,
    TransactionDetails,
    python_utxo_balance,
)
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.util import SATOSHIS_PER_BTC, filename_clean
from bitcoin_safe.wallet_util import WalletDifferenceType

from ...config import UserConfig
from ...execute_config import DEFAULT_LANG_CODE, ENABLE_PLUGINS, ENABLE_TIMERS
from ...mempool_manager import MempoolManager
from ...signals import UpdateFilter, UpdateFilterReason, WalletFunctions, WalletSignals
from ...tx import TxBuilderInfos, TxUiInfos, short_tx_id
from ...util import fast_version
from ...wallet import (
    LOCAL_TX_LAST_SEEN,
    DeltaCacheListTransactions,
    ProtoWallet,
    TxStatus,
    Wallet,
    get_wallets,
)
from .address_list import AddressList, AddressListWithToolbar
from .bitcoin_quick_receive import BitcoinQuickReceive
from .descriptor_ui import DescriptorUI
from .dialogs import PasswordCreation, PasswordQuestion
from .hist_list import HistList, HistListWithToolbar
from .util import Message, MessageType, caught_exception_message
from .wallet_balance_chart import WalletBalanceChart

logger = logging.getLogger(__name__)


T = TypeVar("T")


MINIMUM_INTERVAL_SYNC_REGULARLY = (
    5 * 60
)  # in seconds  .  A high value is OK here because the p2p monitoring will inform of any new txs instantly


class QTProtoWallet(QtWalletBase):
    signal_create_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_close_wallet = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        protowallet: ProtoWallet,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        loop_in_thread: LoopInThread | None,
        tutorial_index: int | None = None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            config=config,
            wallet_functions=wallet_functions,
            tutorial_index=tutorial_index,
            parent=parent,
            loop_in_thread=loop_in_thread,
        )

        self.tabs.setTitle(protowallet.id)
        self.wallet_descriptor_ui, self.settings_node = self.create_and_add_settings_tab(protowallet)

    @property
    def protowallet(self) -> ProtoWallet:
        """Protowallet."""
        return self.wallet_descriptor_ui.protowallet

    @protowallet.setter
    def protowallet(self, protowallet) -> None:
        """Protowallet."""
        self.wallet_descriptor_ui.set_protowallet(protowallet)

    def get_mn_tuple(self) -> tuple[int, int]:
        """Get mn tuple."""
        return self.protowallet.threshold, len(self.protowallet.keystores)

    def get_keystore_labels(self) -> list[str]:
        """Get keystore labels."""
        return [self.protowallet.signer_name(i) for i in range(len(self.protowallet.keystores))]

    def create_and_add_settings_tab(self, protowallet: ProtoWallet) -> tuple[DescriptorUI, SidebarNode]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=protowallet,
            wallet_functions=self.wallet_functions,
            loop_in_thread=self.loop_in_thread,
        )
        settings_node = SidebarNode[object](
            widget=wallet_descriptor_ui,
            data=wallet_descriptor_ui,
            icon=svg_tools.get_QIcon("bi--text-left.svg"),
            title=self.tr("Setup wallet"),
        )
        self.tabs.addChildNode(settings_node)

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(self.on_apply_setting_changes)
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(self.on_cancel_wallet_creation)
        return wallet_descriptor_ui, settings_node

    def on_cancel_wallet_creation(self):
        """On cancel wallet creation."""
        self.signal_close_wallet.emit(self.protowallet.id)

    def on_apply_setting_changes(self) -> None:
        """On apply setting changes."""
        try:
            self.wallet_descriptor_ui.set_protowallet_from_ui()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), type=MessageType.Error, parent=self)
            return

        self.signal_create_wallet.emit(self.protowallet.id)

    def get_editable_protowallet(self) -> ProtoWallet:
        """Get editable protowallet."""
        return self.protowallet

    def close(self) -> bool:
        """Close."""
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()


class ProgressSignal:
    def __init__(self, signal_settext_balance_label: SignalProtocol[[str]]) -> None:
        """Initialize instance."""
        self.signal_settext_balance_label = signal_settext_balance_label

    def update(self, progress: float, message: str | None):
        """Update."""
        self.signal_settext_balance_label.emit(f"Syncing wallet: {round(progress)}%  {message}")


class QTWallet(QtWalletBase, BaseSaveableClass):
    VERSION = "0.3.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        Wallet.__name__: Wallet,
        Balance.__name__: Balance,
        HistListWithToolbar.__name__: HistListWithToolbar,
        AddressListWithToolbar.__name__: AddressListWithToolbar,
        UITx_Creator.__name__: UITx_Creator,
        PluginManager.__name__: PluginManager,
    }

    signal_settext_balance_label = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_progress_info = cast(SignalProtocol[[ProgressInfo]], pyqtSignal(ProgressInfo))
    signal_show_manage_categories = cast(SignalProtocol[[]], pyqtSignal())
    signal_client_log_info = cast(SignalProtocol[[bdk.Info]], pyqtSignal(bdk.Info))
    signal_client_log_warning = cast(SignalProtocol[[bdk.Warning]], pyqtSignal(bdk.Warning))
    signal_client_log_str = cast(SignalProtocol[[str]], pyqtSignal(str))
    signal_wallet_update = cast(SignalProtocol[[UpdateInfo]], pyqtSignal(UpdateInfo))
    signal_refresh_sync_status = cast(SignalProtocol[[]], pyqtSignal())

    @staticmethod
    def cls_kwargs(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        mempool_manager: MempoolManager,
        loop_in_thread: LoopInThread | None,
        file_path: str | None,
    ):
        return {
            "config": config,
            "wallet_functions": wallet_functions,
            "mempool_manager": mempool_manager,
            "fx": fx,
            "file_path": file_path,
            "loop_in_thread": loop_in_thread,
        }

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        mempool_manager: MempoolManager,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        password: str | None = None,
        file_path: str | None = None,
        notified_tx_ids: Iterable[str] | None = None,
        warned_change_without_input_txids: Iterable[str] | None = None,
        tutorial_index: int | None = None,
        history_list_with_toolbar: HistListWithToolbar | None = None,
        address_list_with_toolbar: AddressListWithToolbar | None = None,
        uitx_creator: UITx_Creator | None = None,
        last_tab_title: str = "",
        plugin_manager: PluginManager | None = None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        super().__init__(
            wallet_functions=wallet_functions,
            config=config,
            tutorial_index=tutorial_index,
            parent=parent,
            loop_in_thread=loop_in_thread,
        )
        self.last_tab_title = last_tab_title
        self.mempool_manager = mempool_manager
        self.wallet = self.set_wallet(wallet)
        self.password = password
        self.fx = fx
        self.plugins_menu = QMenu()
        self._file_path = file_path
        self._client_bridge_tasks: list[Future[Any]] = []
        self.progress_update_timer = QTimer()
        self.timer_sync_retry = QTimer()
        self.timer_sync_regularly = QTimer()
        self.notified_tx_ids = set(notified_tx_ids if notified_tx_ids else [])
        self.category_core = CategoryCore(
            wallet=self.wallet,
            signals=self.signals,
            wallet_signals=self.wallet_functions.wallet_signals[self.wallet.id],
        )
        self._warned_change_without_input_txids = set(
            warned_change_without_input_txids if warned_change_without_input_txids else []
        )

        self._last_syncing_start = datetime.datetime.now()
        self._syncing_delay = timedelta(seconds=0)
        self._last_sync_chain_height = 0
        self._rows_after_hist_list_update: list[str] = []

        ########### create tabs
        (
            self.history_tab,
            self.history_list,
            self.hist_node,
            self.wallet_balance_chart,
            self.history_list_with_toolbar,
        ) = self._create_hist_tab(self.tabs, history_list_with_toolbar=history_list_with_toolbar)

        (
            self.address_tab,
            self.address_list,
            self.address_node,
            self.category_manager,
            self.address_list_with_toolbar,
        ) = self._create_addresses_tab(self.tabs, address_list_with_toolbar=address_list_with_toolbar)

        self.quick_receive.set_manage_categories_enabled(True)

        self.uitx_creator, self.send_node = self._create_send_tab(uitx_creator=uitx_creator)
        self.wallet_descriptor_ui, self.settings_node = self.create_and_add_settings_tab()

        self.plugin_manager: PluginManager | None = None
        if ENABLE_PLUGINS:
            self.plugin_manager = (
                plugin_manager
                if plugin_manager
                else PluginManager(
                    wallet_functions=self.wallet_functions,
                    config=self.config,
                    fx=self.fx,
                    loop_in_thread=self.loop_in_thread,
                )
            )
            self.plugin_manager_widget = PluginListWidget()
            self.tabs.addChildNode(self.plugin_manager_widget.node)

            # register and save details
            self.plugin_manager.create_and_connect_clients(
                descriptor=self.wallet.multipath_descriptor,
                wallet_id=self.wallet.id,
                category_core=self.category_core,
            )

            self.plugin_manager.load_all_enabled()
            self.plugin_manager_widget.set_plugins(plugins=self.plugin_manager.clients)

        self.create_status_bar(self, self.outer_layout)
        self.update_sync_status()

        self.updateUi()
        self.quick_receive.update_content(UpdateFilter(refresh_all=True))

        #### connect signals
        # only signals, not member of [wallet_signals, wallet_signals] have to be tracked,
        # all others I can connect automatically
        self.signal_tracker.connect(self.signals.language_switch, self.updateUi)
        self.wallet_signals.updated.connect(self.signals.any_wallet_updated)
        self.wallet_signals.updated.connect(self.on_updated)
        self.wallet_signals.export_labels.connect(self.export_labels)
        self.wallet_signals.export_bip329_labels.connect(self.export_bip329_labels)
        self.wallet_signals.import_labels.connect(self.import_labels)
        self.wallet_signals.import_bip329_labels.connect(self.import_bip329_labels)
        self.wallet_signals.import_electrum_wallet_labels.connect(
            self.import_electrum_wallet_labels,
        )

        self.signal_tracker.connect(self.signals.language_switch, self.wallet_signals.language_switch)
        self.signal_tracker.connect(self.signals.currency_switch, self.wallet_signals.currency_switch)
        self.signal_tracker.connect(self.signals.currency_switch, self.update_display_balance)
        self.quick_receive.signal_manage_categories_requested.connect(self.signal_show_manage_categories)
        self.quick_receive.signal_add_category_requested.connect(self.category_manager.add_category)
        self.signal_tracker.connect(self.signal_show_manage_categories, self.category_manager.show)
        self.signal_tracker.connect(self.signal_client_log_info, self._handle_client_log_info)
        self.signal_tracker.connect(self.signal_client_log_warning, self._handle_client_log_warning)
        self.signal_tracker.connect(self.signal_client_log_str, self._handle_client_log_str)
        self.signal_tracker.connect(self.signal_wallet_update, self._handle_client_update)
        self.signal_tracker.connect(self.signal_refresh_sync_status, self.update_sync_status)

        self._start_progress_update_timer()
        self._start_sync_retry_timer()
        self._start_sync_regularly_timer()
        # since a Wallet can now have txs before syncing
        # we need to treat it like something has changed
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True))

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()

        d["wallet"] = self.wallet.dump()
        d["tutorial_index"] = self.tutorial_index
        d["notified_tx_ids"] = list(self.notified_tx_ids)
        d["warned_change_without_input_txids"] = list(self._warned_change_without_input_txids)
        d["history_list_with_toolbar"] = self.history_list_with_toolbar.dump()
        d["address_list_with_toolbar"] = self.address_list_with_toolbar.dump()
        d["uitx_creator"] = self.uitx_creator.dump()
        d["last_tab_title"] = current.title if (current := self.tabs.currentChildNode()) else None
        d["plugin_manager"] = self.plugin_manager

        return d

    @classmethod
    def from_file(
        cls,
        file_path: str,
        config: UserConfig,
        wallet_functions: WalletFunctions,
        mempool_manager: MempoolManager,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        password: str | None = None,
    ) -> QTWallet:
        """From file."""

        class_kwargs = {
            Wallet.__name__: Wallet.cls_kwargs(config=config, loop_in_thread=loop_in_thread),
            QTWallet.__name__: QTWallet.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
                file_path=file_path,
                mempool_manager=mempool_manager,
            ),
            HistList.__name__: HistList.cls_kwargs(
                wallet_functions=wallet_functions, config=config, fx=fx, mempool_manager=mempool_manager
            ),
            HistListWithToolbar.__name__: HistListWithToolbar.cls_kwargs(
                config=config,
            ),
            UTXOList.__name__: UTXOList.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
            ),
            UtxoListWithToolbar.__name__: HistListWithToolbar.cls_kwargs(
                config=config,
            ),
            AddressList.__name__: AddressList.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
            ),
            AddressListWithToolbar.__name__: AddressListWithToolbar.cls_kwargs(
                config=config,
            ),
            UITx_Creator.__name__: UITx_Creator.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
                mempool_manager=mempool_manager,
            ),
            CategoryList.__name__: CategoryList.cls_kwargs(
                signals=wallet_functions.signals,
                config=config,
            ),
        }
        class_kwargs.update(
            PluginManager.class_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
            ),
        )
        return super()._from_file(filename=file_path, password=password, class_kwargs=class_kwargs)

    @classmethod
    def file_migration(cls, file_content: str):
        "this class can be overwritten in child classes"

        dct = json.loads(file_content)
        qt_wallet_version = dct.get("VERSION")

        if dct["__class__"] == "Wallet":
            d: dict[str, Any] = {}
            d["__class__"] = cls.__name__
            d["VERSION"] = cls.VERSION
            d["wallet"] = dct

            if not d["wallet"].get("data_dump"):
                d["wallet"]["data_dump"] = {}
            d["sync_tab"] = d["wallet"]["data_dump"].get("SyncTab", {})
            del d["wallet"]["data_dump"]
            dct = d

        if (qt_wallet_version) and fast_version(qt_wallet_version) < fast_version("0.3.0"):
            # new plugin_manager
            if dct.get("sync_tab") and not dct.get("plugin_manager"):
                sync_tab = dct["sync_tab"]
                sync_client = {
                    **sync_tab,
                    "VERSION": "0.0.2",
                    "__class__": SyncClient.__name__,
                }
                dct["plugin_manager"] = {
                    "VERSION": "0.0.1",
                    "__class__": PluginManager.__name__,
                    "clients": [sync_client],
                }
                del dct["sync_tab"]

        # in the function above, only default json serilizable things can be set in dct
        return json.dumps(dct)

    @classmethod
    def from_dump_downgrade_migration(cls, dct: dict[str, Any]):
        """From dump downgrade migration."""
        if fast_version(str(dct.get("VERSION", 0))) >= fast_version("0.2.0") > fast_version(cls.VERSION):
            # downgrade bdk 1.x related stuff
            if sync_tab := dct.get("sync_tab"):
                if nostr_sync_dump := sync_tab.get("nostr_sync_dump"):

                    def migrate_network(obj: dict[str, Any], key: str = "network"):
                        """Migrate network."""
                        if obj.get(key) == "TESTNET4":
                            obj[key] = "TESTNET"

                    migrate_network(nostr_sync_dump)
                    if nostr_protocol := nostr_sync_dump.get("nostr_protocol"):
                        migrate_network(nostr_protocol)
                    if group_chat := nostr_sync_dump.get("group_chat"):
                        migrate_network(group_chat)
        return dct

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None) -> QTWallet:
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        return cls(**filtered_for_init(dct, cls))

    @property
    def wallet_signals(self) -> WalletSignals:
        """Wallet signals."""
        return self.wallet_functions.wallet_signals[self.wallet.id]

    def restore_last_selected_tab(self):
        """Restore last selected tab."""
        self.tabs.set_current_tab_by_text(self.last_tab_title)

    def on_updated(self, update_filter: UpdateFilter):
        """On updated."""
        address_infos = [
            self.wallet.get_address_info_min(address=address) for address in update_filter.addresses
        ]
        self.wallet.mark_labeled_addresses_used(
            address_infos=[address_info for address_info in address_infos if address_info]
        )
        self.update_display_balance()

    def updateUi(self) -> None:
        """UpdateUi."""
        if _node := self.tabs.findNodeByWidget(self.uitx_creator):
            _node.setTitle(self.tr("Send"))
        if _node := self.tabs.findNodeByWidget(self.wallet_descriptor_ui):
            _node.setTitle(self.tr("Descriptor"))
        if _node := self.tabs.findNodeByWidget(self.history_tab):
            _node.setTitle(self.tr("History"))
        if _node := self.tabs.findNodeByWidget(self.address_tab):
            _node.setTitle(self.tr("Addresses"))
        if _node := self.tabs.findNodeByWidget(self.plugin_manager_widget):
            _node.setTitle(self.tr("Plugins"))

        self.balance_label_title.setText(self.tr("Balance"))
        self.fiat_value_label_title.setText(self.tr("Value"))
        self.category_manager.updateUi()
        self.quick_receive.updateUi()

    def update_display_balance(self):
        """Update display balance."""
        balance_total = Satoshis(self.wallet.get_balance().total, self.config.network)
        self.balance_label.setText(balance_total.str_with_unit(btc_symbol=self.config.bitcoin_symbol.value))
        self.fiat_value_label.setText(self.fx.btc_to_fiat_str(amount=balance_total.value))
        self._update_fiat_price_tooltip()

    def _update_fiat_price_tooltip(self) -> None:
        """Update tooltip with current fiat price per bitcoin."""
        btc_price_text = self.fx.btc_to_fiat_str(amount=SATOSHIS_PER_BTC)
        currency_iso = self.fx.get_currency_iso()
        if btc_price_text:
            tooltip = self.tr("Current price per bitcoin: {price} ({currency})").format(
                price=btc_price_text, currency=currency_iso
            )
        else:
            tooltip = self.tr("Current price per bitcoin is unavailable.")

        self.fiat_value_label_title.setToolTip(tooltip)
        self.fiat_value_label.setToolTip(tooltip)

    def stop_sync_timer(self) -> None:
        """Stop sync timer."""
        self.timer_sync_retry.stop()
        self.timer_sync_regularly.stop()

    def _start_sync_regularly_timer(self, delay_retry_sync=60) -> None:
        """Start sync regularly timer."""
        if self.timer_sync_regularly.isActive():
            return
        self.timer_sync_regularly.setInterval(delay_retry_sync * 1000)

        self.timer_sync_regularly.timeout.connect(self._regular_sync)
        if ENABLE_TIMERS:
            self.timer_sync_regularly.start()

    def _regular_sync(self):
        """Regular sync."""
        if self.wallet.client and self.wallet.client.sync_status not in [SyncStatus.synced]:
            return

        logger.info(f"Regular update: Sync wallet {self.wallet.id} again")
        self.sync()

    def _sync_if_needed(self) -> None:
        """Sync if needed."""
        if self.wallet.client and self.wallet.client.sync_status in [SyncStatus.syncing, SyncStatus.synced]:
            return

        logger.info(f"Retry timer: Try syncing wallet {self.wallet.id}")
        self.sync()

    def _start_progress_update_timer(self, interval_seconds=1) -> None:
        """Start progress update timer."""
        if self.progress_update_timer.isActive():
            return
        self.progress_update_timer.setInterval(interval_seconds * 1000)

        self.progress_update_timer.timeout.connect(self._on_progress_update_timer)
        if ENABLE_TIMERS:
            self.progress_update_timer.start()

    def _on_progress_update_timer(self):
        """On progress update timer."""
        if not self.wallet.client:
            return
        self.signal_progress_info.emit(self.wallet.client.progress_info)

    def _start_sync_retry_timer(self, delay_retry_sync=30) -> None:
        """Start sync retry timer."""
        if self.timer_sync_retry.isActive():
            return
        self.timer_sync_retry.setInterval(delay_retry_sync * 1000)

        self.timer_sync_retry.timeout.connect(self._sync_if_needed)
        if ENABLE_TIMERS:
            self.timer_sync_retry.start()

    def get_mn_tuple(self) -> tuple[int, int]:
        """Get mn tuple."""
        return self.wallet.get_mn_tuple()

    def get_keystore_labels(self) -> list[str]:
        """Get keystore labels."""
        return [keystore.label for keystore in self.wallet.keystores]

    def _default_file_name(self, id: str | None = None) -> str:
        """Default file name."""
        return filename_clean(id if id else self.wallet.id)

    @property
    def file_path(self) -> str:
        """File path."""
        return self._file_path if self._file_path else self._default_file_name()

    @file_path.setter
    def file_path(self, value: str | None) -> None:
        """File path."""
        self._file_path = value

    def create_and_add_settings_tab(self) -> tuple[DescriptorUI, SidebarNode]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=self.wallet.as_protowallet(),
            wallet_functions=self.wallet_functions,
            wallet=self.wallet,
            loop_in_thread=self.loop_in_thread,
        )
        settings_node = SidebarNode[object](
            data=wallet_descriptor_ui,
            widget=wallet_descriptor_ui,
            icon=svg_tools.get_QIcon("bi--text-left.svg"),
            title="",
        )
        self.tabs.addChildNode(settings_node)

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(
            self.on_qtwallet_apply_setting_changes
        )
        wallet_descriptor_ui.signal_qtwallet_cancel_setting_changes.connect(self.cancel_setting_changes)
        return wallet_descriptor_ui, settings_node

    def _recreate_qt_wallet(self, new_wallet: Wallet):
        # do backup
        filename = self.save_backup()
        if filename:
            Message(self.tr("Backup saved to {filename}").format(filename=filename), parent=self)
        else:
            Message(self.tr("Backup failed. Aborting Changes."), parent=self)
            return

        # i have to close it first, to ensure the wallet is shut down completely
        self.signals.close_qt_wallet.emit(self.wallet.id)

        if self.plugin_manager and not self.wallet.bdkwallet.addresses_identical(new_wallet.bdkwallet):
            # if the wallet/addresses have changed, then
            self.plugin_manager.drop_wallet_specific_things()
        qt_wallet = QTWallet(
            new_wallet,
            self.config,
            self.wallet_functions,
            self.mempool_manager,
            self.fx,
            file_path=self.file_path,
            password=self.password,
            parent=self.parent(),
            loop_in_thread=self.loop_in_thread,
            plugin_manager=self.plugin_manager.clone() if self.plugin_manager else None,
        )

        self.signals.add_qt_wallet.emit(qt_wallet, self._file_path, self.password)
        qt_wallet.sync()

    def on_qtwallet_apply_setting_changes(self):
        # save old status, such that the backup has all old data (inlcuding the "SyncTab" in the data_dump)
        """On qtwallet apply setting changes."""
        self.save()

        current_protowallet = self.wallet.as_protowallet()
        self.wallet_descriptor_ui.set_protowallet_from_ui()
        updated_protowallet = self.wallet_descriptor_ui.protowallet

        differences = current_protowallet.get_differences(updated_protowallet)
        worst = differences.worst()
        if not worst:
            Message(self.tr("No changes to apply."), parent=self)
            return

        if worst.type == WalletDifferenceType.NoRescan:
            self._apply_no_impact_setting_changes(updated_protowallet)
            self.save()
            Message(self.tr("Changes applied."), parent=self)
            return
        elif worst.type == WalletDifferenceType.NeedsRescan:
            pass
        elif worst.type == WalletDifferenceType.ImpactOnAddresses:
            if not question_dialog(
                self.tr("Proceeding will potentially change all wallet addresses."),
                true_button=self.tr("Proceed"),
            ):
                return

        new_wallet = Wallet.from_protowallet(
            protowallet=updated_protowallet,
            config=self.config,
            labels=self.wallet.labels,
            default_category=self.wallet.labels.default_category,
            loop_in_thread=self.loop_in_thread,
            initialization_tips=self.wallet.tips,
        )
        self._recreate_qt_wallet(new_wallet=new_wallet)

    def _apply_no_impact_setting_changes(self, updated_protowallet: ProtoWallet) -> None:
        """Apply no-impact settings changes without rebuilding the wallet."""

        def keystore_key(keystore: KeyStore) -> str:
            return keystore.xpub

        updated_keystores = {
            keystore_key(keystore): keystore for keystore in updated_protowallet.keystores if keystore
        }

        for keystore in self.wallet.keystores:
            if not keystore:
                continue
            updated_keystore = updated_keystores.get(keystore_key(keystore))
            if not updated_keystore:
                continue
            keystore.description = updated_keystore.description
            keystore.label = updated_keystore.label

    def save_backup(self) -> str:
        """_summary_

        Returns:
            str: filename
        """
        file_path = os.path.join(
            self.config.wallet_dir, "backups", filename_clean(f"{self.wallet.id}-backup-{0}")
        )
        max_number_backups = 100000
        for i in range(max_number_backups):
            file_path = os.path.join(
                self.config.wallet_dir, "backups", filename_clean(f"{self.wallet.id}-backup-{i}")
            )
            if not os.path.exists(file_path):
                break

        # save the tutorial step into the wallet
        if self.wizard:
            self.tutorial_index = (
                self.wizard.step_container.current_index() if not self.wizard.isHidden() else None
            )

        self.save_to(
            wallet_id=Path(file_path).stem,
            file_path=file_path,
        )
        return file_path

    def change_wallet_id(self, new_id: str) -> Path | None:
        """Change wallet id."""
        old_file_path = self.file_path

        if not os.path.exists(self.config.wallet_dir):
            os.makedirs(self.config.wallet_dir, exist_ok=True)

        new_file_path = Path(self.config.wallet_dir) / self._default_file_name(id=new_id)
        if new_file_path.exists():
            Message(
                self.tr("Cannot move the wallet file, because {file_path} exists").format(
                    file_path=new_file_path
                ),
                parent=self,
            )
            return None

        # in the wallet
        self.wallet.set_wallet_id(new_id)
        # tab text
        self.tabs.setTitle(new_id)

        # move wallet
        shutil.move(old_file_path, new_file_path)
        self.remove_lockfile(Path(old_file_path))

        # set the new file_path
        self.file_path = str(new_file_path)

        self.get_wallet_lockfile(new_file_path)
        logger.info(f"Saved {old_file_path} under new name {new_file_path}")
        return new_file_path

    @classmethod
    def get_wallet_lockfile_path(cls, wallet_file_path: Path) -> Path:
        """Get wallet lockfile path."""
        return wallet_file_path.with_suffix(".lock")

    @classmethod
    def get_wallet_lockfile(cls, wallet_file_path: Path) -> Path | None:
        """Get wallet lockfile."""
        lockfile_path = cls.get_wallet_lockfile_path(wallet_file_path)
        if os.path.exists(lockfile_path):
            return None
        with open(lockfile_path, "w") as lockfile:
            lockfile.write(str(os.getpid()))
            return lockfile_path

    @classmethod
    def remove_lockfile(cls, wallet_file_path: Path) -> None:
        """Remove lockfile."""
        lock_file_path = cls.get_wallet_lockfile_path(wallet_file_path)
        if not lock_file_path:
            return
        if lock_file_path.exists():
            os.remove(lock_file_path)
            logger.info(f"Lock file {lock_file_path} removed.")

    def save(self) -> str | None:  # type: ignore
        """Save."""
        if not self._file_path:
            if not os.path.exists(self.config.wallet_dir):
                os.makedirs(self.config.wallet_dir, exist_ok=True)

            # not saving a wallet is dangerous. Therefore I ensure the user has ample
            # opportunity to set a filename
            while not self._file_path:
                self._file_path, _ = QFileDialog.getSaveFileName(
                    self,
                    self.tr("Save wallet"),
                    f"{os.path.join(self.config.wallet_dir, filename_clean(self.wallet.id))}",
                    self.tr("All Files (*);;Wallet Files (*.wallet)"),
                )
                if not self._file_path and not question_dialog(
                    text=self.tr("Wallet was not saved.").format(id=self.wallet.id),
                    title=self.tr("Wallet not saved yet"),
                    true_button=self.tr("Save wallet"),
                    false_button=self.tr("Don't save wallet"),
                ):
                    logger.info("No file selected")
                    return None

        # if it is the first time saving, then the user can set a password
        if not os.path.isfile(self.file_path):
            self.password = PasswordCreation().get_password()

        self.save_to(file_path=self.file_path)
        return self.file_path

    def save_to(self, file_path: str, wallet_id: str | None = None):
        """Save to."""
        original_id = self.wallet.id
        if wallet_id:
            self.wallet.id = wallet_id
        super().save(
            file_path,
            password=self.password,
        )
        self.wallet.id = original_id
        logger.info(f"wallet {self.wallet.id} saved to {file_path}")

    def change_password(self) -> str | None:
        """Change password."""
        if self.password:
            ui_password_question = PasswordQuestion(label_text="Your current password:")
            password = ui_password_question.ask_for_password()
            if password is None:
                return None
            if password != self.password:
                Message(self.tr("Password incorrect"), type=MessageType.Warning, parent=self)
                return None

        new_password = PasswordCreation(
            window_title=self.tr("Change password"), label_text=self.tr("New password:")
        ).get_password()
        if new_password is None:
            return None

        self.password = new_password
        self.save()
        Message(self.tr("Wallet saved"), parent=self)
        return self.password

    def cancel_setting_changes(self) -> None:
        """Cancel setting changes."""
        self.wallet_descriptor_ui.protowallet = self.wallet.as_protowallet()
        self.wallet_descriptor_ui.set_all_ui_from_protowallet()

    @time_logger
    def get_delta_txs(self, access_marker="notifications") -> DeltaCacheListTransactions:
        """Get delta txs."""
        delta_txs = self.wallet.bdkwallet.list_delta_transactions(access_marker=access_marker)
        return delta_txs

    def format_txs_for_notification(self, txs: list[TransactionDetails]) -> str:
        """Format txs for notification."""
        return "\n".join(
            [
                f"  {Satoshis(tx.received - tx.sent, self.config.network).str_as_change(unit=True, btc_symbol=self.config.bitcoin_symbol.value)}"
                for tx in txs
            ]
        )

    def hanlde_removed_txs(self, removed_txs: list[TransactionDetails]) -> None:
        """Hanlde removed txs."""
        if not removed_txs:
            return

        # if transactions were removed (reorg or other), then recalculate everything
        message_content = self.tr(
            "The transactions \n{txs}\n in wallet '{wallet}' were removed from the history!!!"
        ).format(txs=self.format_txs_for_notification(removed_txs), wallet=self.wallet.id)
        Message(
            message_content,
            no_show=True,
            parent=self,
        ).emit_with(self.signals.notification)
        if question_dialog(
            message_content + "\n" + self.tr("Do you want to save a copy of these transactions?"),
            true_button=self.tr("Save transactions"),
            false_button=QMessageBox.StandardButton.No,
        ):
            folder_path = QFileDialog.getExistingDirectory(
                self, "Select Folder to save the removed transactions"
            )

            if folder_path:
                for tx in removed_txs:
                    data = Data.from_tx(tx.transaction, network=self.wallet.network)
                    filename = Path(folder_path) / f"{short_tx_id(tx.txid)}.tx"

                    # create a file descriptor
                    fd = os.open(filename, os.O_CREAT | os.O_WRONLY)
                    data.write_to_filedescriptor(fd)
                    logger.info(f"Exported {tx.txid} to {filename}")

        self.notified_tx_ids -= set([tx.txid for tx in removed_txs])
        # all the lists must be updated
        self.refresh_caches_and_ui_lists(force_ui_refresh=True)

    def handle_appended_txs(self, appended_txs: list[TransactionDetails]) -> None:
        """Handle appended txs."""
        if not appended_txs:
            return

        appended_txs = [tx for tx in appended_txs if tx.txid not in self.notified_tx_ids]

        if len(appended_txs) == 1:
            Message(
                self.tr("New transaction in wallet '{wallet}':\n{txs}").format(
                    txs=self.format_txs_for_notification(appended_txs), wallet=self.wallet.id
                ),
                no_show=True,
                parent=self,
            ).emit_with(self.signals.notification)
        elif len(appended_txs) > 1:
            Message(
                self.tr("{number} new transactions in wallet '{wallet}':\n{txs}").format(
                    number=len(appended_txs),
                    txs=self.format_txs_for_notification(appended_txs),
                    wallet=self.wallet.id,
                ),
                no_show=True,
                parent=self,
            ).emit_with(self.signals.notification)

        self.notified_tx_ids = self.notified_tx_ids.union([tx.txid for tx in appended_txs])

    def handle_delta_txs(self, delta_txs: DeltaCacheListTransactions) -> None:
        """Handle delta txs."""
        self.hanlde_removed_txs(delta_txs.removed)
        self.handle_appended_txs(delta_txs.appended)

    @time_logger
    def refresh_caches_and_ui_lists(
        self,
        force_ui_refresh=True,
        chain_height_advanced=False,
    ) -> None:
        # before the wallet UI updates, we have to refresh the wallet caches to make the UI update faster

        """Refresh caches and ui lists."""
        self.wallet.fill_commonly_used_caches_min()

        change_without_input_txids = self.wallet.list_txids_with_change_outputs_without_wallet_inputs()
        new_tx_warnings = [
            txid for txid in change_without_input_txids if txid not in self._warned_change_without_input_txids
        ]

        if new_tx_warnings:
            self._warned_change_without_input_txids.update(new_tx_warnings)
            new_gap = max(100, self.wallet.gap * 2)
            if question_dialog(
                self.tr(
                    "An indication for a low gap limit was detected (received Bitcoin to change addresses)."
                    "\nDo you want to rescan the wallet with an increased gap limit of {new_gap}"
                ).format(txids="\n".join(new_tx_warnings), new_gap=new_gap),
                title=self.tr("Gap limit may be too low"),
                true_button=QMessageBox.StandardButton.Yes,
                false_button=QMessageBox.StandardButton.No,
                default_is_true_button=False,
            ):
                new_wallet = self.wallet.clone_without_peristence()
                new_wallet.set_gap(new_gap)
                self._recreate_qt_wallet(new_wallet)
                return

        delta_txs = self.get_delta_txs()
        change_dict = delta_txs.was_changed()
        formatted_dict = {k: [tx.txid for tx in v] for k, v in change_dict.items()}
        logger.debug(f"{len(formatted_dict)=}")
        if force_ui_refresh or change_dict:
            self.handle_delta_txs(delta_txs)

            # now do the UI
            logger.debug("start refresh ui")

            self.wallet_signals.updated.emit(
                UpdateFilter(
                    refresh_all=True,
                    reason=(
                        UpdateFilterReason.TransactionChange
                        if change_dict
                        else UpdateFilterReason.ForceRefresh
                    ),
                )
            )
        elif chain_height_advanced:
            self.wallet_signals.updated.emit(UpdateFilter(reason=UpdateFilterReason.ChainHeightAdvanced))

    def _create_send_tab(
        self,
        uitx_creator: UITx_Creator | None = None,
    ) -> tuple[UITx_Creator, SidebarNode]:
        """Create send tab."""
        if uitx_creator:
            uitx_creator.set_category_core(category_core=self.category_core)
        else:
            uitx_creator = UITx_Creator(
                mempool_manager=self.mempool_manager,
                fx=self.fx,
                config=self.config,
                wallet_functions=self.wallet_functions,
                parent=self,
                category_core=self.category_core,
            )
        send_node = SidebarNode[object](
            data=uitx_creator, widget=uitx_creator, icon=svg_tools.get_QIcon("bi--send.svg"), title=""
        )
        self.tabs.addChildNode(send_node)

        uitx_creator.signal_create_tx.connect(self.create_psbt)
        return uitx_creator, send_node

    def create_psbt(self, txinfos: TxUiInfos) -> None:
        """Create psbt."""

        async def do() -> TxBuilderInfos | Exception:
            """Do."""
            try:
                return self.wallet.create_psbt(txinfos)
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
                return e

        def on_done(builder_infos: TxBuilderInfos | Exception | None) -> None:
            """On done."""
            if not builder_infos:
                self.wallet_signals.finished_psbt_creation.emit()
                return
            if isinstance(builder_infos, Exception):
                caught_exception_message(builder_infos, parent=self)
                self.wallet_signals.finished_psbt_creation.emit()
                return
            if not isinstance(builder_infos, TxBuilderInfos):
                self.wallet_signals.finished_psbt_creation.emit()  # type: ignore
                Message("Could not create PSBT", type=MessageType.Error, parent=self)
                return

            try:
                # set labels in other wallets  (recipients can be another open wallet)
                for wallet in get_wallets(self.wallet_functions):
                    wallet._set_labels_for_change_outputs(builder_infos)

                update_filter = UpdateFilter(
                    addresses=set(
                        [
                            str(bdk.Address.from_script(output.script_pubkey, self.wallet.network))
                            for output in builder_infos.psbt.extract_tx().output()
                        ]
                    ),
                    reason=UpdateFilterReason.CreatePSBT,
                )
                self.wallet_signals.updated.emit(update_filter)
                self.signals.open_tx_like.emit(builder_infos)
                self.uitx_creator.clear_ui()
            except Exception as e:
                caught_exception_message(e, parent=self)
            finally:
                self.wallet_signals.finished_psbt_creation.emit()

        def on_success(builder_infos: TxBuilderInfos | Exception) -> None:
            """On success."""
            pass

        def on_error(packed_error_info: ExcInfo | None) -> None:
            """On error."""
            self.wallet_signals.finished_psbt_creation.emit()

        self.wallet.loop_in_thread.run_task(
            do(),
            on_done=on_done,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}create_psbt",
            multiple_strategy=MultipleStrategy.QUEUE,
        )

    def get_wallet(self) -> Wallet:
        """Get wallet."""
        return self.wallet

    def get_qt_wallet(self) -> QTWallet:
        """Get qt wallet."""
        return self

    def set_wallet(self, wallet: Wallet) -> Wallet:
        """Set wallet."""
        self.wallet = wallet

        self.wallet_signals.updated.connect(self.wallet.on_addresses_updated)
        self.signal_tracker.connect(
            cast(SignalProtocol, self.wallet_functions.get_wallets), self.get_wallet, self.wallet.id
        )
        self.signal_tracker.connect(
            cast(SignalProtocol, self.wallet_functions.get_qt_wallets), self.get_qt_wallet, self.wallet.id
        )
        self.signal_tracker.connect(
            cast(SignalProtocol, self.wallet_signals.get_category_infos),
            self.get_category_infos,
            self.wallet.id,
        )
        return wallet

    def create_status_bar(self, tab: QWidget, outer_layout) -> None:
        """Create status bar."""
        pass

    def create_list_tab(
        self,
        treeview_with_toolbar: TreeViewWithToolbar,
        tabs: SidebarNode,
        horizontal_widgets_left: list[QWidget] | None = None,
        horizontal_widgets_right: list[QWidget] | None = None,
    ) -> SearchableTab:
        # create a horizontal widget and layout
        """Create list tab."""
        searchable_tab = SearchableTab()
        searchable_tab.setObjectName(f"created for {treeview_with_toolbar.__class__.__name__}")
        searchable_tab.searchable_list = treeview_with_toolbar.searchable_list
        searchable_tab_layout = QHBoxLayout(searchable_tab)
        searchable_tab.setLayout(searchable_tab_layout)

        if horizontal_widgets_left:
            for widget in horizontal_widgets_left:
                searchable_tab_layout.addWidget(widget)

        searchable_tab_layout.addWidget(treeview_with_toolbar)

        if horizontal_widgets_right:
            for widget in horizontal_widgets_right:
                searchable_tab_layout.addWidget(widget)
        return searchable_tab

    def _create_hist_tab(
        self, tabs: SidebarNode, history_list_with_toolbar: HistListWithToolbar | None
    ) -> tuple[SearchableTab, HistList, SidebarNode, WalletBalanceChart, HistListWithToolbar]:
        """Create hist tab."""
        tab = SearchableTab()
        tab.setObjectName("created as HistList tab containrer")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        splitter = QSplitter(orientation=Qt.Orientation.Vertical)
        tab_layout.addWidget(splitter)

        if history_list_with_toolbar:
            history_list_with_toolbar.hist_list.set_wallets(wallets=[self.wallet])
        else:
            hist_list = HistList(
                fx=self.fx,
                config=self.config,
                wallet_functions=self.wallet_functions,
                wallets=[self.wallet],
                hidden_columns=(
                    [
                        HistList.Columns.WALLET_ID,
                        HistList.Columns.BALANCE,
                        HistList.Columns.TXID,
                    ]
                ),
                mempool_manager=self.mempool_manager,
            )
            history_list_with_toolbar = HistListWithToolbar(hist_list, self.config, parent=tabs)

        history_list_with_toolbar.hist_list.signal_selection_changed.connect(
            self.on_hist_list_selection_changed
        )
        self.signal_tracker.connect(self.signal_progress_info, history_list_with_toolbar._set_progress_info)
        history_list_with_toolbar.signal_export_pdf_statement.connect(self.export_pdf_statement)

        list_widget = self.create_list_tab(history_list_with_toolbar, tabs)
        tab.searchable_list = history_list_with_toolbar.searchable_list

        top_widget = QWidget(self)
        top_widget_layout = QHBoxLayout(top_widget)
        top_widget_layout.setContentsMargins(0, 0, 0, 0)

        chart_container = QWidget(self)
        chart_container_layout = QVBoxLayout(chart_container)
        chart_container_layout.setContentsMargins(0, 0, 0, 0)

        self.quick_receive: BitcoinQuickReceive = BitcoinQuickReceive(
            self.wallet_signals, self.wallet, parent=top_widget, signals_min=self.signals
        )

        wallet_balance_chart = WalletBalanceChart(
            self.wallet,
            wallet_signals=self.wallet_signals,
            parent=top_widget,
        )
        wallet_balance_chart.signal_click_transaction.connect(self.on_hist_chart_click)

        balance_group = QWidget(self)
        self.balance_label_title = QLabel()
        self.balance_label = QLabel()
        self.fiat_value_label_title = QLabel()
        self.fiat_value_label = QLabel()
        font = self.fiat_value_label.font()
        font.setPixelSize(15)
        self.fiat_value_label.setFont(font)
        self.balance_label.setFont(font)
        label_layout = QGridLayout(balance_group)
        label_layout.addWidget(self.balance_label_title, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        label_layout.addWidget(self.balance_label, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        label_layout.addWidget(self.fiat_value_label_title, 0, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        label_layout.addWidget(self.fiat_value_label, 1, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        chart_container_layout.addWidget(balance_group)
        chart_container_layout.addWidget(wallet_balance_chart)
        top_widget_layout.addWidget(chart_container, stretch=3)
        top_widget_layout.addWidget(self.quick_receive, stretch=2)

        self.signal_tracker.connect(self.fx.signal_data_updated, self.update_display_balance)

        splitter.addWidget(top_widget)
        splitter.addWidget(list_widget)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)

        hist_node = SidebarNode(
            data=tab,
            widget=tab,
            icon=svg_tools.get_QIcon("ic--sharp-timeline.svg"),
            title="",
        )
        tabs.insertChildNode(
            0,
            hist_node,
        )

        # set initial sizes so that top starts at its minimum
        splitter.setStretchFactor(0, 0)  # index 0 = top
        splitter.setStretchFactor(1, 1)  # index 1 = bottom
        splitter.setSizes([240, 10])
        return (
            tab,
            history_list_with_toolbar.hist_list,
            hist_node,
            wallet_balance_chart,
            history_list_with_toolbar,
        )

    def on_hist_chart_click(self, tx_details: TransactionDetails):
        """On hist chart click."""
        self.history_list.select_rows(
            content_list=[tx_details.txid],
            column=self.history_list.key_column,
            role=MyItemDataRole.ROLE_KEY,
            scroll_to_last=True,
        )

    def get_category_infos(self) -> list[CategoryInfo]:
        """Get category infos."""
        category_python_txo_dict = self.wallet.get_category_python_txo_dict(include_spent=True)

        category_infos: list[CategoryInfo] = []
        address_category_dict_raw = self.wallet.labels.get_category_dict_raw(filter_type=LabelType.addr)

        for category in self.wallet.labels.categories:
            txos = category_python_txo_dict.get(category, [])
            utxos = [txo for txo in txos if not txo.is_spent_by_txid]
            txo_balance = python_utxo_balance(txos)
            utxo_balance = python_utxo_balance(utxos)
            item = CategoryInfo(
                category=category,
                address_count=len(address_category_dict_raw[category]),
                txo_balance=txo_balance,
                utxo_balance=utxo_balance,
                txo_count=len(txos),
                utxo_count=len(utxos),
            )
            category_infos.append(item)
        return category_infos

    def _create_addresses_tab(
        self,
        tabs: SidebarNode,
        address_list_with_toolbar: AddressListWithToolbar | None = None,
    ) -> tuple[SearchableTab, AddressList, SidebarNode, CategoryManager, AddressListWithToolbar]:
        """Create addresses tab."""
        category_manager = CategoryManager(
            config=self.config, category_core=self.category_core, wallet_id=self.wallet.id
        )

        if address_list_with_toolbar:
            address_list_with_toolbar.address_list.set_wallets(wallets=[self.wallet])
            address_list_with_toolbar.set_category_core(self.category_core)
        else:
            address_list = AddressList(
                fx=self.fx,
                config=self.config,
                wallets=[self.wallet],
                wallet_functions=self.wallet_functions,
                hidden_columns=([AddressList.Columns.WALLET_ID, AddressList.Columns.INDEX]),
            )
            address_list_with_toolbar = AddressListWithToolbar(
                address_list=address_list,
                config=self.config,
                category_core=self.category_core,
            )
        address_list_with_toolbar.address_list.signal_tag_dropped.connect(category_manager.set_category)
        category_manager.category_list.signal_addresses_dropped.connect(category_manager.set_category)

        address_list_with_toolbar.action_manage_categories.triggered.connect(category_manager.show)

        tab = self.create_list_tab(address_list_with_toolbar, tabs)

        address_node = SidebarNode(
            data=tab, widget=tab, icon=svg_tools.get_QIcon("ic--baseline-call-received.svg"), title=""
        )
        tabs.insertChildNode(
            1,
            address_node,
        )
        return (
            tab,
            address_list_with_toolbar.address_list,
            address_node,
            category_manager,
            address_list_with_toolbar,
        )

    def update_sync_status(self) -> None:
        """Set sync status.


        It should be called via a signal, since the caller is likely from another thread, and the UI update wont work properly.
        """
        if not self.wallet.client:
            return

        sync_status = self.wallet.client.sync_status

        logger.info(f"{self.wallet.id} set_sync_status {sync_status}")

        icon_text = ""
        tooltip = ""
        if sync_status == SyncStatus.syncing:
            icon_text = "status_waiting.svg"
            self.history_list_with_toolbar.sync_button.start_spin()
            tooltip = self.tr("Syncing with {server}").format(
                server=self.config.network_config.description_short()
            )

        elif self.wallet.get_height() and sync_status in [SyncStatus.synced]:
            using_proxy = self.config.network_config.proxy_url
            icon_text = ("status_connected_proxy.svg") if using_proxy else ("status_connected.svg")
            tooltip = self.config.network_config.description_short()
            tooltip = self.tr("Connected to {server}").format(
                server=self.config.network_config.description_short()
            )
            self.history_list_with_toolbar.sync_button.enable_button()
        else:
            icon_text = "status_disconnected.svg"
            tooltip = self.tr("Disconnected from {server}").format(
                server=self.config.network_config.description_short()
            )
            self.history_list_with_toolbar.sync_button.enable_button()

        self.signals.signal_set_tab_properties.emit(self, self.wallet.id, icon_text, tooltip)

    async def _trigger_sync(self) -> Any:
        """Trigger sync."""
        self.init_blockchain()
        if self.wallet.client:
            self.signal_progress_info.emit(self.wallet.client.progress_info)
            self.signal_refresh_sync_status.emit()
        self.wallet.trigger_sync()
        if self.wallet.client:
            self.signal_progress_info.emit(self.wallet.client.progress_info)
            self.signal_refresh_sync_status.emit()
        return None

    def _sync_on_done(self, result: object) -> None:
        """Sync on done."""
        self._syncing_delay = datetime.datetime.now() - self._last_syncing_start
        interval_timer_sync_regularly = min(
            60 * 60 * 24, max(int(self._syncing_delay.total_seconds() * 200), MINIMUM_INTERVAL_SYNC_REGULARLY)
        )  # in sec
        self.timer_sync_regularly.setInterval(interval_timer_sync_regularly * 1000)
        logger.info(
            f"Syncing took {self._syncing_delay} --> set the "
            f"interval_timer_sync_regularly to {interval_timer_sync_regularly}s"
        )

    def _notify_sync_error(self, exc_value: BaseException | None) -> None:
        """Send a tray notification for any sync error."""
        if not exc_value:
            return

        parts: list[str] = [
            self.tr("Sync failed for wallet '{wallet}'.").format(wallet=self.wallet.id),
            str(exc_value),
        ]
        Message(
            "\n\n".join(parts),
            type=MessageType.Error,
            no_show=True,
            parent=self,
        ).emit_with(self.signals.notification)

    def _sync_on_error(
        self, packed_error_info: tuple[type[BaseException], BaseException, TracebackType | None] | None
    ) -> None:
        """Sync on error."""
        if self.wallet.client:
            self.wallet.client.set_sync_status(SyncStatus.error)
        self.signal_refresh_sync_status.emit()
        logger.info(f"Could not sync. SynStatus set to {SyncStatus.error.name} for wallet {self.wallet.id}")
        logger.error(str(packed_error_info))
        exc_value = packed_error_info[1] if packed_error_info else None
        self._notify_sync_error(exc_value)
        # custom_exception_handler(*packed_error_info)

    def _sync_on_success(self, result) -> None:
        """Sync on success."""
        logger.info(f"success syncing wallet '{self.wallet.id}'")

    def sync(self) -> None:
        """Sync."""
        if self.wallet.client and self.wallet.client.sync_status == SyncStatus.syncing:
            logger.info("Syncing already in progress")
            return

        logger.info(self.tr("Refresh all caches before syncing."))
        # This takkles the following problem:
        # During the syncing process the cache and the bdk results
        # become inconsitent (since the bdk has newer info)
        # If now some results are caches, and some are not
        # then the results become inconsitent
        # Possible solutions:
        #   1. Disable cache while syncing and force access to bdk.
        #       This might work, but also probably has considerable freezing effects
        #       (since bdk is blocked due to syncing)
        #   2. Only use the cache during syncing.  This is the chosen solution here.
        #       by filling all the cache before the sync
        #       I do this in the main thread so all caches
        #       are filled before the syncing process
        # not necessary anymore, since the library is noch blocking since 1.0.0
        # self.refresh_caches_and_ui_lists(enable_threading=False, force_ui_refresh=False, clear_cache=False)

        logger.info(f"Start syncing wallet {self.wallet.id}")

        self._last_syncing_start = datetime.datetime.now()

        if self.config.network_config.server_type == BlockchainType.CompactBlockFilter:
            # must be started from the main thread for cbf node!!!
            self.init_blockchain()

        self.wallet.loop_in_thread.run_task(
            self._trigger_sync(),
            on_done=self._sync_on_done,
            on_success=self._sync_on_success,
            on_error=self._sync_on_error,
            key=f"{id(self)}sync",
            multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
        )

    def _handle_client_log_info(self, info: bdk.Info):
        """Handle client log info."""
        if not self.wallet.client:
            return

        if self.wallet.client.handle_log_info(info):
            self.signal_progress_info.emit(self.wallet.client.progress_info)
            self.signal_refresh_sync_status.emit()

    def _handle_client_log_warning(self, warning: bdk.Warning):
        """Handle client log warning."""
        if not self.wallet.client:
            return

        if self.wallet.client.handle_log_warning(warning):
            self.signal_progress_info.emit(self.wallet.client.progress_info)
            self.signal_refresh_sync_status.emit()

    def _handle_client_log_str(self, message: str):
        """Handle client log str."""
        logger.info(message)

    def _handle_client_update(self, update_info: UpdateInfo):
        """Handle client update."""
        if not self.wallet.client:
            return
        self.wallet.client.set_sync_status(SyncStatus.synced)
        self.signal_progress_info.emit(self.wallet.client.progress_info)
        self.signal_refresh_sync_status.emit()
        self.on_update(update_info)

    def _cancel_client_tasks(self) -> None:
        """Cancel client tasks."""
        for task in self._client_bridge_tasks:
            if task and not task.done():
                task.cancel()
        self._client_bridge_tasks.clear()

    def _start_bridges(self) -> None:
        """Start bridges."""
        if not self.wallet.client:
            return
        self._add_bridge_tasks(self.wallet.update, self.signal_wallet_update, self.wallet.loop_in_thread)
        self._add_bridge_tasks(
            self.wallet.client.next_info, self.signal_client_log_info, self.wallet.loop_in_thread
        )
        self._add_bridge_tasks(
            self.wallet.client.next_warning, self.signal_client_log_warning, self.wallet.loop_in_thread
        )

    def _add_bridge_tasks(
        self,
        coro: Callable[[], Coroutine[Any, Any, T | None]],
        signal: SignalProtocol[[T]],
        loop: LoopInThread,
    ) -> None:
        """Add bridge tasks."""
        self._client_bridge_tasks.append(loop.run_background(self._convert_to_signal(coro, signal)))

    async def _convert_to_signal(
        self,
        coro: Callable[[], Coroutine[Any, Any, T | None]],
        signal: SignalProtocol[[T]],
    ) -> None:
        """Convert to signal."""
        try:
            while True:
                result = await coro()
                if result is None:
                    continue
                signal.emit(result)
        except asyncio.CancelledError:
            logger.debug(f"Cancelled bridge for {coro}")
        except Exception:
            logger.exception(f"Error while bridging coroutine {coro}")

    def init_blockchain(self):
        """Init blockchain."""
        client = self.wallet.init_blockchain()
        if not client:
            return

        self._cancel_client_tasks()
        self.signal_refresh_sync_status.emit()
        self._start_bridges()

    def is_in_cbf_ibd(self) -> bool:
        """Is in cbf ibd."""
        if not self.wallet.client:
            return False
        return (
            (self.wallet.bdkwallet.latest_checkpoint().height == 0)
            and (self.config.network_config.server_type == BlockchainType.CompactBlockFilter)
            and self.wallet.client.sync_status in [SyncStatus.syncing, SyncStatus.unknown]
        )

    def on_update(self, update_info: UpdateInfo):
        """On update."""
        logger.info(self.tr("start updating lists"))
        new_chain_height = self.wallet.get_height_no_cache()
        # self.wallet.clear_cache()
        self.refresh_caches_and_ui_lists(
            force_ui_refresh=False,
            chain_height_advanced=new_chain_height != self._last_sync_chain_height,
        )
        # self.update_tabs()
        logger.info(self.tr("finished updating lists"))
        self._last_sync_chain_height = new_chain_height

        self.fx.update_if_needed()
        self.save()
        if self.wallet.client:
            self.signal_after_sync.emit(self.wallet.client.sync_status)

        # after the caches are refreshed i can check fast if
        # the last used address is more than gap distand from the tip
        if (
            update_info.update_type == UpdateInfo.UpdateType.full_sync
            and self.wallet._more_than_gap_revealed_addresses()
        ):
            # update_info.update_type==UpdateInfo.UpdateType.full_sync prevents infinite loops
            # because _sync_revealed_spks will emit a update every time (even though there are no new txs)
            self.loop_in_thread.run_task(
                self._sync_revealed_spks(),
                on_done=self._sync_on_done,
                on_success=self._sync_on_success,
                on_error=self._sync_on_error,
                key=f"{id(self)}sync",
                multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
            )

    async def _sync_revealed_spks(self):
        "Syncs all revealed skps"
        if not self.wallet.client:
            return
        self.wallet.client.sync(self.wallet.bdkwallet.start_sync_with_revealed_spks().build())
        self.signal_progress_info.emit(self.wallet.client.progress_info)
        self.signal_refresh_sync_status.emit()
        return None

    def get_editable_protowallet(self) -> ProtoWallet:
        """Get editable protowallet."""
        return self.wallet.as_protowallet()

    def export_bip329_labels(self) -> None:
        """Export bip329 labels."""
        s = self.wallet.labels.export_bip329_jsonlines()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export labels"),
            f"{self.wallet.id}_labels.jsonl",
            self.tr("All Files (*);;JSON Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path, "w") as file:
            file.write(s)

    def export_labels(self) -> None:
        """Export labels."""
        s = self.wallet.labels.dumps_data_jsonlines()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export labels"),
            f"{self.wallet.id}_labels.jsonl",
            self.tr("All Files (*);;JSON Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path, "w") as file:
            file.write(s)

    def import_bip329_labels(self) -> None:
        """Import bip329 labels."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import labels"),
            "",
            self.tr("All Files (*);;JSONL Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path) as file:
            lines = file.read()

        changed_data = self.wallet.labels.import_bip329_jsonlines(lines)
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True, reason=UpdateFilterReason.UserImport))
        Message(
            self.tr("Successfully updated {number} Labels").format(number=len(changed_data)),
            type=MessageType.Info,
            parent=self,
        )

    def import_labels(self) -> None:
        """Import labels."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import labels"),
            "",
            self.tr("All Files (*);;JSONL Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path) as file:
            lines = file.read()

        force_overwrite = not bool(
            question_dialog(
                "Do you want to keep existing labels?",
                true_button=self.tr("Keep existing"),
                false_button=self.tr("Overwrite existing"),
            )
        )

        changed_data = self.wallet.labels.import_dumps_data(lines, force_overwrite=force_overwrite)
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True, reason=UpdateFilterReason.UserImport))
        Message(
            self.tr("Successfully updated {number} Labels").format(number=len(changed_data)),
            type=MessageType.Info,
            parent=self,
        )

    def import_electrum_wallet_labels(self) -> None:
        """Import electrum wallet labels."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Electrum Wallet labels"),
            "",
            self.tr("All Files (*);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path) as file:
            lines = file.read()

        changed_data = self.wallet.labels.import_electrum_wallet_json(lines, network=self.config.network)
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True, reason=UpdateFilterReason.UserImport))
        Message(
            self.tr("Successfully updated {number} Labels").format(number=len(changed_data)),
            type=MessageType.Info,
            parent=self,
        )

    def on_hist_list_selection_changed(self):
        """On hist list selection changed."""
        keys = self.history_list.get_selected_keys()
        self.wallet_balance_chart.highlight_txids(txids=set(keys))

    def apply_txs(self, txs: list[bdk.Transaction], last_seen: int = LOCAL_TX_LAST_SEEN):
        """Apply txs."""

        txs_dict = {str(tx.compute_txid()): tx for tx in txs}

        all_hidden_txs = self.wallet.get_hidden_txs_in_tx_graph()
        append_hidden_tx = {txid: tx for txid, tx in txs_dict.items() if txid in all_hidden_txs}
        only_non_hidden_txs = {txid: tx for txid, tx in txs_dict.items() if txid not in all_hidden_txs}

        if append_hidden_tx and not question_dialog(
            text=self.tr(
                "The transactions\n{}\n"
                "can only be added as unconfirmed in-mempool. \n"
                "Do you want to continue anyway?"
            ).format("\n".join(append_hidden_tx.keys())),
            title=self.tr("Add as unconfirmed in-mempool?"),
            true_button=self.tr("Add as unconfirmed in-mempool"),
            false_button=self.tr("Cancel"),
        ):
            return

        applied_txs: list[bdk.UnconfirmedTx] = []

        if append_hidden_tx:
            applied_txs += self.wallet.apply_unconfirmed_txs(
                list(append_hidden_tx.values()), last_seen=int(datetime.datetime.now().timestamp())
            )
        if only_non_hidden_txs:
            applied_txs += self.wallet.apply_unconfirmed_txs(
                list(only_non_hidden_txs.values()), last_seen=last_seen
            )
        if not applied_txs:
            return

        self.refresh_caches_and_ui_lists(force_ui_refresh=False)

    def apply_evicted_txs(self, txids: list[str], last_seen: int):
        statuses = [TxStatus.from_wallet(txid=txid, wallet=self.wallet) for txid in txids]

        if any(status.is_unconfirmed() for status in statuses) and not question_dialog(
            text=self.tr(
                "This will only remove the transaction from this wallet view. "
                "It is already broadcast to the Bitcoin network and will likely still confirm.\n\n"
                "Do you want to remove it from the wallet anyway?"
            ),
            title=self.tr("Remove unconfirmed transaction?"),
            true_button=self.tr("Remove"),
            false_button=self.tr("Cancel"),
        ):
            return

        self.wallet.apply_evicted_txs(txids, evicted_at=last_seen)

        self.refresh_caches_and_ui_lists(force_ui_refresh=False)

    def export_pdf_statement(self, wallet_id: str | None = None) -> None:
        """Export pdf statement."""
        if wallet_id and wallet_id != self.wallet.id:
            logger.error(f"Cannot export for {wallet_id=}, since this is {self.wallet.id=}")
            return
        if not self.plugin_manager:
            return

        sync_client = self.plugin_manager.get_instance(SyncClient)
        if not sync_client:
            return

        make_and_open_pdf_statement(
            self.wallet,
            lang_code=QLocale().name() or DEFAULT_LANG_CODE,
        )

    def close(self) -> bool:
        # crucial is to explicitly close everything that has a wallet attached
        """Close."""
        self.stop_sync_timer()
        self._cancel_client_tasks()
        self.quick_receive.close()
        self.address_tab.close()
        self.address_list_with_toolbar.close()
        self.history_tab.close()
        self.history_tab.searchable_list = None
        self.history_list_with_toolbar.close()
        self.wallet_descriptor_ui.close()
        self.uitx_creator.close()
        self.wallet_balance_chart.close()
        if self.plugin_manager:
            self.plugin_manager.close()
        self.tabs.clearChildren()
        self.tabs.close()
        self.wallet.close()
        SignalTools.disconnect_all_signals_from(self.wallet_signals)
        self.setParent(None)  #  THIS made it that the qt wallet is destroyed
        return super().close()


def get_syncclients(wallet_functions: WalletFunctions) -> dict[str, SyncClient]:
    """Get syncclients."""
    d: dict[str, SyncClient] = {}
    for wallet_id, qt_wallet in wallet_functions.get_qt_wallets().items():
        if not qt_wallet.plugin_manager:
            continue
        client = qt_wallet.plugin_manager.get_instance(SyncClient)
        if not client:
            continue
        d[wallet_id] = client
    return d
