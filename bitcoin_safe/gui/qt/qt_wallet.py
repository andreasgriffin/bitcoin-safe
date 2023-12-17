import enum
import logging
from unittest import signals

from matplotlib import category
from matplotlib.pyplot import cla
from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.debug_widget import generate_debug_class
from bitcoin_safe.gui.qt.mytabwidget import ExtendedTabWidget
from bitcoin_safe.gui.qt.qr_components.quick_receive import QuickReceive, ReceiveGroup
from bitcoin_safe.gui.qt.step_progress_bar import StepProgressContainer
from bitcoin_safe.gui.qt.taglist.main import hash_color
from bitcoin_safe.gui.qt.tutorial import WalletSteps
from bitcoin_safe.mempool import MempoolData
from .bitcoin_quick_receive import BitcoinQuickReceive

logger = logging.getLogger(__name__)

from bitcoin_safe.wallet import ProtoWallet, Wallet, filename_clean, unique_txs
from .util import (
    ShowCopyTextEdit,
    SearchableTab,
    custom_exception_handler,
    exception_message,
    read_QIcon,
)
from typing import List
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from .balance_dialog import BalanceToolButton
from .balance_dialog import (
    COLOR_FROZEN,
    COLOR_CONFIRMED,
    COLOR_FROZEN_LIGHTNING,
    COLOR_LIGHTNING,
    COLOR_UNCONFIRMED,
    COLOR_UNMATURED,
)
from .hist_list import HistList
from .address_list import AddressList
from .utxo_list import UTXOList
from .util import add_tab_to_tabs, Message
from .taglist import AddressDragInfo
from .ui_tx import UITX_Creator, UITx_Viewer

from ...util import NoThread, Satoshis
from ...signals import Signals, UpdateFilter
from ...i18n import _
from .ui_descriptor import WalletDescriptorUI
from .dialogs import PasswordQuestion, PasswordCreation, WalletIdDialog, question_dialog
from .category_list import CategoryEditor
from ...tx import TxUiInfos
import bdkpython as bdk
import os
from .plot import WalletBalanceChart
from .util import TaskThread
import numpy as np


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
        """Drops the unwanted PySide2 "checked" argument"""
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
        self._connected_signals = []

    def connect_signal(self, signal, f, **kwargs):
        signal.connect(f, **kwargs)
        self._connected_signals.append((signal, f))

    def disconnect_signals(self):
        for signal, f in self._connected_signals:
            signal.disconnect(f)


class WalletTab(SignalCarryingObject):
    def __init__(self, wallet_id: str):
        super().__init__()
        self.wallet_id = wallet_id

        self._create_wallet_tab_and_subtabs()

    def _create_wallet_tab_and_subtabs(self):
        "Create a tab, and layout, that other UI components can fit inside"
        # create UI part
        self.tab = QWidget()
        self.tab.setObjectName(self.wallet_id)

        self.outer_layout = QVBoxLayout(self.tab)

        # add the tab_widget for  history, utx, send tabs
        self.tabs = ExtendedTabWidget(self.tab)
        self.outer_layout.addWidget(self.tabs)


class QTProtoWallet(WalletTab):
    signal_create_wallet = Signal()
    signal_close_wallet = Signal()

    def __init__(
        self,
        wallet_id: str,
        protowallet: ProtoWallet,
        config: UserConfig,
        signals: Signals,
    ):
        if wallet_id is None:
            dialog = WalletIdDialog(config.wallet_dir)
            if dialog.exec_() == QDialog.Accepted:
                wallet_id = dialog.name_input.text()
                print(f"Creating wallet: {wallet_id}")

        super().__init__(wallet_id=wallet_id)

        self.protowallet = protowallet
        self.config = config
        self.signals = signals

        self.create_protowallet_tab()
        self.tabs.setVisible(False)

        self.step_progress_container = WalletSteps(
            protowallet=protowallet,
            wallet_tabs=self.tabs,
            signal_create_wallet=self.signal_create_wallet,
        )
        self.outer_layout.insertWidget(0, self.step_progress_container)

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

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(
            self.on_apply_setting_changes
        )
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(
            self.signal_close_wallet.emit
        )
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


class QTWallet(WalletTab):
    signal_settext_balance_label = Signal(str)
    signal_close_wallet = Signal()
    signal_on_change_sync_status = Signal(SyncStatus)  # SyncStatus

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
        set_tab_widget_icon=None,
    ):
        super().__init__(wallet_id=wallet.id)

        self.signals = signals
        self.mempool_data = mempool_data
        self.set_wallet(wallet)
        self.password = None
        self.set_tab_widget_icon = set_tab_widget_icon
        self.wallet_descriptor_tab = None
        self.config = config
        self.fx = FX()
        self.ui_password_question = PasswordQuestion()
        self._file_path = None
        self.sync_status: SyncStatus = SyncStatus.unknown

        self.history_tab, self.history_list = None, None
        self.addresses_tab, self.address_list, self.address_list_tags = None, None, None
        self.utxo_tab, self.utxo_list = None, None
        self.send_tab = None

        self.create_wallet_tabs()
        self.quick_receive.update()
        self.signal_on_change_sync_status.connect(self.update_status_visualization)

    @property
    def file_path(self):
        return self._file_path if self._file_path else filename_clean(self.wallet.id)

    @file_path.setter
    def file_path(self, value):
        self._file_path = value

    def apply_setting_changes(self):
        self.wallet_descriptor_ui.set_protowallet_from_keystore_ui()
        self.wallet = Wallet.from_protowallet(
            self.wallet_descriptor_ui.protowallet, self.wallet.id, self.config
        )
        self.wallet.clear_cache(include_always_keep=True)
        self.sync()

    def create_and_add_settings_tab(self):
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        wallet_descriptor_ui = WalletDescriptorUI(wallet=self.wallet)
        add_tab_to_tabs(
            self.tabs,
            wallet_descriptor_ui.tab,
            read_QIcon("preferences.png"),
            "Descriptor",
            "descriptor",
        )

        wallet_descriptor_ui.signal_qtwallet_apply_setting_changes.connect(
            self.apply_setting_changes
        )
        wallet_descriptor_ui.signal_qtwallet_cancel_setting_changes.connect(
            self.cancel_setting_changes
        )
        wallet_descriptor_ui.signal_qtwallet_cancel_wallet_creation.connect(
            self.signal_close_wallet.emit
        )
        return wallet_descriptor_ui.tab, wallet_descriptor_ui

    def __repr__(self) -> str:
        return f"QTWallet({self.__dict__})"

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
                    no_button_text="Select filename",
                    yes_button_text="Delete wallet",
                ):
                    logger.debug("No file selected")
                    return

        # if it is the first time saving, then the user can set a password
        if not os.path.isfile(self.file_path):
            self.password = PasswordCreation().get_password()

        self.wallet.tutorial_step = (
            self.step_progress_container.step_bar.current_step
            if not self.step_progress_container.isHidden()
            else None
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
        category_utxo_dict = self.wallet.get_category_utxo_dict()

        def sum_value(category):
            utxos = category_utxo_dict.get(category)
            if not utxos:
                return 0
            return sum([utxo.txout.value for utxo in utxos])

        return [
            f"{len(category_utxo_dict.get(category, []))} Inputs: {Satoshis(sum_value(category), self.wallet.network).str_with_unit()}"
            for category in self.wallet.labels.categories
        ]

    def _create_send_tab(self, tabs):
        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=lambda: [],  # this is filled in uitx_creator
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
                UTXOList.Columns.WALLET_ID,
                UTXOList.Columns.SATOSHIS,
            ],
        )

        uitx_creator = UITX_Creator(
            self.wallet,
            self.mempool_data,
            self.wallet.labels.categories,
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
        for wallet in self.signals.get_wallets().values():
            wallet.set_output_categories_and_labels(builder_infos)

        update_filter = UpdateFilter(
            addresses=[recipient.address for recipient in builder_infos.recipients],
        )
        self.wallet.clear_cache()
        self.signals.category_updated.emit(update_filter)
        self.signals.labels_updated.emit(update_filter)

        self.signals.open_tx_like.emit(builder_infos)

    def set_wallet(self, wallet: Wallet):
        self.wallet = wallet

        # for name, signal in self.signals.__dict__.items():
        #     if hasattr(self.wallet, name) and callable(getattr(self.wallet, name)):
        #         signal.connect(getattr(self.wallet, name), name=self.wallet.id)

        self.connect_signal(
            self.signals.addresses_updated, lambda x: self.wallet.clear_cache()
        )

        self.connect_signal(
            self.signals.get_wallets, lambda: self.wallet, slot_name=self.wallet.id
        )

    def create_wallet_tabs(self):
        "Create tabs.  set_wallet be called first"
        assert bool(self.wallet)

        self.history_tab, self.history_list, self.balance_plot = self._create_hist_tab(
            self.tabs
        )

        (
            self.addresses_tab,
            self.address_list,
            self.address_list_tags,
        ) = self._create_addresses_tab(self.tabs)

        self.send_tab, self.uitx_creator = self._create_send_tab(self.tabs)
        # self.utxo_tab, self.utxo_list = self._create_utxo_tab(self.tabs)

        (
            self.settings_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab()

        self.create_status_bar(self.tab, self.outer_layout)

        self.update_status_visualization(self.sync_status)
        self.tabs.setCurrentIndex(0)

        self.address_list.signal_tag_dropped.connect(self.set_category)
        self.address_list_tags.list_widget.signal_addresses_dropped.connect(
            self.set_category
        )
        self.address_list_tags.delete_button.signal_addresses_dropped.connect(
            self.set_category
        )
        self.address_list_tags.list_widget.signal_tag_deleted.connect(
            self.delete_category
        )
        self.address_list_tags.list_widget.signal_tag_renamed.connect(
            lambda old, new: self.rename_category(old, new)
        )

        # tutorial
        self.step_progress_container = WalletSteps(
            wallet=self.wallet,
            wallet_tabs=self.tabs,
            qt_wallet=self,
            signal_create_wallet=self.wallet_descriptor_ui.signal_qtwallet_apply_setting_changes,
        )
        self.outer_layout.insertWidget(0, self.step_progress_container)

    def rename_category(self, old_category, new_category):
        affected_keys = self.wallet.labels.rename_category(old_category, new_category)
        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=affected_keys, categories=[category], txids=affected_keys
            )
        )

    def delete_category(self, category):
        affected_keys = self.wallet.labels.delete_category(category)
        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=affected_keys, categories=[category], txids=affected_keys
            )
        )

    def set_category(self, address_drag_info: AddressDragInfo):
        for address in address_drag_info.addresses:
            for category in address_drag_info.tags:
                self.wallet.labels.set_addr_category(address, category)

        unique_txids = set()
        for address in address_drag_info.addresses:
            unique_txids = unique_txids.union(
                [info.txid for info in self.wallet.get_partialtxinfos(address)]
            )

        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=address_drag_info.addresses,
                categories=address_drag_info.tags,
                txids=unique_txids,
            )
        )

    def create_status_bar(self, tab, outer_layout):
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

        self.search_box = QLineEdit()
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setPlaceholderText("Search here")
        self.search_box.textChanged.connect(self.do_search)
        self.tabs.currentChanged.connect(lambda: self.do_search(self.search_box.text()))
        # sb.addPermanentWidget(self.search_box)
        self.tabs.set_top_right_widget(self.search_box)

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

    def do_search(self, t):
        row_hidden_states = []
        tab = self.tabs.currentWidget()
        if isinstance(tab, SearchableTab) and tab.searchable_list:
            row_hidden_states = tab.searchable_list.filter(t)

        # format search field
        are_all_hidden = all(row_hidden_states)
        if not row_hidden_states or not are_all_hidden:
            self.search_box.setStyleSheet("")
        else:
            self.search_box.setStyleSheet("background-color: #F2C1C3;")  # red

    def update_status_visualization(self, sync_status):
        if not self.wallet:
            return

        balance_text = ""
        network_text = _("Offline")
        icon = read_QIcon("status_disconnected.png")

        if sync_status == SyncStatus.syncing:
            network_text = _("Synchronizing...")
            icon = read_QIcon("status_waiting.png")
        elif (
            self.wallet.blockchain
            and self.wallet.get_height()
            and sync_status in [SyncStatus.synced]
        ):
            network_text = _("Connected")
            (
                confirmed,
                unconfirmed,
                unmatured,
            ) = self.wallet.get_balances_for_piechart()
            if hasattr(self, "balance_label"):
                self.balance_label.update_list(
                    [
                        (_("Unmatured"), COLOR_UNMATURED, unmatured.value),
                        (_("Unconfirmed"), COLOR_UNCONFIRMED, unconfirmed.value),
                        (_("On-chain"), COLOR_CONFIRMED, confirmed.value),
                    ]
                )
            balance = confirmed + unconfirmed + unmatured
            balance_text = _("Balance") + f": {balance.str_with_unit()} "
            # append fiat balance and price
            if self.fx.is_enabled():
                balance_text += (
                    self.fx.get_fiat_status_text(
                        balance, self.base_unit(), self.get_decimal_point()
                    )
                    or ""
                )
            icon = read_QIcon("status_connected.png")

        if hasattr(self, "balance_label"):
            self.balance_label.setText(balance_text or network_text)
            if self.status_button:
                self.status_button.setIcon(icon)
        if self.set_tab_widget_icon:
            self.set_tab_widget_icon(self.tab, icon)

    def get_tabs(self, tab_widget):
        return [tab_widget.widget(i) for i in range(tab_widget.count())]

    def create_list_tab(
        self,
        l: HistList,
        horizontal_widgets_left=None,
        horizontal_widgets_right=None,
    ):
        # create a horizontal widget and layout
        h = SearchableTab()
        h.searchable_list = l
        hbox = QHBoxLayout(h)
        h.setLayout(hbox)

        if horizontal_widgets_left:
            for widget in horizontal_widgets_left:
                hbox.addWidget(widget)

        w = QWidget()
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        w.setLayout(vbox)
        toolbar = l.create_toolbar(self.config)
        if toolbar:
            vbox.addLayout(toolbar)

        vbox.addWidget(l)
        hbox.addWidget(w)

        if horizontal_widgets_right:
            for widget in horizontal_widgets_right:
                hbox.addWidget(widget)
        return h

    def _create_hist_tab(self, tabs):
        tab = SearchableTab()
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
        list_widget = self.create_list_tab(l)
        splitter1.addWidget(list_widget)
        tab.searchable_list = l

        right_widget = QWidget()
        right_widget_layout = QVBoxLayout(right_widget)
        right_widget_layout.setContentsMargins(0, 0, 0, 0)

        self.quick_receive = BitcoinQuickReceive(self.signals, self.wallet)
        right_widget_layout.addWidget(self.quick_receive)

        plot = WalletBalanceChart(self.wallet, signals=self.signals)
        right_widget_layout.addWidget(plot)

        splitter1.addWidget(right_widget)

        add_tab_to_tabs(
            tabs, tab, read_QIcon("history.svg"), "History", "history", position=2
        )

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

        return [
            f"{len(d.get(category, []))} Addresses"
            for category in self.wallet.labels.categories
        ]

    def _create_addresses_tab(self, tabs):
        l = AddressList(self.fx, self.config, self.wallet, self.signals)

        tags = CategoryEditor(
            self.wallet.labels.categories,
            self.signals,
            get_sub_texts=self._subtexts_for_categories,
        )

        def create_new_address(category):
            address_info = self.address_list.get_address(
                force_new=True, category=category
            )

        tags.list_widget.signal_tag_clicked.connect(create_new_address)

        tags.setMaximumWidth(150)
        tab = self.create_list_tab(l, horizontal_widgets_left=[tags])

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
            self.signal_settext_balance_label.emit(
                f"Syncing wallet: {round(progress)}%  {message}"
            )

        def do():
            self.wallet.sync(progress_function_threadsafe=progress_function_threadsafe)

        def on_done(result):
            logger.debug("start updating lists")
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
        TaskThread(self).add_and_start(do, on_success, on_done, on_error)
