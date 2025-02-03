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
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.category_info import CategoryInfo, SubtextType
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.label_syncer import LabelSyncer
from bitcoin_safe.gui.qt.my_treeview import SearchableTab, TreeViewWithToolbar
from bitcoin_safe.gui.qt.qt_wallet_base import QtWalletBase, SyncStatus
from bitcoin_safe.gui.qt.sync_tab import SyncTab
from bitcoin_safe.pythonbdk_types import Balance, python_utxo_balance
from bitcoin_safe.signal_tracker import SignalTools
from bitcoin_safe.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe.threading_manager import TaskThread, ThreadingManager
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.util import Satoshis

from ...config import UserConfig
from ...execute_config import ENABLE_THREADING, ENABLE_TIMERS
from ...mempool import MempoolData
from ...signals import Signals, UpdateFilter, UpdateFilterReason, WalletSignals
from ...tx import TxBuilderInfos, TxUiInfos, short_tx_id
from ...wallet import (
    DeltaCacheListTransactions,
    ProtoWallet,
    Wallet,
    filename_clean,
    get_wallets,
)
from .address_list import AddressList, AddressListWithToolbar
from .bitcoin_quick_receive import BitcoinQuickReceive
from .category_list import CategoryEditor
from .descriptor_ui import DescriptorUI
from .dialogs import PasswordCreation, PasswordQuestion, question_dialog
from .hist_list import HistList, HistListWithToolbar
from .taglist import AddressDragInfo
from .ui_tx import UITx_Creator
from .util import (
    Message,
    MessageType,
    caught_exception_message,
    custom_exception_handler,
    read_QIcon,
)
from .utxo_list import UTXOList, UtxoListWithToolbar
from .wallet_balance_chart import WalletBalanceChart

logger = logging.getLogger(__name__)


class QTProtoWallet(QtWalletBase):
    signal_create_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_close_wallet: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore

    def __init__(
        self,
        protowallet: ProtoWallet,
        config: UserConfig,
        signals: Signals,
        threading_parent: ThreadingManager | None = None,
        tutorial_index: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(
            config=config,
            signals=signals,
            threading_parent=threading_parent,
            tutorial_index=tutorial_index,
            parent=parent,
        )

        (
            self.wallet_descriptor_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab(protowallet)

        self.tabs.setVisible(False)

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

    def create_and_add_settings_tab(self, protowallet: ProtoWallet) -> Tuple[QWidget, DescriptorUI]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=protowallet,
            signals_min=self.signals,
            threading_parent=self,
        )
        self.tabs.addTab(
            wallet_descriptor_ui,
            read_QIcon("preferences.svg"),
            self.tr("Setup wallet"),
        )

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(self.on_apply_setting_changes)
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(self.on_cancel_wallet_creation)
        return wallet_descriptor_ui, wallet_descriptor_ui

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

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        super().close()


class ProgressSignal:
    def __init__(self, signal_settext_balance_label: TypedPyQtSignal[str]) -> None:
        self.signal_settext_balance_label = signal_settext_balance_label

    def update(self, progress: "float", message: "Optional[str]"):
        self.signal_settext_balance_label.emit(f"Syncing wallet: {round(progress)}%  {message}")


class QTWallet(QtWalletBase, BaseSaveableClass):
    VERSION = "0.1.1"
    known_classes = {
        **BaseSaveableClass.known_classes,
        "Wallet": Wallet,
        "Balance": Balance,
    }

    signal_settext_balance_label: TypedPyQtSignal[str] = pyqtSignal(str)  # type: ignore
    signal_on_change_sync_status: TypedPyQtSignal[SyncStatus] = pyqtSignal(SyncStatus)  # type: ignore  # SyncStatus

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
        fx: FX,
        sync_tab: SyncTab | None = None,
        password: str | None = None,
        file_path: str | None = None,
        threading_parent: ThreadingManager | None = None,
        display_balance: Balance | None = None,
        notified_tx_ids: Iterable[str] | None = None,
        tutorial_index: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(
            signals=signals,
            config=config,
            threading_parent=threading_parent,
            tutorial_index=tutorial_index,
            parent=parent,
        )
        self.mempool_data = mempool_data
        self.wallet = self.set_wallet(wallet)
        self.password = password
        self.fx = fx
        self._file_path = file_path
        self.sync_status: SyncStatus = SyncStatus.unknown
        self.timer_sync_retry = QTimer()
        self.timer_sync_regularly = QTimer()
        self.notified_tx_ids = set(notified_tx_ids if notified_tx_ids else [])

        self._last_syncing_start = datetime.datetime.now()
        self._syncing_delay = timedelta(seconds=0)
        self._last_sync_chain_height = 0
        self.display_balance = display_balance if display_balance else Balance()

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

        ########### create tabs
        (
            self.history_tab,
            self.history_list,
            self.wallet_balance_chart,
            self.history_tab_with_toolbar,
        ) = self._create_hist_tab(self.tabs)

        (
            self.address_tab,
            self.address_list,
            self.address_tab_category_editor,
            self.address_list_with_toolbar,
        ) = self._create_addresses_tab(self.tabs)

        self.send_tab, self.uitx_creator = self._create_send_tab(self.tabs)

        (
            self.wallet_descriptor_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab()

        self.sync_tab, self.sync_tab_widget, self.label_syncer = self.add_sync_tab()

        self.create_status_bar(self, self.outer_layout)

        self.update_status_visualization(self.sync_status)
        self.tabs.setCurrentIndex(0)

        self.address_list.signal_tag_dropped.connect(self.set_category)
        self.address_tab_category_editor.list_widget.signal_addresses_dropped.connect(self.set_category)
        self.address_tab_category_editor.delete_button.signal_addresses_dropped.connect(self.set_category)
        self.address_tab_category_editor.list_widget.signal_tag_deleted.connect(self.delete_category)
        self.address_tab_category_editor.list_widget.signal_tag_renamed.connect(self.rename_category)

        self.updateUi()
        self.quick_receive.update_content(UpdateFilter(refresh_all=True))

        #### connect signals
        # only signals, not member of [wallet_signals, wallet_signals] have to be tracked,
        # all others I can connect automatically
        self.signal_tracker.connect(self.signal_on_change_sync_status, self.update_status_visualization)
        self.signal_tracker.connect(self.signals.language_switch, self.updateUi)
        self.signal_tracker.connect(self.signal_on_change_sync_status, self.update_display_balance)
        self.wallet_signals.updated.connect(self.signals.any_wallet_updated.emit)
        self.wallet_signals.export_labels.connect(self.export_labels)
        self.wallet_signals.export_bip329_labels.connect(self.export_bip329_labels)
        self.wallet_signals.import_labels.connect(self.import_labels)
        self.wallet_signals.import_bip329_labels.connect(self.import_bip329_labels)
        self.wallet_signals.import_electrum_wallet_labels.connect(
            self.import_electrum_wallet_labels,
        )

        self._start_sync_retry_timer()
        self._start_sync_regularly_timer()

    def dump(self) -> Dict[str, Any]:
        d = super().dump()

        d["wallet"] = self.wallet.dump()
        d["sync_tab"] = self.sync_tab.dump()
        d["display_balance"] = self.get_display_balance()
        d["tutorial_index"] = self.tutorial_index
        d["notified_tx_ids"] = list(self.notified_tx_ids)

        return d

    @classmethod
    def from_file(
        cls,
        file_path: str,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
        fx: FX,
        password: str | None = None,
        threading_parent: ThreadingManager | None = None,
    ) -> "QTWallet":
        return super()._from_file(
            filename=file_path,
            password=password,
            class_kwargs={
                "Wallet": {"config": config},
                "QTWallet": {
                    "config": config,
                    "signals": signals,
                    "mempool_data": mempool_data,
                    "fx": fx,
                    "file_path": file_path,
                    "threading_parent": threading_parent,
                },
                "SyncTab": {
                    "signals": signals,
                    "network": config.network,
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
            d["display_balance"] = d["wallet"]["data_dump"].get("display_balance", None)
            del d["wallet"]["data_dump"]
            dct = d

        # in the function above, only default json serilizable things can be set in dct
        return json.dumps(dct)

    @classmethod
    def from_dump_migration(cls, dct: Dict[str, Any]) -> Dict[str, Any]:
        "this class should be overwritten in child classes"
        # if version.parse(str(dct["VERSION"])) <= version.parse("0.1.0"):
        #     if "labels" in dct:
        #         # no real migration. Just delete old data
        #         del dct["labels"]

        # now the VERSION is newest, so it can be deleted from the dict
        if "VERSION" in dct:
            del dct["VERSION"]
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

        return cls(**filtered_for_init(dct, cls))

    @property
    def wallet_signals(self) -> WalletSignals:
        return self.signals.wallet_signals[self.wallet.id]

    def updateUi(self) -> None:
        self.tabs.setTabText(self.tabs.indexOf(self.send_tab), self.tr("Send"))
        self.tabs.setTabText(self.tabs.indexOf(self.wallet_descriptor_tab), self.tr("Descriptor"))
        self.tabs.setTabText(self.tabs.indexOf(self.sync_tab_widget), self.tr("Sync && Chat"))
        self.tabs.setTabText(self.tabs.indexOf(self.history_tab), self.tr("History"))
        self.tabs.setTabText(self.tabs.indexOf(self.address_tab), self.tr("Receive"))

    def set_display_balance(self, value: Balance):
        self.display_balance = value

    def get_display_balance(self) -> Balance:
        if self.sync_status == SyncStatus.synced:
            return self.wallet.get_balance()
        else:
            return self.display_balance

    def update_display_balance(self, sync_status: SyncStatus):
        if sync_status == SyncStatus.synced:
            self.set_display_balance(self.wallet.get_balance())

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

    def create_and_add_settings_tab(self) -> Tuple[QWidget, DescriptorUI]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = DescriptorUI(
            protowallet=self.wallet.as_protowallet(),
            signals_min=self.signals,
            wallet=self.wallet,
            threading_parent=self,
        )
        self.tabs.addTab(
            wallet_descriptor_ui,
            read_QIcon("preferences.svg"),
            "",
        )

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(
            self.on_qtwallet_apply_setting_changes
        )
        wallet_descriptor_ui.signal_qtwallet_cancel_setting_changes.connect(self.cancel_setting_changes)
        return wallet_descriptor_ui, wallet_descriptor_ui

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
        if self.wallet.is_essentially_equal(new_wallet):
            Message(self.tr("No changes to apply."))
            return

        # do backup
        filename = self.save_backup()
        if filename:
            Message(self.tr("Backup saved to {filename}").format(filename=filename))
        else:
            Message(self.tr("Backup failed. Aborting Changes."))
            return

        if not question_dialog(
            self.tr("Proceeding will potentially change all wallet addresses. Do you want to proceed?")
        ):
            return

        # i have to close it first, to ensure the wallet is shut down completely
        self.signals.close_qt_wallet.emit(self.wallet.id)

        qt_wallet = QTWallet(
            new_wallet,
            self.config,
            self.signals,
            self.mempool_data,
            self.fx,
            file_path=self.file_path,
            password=self.password,
            threading_parent=self.threading_parent,
            parent=self,
        )

        self.signals.add_qt_wallet.emit(qt_wallet, self._file_path, self.password)

    def add_sync_tab(self) -> Tuple[SyncTab, QWidget, LabelSyncer]:
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"

        icon_path = SyncTab.get_icon_path(enabled=self.sync_tab.enabled())
        self.tabs.addTab(self.sync_tab.main_widget, QIcon(icon_path), "")
        self.sync_tab.main_widget.checkbox.stateChanged.connect(self._set_sync_tab_icon)

        label_syncer = LabelSyncer(self.wallet.labels, self.sync_tab, self.wallet_signals)
        self.sync_tab.finish_init_after_signal_connection()
        return self.sync_tab, self.sync_tab.main_widget, label_syncer

    def _set_sync_tab_icon(self, enabled: bool):
        index = self.tabs.indexOf(self.sync_tab.main_widget)
        if index < 0:
            return
        icon_path = SyncTab.get_icon_path(enabled=enabled)
        self.tabs.setTabIcon(index, QIcon(icon_path))

    def save_backup(self) -> str:
        """_summary_

        Returns:
            str: filename
        """
        filename = os.path.join(
            self.config.wallet_dir, "backups", filename_clean(f"{self.wallet.id}-backup-{0}")
        )
        max_number_backups = 100000
        for i in range(max_number_backups):
            filename = os.path.join(
                self.config.wallet_dir, "backups", filename_clean(f"{self.wallet.id}-backup-{i}")
            )
            if not os.path.exists(filename):
                break

        # save the tutorial step into the wallet
        if self.wizard:
            self.tutorial_index = self.wizard.current_index() if not self.wizard.isHidden() else None

        self.wallet.save(
            filename,
            password=self.password,
        )
        return filename

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
                if not self._file_path and question_dialog(
                    text=self.tr("Are you SURE you don't want save the wallet {id}?").format(
                        id=self.wallet.id
                    ),
                    title=self.tr("Delete wallet"),
                ):
                    logger.info(self.tr("No file selected"))
                    return None

        # if it is the first time saving, then the user can set a password
        if not os.path.isfile(self.file_path):
            self.password = PasswordCreation().get_password()

        super().save(
            self.file_path,
            password=self.password,
        )
        logger.info(f"wallet {self.wallet.id} saved")
        return self.file_path

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

    def get_delta_txs(self, access_marker="notifications") -> DeltaCacheListTransactions:
        delta_txs = self.wallet.bdkwallet.list_delta_transactions(access_marker=access_marker)
        return delta_txs

    def format_txs(self, txs: List[bdk.TransactionDetails]) -> str:
        return "\n".join(
            [
                self.tr("  {amount} in {shortid}").format(
                    amount=Satoshis(tx.received - tx.sent, self.config.network).str_as_change(unit=True),
                    shortid=short_tx_id(tx.txid),
                )
                for tx in txs
            ]
        )

    def hanlde_removed_txs(self, removed_txs: List[bdk.TransactionDetails]) -> None:
        if not removed_txs:
            return

        # if transactions were removed (reorg or other), then recalculate everything
        message_content = self.tr(
            "The transactions \n{txs}\n in wallet '{wallet}' were removed from the history!!!"
        ).format(txs=self.format_txs(removed_txs), wallet=self.wallet.id)
        Message(
            message_content,
            no_show=True,
        ).emit_with(self.signals.notification)
        if question_dialog(
            message_content + "\n" + self.tr("Do you want to save a copy of these transactions?")
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

        self.notified_tx_ids -= set([tx.txid for tx in removed_txs])
        # all the lists must be updated
        self.refresh_caches_and_ui_lists(force_ui_refresh=True)

    def handle_appended_txs(self, appended_txs: List[bdk.TransactionDetails]) -> None:
        if not appended_txs:
            return

        appended_txs = [tx for tx in appended_txs if tx.txid not in self.notified_tx_ids]

        if len(appended_txs) == 1:
            Message(
                self.tr("New transaction in wallet '{wallet}':\n{txs}").format(
                    txs=self.format_txs(appended_txs), wallet=self.wallet.id
                ),
                no_show=True,
            ).emit_with(self.signals.notification)
        elif len(appended_txs) > 1:
            Message(
                self.tr("{number} new transactions in wallet '{wallet}':\n{txs}").format(
                    number=len(appended_txs),
                    txs=self.format_txs(appended_txs),
                    wallet=self.wallet.id,
                ),
                no_show=True,
            ).emit_with(self.signals.notification)

        self.notified_tx_ids = self.notified_tx_ids.union([tx.txid for tx in appended_txs])

    def handle_delta_txs(self, delta_txs: DeltaCacheListTransactions) -> None:
        self.hanlde_removed_txs(delta_txs.removed)
        self.handle_appended_txs(delta_txs.appended)

    def refresh_caches_and_ui_lists(
        self,
        enable_threading=ENABLE_THREADING,
        force_ui_refresh=True,
        chain_height_advanced=False,
        clear_cache=True,
    ) -> None:
        # before the wallet UI updates, we have to refresh the wallet caches to make the UI update faster
        logger.debug("refresh_caches_and_ui_lists")
        if clear_cache:
            self.wallet.clear_cache()

        def do() -> Any:
            self.wallet.fill_commonly_used_caches()

        def on_done(result) -> None:
            delta_txs = self.get_delta_txs()
            change_dict = delta_txs.was_changed()
            formatted_dict = {k: [tx.txid for tx in v] for k, v in change_dict.items()}
            logger.debug(f"change_dict={formatted_dict}")
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

        def on_success(result) -> None:
            # now do the UI
            logger.debug("on_success refresh ui")

        def on_error(packed_error_info) -> None:
            custom_exception_handler(*packed_error_info)

        self.append_thread(
            TaskThread(enable_threading=enable_threading).add_and_start(do, on_success, on_done, on_error)
        )

    def _create_send_tab(self, tabs: QTabWidget) -> Tuple[SearchableTab, UITx_Creator]:
        utxo_list = UTXOList(
            self.config,
            self.signals,
            outpoints=[],
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
                UTXOList.Columns.WALLET_ID,
            ],
            sort_column=UTXOList.Columns.CATEGORY,
            sort_order=Qt.SortOrder.AscendingOrder,
        )

        toolbar_list = UtxoListWithToolbar(utxo_list, self.config, parent=tabs)

        uitx_creator = UITx_Creator(
            wallet=self.wallet,
            mempool_data=self.mempool_data,
            fx=self.fx,
            categories=self.wallet.labels.categories,
            widget_utxo_with_toolbar=toolbar_list,
            utxo_list=utxo_list,
            config=self.config,
            signals=self.signals,
            parent=self,
        )
        self.tabs.addTab(uitx_creator, read_QIcon("send.svg"), "")

        uitx_creator.signal_create_tx.connect(self.create_psbt)

        return uitx_creator, uitx_creator

    def create_psbt(self, txinfos: TxUiInfos) -> None:

        def do() -> Union[TxBuilderInfos, Exception]:
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
                            bdk.Address.from_script(output.script_pubkey, self.wallet.network).as_string()
                            for output in builder_infos.builder_result.psbt.extract_tx().output()
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

        self.append_thread(TaskThread().add_and_start(do, on_success, on_done, on_error))

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
            self.wallet_signals.get_display_balance,
            self.get_display_balance,
            slot_name=self.wallet.id,
        )
        self.signal_tracker.connect(
            self.wallet_signals.get_category_infos,
            self.get_category_infos,
            slot_name=self.wallet.id,
        )
        return wallet

    def rename_category(self, old_category: str, new_category: str) -> None:
        affected_keys = self.wallet.labels.rename_category(old_category, new_category)
        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=affected_keys,
                categories=([old_category]),
                txids=affected_keys,
                reason=UpdateFilterReason.CategoryRenamed,
            )
        )

    def delete_category(self, category: str) -> None:
        # Show dialog and get input
        text, ok = QInputDialog.getText(
            self,
            self.tr("Rename or merge categories"),
            self.tr("Choose a new name, or an existing name for merging:"),
            text=category,
        )
        if ok and text:
            new_category = text
        else:
            # just rename it with the same name
            new_category = category

        affected_keys = self.wallet.labels.rename_category(category, new_category)
        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=affected_keys,
                categories=([category]),
                txids=affected_keys,
                reason=UpdateFilterReason.CategoryRenamed,
            )
        )

    def set_category(self, address_drag_info: AddressDragInfo) -> None:
        for address in address_drag_info.addresses:
            for category in address_drag_info.tags:
                self.wallet.labels.set_addr_category(address, category, timestamp="now")

        txids: Set[str] = set()
        for address in address_drag_info.addresses:
            txids = txids.union(self.wallet.get_involved_txids(address))

        self.wallet_signals.updated.emit(
            UpdateFilter(
                addresses=address_drag_info.addresses,
                categories=address_drag_info.tags,
                txids=txids,
                reason=UpdateFilterReason.UserInput,
            )
        )

    def create_status_bar(self, tab: QWidget, outer_layout) -> None:
        pass

    def update_status_visualization(self, sync_status: SyncStatus) -> None:
        if not self.wallet:
            return

        icon_text = ""
        tooltip = ""
        if sync_status == SyncStatus.syncing:
            icon_text = "status_waiting.svg"
            self.history_tab_with_toolbar.sync_button.set_icon_is_syncing()
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
            self.history_tab_with_toolbar.sync_button.set_icon_allow_refresh()
        else:
            icon_text = "status_disconnected.svg"
            tooltip = self.tr("Disconnected from {server}").format(
                server=self.config.network_config.description_short()
            )
            self.history_tab_with_toolbar.sync_button.set_icon_allow_refresh()

        self.signals.signal_set_tab_properties.emit(self.wallet.id, icon_text, tooltip)

    def create_list_tab(
        self,
        treeview_with_toolbar: TreeViewWithToolbar,
        tabs: QTabWidget,
        horizontal_widgets_left: Optional[List[QWidget]] = None,
        horizontal_widgets_right: Optional[List[QWidget]] = None,
    ) -> SearchableTab:
        # create a horizontal widget and layout
        searchable_tab = SearchableTab(parent=tabs)
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
        self, tabs: QTabWidget
    ) -> Tuple[SearchableTab, HistList, WalletBalanceChart, HistListWithToolbar]:
        tab = SearchableTab(parent=tabs)
        tab.setObjectName(f"created as HistList tab containrer")
        tab_layout = QHBoxLayout(tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        splitter1 = QSplitter()  # horizontal splitter by default
        tab_layout.addWidget(splitter1)

        l = HistList(
            fx=self.fx,
            config=self.config,
            signals=self.signals,
            wallet_id=self.wallet.id,
            hidden_columns=[
                HistList.Columns.WALLET_ID,
                HistList.Columns.BALANCE,
                HistList.Columns.TXID,
            ],
            mempool_data=self.mempool_data,
        )
        treeview_with_toolbar = HistListWithToolbar(l, self.config, parent=tabs)

        list_widget = self.create_list_tab(treeview_with_toolbar, tabs)
        splitter1.addWidget(list_widget)
        tab.searchable_list = l

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setContentsMargins(0, 0, 0, 0)

        self.quick_receive: BitcoinQuickReceive = BitcoinQuickReceive(
            self.wallet_signals, self.wallet, parent=right_widget, signals_min=self.signals
        )
        right_widget_layout.addWidget(self.quick_receive)

        wallet_balance_chart = WalletBalanceChart(
            self.wallet, wallet_signals=self.wallet_signals, parent=right_widget
        )
        right_widget_layout.addWidget(wallet_balance_chart)

        splitter1.addWidget(right_widget)

        tabs.insertTab(
            2,
            tab,
            read_QIcon("history.svg"),
            "",
        )

        splitter1.setSizes([1, 1])
        return tab, l, wallet_balance_chart, treeview_with_toolbar

    def get_category_infos(self) -> List[CategoryInfo]:

        category_python_utxo_dict = self.wallet.get_category_python_utxo_dict()

        return [
            CategoryInfo(
                category=category,
                text_click_new_address=self.tr("Click for new address"),
                text_balance=self.tr("{num_inputs} Inputs: {inputs}").format(
                    num_inputs=len(category_python_utxo_dict.get(category, [])),
                    inputs=Satoshis(
                        python_utxo_balance(category_python_utxo_dict.get(category, [])), self.wallet.network
                    ).str_with_unit(),
                ),
            )
            for category in self.wallet.labels.categories
        ]

    def _create_addresses_tab(
        self, tabs: QTabWidget
    ) -> Tuple[SearchableTab, AddressList, CategoryEditor, AddressListWithToolbar]:
        l = AddressList(
            fx=self.fx,
            config=self.config,
            wallet=self.wallet,
            wallet_signals=self.wallet_signals,
            signals=self.signals,
        )
        treeview_with_toolbar = AddressListWithToolbar(l, self.config, parent=tabs, signals=self.signals)

        address_tab_category_editor = CategoryEditor(
            self.wallet_signals, subtext_type=SubtextType.click_new_address
        )
        address_tab_category_editor.signal_category_added.connect(self.on_add_category)

        address_tab_category_editor.list_widget.signal_tag_clicked.connect(self.create_new_address)

        address_tab_category_editor.setMaximumWidth(150)
        tab = self.create_list_tab(
            treeview_with_toolbar, tabs, horizontal_widgets_left=[address_tab_category_editor]
        )

        tabs.insertTab(1, tab, read_QIcon("receive.svg"), "")
        return tab, l, address_tab_category_editor, treeview_with_toolbar

    def create_new_address(self, category) -> None:
        self.address_list.get_address(force_new=True, category=category)

    def on_add_category(self, category: str) -> None:
        self.wallet.labels.add_category(category)

    def set_sync_status(self, new: SyncStatus) -> None:
        self.sync_status = new
        logger.info(f"{self.wallet.id} set_sync_status {new}")
        self.signal_on_change_sync_status.emit(new)
        QApplication.processEvents()

    def _sync(self) -> Any:
        self.wallet.sync(progress=ProgressSignal(self.signal_settext_balance_label))

    def _sync_on_done(self, result) -> None:
        self._syncing_delay = datetime.datetime.now() - self._last_syncing_start
        interval_timer_sync_regularly = max(int(self._syncing_delay.total_seconds() * 200), 30)  # in sec
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
        self.refresh_caches_and_ui_lists(enable_threading=False, force_ui_refresh=False, clear_cache=False)

        logger.info(f"Start syncing wallet {self.wallet.id}")
        self.set_sync_status(SyncStatus.syncing)

        self._last_syncing_start = datetime.datetime.now()
        self.append_thread(
            TaskThread().add_and_start(
                self._sync, self._sync_on_success, self._sync_on_done, self._sync_on_error
            )
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

        force_overwrite = bool(
            question_dialog(
                "Do you want to overwrite all labels?",
                buttons=QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes,
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

    def close(self) -> bool:
        # crucial is to explicitly close everything that has a wallet attached
        self.stop_sync_timer()
        self.address_tab_category_editor.close()
        self.quick_receive.close()
        self.address_tab.close()
        self.address_list_with_toolbar.close()
        self.history_tab.close()
        self.history_tab.searchable_list = None
        self.history_tab_with_toolbar.close()
        self.wallet_descriptor_tab.close()
        self.wallet_descriptor_ui.close()
        self.send_tab.close()
        self.uitx_creator.close()
        self.wallet_balance_chart.close()
        self.label_syncer.send_all_labels_to_myself()
        self.sync_tab.unsubscribe_all()
        self.sync_tab.nostr_sync.stop()
        self.tabs.clear()
        self.tabs.close()
        self.wallet.close()
        SignalTools.disconnect_all_signals_from(self.wallet_signals)
        self.setParent(None)  #  THIS made it that the qt wallet is destroyed
        return super().close()
