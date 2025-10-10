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


import datetime
import json
import logging
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from bitcoin_safe_lib.async_tools.loop_in_thread import MultipleStrategy
from bitcoin_safe_lib.gui.qt.satoshis import Satoshis
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalTools
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.util import time_logger
from packaging import version
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.category_info import CategoryInfo
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.category_manager.category_manager import CategoryManager
from bitcoin_safe.gui.qt.label_syncer import LabelSyncer
from bitcoin_safe.gui.qt.my_treeview import (
    MyItemDataRole,
    SearchableTab,
    TreeViewWithToolbar,
)
from bitcoin_safe.gui.qt.qt_wallet_base import QtWalletBase, SyncStatus
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.sync_tab import SyncTab
from bitcoin_safe.gui.qt.ui_tx.ui_tx_creator import UITx_Creator
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.labels import LabelType
from bitcoin_safe.pdf_statement import make_and_open_pdf_statement
from bitcoin_safe.pythonbdk_types import (
    Balance,
    TransactionDetails,
    python_utxo_balance,
)
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.wallet_util import WalletDifferenceType

from ...config import UserConfig
from ...execute_config import DEFAULT_LANG_CODE, ENABLE_TIMERS
from ...mempool_manager import MempoolManager
from ...signals import Signals, UpdateFilter, UpdateFilterReason, WalletSignals
from ...tx import TxBuilderInfos, TxUiInfos, short_tx_id
from ...wallet import (
    LOCAL_TX_LAST_SEEN,
    DeltaCacheListTransactions,
    ProtoWallet,
    Wallet,
    filename_clean,
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


MINIMUM_INTERVAL_SYNC_REGULARLY = (
    5 * 60
)  # in seconds  .  A high value is OK here because the p2p monitoring will inform of any new txs instantly


class QTProtoWallet(QtWalletBase):
    signal_create_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_close_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore

    def __init__(
        self,
        protowallet: ProtoWallet,
        config: UserConfig,
        signals: Signals,
        tutorial_index: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(
            config=config,
            signals=signals,
            tutorial_index=tutorial_index,
            parent=parent,
        )

        self.tabs.setTitle(protowallet.id)
        self.wallet_descriptor_ui, self.settings_node = self.create_and_add_settings_tab(protowallet)

    @property
    def protowallet(self) -> ProtoWallet:
        return self.wallet_descriptor_ui.protowallet

    @protowallet.setter
    def protowallet(self, protowallet) -> None:
        self.wallet_descriptor_ui.set_protowallet(protowallet)

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.protowallet.threshold, len(self.protowallet.keystores)

    def get_keystore_labels(self) -> List[str]:
        return [self.protowallet.signer_name(i) for i in range(len(self.protowallet.keystores))]

    def create_and_add_settings_tab(self, protowallet: ProtoWallet) -> Tuple[DescriptorUI, SidebarNode]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=protowallet,
            signals=self.signals,
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
        self.signal_close_wallet.emit(self.protowallet.id)

    def on_apply_setting_changes(self) -> None:
        try:
            self.wallet_descriptor_ui.set_protowallet_from_ui()
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), type=MessageType.Error)
            return

        self.signal_create_wallet.emit(self.protowallet.id)

    def get_editable_protowallet(self) -> ProtoWallet:
        return self.protowallet

    def close(self) -> bool:
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()


class ProgressSignal:
    def __init__(self, signal_settext_balance_label: TypedPyQtSignal[str]) -> None:
        self.signal_settext_balance_label = signal_settext_balance_label

    def update(self, progress: "float", message: "Optional[str]"):
        self.signal_settext_balance_label.emit(f"Syncing wallet: {round(progress)}%  {message}")


class QTWallet(QtWalletBase, BaseSaveableClass):
    VERSION = "0.2.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "Wallet": Wallet,
        "Balance": Balance,
        HistListWithToolbar.__name__: HistListWithToolbar,
        AddressListWithToolbar.__name__: AddressListWithToolbar,
        UITx_Creator.__name__: UITx_Creator,
    }

    signal_settext_balance_label: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_on_change_sync_status: TypedPyQtSignal[SyncStatus] = pyqtSignal(SyncStatus)  # type: ignore  # SyncStatus

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        signals: Signals,
        mempool_manager: MempoolManager,
        fx: FX,
        sync_tab: SyncTab | None = None,
        password: str | None = None,
        file_path: str | None = None,
        notified_tx_ids: Iterable[str] | None = None,
        tutorial_index: int | None = None,
        history_list_with_toolbar: HistListWithToolbar | None = None,
        address_list_with_toolbar: AddressListWithToolbar | None = None,
        uitx_creator: UITx_Creator | None = None,
        last_tab_title: str = "",
        parent=None,
    ) -> None:
        super().__init__(
            signals=signals,
            config=config,
            tutorial_index=tutorial_index,
            parent=parent,
        )
        self.mempool_manager = mempool_manager
        self.wallet = self.set_wallet(wallet)
        self.password = password
        self.fx = fx
        self._file_path = file_path
        self.sync_status: SyncStatus = SyncStatus.unknown
        self.timer_sync_retry = QTimer()
        self.timer_sync_regularly = QTimer()
        self.notified_tx_ids = set(notified_tx_ids if notified_tx_ids else [])
        self.category_core = CategoryCore(wallet=self.wallet, signals=self.signals)

        self._last_syncing_start = datetime.datetime.now()
        self._syncing_delay = timedelta(seconds=0)
        self._last_sync_chain_height = 0
        self._rows_after_hist_list_update: List[str] = []

        self.sync_tab = (
            sync_tab
            if sync_tab
            else SyncTab.from_descriptor_new_device_keys(
                self.wallet.multipath_descriptor,
                network=self.config.network,
                signals=self.signals,
                parent=self,
            )
        )
        self.sync_tab.set_wallet_id(self.wallet.id)

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

        self.uitx_creator, self.send_node = self._create_send_tab(uitx_creator=uitx_creator)
        self.wallet_descriptor_ui, self.settings_node = self.create_and_add_settings_tab()

        self.sync_tab, self.label_syncer, self.sync_node = self.add_sync_tab()

        self.create_status_bar(self, self.outer_layout)
        self.update_status_visualization(self.sync_status)

        self.updateUi()
        self.tabs.set_current_tab_by_text(last_tab_title)
        self.quick_receive.update_content(UpdateFilter(refresh_all=True))

        #### connect signals
        # only signals, not member of [wallet_signals, wallet_signals] have to be tracked,
        # all others I can connect automatically
        self.signal_tracker.connect(self.signal_on_change_sync_status, self.update_status_visualization)
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

        self._start_sync_retry_timer()
        self._start_sync_regularly_timer()
        # since a Wallet can now have txs before syncing
        # we need to treat it like something has changed
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True))

    def dump(self) -> Dict[str, Any]:
        d = super().dump()

        d["wallet"] = self.wallet.dump()
        d["sync_tab"] = self.sync_tab.dump()
        d["tutorial_index"] = self.tutorial_index
        d["notified_tx_ids"] = list(self.notified_tx_ids)
        d["history_list_with_toolbar"] = self.history_list_with_toolbar.dump()
        d["address_list_with_toolbar"] = self.address_list_with_toolbar.dump()
        d["uitx_creator"] = self.uitx_creator.dump()
        d["last_tab_title"] = current.title if (current := self.tabs.currentChildNode()) else None

        return d

    @classmethod
    def from_file(
        cls,
        file_path: str,
        config: UserConfig,
        signals: Signals,
        mempool_manager: MempoolManager,
        fx: FX,
        password: str | None = None,
    ) -> "QTWallet":
        return super()._from_file(
            filename=file_path,
            password=password,
            class_kwargs={
                "Wallet": {"config": config},
                "QTWallet": {
                    "config": config,
                    "signals": signals,
                    "mempool_manager": mempool_manager,
                    "fx": fx,
                    "file_path": file_path,
                },
                "HistList": {
                    "config": config,
                    "signals": signals,
                    "mempool_manager": mempool_manager,
                    "fx": fx,
                },
                "HistListWithToolbar": {
                    "config": config,
                },
                "UTXOList": {
                    "config": config,
                    "signals": signals,
                    "fx": fx,
                },
                "UtxoListWithToolbar": {
                    "config": config,
                },
                "AddressList": {
                    "config": config,
                    "signals": signals,
                    "fx": fx,
                },
                "AddressListWithToolbar": {
                    "config": config,
                },
                "SyncTab": {
                    "signals": signals,
                    "network": config.network,
                },
                "UITx_Creator": {
                    "signals": signals,
                    "config": config,
                    "mempool_manager": mempool_manager,
                    "fx": fx,
                },
                "CategoryList": {
                    "signals": signals,
                    "config": config,
                },
            },
        )

    @classmethod
    def file_migration(cls, file_content: str):
        "this class can be overwritten in child classes"

        dct = json.loads(file_content)

        if dct["__class__"] == "Wallet":
            d: Dict[str, Any] = {}
            d["__class__"] = cls.__name__
            d["VERSION"] = cls.VERSION
            d["wallet"] = dct

            if not d["wallet"].get("data_dump"):
                d["wallet"]["data_dump"] = {}
            d["sync_tab"] = d["wallet"]["data_dump"].get("SyncTab", {})
            del d["wallet"]["data_dump"]
            dct = d

        # in the function above, only default json serilizable things can be set in dct
        return json.dumps(dct)

    @classmethod
    def from_dump_downgrade_migration(cls, dct: Dict[str, Any]):
        if version.parse(str(dct.get("VERSION", 0))) >= version.parse("0.2.0") > version.parse(cls.VERSION):
            # downgrade bdk 1.x related stuff
            if sync_tab := dct.get("sync_tab"):
                if nostr_sync_dump := sync_tab.get("nostr_sync_dump"):

                    def migrate_network(obj: Dict[str, Any], key: str = "network"):
                        if obj.get(key) == "TESTNET4":
                            obj[key] = "TESTNET"

                    migrate_network(nostr_sync_dump)
                    if nostr_protocol := nostr_sync_dump.get("nostr_protocol"):
                        migrate_network(nostr_protocol)
                    if group_chat := nostr_sync_dump.get("group_chat"):
                        migrate_network(group_chat)
        return dct

    @classmethod
    def from_dump(cls, dct: Dict, class_kwargs: Dict | None = None) -> "QTWallet":
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if class_kwargs:
            # must contain "Wallet":{"config": ... }
            dct.update(class_kwargs[cls.__name__])

        if class_kwargs:
            dct["sync_tab"] = (
                SyncTab.from_dump(dct["sync_tab"], network=dct["config"].network, signals=dct["signals"])
                if dct.get("sync_tab")
                else None
            )
        else:
            logger.warning(f"No class_kwargs given for {cls.__name__}.from_dump")

        instance = cls(**filtered_for_init(dct, cls))
        return instance

    @property
    def wallet_signals(self) -> WalletSignals:
        return self.signals.wallet_signals[self.wallet.id]

    def on_updated(self, update_filter: UpdateFilter):
        address_infos = [
            self.wallet.get_address_info_min(address=address) for address in update_filter.addresses
        ]
        self.wallet.mark_labeled_addresses_used(
            address_infos=[address_info for address_info in address_infos if address_info]
        )
        self.update_display_balance()

    def updateUi(self) -> None:
        if _node := self.tabs.findNodeByWidget(self.uitx_creator):
            _node.setTitle(self.tr("Send"))
        if _node := self.tabs.findNodeByWidget(self.wallet_descriptor_ui):
            _node.setTitle(self.tr("Descriptor"))
        if _node := self.tabs.findNodeByWidget(self.sync_tab):
            _node.setTitle(self.tr("Sync && Chat"))
        if _node := self.tabs.findNodeByWidget(self.history_tab):
            _node.setTitle(self.tr("History"))
        if _node := self.tabs.findNodeByWidget(self.address_tab):
            _node.setTitle(self.tr("Receive"))

        self.balance_label_title.setText(self.tr("Balance"))
        self.fiat_value_label_title.setText(self.tr("Value"))
        self.category_manager.updateUi()
        self.quick_receive.updateUi()

    def update_display_balance(self):
        balance_total = Satoshis(self.wallet.get_balance().total, self.config.network)
        self.balance_label.setText(balance_total.str_with_unit())
        self.fiat_value_label.setText(self.fx.btc_to_fiat_str(amount=balance_total.value))

    def stop_sync_timer(self) -> None:
        self.timer_sync_retry.stop()
        self.timer_sync_regularly.stop()

    def _start_sync_regularly_timer(self, delay_retry_sync=60) -> None:
        if self.timer_sync_regularly.isActive():
            return
        self.timer_sync_regularly.setInterval(delay_retry_sync * 1000)

        self.timer_sync_regularly.timeout.connect(self._regular_sync)
        if ENABLE_TIMERS:
            self.timer_sync_regularly.start()

    def _regular_sync(self):
        if self.sync_status not in [SyncStatus.synced]:
            return

        logger.info(f"Regular update: Sync wallet {self.wallet.id} again")
        self.sync()

    def _sync_if_needed(self) -> None:
        if self.sync_status in [SyncStatus.syncing, SyncStatus.synced]:
            return

        logger.info(f"Retry timer: Try syncing wallet {self.wallet.id}")
        self.sync()

    def _start_sync_retry_timer(self, delay_retry_sync=30) -> None:
        if self.timer_sync_retry.isActive():
            return
        self.timer_sync_retry.setInterval(delay_retry_sync * 1000)

        self.timer_sync_retry.timeout.connect(self._sync_if_needed)
        if ENABLE_TIMERS:
            self.timer_sync_retry.start()

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.wallet.get_mn_tuple()

    def get_keystore_labels(self) -> List[str]:
        return [keystore.label for keystore in self.wallet.keystores]

    @property
    def file_path(self) -> str:
        return self._file_path if self._file_path else filename_clean(self.wallet.id)

    @file_path.setter
    def file_path(self, value: Optional[str]) -> None:
        self._file_path = value

    def create_and_add_settings_tab(self) -> Tuple[DescriptorUI, SidebarNode]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=self.wallet.as_protowallet(),
            signals=self.signals,
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

    def on_qtwallet_apply_setting_changes(self):
        # save old status, such that the backup has all old data (inlcuding the "SyncTab" in the data_dump)
        self.save()

        self.wallet_descriptor_ui.set_protowallet_from_ui()
        new_wallet = Wallet.from_protowallet(
            protowallet=self.wallet_descriptor_ui.protowallet,
            config=self.config,
            labels=self.wallet.labels,
            default_category=self.wallet.labels.default_category,
        )
        # compare if something change
        worst = self.wallet.get_differences(new_wallet).worst()
        if not worst:
            Message(self.tr("No changes to apply."))
            return

        if worst.type == WalletDifferenceType.NoImpactOnAddresses:
            # no message needs to be shown here
            pass
        elif worst.type == WalletDifferenceType.ImpactOnAddresses:
            if not question_dialog(
                self.tr("Proceeding will potentially change all wallet addresses."),
                true_button=self.tr("Proceed"),
            ):
                return

        # do backup
        filename = self.save_backup()
        if filename:
            Message(self.tr("Backup saved to {filename}").format(filename=filename))
        else:
            Message(self.tr("Backup failed. Aborting Changes."))
            return

        # i have to close it first, to ensure the wallet is shut down completely
        self.signals.close_qt_wallet.emit(self.wallet.id)

        qt_wallet = QTWallet(
            new_wallet,
            self.config,
            self.signals,
            self.mempool_manager,
            self.fx,
            file_path=self.file_path,
            password=self.password,
            parent=self.parent(),
        )

        self.signals.add_qt_wallet.emit(qt_wallet, self._file_path, self.password)
        qt_wallet.sync()

    def add_sync_tab(self) -> Tuple[SyncTab, LabelSyncer, SidebarNode]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"

        icon_basename = SyncTab.get_icon_basename(enabled=self.sync_tab.enabled())
        sync_node = SidebarNode[object](
            data=self.sync_tab, widget=self.sync_tab, icon=svg_tools.get_QIcon(icon_basename), title=""
        )
        self.tabs.addChildNode(sync_node)
        self.sync_tab.checkbox.stateChanged.connect(self._set_sync_tab_icon)

        label_syncer = LabelSyncer(self.wallet.labels, self.sync_tab, self.wallet_signals)
        self.sync_tab.finish_init_after_signal_connection()
        return self.sync_tab, label_syncer, sync_node

    def _set_sync_tab_icon(self, enabled: bool):
        node = self.tabs.findNodeByWidget(self.sync_tab)
        if not node:
            return
        icon_basename = SyncTab.get_icon_basename(enabled=enabled)
        node.setIcon(svg_tools.get_QIcon(icon_basename))

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

    def move_wallet_file(self, new_file_path) -> Optional[str]:
        if os.path.exists(new_file_path):
            Message(
                self.tr("Cannot move the wallet file, because {file_path} exists").format(
                    file_path=new_file_path
                )
            )
            return None
        shutil.move(self.file_path, new_file_path)
        self.remove_lockfile(Path(self.file_path))
        old_file_path = self.file_path
        self.file_path = new_file_path
        self.get_wallet_lockfile(Path(self.file_path))
        logger.info(f"Saved {old_file_path} under new name {self.file_path}")
        return new_file_path

    @classmethod
    def get_wallet_lockfile_path(cls, wallet_file_path: Path) -> Path:
        return wallet_file_path.with_suffix(".lock")

    @classmethod
    def get_wallet_lockfile(cls, wallet_file_path: Path) -> Optional[Path]:
        lockfile_path = cls.get_wallet_lockfile_path(wallet_file_path)
        if os.path.exists(lockfile_path):
            return None
        with open(lockfile_path, "w") as lockfile:
            lockfile.write(str(os.getpid()))
            return lockfile_path

    @classmethod
    def remove_lockfile(cls, wallet_file_path: Path) -> None:
        lock_file_path = cls.get_wallet_lockfile_path(wallet_file_path)
        if not lock_file_path:
            return
        if lock_file_path.exists():
            os.remove(lock_file_path)
            logger.info(f"Lock file {lock_file_path} removed.")

    def save(self) -> Optional[str]:  # type: ignore
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
        original_id = self.wallet.id
        if wallet_id:
            self.wallet.id = wallet_id
        super().save(
            file_path,
            password=self.password,
        )
        self.wallet.id = original_id
        logger.info(f"wallet {self.wallet.id} saved to {file_path}")

    def change_password(self) -> Optional[str]:
        if self.password:
            ui_password_question = PasswordQuestion(label_text="Your current password:")
            password = ui_password_question.ask_for_password()
            password = password if password else None
            if password != self.password:
                Message(self.tr("Password incorrect"), type=MessageType.Warning)
                return None

        new_password = PasswordCreation(
            window_title=self.tr("Change password"), label_text=self.tr("New password:")
        ).get_password()
        if new_password is None:
            return None

        self.password = new_password
        self.save()
        Message(self.tr("Wallet saved"))
        return self.password

    def cancel_setting_changes(self) -> None:
        self.wallet_descriptor_ui.protowallet = self.wallet.as_protowallet()
        self.wallet_descriptor_ui.set_all_ui_from_protowallet()

    @time_logger
    def get_delta_txs(self, access_marker="notifications") -> DeltaCacheListTransactions:
        delta_txs = self.wallet.bdkwallet.list_delta_transactions(access_marker=access_marker)
        return delta_txs

    def format_txs_for_notification(self, txs: List[TransactionDetails]) -> str:
        return "\n".join(
            [
                "  {amount}".format(
                    amount=Satoshis(tx.received - tx.sent, self.config.network).str_as_change(unit=True),
                    # shortid=short_tx_id(tx.txid),
                )
                for tx in txs
            ]
        )

    def hanlde_removed_txs(self, removed_txs: List[TransactionDetails]) -> None:
        if not removed_txs:
            return

        # if transactions were removed (reorg or other), then recalculate everything
        message_content = self.tr(
            "The transactions \n{txs}\n in wallet '{wallet}' were removed from the history!!!"
        ).format(txs=self.format_txs_for_notification(removed_txs), wallet=self.wallet.id)
        Message(
            message_content,
            no_show=True,
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
                    filename = Path(folder_path) / f"{short_tx_id( tx.txid)}.tx"

                    # create a file descriptor
                    fd = os.open(filename, os.O_CREAT | os.O_WRONLY)
                    data.write_to_filedescriptor(fd)
                    logger.info(f"Exported {tx.txid} to {filename}")
        else:
            self.signals.signal_close_tabs_with_txids.emit(
                [tx.transaction.compute_txid() for tx in removed_txs]
            )

        self.notified_tx_ids -= set([tx.txid for tx in removed_txs])
        # all the lists must be updated
        self.refresh_caches_and_ui_lists(force_ui_refresh=True)

    def handle_appended_txs(self, appended_txs: List[TransactionDetails]) -> None:
        if not appended_txs:
            return

        appended_txs = [tx for tx in appended_txs if tx.txid not in self.notified_tx_ids]

        if len(appended_txs) == 1:
            Message(
                self.tr("New transaction in wallet '{wallet}':\n{txs}").format(
                    txs=self.format_txs_for_notification(appended_txs), wallet=self.wallet.id
                ),
                no_show=True,
            ).emit_with(self.signals.notification)
        elif len(appended_txs) > 1:
            Message(
                self.tr("{number} new transactions in wallet '{wallet}':\n{txs}").format(
                    number=len(appended_txs),
                    txs=self.format_txs_for_notification(appended_txs),
                    wallet=self.wallet.id,
                ),
                no_show=True,
            ).emit_with(self.signals.notification)

        self.notified_tx_ids = self.notified_tx_ids.union([tx.txid for tx in appended_txs])

    def handle_delta_txs(self, delta_txs: DeltaCacheListTransactions) -> None:
        self.hanlde_removed_txs(delta_txs.removed)
        self.handle_appended_txs(delta_txs.appended)

    @time_logger
    def refresh_caches_and_ui_lists(
        self,
        force_ui_refresh=True,
        chain_height_advanced=False,
    ) -> None:
        # before the wallet UI updates, we have to refresh the wallet caches to make the UI update faster

        self.wallet.fill_commonly_used_caches_min()

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
    ) -> Tuple[UITx_Creator, SidebarNode]:

        if uitx_creator:
            uitx_creator.set_category_core(category_core=self.category_core)
        else:
            uitx_creator = UITx_Creator(
                mempool_manager=self.mempool_manager,
                fx=self.fx,
                config=self.config,
                signals=self.signals,
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

        async def do() -> Union[TxBuilderInfos, Exception]:
            try:
                return self.wallet.create_psbt(txinfos)
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
                return e

        def on_done(builder_infos: Union[TxBuilderInfos, Exception]) -> None:
            if not builder_infos:
                self.wallet_signals.finished_psbt_creation.emit()
                return
            if isinstance(builder_infos, Exception):
                caught_exception_message(builder_infos)
                self.wallet_signals.finished_psbt_creation.emit()
                return
            if not isinstance(builder_infos, TxBuilderInfos):
                self.wallet_signals.finished_psbt_creation.emit()  # type: ignore
                Message("Could not create PSBT", type=MessageType.Error)
                return

            try:
                # set labels in other wallets  (recipients can be another open wallet)
                for wallet in get_wallets(self.signals):
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
                caught_exception_message(e)
            finally:
                self.wallet_signals.finished_psbt_creation.emit()

        def on_success(builder_infos: Union[TxBuilderInfos, Exception]) -> None:
            pass

        def on_error(packed_error_info) -> None:
            self.wallet_signals.finished_psbt_creation.emit()

        self.loop_in_thread.run_task(
            do(),
            on_done=on_done,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}create_psbt",
            multiple_strategy=MultipleStrategy.QUEUE,
        )

    def get_wallet(self) -> Wallet:
        return self.wallet

    def get_qt_wallet(self) -> "QTWallet":
        return self

    def set_wallet(self, wallet: Wallet) -> Wallet:
        self.wallet = wallet

        self.wallet_signals.updated.connect(self.wallet.on_addresses_updated)
        self.signal_tracker.connect(self.signals.get_wallets, self.get_wallet, slot_name=self.wallet.id)
        self.signal_tracker.connect(self.signals.get_qt_wallets, self.get_qt_wallet, slot_name=self.wallet.id)
        self.signal_tracker.connect(
            self.wallet_signals.get_category_infos,
            self.get_category_infos,
            slot_name=self.wallet.id,
        )
        return wallet

    def create_status_bar(self, tab: QWidget, outer_layout) -> None:
        pass

    def update_status_visualization(self, sync_status: SyncStatus) -> None:
        if not self.wallet:
            return

        icon_text = ""
        tooltip = ""
        if sync_status == SyncStatus.syncing:
            icon_text = "status_waiting.svg"
            self.history_list_with_toolbar.sync_button.set_icon_is_syncing()
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
            self.history_list_with_toolbar.sync_button.set_icon_allow_refresh()
        else:
            icon_text = "status_disconnected.svg"
            tooltip = self.tr("Disconnected from {server}").format(
                server=self.config.network_config.description_short()
            )
            self.history_list_with_toolbar.sync_button.set_icon_allow_refresh()

        self.signals.signal_set_tab_properties.emit(self, self.wallet.id, icon_text, tooltip)

    def create_list_tab(
        self,
        treeview_with_toolbar: TreeViewWithToolbar,
        tabs: SidebarNode,
        horizontal_widgets_left: Optional[List[QWidget]] = None,
        horizontal_widgets_right: Optional[List[QWidget]] = None,
    ) -> SearchableTab:
        # create a horizontal widget and layout
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
    ) -> Tuple[SearchableTab, HistList, SidebarNode, WalletBalanceChart, HistListWithToolbar]:
        tab = SearchableTab()
        tab.setObjectName(f"created as HistList tab containrer")
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        splitter = QSplitter(orientation=Qt.Orientation.Vertical)
        tab_layout.addWidget(splitter)

        if history_list_with_toolbar:
            history_list_with_toolbar.hist_list.set_wallets(wallets=[self.wallet])
        else:
            l = HistList(
                fx=self.fx,
                config=self.config,
                signals=self.signals,
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
            history_list_with_toolbar = HistListWithToolbar(l, self.config, parent=tabs)

        history_list_with_toolbar.hist_list.signal_selection_changed.connect(
            self.on_hist_list_selection_changed
        )
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
        top_widget_layout.addWidget(chart_container)
        top_widget_layout.addWidget(self.quick_receive)

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
            2,
            hist_node,
        )

        # set initial sizes so that top starts at its minimum
        splitter.setSizes([1, 10])
        splitter.setStretchFactor(0, 0)  # index 0 = top
        splitter.setStretchFactor(1, 1)  # index 1 = bottom
        splitter.setSizes(
            [self.quick_receive.minimumHeight(), self.height() - self.quick_receive.minimumHeight()]
        )
        return (
            tab,
            history_list_with_toolbar.hist_list,
            hist_node,
            wallet_balance_chart,
            history_list_with_toolbar,
        )

    def on_hist_chart_click(self, tx_details: TransactionDetails):
        self.history_list.select_rows(
            content_list=[tx_details.txid],
            column=self.history_list.key_column,
            role=MyItemDataRole.ROLE_KEY,
            scroll_to_last=True,
        )

    def get_category_infos(self) -> List[CategoryInfo]:

        category_python_txo_dict = self.wallet.get_category_python_txo_dict(include_spent=True)

        category_infos: List[CategoryInfo] = []
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
    ) -> Tuple[SearchableTab, AddressList, SidebarNode, CategoryManager, AddressListWithToolbar]:

        category_manager = CategoryManager(
            config=self.config, category_core=self.category_core, wallet_id=self.wallet.id
        )

        if address_list_with_toolbar:
            address_list_with_toolbar.address_list.set_wallets(wallets=[self.wallet])
            address_list_with_toolbar.set_category_core(self.category_core)
        else:
            l = AddressList(
                fx=self.fx,
                config=self.config,
                wallets=[self.wallet],
                signals=self.signals,
                hidden_columns=([AddressList.Columns.WALLET_ID, AddressList.Columns.INDEX]),
            )
            address_list_with_toolbar = AddressListWithToolbar(
                address_list=l,
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

    def set_sync_status(self, new: SyncStatus) -> None:
        self.sync_status = new
        logger.info(f"{self.wallet.id} set_sync_status {new}")
        self.signal_on_change_sync_status.emit(new)
        QApplication.processEvents()

    async def _sync(self) -> Any:
        self.wallet.sync()

    def _sync_on_done(self, result) -> None:
        self._syncing_delay = datetime.datetime.now() - self._last_syncing_start
        interval_timer_sync_regularly = min(
            60 * 60 * 24, max(int(self._syncing_delay.total_seconds() * 200), MINIMUM_INTERVAL_SYNC_REGULARLY)
        )  # in sec
        self.timer_sync_regularly.setInterval(interval_timer_sync_regularly * 1000)
        logger.info(
            f"Syncing took {self._syncing_delay} --> set the interval_timer_sync_regularly to {interval_timer_sync_regularly}s"
        )

    def _sync_on_error(self, packed_error_info) -> None:
        self.set_sync_status(SyncStatus.error)
        logger.info(f"Could not sync. SynStatus set to {SyncStatus.error.name} for wallet {self.wallet.id}")
        logger.error(str(packed_error_info))
        # custom_exception_handler(*packed_error_info)

    def _sync_on_success(self, result) -> None:
        self.set_sync_status(SyncStatus.synced)
        logger.info(f"success syncing wallet '{self.wallet.id}'")

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
        self.signal_after_sync.emit(self.sync_status)

    def sync(self) -> None:
        if self.sync_status == SyncStatus.syncing:
            logger.info(f"Syncing already in progress")
            return

        logger.info(self.tr(f"Refresh all caches before syncing."))
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
        self.set_sync_status(SyncStatus.syncing)

        self._last_syncing_start = datetime.datetime.now()

        self.loop_in_thread.run_task(
            self._sync(),
            on_done=self._sync_on_done,
            on_success=self._sync_on_success,
            on_error=self._sync_on_error,
            key=f"{id(self)}sync",
            multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
        )

    def get_editable_protowallet(self) -> ProtoWallet:
        return self.wallet.as_protowallet()

    def export_bip329_labels(self) -> None:
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
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import labels"),
            "",
            self.tr("All Files (*);;JSONL Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path, "r") as file:
            lines = file.read()

        changed_data = self.wallet.labels.import_bip329_jsonlines(lines)
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True, reason=UpdateFilterReason.UserImport))
        Message(
            self.tr("Successfully updated {number} Labels").format(number=len(changed_data)),
            type=MessageType.Info,
        )

    def import_labels(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import labels"),
            "",
            self.tr("All Files (*);;JSONL Files (*.jsonl);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path, "r") as file:
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
        )

    def import_electrum_wallet_labels(self) -> None:

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Electrum Wallet labels"),
            "",
            self.tr("All Files (*);;JSON Files (*.json)"),
        )
        if not file_path:
            logger.info(self.tr("No file selected"))
            return

        with open(file_path, "r") as file:
            lines = file.read()

        changed_data = self.wallet.labels.import_electrum_wallet_json(lines, network=self.config.network)
        self.wallet_signals.updated.emit(UpdateFilter(refresh_all=True, reason=UpdateFilterReason.UserImport))
        Message(
            self.tr("Successfully updated {number} Labels").format(number=len(changed_data)),
            type=MessageType.Info,
        )

    def on_hist_list_selection_changed(self):
        keys = self.history_list.get_selected_keys()
        self.wallet_balance_chart.highlight_txids(txids=set(keys))

    def apply_txs(self, txs: List[bdk.Transaction], last_seen: int = LOCAL_TX_LAST_SEEN):
        applied_txs = self.wallet.apply_unconfirmed_txs(txs, last_seen=last_seen)
        if not applied_txs:
            return
        self.hist_node.select()
        self.wallet_signals.updated.emit(
            UpdateFilter(refresh_all=True, reason=UpdateFilterReason.TransactionChange)
        )

        self._rows_after_hist_list_update = [tx.compute_txid() for tx in txs]

        self.history_list.select_rows(
            self._rows_after_hist_list_update,
            self.history_list.key_column,
            role=MyItemDataRole.ROLE_KEY,
            scroll_to_last=True,
        )

    def export_pdf_statement(self, wallet_id: str | None = None) -> None:
        if wallet_id and wallet_id != self.wallet.id:
            logger.error(f"Cannot export for {wallet_id=}, since this is {self.wallet.id=}")
            return

        make_and_open_pdf_statement(
            self.wallet,
            lang_code=self.signals.get_current_lang_code() or DEFAULT_LANG_CODE,
            label_sync_nsec=(
                self.sync_tab.nostr_sync.group_chat.dm_connection.async_dm_connection.keys.secret_key().to_bech32()
                if self.sync_tab.enabled()
                else None
            ),
        )

    def close(self) -> bool:
        # crucial is to explicitly close everything that has a wallet attached
        self.stop_sync_timer()
        self.quick_receive.close()
        self.address_tab.close()
        self.address_list_with_toolbar.close()
        self.history_tab.close()
        self.history_tab.searchable_list = None
        self.history_list_with_toolbar.close()
        self.wallet_descriptor_ui.close()
        self.uitx_creator.close()
        self.wallet_balance_chart.close()
        self.label_syncer.send_all_labels_to_myself()
        self.sync_tab.unsubscribe_all()
        self.sync_tab.close()
        self.tabs.clearChildren()
        self.tabs.close()
        self.wallet.close()
        SignalTools.disconnect_all_signals_from(self.wallet_signals)
        self.setParent(None)  #  THIS made it that the qt wallet is destroyed
        return super().close()
