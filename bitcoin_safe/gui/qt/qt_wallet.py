import enum
import logging
from abc import abstractmethod
from typing import Callable, List, Optional, Set, Tuple

from bitcoin_safe.gui.qt.my_treeview import SearchableTab, _create_list_with_toolbar

from ...config import UserConfig
from ...mempool import MempoolData
from .bitcoin_quick_receive import BitcoinQuickReceive

logger = logging.getLogger(__name__)

import os

import bdkpython as bdk
from PySide2.QtCore import QObject, QSize, Signal
from PySide2.QtGui import QCursor, QIcon, Qt
from PySide2.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import _
from ...signals import SignalFunction, Signals, UpdateFilter
from ...tx import TxUiInfos
from ...util import NoThread, Satoshis
from ...wallet import ProtoWallet, Wallet, filename_clean, get_wallets
from .address_list import AddressList
from .category_list import CategoryEditor
from .dialogs import PasswordCreation, PasswordQuestion, question_dialog
from .hist_list import HistList
from .plot import WalletBalanceChart
from .taglist import AddressDragInfo
from .ui_descriptor import WalletDescriptorUI
from .ui_tx import UITX_Creator
from .util import (
    Message,
    TaskThread,
    add_tab_to_tabs,
    custom_exception_handler,
    read_QIcon,
    save_file_dialog,
)
from .utxo_list import UTXOList


class StatusBarButton(QToolButton):
    # note: this class has a custom stylesheet applied in stylesheet_patcher.py
    def __init__(self, icon, tooltip, func, sb_height):
        QToolButton.__init__(self)
        self.setText("")
        self.setIcon(icon)
        self.setToolTip(tooltip)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setAutoRaise(True)
        size = max(25, round(0.9 * sb_height))
        self.setMaximumWidth(size)
        self.clicked.connect(self.onPress)
        self.func = func
        self.setIconSize(QSize(size, size))
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def onPress(self, checked=False):
        """Drops the unwanted PySide2 "checked" argument."""
        self.func()

    def keyPressEvent(self, e):
        if e.key() in [Qt.Key_Return, Qt.Key_Enter]:
            self.func()


class FX:
    def __init__(self):
        pass

    def is_enabled(self):
        return False

    def can_have_history(self):
        return False

    def has_history(self):
        return False


class SignalCarryingObject(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._connected_signals: List[Tuple[SignalFunction, Callable]] = []

    def connect_signal(self, signal, f, **kwargs):
        signal.connect(f, **kwargs)
        self._connected_signals.append((signal, f))

    def disconnect_signals(self):
        for signal, f in self._connected_signals:
            signal.disconnect(f)


class QtWalletBase(SignalCarryingObject):
    wallet_steps: QWidget
    wallet_descriptor_tab: QWidget

    def __init__(self, config: UserConfig, signals: Signals, wallet_id: str):
        super().__init__()
        self.wallet_id = wallet_id
        self.config = config
        self.signals = signals

        self._create_wallet_tab_and_subtabs()

    def _create_wallet_tab_and_subtabs(self):
        "Create a tab, and layout, that other UI components can fit inside"
        # create UI part
        self.tab = QWidget()
        self.tab.setObjectName(self.wallet_id)

        self.outer_layout = QVBoxLayout(self.tab)

        # add the tab_widget for  history, utx, send tabs
        self.tabs = QTabWidget(self.tab)
        self.outer_layout.addWidget(self.tabs)

    @abstractmethod
    def get_mn_tuple(self) -> Tuple[int, int]:
        pass

    @abstractmethod
    def get_keystore_labels(self) -> List[str]:
        pass


class QTProtoWallet(QtWalletBase):
    signal_create_wallet = Signal()
    signal_close_wallet = Signal()

    def __init__(
        self,
        wallet_id: str,
        protowallet: ProtoWallet,
        config: UserConfig,
        signals: Signals,
    ):

        super().__init__(wallet_id=wallet_id, config=config, signals=signals)

        self.protowallet = protowallet

        self.create_protowallet_tab()
        self.tabs.setVisible(False)

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.protowallet.threshold, len(self.protowallet.keystores)

    def get_keystore_labels(self) -> List[str]:
        return [self.protowallet.signer_name(i) for i in range(len(self.protowallet.keystores))]

    def create_protowallet_tab(self):
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        (
            self.wallet_descriptor_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab()

    def create_and_add_settings_tab(self):
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = WalletDescriptorUI(protowallet=self.protowallet)
        add_tab_to_tabs(
            self.tabs,
            wallet_descriptor_ui.tab,
            read_QIcon("preferences.png"),
            "Setup wallet",
            "setup wallet",
        )

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(self.on_apply_setting_changes)
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(self.signal_close_wallet.emit)
        return wallet_descriptor_ui.tab, wallet_descriptor_ui

    def on_apply_setting_changes(self):

        self.wallet_descriptor_ui.set_protowallet_from_keystore_ui()

        self.signal_create_wallet.emit()


class SyncStatus(enum.Enum):
    unknown = enum.auto()
    unsynced = enum.auto()
    syncing = enum.auto()
    synced = enum.auto()
    error = enum.auto()


class QTWallet(QtWalletBase):
    signal_settext_balance_label = Signal(str)
    signal_close_wallet = Signal()
    signal_on_change_sync_status = Signal(SyncStatus)  # SyncStatus

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
        set_tab_widget_icon: Optional[Callable[[QWidget, QIcon], None]] = None,
    ):
        super().__init__(wallet_id=wallet.id, signals=signals, config=config)

        self.mempool_data = mempool_data
        self.wallet = self.set_wallet(wallet)
        self.password: Optional[str] = None
        self.set_tab_widget_icon = set_tab_widget_icon
        self.wallet_descriptor_tab = None
        self.fx = FX()
        self.ui_password_question = PasswordQuestion()
        self._file_path: Optional[str] = None
        self.sync_status: SyncStatus = SyncStatus.unknown

        ########### create tabs
        self.history_tab, self.history_list, self.balance_plot = self._create_hist_tab(self.tabs)

        (
            self.addresses_tab,
            self.address_list,
            self.address_list_tags,
        ) = self._create_addresses_tab(self.tabs)

        self.send_tab, self.uitx_creator = self._create_send_tab(self.tabs)
        # self.utxo_tab, self.utxo_list = self._create_utxo_tab(self.tabs)

        (
            self.wallet_descriptor_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab()

        self.create_status_bar(self.tab, self.outer_layout)

        self.update_status_visualization(self.sync_status)
        self.tabs.setCurrentIndex(0)

        self.address_list.signal_tag_dropped.connect(self.set_category)
        self.address_list_tags.list_widget.signal_addresses_dropped.connect(self.set_category)
        self.address_list_tags.delete_button.signal_addresses_dropped.connect(self.set_category)
        self.address_list_tags.list_widget.signal_tag_deleted.connect(self.delete_category)
        self.address_list_tags.list_widget.signal_tag_renamed.connect(
            lambda old, new: self.rename_category(old, new)
        )

        #### connect signals
        self.quick_receive.update()
        self.signal_on_change_sync_status.connect(self.update_status_visualization)

    def get_mn_tuple(self) -> Tuple[int, int]:
        return self.wallet.get_mn_tuple()

    def get_keystore_labels(self) -> List[str]:
        return [keystore.label for keystore in self.wallet.keystores]

    @property
    def file_path(self):
        return self._file_path if self._file_path else filename_clean(self.wallet.id)

    @file_path.setter
    def file_path(self, value: Optional[str]):
        self._file_path = value

    def apply_setting_changes(self):
        self.wallet_descriptor_ui.set_protowallet_from_keystore_ui()
        old_wallet = self.wallet
        new_wallet = Wallet.from_protowallet(
            self.wallet_descriptor_ui.protowallet, old_wallet.id, self.config
        )
        # compare if something change
        if old_wallet.is_essentially_equal(new_wallet):
            Message("No changes to apply.")
            return

        # ask if backup
        if question_dialog(text=f"Do you want to backup the old wallet?", title="Backup old wallet"):
            filename = self.save_backup()
            if filename:
                Message(f"Backup saved to {filename}")
            else:
                Message(f"Backup failed. Aborting Changes.")
                return

        # replace old wallet & save
        self.wallet = new_wallet
        self.save()

        # update wallet
        self.wallet.clear_cache(clear_always_keep=True)
        self.sync()

    def create_and_add_settings_tab(self):
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = WalletDescriptorUI(
            protowallet=self.wallet.as_protowallet(), get_wallet=lambda: self.wallet
        )
        add_tab_to_tabs(
            self.tabs,
            wallet_descriptor_ui.tab,
            read_QIcon("preferences.png"),
            "Descriptor",
            "descriptor",
        )

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(self.apply_setting_changes)
        wallet_descriptor_ui.signal_qtwallet_cancel_setting_changes.connect(self.cancel_setting_changes)
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(self.signal_close_wallet.emit)
        return wallet_descriptor_ui.tab, wallet_descriptor_ui

    def __repr__(self) -> str:
        return f"QTWallet({self.__dict__})"

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
        if self.wallet_steps:
            self.wallet.tutorial_step = (
                self.wallet_steps.step_bar.current_step if not self.wallet_steps.isHidden() else None
            )

        self.wallet.save(
            filename,
            password=self.password,
        )
        return filename

    def save(self):
        if not self._file_path:
            if not os.path.exists(self.config.wallet_dir):
                os.makedirs(self.config.wallet_dir, exist_ok=True)

            # not saving a wallet is dangerous. Therefore I ensure the user has ample
            # opportunity to set a filename
            while not self._file_path:
                self._file_path, _ = QFileDialog.getSaveFileName(
                    self.parent(),
                    "Export labels",
                    f"{os.path.join(self.config.wallet_dir, filename_clean(self.wallet.id))}",
                    "All Files (*);;Wallet Files (*.wallet)",
                )
                if not self._file_path and question_dialog(
                    text=f"Are you SURE you want to delete the wallet {self.wallet.id}",
                    title="Delete wallet",
                ):
                    logger.debug("No file selected")
                    return

        # if it is the first time saving, then the user can set a password
        if not os.path.isfile(self.file_path):
            self.password = PasswordCreation().get_password()

        # save the tutorial step into the wallet
        if self.wallet_steps:
            self.wallet.tutorial_step = (
                self.wallet_steps.step_bar.current_step if not self.wallet_steps.isHidden() else None
            )

        self.wallet.save(
            self.file_path,
            password=self.password,
        )

    def cancel_setting_changes(self):
        self.wallet_descriptor_ui.protowallet = self.wallet.as_protowallet()
        self.wallet_descriptor_ui.set_all_ui_from_protowallet()

    def refresh_caches_and_ui_lists(self):
        # before the wallet UI updates, we have to refresh the wallet caches to make the UI update faster
        logger.debug("refresh_caches_and_ui_lists")
        self.wallet.clear_cache()

        def do():
            self.wallet.fill_commonly_used_caches()

        def on_done(result):
            # now do the UI
            logger.debug("start refresh ui")

            # self.address_list.update()
            # self.address_list_tags.update()
            self.signals.category_updated.emit(UpdateFilter(refresh_all=True))
            self.signals.utxos_updated.emit(UpdateFilter(refresh_all=True))
            # self.history_list.update()

        def on_error(packed_error_info):
            custom_exception_handler(*packed_error_info)

        TaskThread(self).add_and_start(do, None, on_done, on_error)

    def _get_sub_texts_for_uitx(self):
        category_python_utxo_dict = self.wallet.get_category_utxo_dict()

        def sum_value(category):
            python_utxos = category_python_utxo_dict.get(category)
            if not python_utxos:
                return 0
            return sum([python_utxo.txout.value for python_utxo in python_utxos])

        return [
            f"{len(category_python_utxo_dict.get(category, []))} Inputs: {Satoshis(sum_value(category), self.wallet.network).str_with_unit()}"
            for category in self.wallet.labels.categories
        ]

    def _create_send_tab(self, tabs: QTabWidget):
        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=lambda: [],  # this is filled in uitx_creator
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
                UTXOList.Columns.WALLET_ID,
            ],
        )

        widget_utxo_with_toolbar = _create_list_with_toolbar(utxo_list, tabs, self.config)

        uitx_creator = UITX_Creator(
            self.wallet,
            self.mempool_data,
            self.wallet.labels.categories,
            widget_utxo_with_toolbar,
            utxo_list,
            self.config,
            self.signals,
            self._get_sub_texts_for_uitx,
            enable_opportunistic_merging_fee_rate=self.config.enable_opportunistic_merging_fee_rate,
        )
        add_tab_to_tabs(
            self.tabs,
            uitx_creator.main_widget,
            read_QIcon("send.svg"),
            "Send",
            "send",
        )

        uitx_creator.signal_create_tx.connect(self.create_psbt)

        return uitx_creator.main_widget, uitx_creator

    def create_psbt(self, txinfos: TxUiInfos):
        builder_infos = self.wallet.create_psbt(txinfos)

        # set labels in other wallets  (recipients can be another open wallet)
        for wallet in get_wallets(self.signals):
            wallet.set_output_categories_and_labels(builder_infos)

        update_filter = UpdateFilter(
            addresses=set(
                [
                    bdk.Address.from_script(output.script_pubkey, self.wallet.network).as_string()
                    for output in builder_infos.builder_result.psbt.extract_tx().output()
                ]
            ),
        )
        self.signals.addresses_updated.emit(update_filter)
        self.signals.category_updated.emit(update_filter)
        self.signals.labels_updated.emit(update_filter)
        self.signals.open_tx_like.emit(builder_infos)

        self.uitx_creator.clear_ui()

    def set_wallet(self, wallet: Wallet) -> Wallet:
        self.wallet = wallet

        # for name, signal in self.signals.__dict__.items():
        #     if hasattr(self.wallet, name) and callable(getattr(self.wallet, name)):
        #         signal.connect(getattr(self.wallet, name), name=self.wallet.id)

        self.connect_signal(self.signals.addresses_updated, self.wallet.on_addresses_updated)

        self.connect_signal(self.signals.get_wallets, lambda: self.wallet, slot_name=self.wallet.id)
        return wallet

    def rename_category(self, old_category: str, new_category: str):
        affected_keys = self.wallet.labels.rename_category(old_category, new_category)
        self.signals.category_updated.emit(
            UpdateFilter(addresses=affected_keys, categories=([old_category]), txids=affected_keys)
        )

    def delete_category(self, category: str):
        affected_keys = self.wallet.labels.delete_category(category)
        self.signals.category_updated.emit(
            UpdateFilter(addresses=affected_keys, categories=([category]), txids=affected_keys)
        )

    def set_category(self, address_drag_info: AddressDragInfo):
        for address in address_drag_info.addresses:
            for category in address_drag_info.tags:
                self.wallet.labels.set_addr_category(address, category)

        txids: Set[str] = set()
        for address in address_drag_info.addresses:
            txids = txids.union(self.wallet.get_address_to_txids(address))

        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=address_drag_info.addresses,
                categories=address_drag_info.tags,
                txids=txids,
            )
        )

    def create_status_bar(self, tab: QWidget, outer_layout):
        pass
        # sb = QStatusBar()
        # self.balance_label = BalanceToolButton()
        # self.balance_label.setText("Loading wallet...")
        # # self.balance_label.clicked.connect(self.show_balance_dialog)
        # sb.addWidget(self.balance_label)
        # self.signal_settext_balance_label.connect(self.balance_label.setText)

        # font_height = QFontMetrics(self.balance_label.font()).height()
        # sb_height = max(35, int(2 * font_height))
        # sb.setFixedHeight(sb_height)

        # # remove border of all items in status bar
        # tab.setStyleSheet("QStatusBar::item { border: 0px;} ")

        # sb.addPermanentWidget(self.search_box)

        # self.update_check_button = QPushButton("")
        # self.update_check_button.setFlat(True)
        # self.update_check_button.setCursor(QCursor(Qt.PointingHandCursor))
        # self.update_check_button.setIcon(read_QIcon("update.png"))
        # self.update_check_button.hide()
        # sb.addPermanentWidget(self.update_check_button)

        # self.tasks_label = QLabel('')
        # sb.addPermanentWidget(self.tasks_label)

        # self.password_button = StatusBarButton(QIcon(), _("Password"), self.change_password_dialog, sb_height)
        # sb.addPermanentWidget(self.password_button)

        # sb.addPermanentWidget(
        #     StatusBarButton(
        #         read_QIcon("preferences.png"),
        #         _("Preferences"),
        #         self.settings_dialog,
        #         sb_height,
        #     )
        # )
        # self.seed_button = StatusBarButton(read_QIcon("seed.png"), _("Seed"), self.show_seed_dialog, sb_height)
        # sb.addPermanentWidget(self.seed_button)
        # self.lightning_button = StatusBarButton(read_QIcon("lightning.png"), _("Lightning Network"), self.gui_object.show_lightning_dialog, sb_height)
        # sb.addPermanentWidget(self.lightning_button)
        # self.update_lightning_icon()
        # self.status_button = StatusBarButton(
        #     read_QIcon("status_disconnected.png"),
        #     _("Network"),
        #     self.signals.show_network_settings.emit,
        #     sb_height,
        # )
        # sb.addPermanentWidget(self.status_button)
        # # run_hook('create_status_bar', sb)
        # outer_layout.addWidget(sb)

    def toggle_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def update_status_visualization(self, sync_status: SyncStatus):
        if not self.wallet:
            return

        balance_text = ""
        _("Offline")
        icon = read_QIcon("status_disconnected.png")

        if sync_status == SyncStatus.syncing:
            _("Synchronizing...")
            icon = read_QIcon("status_waiting.png")
        elif self.wallet.blockchain and self.wallet.get_height() and sync_status in [SyncStatus.synced]:
            _("Connected")
            (
                confirmed,
                unconfirmed,
                unmatured,
            ) = self.wallet.get_balances_for_piechart()

            balance = confirmed + unconfirmed + unmatured
            balance_text = _("Balance") + f": {balance.str_with_unit()} "
            icon = read_QIcon("status_connected.png")

        if self.set_tab_widget_icon:
            self.set_tab_widget_icon(self.tab, icon)

    def get_tabs(self, tab_widget: QWidget) -> List[QWidget]:
        return [tab_widget.widget(i) for i in range(tab_widget.count())]

    def create_list_tab(
        self,
        l: HistList,
        tabs: QTabWidget,
        horizontal_widgets_left: Optional[List[QWidget]] = None,
        horizontal_widgets_right: Optional[List[QWidget]] = None,
    ) -> SearchableTab:
        # create a horizontal widget and layout
        h = SearchableTab(tabs)
        h.searchable_list = l
        hbox = QHBoxLayout(h)
        h.setLayout(hbox)

        if horizontal_widgets_left:
            for widget in horizontal_widgets_left:
                hbox.addWidget(widget)

        w = _create_list_with_toolbar(l, tabs, self.config)
        hbox.addWidget(w)

        if horizontal_widgets_right:
            for widget in horizontal_widgets_right:
                hbox.addWidget(widget)
        return h

    def _create_hist_tab(self, tabs: QTabWidget):
        tab = SearchableTab(tabs)
        tab_layout = QHBoxLayout(tab)

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
        )
        list_widget = self.create_list_tab(l, tabs)
        splitter1.addWidget(list_widget)
        tab.searchable_list = l

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setContentsMargins(0, 0, 0, 0)

        self.quick_receive: BitcoinQuickReceive = BitcoinQuickReceive(self.signals, self.wallet)
        right_widget_layout.addWidget(self.quick_receive)

        plot = WalletBalanceChart(self.wallet, signals=self.signals)
        right_widget_layout.addWidget(plot)

        splitter1.addWidget(right_widget)

        add_tab_to_tabs(tabs, tab, read_QIcon("history.svg"), "History", "history", position=2)

        splitter1.setSizes([1, 1])
        return tab, l, plot

    def _subtexts_for_categories(self):
        return ["Click for new address" for category in self.wallet.labels.categories]

        d = {}
        for address in self.wallet.get_addresses():
            category = self.wallet.labels.get_category(address)
            if category not in d:
                d[category] = []

            d[category].append(address)

        return [f"{len(d.get(category, []))} Addresses" for category in self.wallet.labels.categories]

    def _create_addresses_tab(self, tabs: QTabWidget) -> Tuple[SearchableTab, AddressList, CategoryEditor]:
        l = AddressList(self.fx, self.config, self.wallet, self.signals)

        tags = CategoryEditor(
            self.wallet.labels.categories,
            self.signals,
            get_sub_texts=self._subtexts_for_categories,
        )

        def create_new_address(category):
            self.address_list.get_address(force_new=True, category=category)

        tags.list_widget.signal_tag_clicked.connect(create_new_address)

        tags.setMaximumWidth(150)
        tab = self.create_list_tab(l, tabs, horizontal_widgets_left=[tags])

        add_tab_to_tabs(
            tabs,
            tab,
            read_QIcon("receive.svg"),
            "Receive",
            "receive",
            position=1,
        )
        return tab, l, tags

    def set_sync_status(self, new: SyncStatus):
        self.sync_status = new
        logger.debug(f"{self.wallet.id} set_sync_status {new}")
        self.signal_on_change_sync_status.emit(new)

    def sync(self):
        def progress_function_threadsafe(progress: float, message: str):
            self.signal_settext_balance_label.emit(f"Syncing wallet: {round(progress)}%  {message}")

        def do():
            self.wallet.sync(progress_function_threadsafe=progress_function_threadsafe)

        def on_done(result):
            logger.debug("start updating lists")
            # self.wallet.clear_cache()
            self.refresh_caches_and_ui_lists()
            # self.update_tabs()
            logger.debug("finished updating lists")

        def on_error(packed_error_info):
            self.set_sync_status(SyncStatus.error)
            custom_exception_handler(*packed_error_info)

        def on_success(result):
            self.set_sync_status(SyncStatus.synced)
            logger.debug(f"{self.wallet.id} success syncing wallet {self.wallet.id}")

        self.set_sync_status(SyncStatus.syncing)
        NoThread(self).add_and_start(do, on_success, on_done, on_error)

    def export_wallet_for_coldcard(self):
        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=f"descriptor_{self.wallet.id}.txt",
        )
        if not filename:
            return

        text = f"""# Coldcard descriptor export of wallet {self.wallet.id}\n{self.wallet.multipath_descriptor.bdk_descriptors[0].as_string() }
        """
        with open(filename, "w") as file:
            file.write(text)
