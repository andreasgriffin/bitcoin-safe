import logging
from unittest import signals

from matplotlib import category
from bitcoin_safe.config import UserConfig
from bitcoin_safe.mempool import MempoolData

logger = logging.getLogger(__name__)

from bitcoin_safe.wallet import Wallet
from .util import read_QIcon
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
from .ui_tx import UITX_Creator, UIPSBT_Viewer

from ...thread_manager import ThreadManager
from ...util import Satoshis, format_satoshis
from ...signals import Signals, UpdateFilter
from ...i18n import _
from .ui_descriptor import WalletDescriptorUI
from .password_question import PasswordQuestion, PasswordCreation
from .category_list import CategoryEditor
from ...tx import TXInfos
from ...pythonbdk_types import Error
import bdkpython as bdk
import os


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


class QTWallet(QObject):
    signal_settext_balance_label = Signal(str)
    signal_start_synchronization = Signal()
    signal_stop_synchronization = Signal()

    def __init__(
        self,
        wallet: Wallet,
        config: UserConfig,
        signals: Signals,
        mempool_data: MempoolData,
    ):
        super().__init__()

        self.thread_manager = ThreadManager()
        self.signals = signals
        self.mempool_data = mempool_data
        self._connected_signals = []
        self.set_wallet(wallet)
        self.password = None
        self.wallet_descriptor_tab = None
        self.config = config
        self.is_synchronizing = False
        self.fx = FX()
        self.ui_password_question = PasswordQuestion()

        self.history_tab, self.history_list = None, None
        self.addresses_tab, self.address_list, self.address_list_tags = None, None, None
        self.utxo_tab, self.utxo_list = None, None
        self.send_tab = None

        self._create_wallet_tab_and_subtabs()
        self.signal_start_synchronization.connect(
            lambda: self.set_synchronization(True)
        )
        self.signal_stop_synchronization.connect(
            lambda: self.set_synchronization(False)
        )
        self.signal_start_synchronization.connect(self.update_status)
        self.signal_stop_synchronization.connect(self.update_status)

    def set_synchronization(self, state):
        logger.debug(f"Set is_synchronizing {state}")
        self.is_synchronizing = state

    def __repr__(self) -> str:
        return f"QTWallet({self.__dict__})"

    def save(self):
        file_path = os.path.join(self.config.wallet_dir, self.wallet.basename())

        # if it is the first time saving, then the user can ste a password
        if not os.path.isfile(file_path):
            self.password = PasswordCreation().get_password()

        self.wallet.save(
            file_path,
            password=self.password,
        )

    def cancel_setting_changes(self):
        self.wallet_descriptor_ui.set_all_ui_from_wallet(self.wallet)

    def apply_setting_changes(self):
        self.wallet_descriptor_ui.set_wallet_from_keystore_ui()
        self.wallet.recreate_bdk_wallet()  # this must be after set_wallet_from_keystore_ui, but before create_wallet_tabs

        self.sync()
        self.refresh_caches_and_ui_lists()

    def refresh_caches_and_ui_lists(self):
        # before the wallet UI updates, we have to refresh the wallet caches to make the UI update faster
        logger.debug("start refresh cashe")
        self.wallet.reset_cache()

        def threaded():
            self.wallet.fill_commonly_used_caches()

        def on_finished():
            # now do the UI
            logger.debug("start refresh ui")

            if self.history_tab:
                # self.address_list.update()
                # self.address_list_tags.update()
                self.signals.category_updated.emit(UpdateFilter(refresh_all=True))
                self.signals.utxos_updated.emit()
                # self.history_list.update()
            else:
                self.create_wallet_tabs()

        self.thread_manager.start_in_background_thread(
            threaded, on_finished=on_finished, name="Update wallet UI"
        )

    def _create_wallet_tab_and_subtabs(self):
        "Create a tab, and layout, that other UI components can fit inside"
        # create UI part
        self.tab = QWidget()
        self.tab.setObjectName(self.wallet.id)

        self.outer_layout = QVBoxLayout(self.tab)
        # add the tab_widget for  history, utx, send tabs
        self.tabs = QTabWidget(self.tab)
        self.outer_layout.addWidget(self.tabs)

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
        return wallet_descriptor_ui.tab, wallet_descriptor_ui

    def _get_sub_texts_for_uitx(self):
        d = {}
        for utxo in self.wallet.get_utxos():
            address = self.wallet.get_utxo_address(utxo)
            category = self.wallet.labels.get_category(address)
            if category not in d:
                d[category] = []
            d[category].append(utxo)

        def sum_value(category):
            utxos = d.get(category)
            if not utxos:
                return 0
            return sum([utxo.txout.value for utxo in utxos])

        return [
            f"{len(d.get(category, []))} Inputs: {Satoshis(sum_value(category)).str_with_unit()}"
            for category in self.wallet.categories
        ]

    def _create_send_tab(self, tabs):
        def get_outpoints():
            return [utxo.outpoint for utxo in self.wallet.get_utxos()]

        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=get_outpoints,
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
                UTXOList.Columns.WALLET_ID,
                UTXOList.Columns.SATOSHIS,
            ],
        )

        uitx_creator = UITX_Creator(
            self.mempool_data,
            self.wallet.categories,
            utxo_list,
            self.signals,
            self._get_sub_texts_for_uitx,
            enable_opportunistic_merging_fee_rate=self.config.enable_opportunistic_merging_fee_rate,
        )
        add_tab_to_tabs(
            self.tabs,
            uitx_creator.main_widget,
            read_QIcon("tab_send.png"),
            "Send",
            "send",
        )

        uitx_creator.signal_create_tx.connect(self.create_psbt)
        uitx_creator.signal_set_category_coin_selection.connect(
            self.set_coin_selection_in_sent_tab
        )
        uitx_creator.main_widget.searchable_list = utxo_list

        return uitx_creator.main_widget, uitx_creator

    def set_coin_selection_in_sent_tab(self, txinfos: TXInfos):
        utxos_for_input = self.wallet.create_coin_selection_dict(txinfos)

        model = self.uitx_creator.utxo_list.model()
        # Get the selection model from the view
        selection = self.uitx_creator.utxo_list.selectionModel()

        utxo_names = [self.wallet.get_utxo_name(utxo) for utxo in utxos_for_input.utxos]

        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            index = model.index(row, self.uitx_creator.utxo_list.Columns.OUTPOINT)
            utxo_name = model.data(index)
            if utxo_name in utxo_names:
                selection.select(
                    index, QItemSelectionModel.Select | QItemSelectionModel.Rows
                )
            else:
                selection.select(
                    index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows
                )

    def create_psbt(self, txinfos: TXInfos):
        try:
            txinfos = self.wallet.create_psbt(txinfos)
        except Exception as e:
            Message(e.args[0], title="er").show_error()
            raise

        update_filter = UpdateFilter(
            addresses=[recipient.address for recipient in txinfos.recipients],
        )
        self.wallet.reset_cache()
        self.signals.category_updated.emit(update_filter)
        self.signals.labels_updated.emit(update_filter)

        self.signals.open_tx.emit(txinfos)

    def create_pre_wallet_tab(self):
        "Create a wallet settings tab, such that one can create a wallet (e.g. with xpub)"
        (
            self.wallet_descriptor_tab,
            self.wallet_descriptor_ui,
        ) = self.create_and_add_settings_tab()

    def connect_signal(self, signal, f, **kwargs):
        signal.connect(f, **kwargs)
        self._connected_signals.append((signal, f))

    def disconnect_signals(self):
        for signal, f in self._connected_signals:
            signal.disconnect(f)

    def set_wallet(self, wallet: Wallet):
        self.wallet = wallet

        # for name, signal in self.signals.__dict__.items():
        #     if hasattr(self.wallet, name) and callable(getattr(self.wallet, name)):
        #         signal.connect(getattr(self.wallet, name), name=self.wallet.id)
        self.connect_signal(self.signals.addresses_updated, self.wallet.reset_cache)

        self.connect_signal(
            self.signals.get_wallets, lambda: self.wallet, slot_name=self.wallet.id
        )

    def create_wallet_tabs(self):
        "Create tabs.  set_wallet be called first"
        assert bool(self.wallet)

        self.history_tab, self.history_list = self._create_hist_tab(self.tabs)
        (
            self.addresses_tab,
            self.address_list,
            self.address_list_tags,
        ) = self._create_addresses_tab(self.tabs)
        self.send_tab, self.uitx_creator = self._create_send_tab(self.tabs)
        # self.utxo_tab, self.utxo_list = self._create_utxo_tab(self.tabs)
        if not self.wallet_descriptor_tab:
            (
                self.settings_tab,
                self.wallet_descriptor_ui,
            ) = self.create_and_add_settings_tab()

        self.create_status_bar(self.tab, self.outer_layout)

        self.update_status()
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

    def rename_category(self, old_category, new_category):
        affected_keys = self.wallet.rename_category(old_category, new_category)
        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=affected_keys, categories=[category], txids=affected_keys
            )
        )

    def delete_category(self, category):
        affected_keys = self.wallet.delete_category(category)
        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=affected_keys, categories=[category], txids=affected_keys
            )
        )

    def set_category(self, address_drag_info: AddressDragInfo):
        for address in address_drag_info.addresses:
            for category in address_drag_info.tags:
                self.wallet.labels.set_addr_category(address, category)

        outputinfos = sum(
            [
                self.wallet.get_txs_involving_address(address)
                for address in address_drag_info.addresses
            ],
            [],
        )
        self.signals.category_updated.emit(
            UpdateFilter(
                addresses=address_drag_info.addresses,
                categories=address_drag_info.tags,
                txids=[outputinfo.tx.txid for outputinfo in outputinfos],
            )
        )

    def create_status_bar(self, tab, outer_layout):
        sb = QStatusBar()
        self.balance_label = BalanceToolButton()
        self.balance_label.setText("Loading wallet...")
        self.balance_label.setAutoRaise(True)
        # self.balance_label.clicked.connect(self.show_balance_dialog)
        sb.addWidget(self.balance_label)
        self.signal_settext_balance_label.connect(self.balance_label.setText)

        font_height = QFontMetrics(self.balance_label.font()).height()
        sb_height = max(35, int(2 * font_height))
        sb.setFixedHeight(sb_height)

        # remove border of all items in status bar
        tab.setStyleSheet("QStatusBar::item { border: 0px;} ")

        self.search_box = QLineEdit()
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setPlaceholderText("Search here")
        self.search_box.textChanged.connect(self.do_search)
        self.tabs.currentChanged.connect(lambda: self.do_search(self.search_box.text()))
        sb.addPermanentWidget(self.search_box)

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
        self.status_button = StatusBarButton(
            read_QIcon("status_disconnected.png"),
            _("Network"),
            self.signals.show_network_settings.emit,
            sb_height,
        )
        sb.addPermanentWidget(self.status_button)
        # run_hook('create_status_bar', sb)
        outer_layout.addWidget(sb)

    def toggle_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    def do_search(self, t):
        row_hidden_states = None
        tab = self.tabs.currentWidget()
        if hasattr(tab, "searchable_list"):
            row_hidden_states = tab.searchable_list.filter(t)

        # format search field
        are_all_hidden = all(row_hidden_states)
        if not row_hidden_states or not are_all_hidden:
            self.search_box.setStyleSheet("")
        else:
            self.search_box.setStyleSheet("background-color: #F2C1C3;")  # red

    def update_status(self):
        if not self.wallet:
            return

        network_text = ""
        balance_text = ""

        if self.is_synchronizing:
            network_text = _("Synchronizing...")
            icon = read_QIcon("status_waiting.png")
        elif self.wallet.blockchain and self.wallet.blockchain.get_height():
            network_text = _("Connected")
            (
                confirmed,
                unconfirmed,
                unmatured,
            ) = self.wallet.get_balances_for_piechart()
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
        else:
            network_text = _("Offline")
            icon = read_QIcon("status_disconnected.png")

        self.balance_label.setText(balance_text or network_text)
        if self.status_button:
            self.status_button.setIcon(icon)

    def get_tabs(self, tab_widget):
        return [tab_widget.widget(i) for i in range(tab_widget.count())]

    def create_list_tab(
        self,
        l: HistList,
        horizontal_widgets_left=None,
        horizontal_widgets_right=None,
    ):
        # create a horizontal widget and layout
        h = QWidget()
        h.searchable_list = l
        hbox = QHBoxLayout(h)
        h.setLayout(hbox)

        if horizontal_widgets_left:
            for widget in horizontal_widgets_left:
                hbox.addWidget(widget)

        w = QWidget()
        vbox = QVBoxLayout()
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
        l = HistList(
            fx=self.fx,
            config=self.config,
            signals=self.signals,
            wallet_id=self.wallet.id,
            hidden_columns=[
                HistList.Columns.WALLET_ID,
                HistList.Columns.BALANCE,
                HistList.Columns.SATOSHIS,
                HistList.Columns.TXID,
            ],
        )
        tab = self.create_list_tab(l)

        add_tab_to_tabs(
            tabs, tab, read_QIcon("tab_history.png"), "History", "history", position=0
        )

        return tab, l

    def _subtexts_for_categories(self):
        d = {}
        for address in self.wallet.get_addresses():
            category = self.wallet.labels.get_category(address)
            if category not in d:
                d[category] = []

            d[category].append(address)

        return [
            f"{len(d.get(category, []))} Addresses"
            for category in self.wallet.categories
        ]

    def _create_addresses_tab(self, tabs):
        l = AddressList(self.fx, self.config, self.wallet, self.signals)

        tags = CategoryEditor(
            self.wallet.categories,
            self.signals,
            get_sub_texts=self._subtexts_for_categories,
        )
        tags.setMaximumWidth(150)
        tab = self.create_list_tab(l, horizontal_widgets_left=[tags])

        add_tab_to_tabs(
            tabs,
            tab,
            read_QIcon("tab_addresses.png"),
            "Receive",
            "receive",
            position=1,
        )
        return tab, l, tags

    # def _create_utxo_tab(self, tabs):
    #     "deprecated"
    #     outpoins = [
    #         utxo.outpoint   for utxo in self.wallet.get_utxos()
    #     ]

    #     l = UTXOList(
    #         self.config,
    #         self.signals,
    #         outpoint_domain=outpoins,
    #         hidden_columns=[UTXOList.Columns.SATOSHIS],
    #     )
    #     tab = self.create_list_tab(l)

    #     add_tab_to_tabs(
    #         tabs, tab, read_QIcon("tab_coins.png"), "Coins", "utxo", position=2
    #     )
    #     return tab, l

    def sync(self, threaded=True):
        self.signal_start_synchronization.emit()
        logger.debug(f'Start {"threaded" if threaded else "non-threaded"} sync')

        def progress_function_threadsafe(progress: float, message: str):
            self.signal_settext_balance_label.emit(
                f"Syncing wallet: {round(progress)}%  {message}"
            )

        def do_sync():
            self.wallet.sync(progress_function_threadsafe=progress_function_threadsafe)
            logger.debug("finished sync")

        def on_finished():
            logger.debug("start updating lists")
            self.refresh_caches_and_ui_lists()
            # self.update_tabs()
            self.signal_stop_synchronization.emit()
            logger.debug("finished updating lists")

        if threaded:
            future = self.thread_manager.start_in_background_thread(
                do_sync, on_finished=on_finished
            )
        else:
            do_sync()
            on_finished()
