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

import base64
import logging
import os
import platform
import signal as syssignal
import sys
from collections.abc import Iterable
from datetime import datetime
from functools import partial
from pathlib import Path
from types import FrameType
from typing import Literal, cast

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from bitcoin_qr_tools.gui.bitcoin_video_widget import BitcoinVideoWidget, DecodingException
from bitcoin_qr_tools.multipath_descriptor import convert_to_multipath_descriptor
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.util import rel_home_path_to_abs_path
from bitcoin_safe_lib.util_os import show_file_in_explorer, webopen, xdg_open_file
from bitcoin_usb.tool_gui import ToolGui
from PyQt6.QtCore import (
    QCoreApplication,
    QLocale,
    QPoint,
    QSettings,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QCloseEvent,
    QKeySequence,
    QPalette,
    QShortcut,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.client import Client
from bitcoin_safe.execute_config import DEMO_MODE, DONATION_ADDRESS, IS_PRODUCTION
from bitcoin_safe.gui.qt.about_tab import UpdateStatus
from bitcoin_safe.gui.qt.demo_testnet_wallet import copy_testnet_demo_wallet
from bitcoin_safe.gui.qt.descriptor_edit import DescriptorExport
from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.language_chooser import LanguageChooser
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole, needs_frequent_flag
from bitcoin_safe.gui.qt.notification_bar_cbf import NotificationBarCBF
from bitcoin_safe.gui.qt.notification_bar_regtest import NotificationBarRegtest
from bitcoin_safe.gui.qt.packaged_tx_like import PackagedTxLike, UiElements
from bitcoin_safe.gui.qt.password_cache import PasswordCache
from bitcoin_safe.gui.qt.payment_widget import DonateDialog
from bitcoin_safe.gui.qt.settings import Settings
from bitcoin_safe.gui.qt.sidebar.search_sidebar_tree import SearchSidebarTree
from bitcoin_safe.gui.qt.sidebar.search_wallets import SearchWallets
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import TT, SidebarNode, SidebarTree
from bitcoin_safe.gui.qt.simple_qr_scanner import SimpleQrScanner
from bitcoin_safe.gui.qt.tx_util import are_txs_identical
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.update_notification_bar import UpdateNotificationBar
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wizard import ImportXpubs, TutorialStep, Wizard
from bitcoin_safe.gui.qt.wrappers import Menu, MenuBar
from bitcoin_safe.keystore import KeyStoreImporterTypes
from bitcoin_safe.logging_handlers import mail_contact, mail_feedback
from bitcoin_safe.logging_setup import get_log_file
from bitcoin_safe.network_config import P2pListenerType, Peers
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.p2p.p2p_client import ConnectionInfo
from bitcoin_safe.p2p.p2p_listener import P2pListener
from bitcoin_safe.p2p.tools import transaction_table
from bitcoin_safe.pdfrecovery import make_and_open_pdf
from bitcoin_safe.pyqt6_restart import restart_application
from bitcoin_safe.util import OptExcInfo
from bitcoin_safe.wallet_util import get_default_categories

from ...config import UserConfig
from ...fx import FX
from ...mempool_manager import MempoolManager
from ...psbt_util import FeeInfo, FeeRate, SimplePSBT
from ...pythonbdk_types import (
    BlockchainType,
    Recipient,
    TransactionDetails,
    get_prev_outpoints,
)
from ...signals import Signals, UpdateFilter, WalletFunctions
from ...storage import Storage
from ...tx import TxBuilderInfos, TxUiInfos, short_tx_id
from ...util import fast_version
from ...wallet import ProtoWallet, ToolsTxUiInfo, Wallet
from . import address_dialog
from .attached_widgets import AttachedWidgets
from .dialog_import import ImportDialog, file_to_str
from .dialogs import PasswordQuestion, WalletIdDialog, show_textedit_message
from .loading_wallet_tab import LoadingWalletTab
from .new_wallet_welcome_screen import NewWalletWelcomeScreen
from .qt_wallet import QTProtoWallet, QTWallet, QtWalletBase
from .sign_message import SignAndVerifyMessage
from .tray_controller import TrayController
from .util import (
    ELECTRUM_SERVER_DELAY_BLOCK,
    ELECTRUM_SERVER_DELAY_MEMPOOL_TX,
    Message,
    MessageType,
    caught_exception_message,
    center_on_screen,
    delayed_execution,
    do_copy,
)
from .utxo_list import UTXOList, UtxoListWithToolbar

logger = logging.getLogger(__name__)

MAC_OPEN_WALLET_LIMIT = 5


class MainWindow(QMainWindow):
    signal_recently_open_wallet_changed = cast(SignalProtocol[[list[str]]], pyqtSignal(list))
    signal_remove_attached_widget = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        network: Literal["bitcoin", "regtest", "signet", "testnet"] | None = None,
        config: UserConfig | None = None,
        open_files_at_startup: list[str] | None = None,
        **kwargs,
    ) -> None:
        "If network == None, then the network from the user config will be taken"
        super().__init__()
        self.open_files_at_startup = open_files_at_startup if open_files_at_startup else []
        config_present = UserConfig.exists() or config
        if config:
            logger.debug("MainWindow was started with config  argument")
        elif UserConfig.exists():
            logger.debug(f"UserConfig file {UserConfig.config_file} exists and will be loaded from there")
        else:
            logger.debug("UserConfig will be created new")
        self.config = config if config else UserConfig.from_file()
        self.config.network = bdk.Network[network.upper()] if network else self.config.network
        self.new_startup_network: bdk.Network | None = None
        self._before_close_was_run = False
        self._was_maximized_before_fullscreen = False
        # i need to keep references of open windows attached
        # to the mainwindow to avoid memory issues
        # however I need to clear them again with signal_remove_attached_widget
        self.attached_widgets = AttachedWidgets(maxlen=10000)
        self.log_color_palette()
        self.password_cache = PasswordCache()

        self.signals = Signals()
        self.wallet_functions = WalletFunctions(self.signals)
        self.loop_in_thread = LoopInThread()
        self._p2p_listener_signals_connected = False
        self.signal_tracker = SignalTracker()

        self.fx = FX(config=self.config, loop_in_thread=self.loop_in_thread)
        self.fx.signal_data_updated.connect(self.update_fx_rate_in_config)
        self.language_chooser = LanguageChooser(
            config=self.config,
            signals_language_switch=[self.signals.language_switch],
            parent=self,
            signals_currency_switch=self.signals.currency_switch,
        )
        if not config_present:
            os_language_code = self.language_chooser.get_os_language_code()
            self.config.language_code = (
                os_language_code
                if os_language_code in self.language_chooser.get_languages()
                else self.language_chooser.dialog_choose_language(self)
            )
            self.config.currency = self.fx.get_currency_iso(QLocale(self.config.language_code))
        self.language_chooser.set_language(self.config.language_code)
        self.hwi_tool_gui = ToolGui(self.config.network, loop_in_thread=self.loop_in_thread)
        self.hwi_tool_gui.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self.setupUi(config_present=bool(config_present))

        self.mempool_manager = MempoolManager(
            network_config=self.config.network_config,
            signals_min=self.signals,
            loop_in_thread=self.loop_in_thread,
        )
        self.mempool_manager.set_data_from_mempoolspace()

        self.last_qtwallet: QTWallet | None = None
        # connect the listeners
        self.signals.open_file_path.connect(self.open_file_path)
        self.signals.open_tx_like.connect(self.open_tx_like_in_tab)
        self.signals.apply_txs_to_wallets.connect(self.apply_txs_to_wallets_and_highlight)
        self.signals.evict_txs_from_wallet_id.connect(self.apply_evicted_txs)
        self.signals.get_network.connect(self.get_network)
        self.signals.get_mempool_url.connect(self.get_mempool_url)
        self.signals.get_btc_symbol.connect(self.get_btc_symbol)

        self.settings = Settings(
            config=self.config,
            signals=self.signals,
            fx=self.fx,
            language_chooser=self.language_chooser,
        )
        self.settings.network_settings_ui.signal_apply_and_shutdown.connect(self.restart)
        self.signals.show_network_settings.connect(self.open_settings_ui)
        self.settings.signal_update_action_requested.connect(
            self.update_notification_bar.check_and_make_visible
        )

        self.welcome_screen = NewWalletWelcomeScreen(
            network=self.config.network,
            signals=self.signals,
            signal_recently_open_wallet_changed=self.signal_recently_open_wallet_changed,
            parent=self.tab_wallets,
        )
        self.welcome_screen.signal_remove_me.connect(self.on_new_wallet_welcome_screen_remove_me)
        self.init_p2p_listening()

        # signals
        self.welcome_screen.signal_onclick_single_signature.connect(self.click_create_single_signature_wallet)
        self.welcome_screen.signal_onclick_multisig_signature.connect(
            self.click_create_multisig_signature_wallet
        )
        self.welcome_screen.signal_onclick_custom_signature.connect(self.click_custom_signature)
        self.signals.add_qt_wallet.connect(self.add_qt_wallet)
        self.signals.close_qt_wallet.connect(self.remove_qt_wallet_by_id)

        self.signals.event_wallet_tab_added.connect(self.event_wallet_tab_added)
        self.signals.event_wallet_tab_closed.connect(self.event_wallet_tab_closed)
        self.signals.chain_data_changed.connect(self.sync)
        self.signals.request_manual_sync.connect(self.manual_sync)
        self.signals.open_wallet.connect(self.open_wallet)
        self.signals.signal_broadcast_tx.connect(self.on_signal_broadcast_tx)
        self.signals.language_switch.connect(self.updateUI)
        self.signal_recently_open_wallet_changed.connect(self.populate_recent_wallets_menu)
        self.signals.close_all_video_widgets.connect(self.close_video_widget)
        self.signals.signal_set_tab_properties.connect(self.on_set_tab_properties)
        self.signal_remove_attached_widget.connect(self.on_signal_remove_attached_widget)
        self.signals.signal_close_tabs_with_txids.connect(self.on_signal_close_tabs_with_txids)

        # Populate recent wallets menu
        self.signal_recently_open_wallet_changed.emit(
            list(self.config.recently_open_wallets[self.config.network])
        )

        self.updateUI()
        self.setup_signal_handlers()

        delayed_execution(self.load_last_state, self)

        # demo wallets
        if self.config.network in [
            bdk.Network.REGTEST,
            bdk.Network.SIGNET,
            bdk.Network.TESTNET,
            bdk.Network.TESTNET4,
        ]:
            demo_wallet_files = copy_testnet_demo_wallet(config=self.config)
            for demo_wallet_file in demo_wallet_files:
                self.add_recently_open_wallet(str(demo_wallet_file))

    @property
    def qt_wallets(self) -> dict[str, QTWallet]:
        """Qt wallets."""
        res: dict[str, QTWallet] = {}
        for tab in self.tab_wallets.roots:
            if isinstance(tab.data, QTWallet):
                res[tab.data.wallet.id] = tab.data
        return res

    def get_node(self, wallet_id: str) -> SidebarNode | None:
        """Get node."""
        for tab in self.tab_wallets.roots:
            if isinstance(tab.data, QTWallet) and tab.data.wallet.id == wallet_id:
                return tab
            if isinstance(tab.data, QTProtoWallet) and tab.data.protowallet.id == wallet_id:
                return tab
            if (
                isinstance(tab.data, Wizard)
                and isinstance(tab.data.qtwalletbase, QTProtoWallet)
                and tab.data.qtwalletbase.protowallet.id == wallet_id
            ):
                return tab
        return None

    def update_fx_rate_in_config(self):
        """Update fx rate in config."""
        self.config.rates.clear()
        self.config.rates.update(self.fx.list_rates())

    def on_new_wallet_welcome_screen_remove_me(self, tab: QWidget):
        """On new wallet welcome screen remove me."""
        if self.tab_wallets.count() > 1:
            # remove only if there is 1 additional tab besides the new_wallet_welcome_screen
            node = self.tab_wallets.root.findNodeByWidget(tab)
            if node:
                self.close_tab(node)

    def close_video_widget(self):
        """Close video widget."""
        self.attached_widgets.remove_all_of_type(BitcoinVideoWidget)

    def _register_attached_widget(self, widget: QWidget) -> None:
        self.attached_widgets.append(widget)

    def get_mempool_url(self) -> str:
        """Get mempool url."""
        return self.config.network_config.mempool_url

    def get_btc_symbol(self) -> str:
        """Get mempool url."""
        return self.config.bitcoin_symbol.value

    def get_network(self) -> bdk.Network:
        """Get network."""
        return self.config.network

    def load_last_state(self) -> None:
        """Load last state."""
        opened_qt_wallets = self.open_last_opened_wallets()
        if not opened_qt_wallets:
            self.welcome_screen.add_new_wallet_welcome_tab(self.tab_wallets)

        self.open_last_opened_tx()
        for file_path in self.open_files_at_startup:
            self.open_file_path(file_path=file_path)

        self.tab_wallets.root.select_by_titles(self.config.last_tab_title)

    def open_file_path(self, file_path: str):
        """Open file path."""
        if file_path and Path(file_path).exists():
            if file_path.endswith(".wallet"):
                self.open_wallet(file_path=file_path)
            else:
                self.signals.open_tx_like.emit(file_to_str(file_path))

    def on_currentChanged(self, node: SidebarNode[TT]):
        """On currentChanged."""
        self.set_title()
        self.rebuild_current_wallet_tab_menu()

    def set_title(self) -> None:
        """Set title."""
        title = "Bitcoin Safe"
        if self.config.network != bdk.Network.BITCOIN and not DEMO_MODE:
            title += f" - {self.config.network.name}"
        if qt_wallet := self.get_qt_wallet():
            title += f" - {qt_wallet.wallet.id}"
        self.setWindowTitle(title)

    def setupUi(self, config_present: bool) -> None:
        """SetupUi."""
        logger.debug("start setupUi")
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        w, h = 900, 600
        self.setMinimumSize(w, h)

        # 1) Configure QSettings to use your app’s name/org
        self.qsettings = QSettings(
            str(self.config.window_properties_config_file.absolute()), QSettings.Format.IniFormat, self
        )

        # 2) Restore geometry (size+pos) if we saved it before
        if self.qsettings.contains("window/geometry"):
            self.restoreGeometry(self.qsettings.value("window/geometry"))
        if self.qsettings.contains("window/state"):
            self.restoreState(self.qsettings.value("window/state"))

        #####

        self.tab_wallets = SidebarTree[object](
            parent=self,
        )
        self.tab_wallets.nodeContextMenuRequested.connect(self.tab_wallets_show_context_menu)

        self.search_box = SearchWallets(
            wallet_functions=self.wallet_functions, parent=self.tab_wallets, search_box_on_bottom=True
        )
        self.sidebar_search_tree = SearchSidebarTree(
            sidebar_tree=self.tab_wallets, search_view=self.search_box, parent=self
        )

        self.tab_wallets.setObjectName(f"member of {self.__class__.__name__}")
        self.tab_wallets.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Connect signals to slots
        self.tab_wallets.closeClicked.connect(self.close_tab)
        self.tab_wallets.currentChanged.connect(self.on_currentChanged)
        self.signals.tab_history_backward.connect(self.tab_wallets.navigate_history_backward)
        self.signals.tab_history_forward.connect(self.tab_wallets.navigate_history_forward)

        # central_widget
        central_widget = QWidget(self)
        vbox = QVBoxLayout(central_widget)
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        # header bar about testnet coins
        self.notification_bar_testnet = NotificationBarRegtest(
            callback_open_network_setting=self.open_network_settings,
            network=self.config.network,
            signals_min=self.signals,
        )
        if self.config.network != bdk.Network.BITCOIN:
            vbox.addWidget(self.notification_bar_testnet)

        self.notification_bar_cbf = NotificationBarCBF(
            callback_open_network_setting=self.open_network_settings,
            callback_enable_button=self.enable_cbf_and_shutdown,
            network_config=self.config.network_config,
            signals_min=self.signals,
        )
        if (
            not config_present
            or (
                (_dump_version := self.config._version_from_dump)
                and fast_version(_dump_version) < fast_version("0.2.4")
            )
            or (
                self.config.network_config.server_type == BlockchainType.Esplora
                and "blockstream" in self.config.network_config.esplora_url
            )
        ):
            # only show this for migrating users.
            # or new users this is anyway
            # or users with unreliable blockstream esplora server
            vbox.addWidget(self.notification_bar_cbf)

        self.update_notification_bar = UpdateNotificationBar(
            signals_min=self.signals,
            loop_in_thread=self.loop_in_thread,
            proxies=(
                ProxyInfo.parse(self.config.network_config.proxy_url).get_requests_proxy_dict()
                if self.config.network_config.proxy_url
                else None
            ),
        )
        self.update_notification_bar.check()
        vbox.addWidget(self.update_notification_bar)

        vbox.addWidget(self.sidebar_search_tree)
        self.setCentralWidget(central_widget)

        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        if self.config.is_maximized:
            self.showMaximized()

        self._init_tray()
        self.init_menubar()
        self.set_title()
        logger.debug("done setupUi")

    def p2p_listening_on_block(self, block_hash: str):
        """P2p listening on block."""
        logger.info(f"Block hash {block_hash} received via the p2p network")

        # When using electrum & similar, we are trusting the server anyway,
        # such that we can trigger a syncing and trust that the server will
        # not forward us invalid transactions

        # for CBF the only source of transactions are Bitcoin core nodes,
        # and we hope they do not forward us invalid transactions.
        # Since we are selecting either a trusted initial, or a random Bitcoin node
        # one would need to compromise/sybill the node list in
        # the DNS seeds to be able to spam

        if self.config.network_config.server_type in [BlockchainType.CompactBlockFilter]:
            # case already handled by CBF Client
            pass
        elif widget := self.any_needs_frequent_flag():
            # the electrum server processing blocks is slower than the bitcoin nodes, such that I have to delay syncing
            logger.info(
                f"Trigger syncing because {widget} has frequent flag somewhere and {block_hash} received via the p2p network"
            )
            QTimer.singleShot(ELECTRUM_SERVER_DELAY_BLOCK, self.sync_all)
        elif widget := self.any_has_no_txs():
            # the electrum server processing blocks is slower than the bitcoin nodes, such that I have to delay syncing
            logger.info(
                f"Trigger syncing because {widget} has no txs and {block_hash} received via the p2p network"
            )
            QTimer.singleShot(ELECTRUM_SERVER_DELAY_BLOCK, self.sync_all)
        else:
            # trigger no needless syncing
            pass

    def _get_update_status(self) -> UpdateStatus:
        """Get update status for the About tab."""
        assets_present = bool(self.update_notification_bar.assets)
        latest_version = self.update_notification_bar.get_asset_tag()
        return UpdateStatus(
            is_checked=assets_present,
            has_update=self.update_notification_bar.is_new_version_available(),
            latest_version=latest_version,
        )

    def any_has_no_txs(self) -> QWidget | None:
        """Any has no txs."""
        for root in self.tab_wallets.roots:
            if isinstance((_qt_wallet := root.data), QTWallet):
                if not _qt_wallet.wallet.sorted_delta_list_transactions():
                    return _qt_wallet
        return None

    def any_needs_frequent_flag(self) -> QWidget | None:
        """Any needs frequent flag."""
        for root in self.tab_wallets.roots:
            if isinstance((_tx_viewer := root.data), UITx_Viewer):
                if needs_frequent_flag(_tx_viewer.get_tx_status(_tx_viewer.chain_position)):
                    return _tx_viewer
            elif isinstance((_qt_wallet := root.data), QTWallet):
                if _qt_wallet.history_list.any_needs_frequent_flag():
                    return _qt_wallet
        return None

    def p2p_listening_on_tx(self, tx: bdk.Transaction):
        """P2p listening on tx."""
        logger.info(f"Received {short_tx_id(tx.compute_txid())} via the p2p network.")
        if not IS_PRODUCTION:
            print(transaction_table(tx, self.config.network))

        # When using electrum & similar, we are trusting the server anyway,
        # such that we can trigger a syncing and trust that the server will
        # not forward us invalid transactions

        # for CBF the only source of transactions are Bitcoin core nodes,
        # and we hope they do not forward us invalid transactions.
        # Since we are selecting either a trusted initial, or a random Bitcoin node
        # one would need to compromise/sybill the node list in
        # the DNS seeds to be able to spam

        if self.config.network_config.server_type in [BlockchainType.CompactBlockFilter]:
            self.apply_txs_to_wallets([tx], last_seen=int(datetime.now().timestamp()))
        else:
            # the electrum server is slower than the bitcoin nodes, such that I have to delay snycing
            QTimer.singleShot(ELECTRUM_SERVER_DELAY_MEMPOOL_TX, self.sync_all)

    def p2p_listening_update_lists(self, update_filter: UpdateFilter):
        """P2p listening update lists."""
        if not self.p2p_listener:
            return
        address_filter: set[str] = set()
        outpoint_filter: set[str] = set()
        for qt_wallet in self.qt_wallets.values():
            address_filter.update(qt_wallet.wallet.get_address_dict_with_peek().keys())
            outpoint_filter.update(qt_wallet.wallet.bdkwallet.list_unspent_outpoints(include_spent=False))
        self.p2p_listener.set_address_filter(address_filter=address_filter)
        self.p2p_listener.set_outpoint_filter(outpoint_filter=outpoint_filter)
        if not self._p2p_listener_signals_connected:
            self.signal_tracker.connect(
                self.p2p_listener.signal_current_peers_change, self.on_p2p_listener_current_peers_change
            )
            self.signal_tracker.connect(
                self.p2p_listener.signal_try_connecting_to, self.on_p2p_listener_try_connecting_to
            )
            self._p2p_listener_signals_connected = True

    def on_p2p_listener_try_connecting_to(self, connection_info: ConnectionInfo):
        """On p2p listener try connecting to."""
        tooltip = ""
        active_count = len(self.p2p_listener.active_connections) if self.p2p_listener else 0
        if self.p2p_listener:
            if connection_info.proxy_info:
                tooltip = self.tr("Try connecting to: {ip} via proxy {proxy}").format(
                    ip=connection_info.peer, proxy=connection_info.proxy_info.get_url()
                )
            else:
                tooltip = self.tr("Try connecting to: {ip}").format(ip=connection_info.peer)
        status_text = (
            self.tr("Trying to connect to bitcoin node...")
            if active_count == 0
            else self.tr("Connecting to additional peer (currently {count} active)").format(
                count=active_count
            )
        )
        status_labels: list[QLabel] = [
            self.settings.network_settings_ui.p2p_listener_status_label,
        ]
        for label in status_labels:
            label.setToolTip(tooltip)
            label.setText(status_text)

    def on_p2p_listener_current_peers_change(self, connections: list[ConnectionInfo]):
        """Update UI when the set of active p2p connections changes."""
        text = self.tr("Status: Disconnected")
        tooltip = ""

        if self.p2p_listener and connections:
            count = len(connections)
            text = (
                self.tr("Status: Connected")
                if count == 1
                else self.tr("Status: Connected to {count} peers").format(count=count)
            )
            lines = []
            for info in connections:
                if info.proxy_info:
                    lines.append(
                        self.tr("{ip} via proxy {proxy}").format(
                            ip=info.peer, proxy=info.proxy_info.get_url()
                        )
                    )
                else:
                    lines.append(str(info.peer))
            tooltip = "\n".join(lines)

        status_labels: list[QLabel] = [
            self.settings.network_settings_ui.p2p_listener_status_label,
        ]
        for label in status_labels:
            label.setText(text)
            label.setToolTip(tooltip)

    def on_signal_close_tabs_with_txids(self, items: list[str]):
        """On signal close tabs with txids."""
        for item in items:
            for root in list(self.tab_wallets.roots):
                if isinstance(root.data, UITx_Viewer):
                    if root.data.txid() == item:
                        self.close_tab(root)

    def enable_cbf_and_shutdown(self):
        # remove this method after most have migrated to the Version 1.6
        self.settings.network_settings_ui.server_type = BlockchainType.CompactBlockFilter
        if self.config.network_config.p2p_listener_type == P2pListenerType.deactive:
            self.settings.network_settings_ui.p2p_listener_type = P2pListenerType.automatic

        self.settings.network_settings_ui.on_apply_click()

    def init_p2p_listening(self):
        """Init p2p listening."""
        self.p2p_listener: P2pListener | None = None
        self._p2p_listener_signals_connected = False
        self.signal_tracker.disconnect_all()
        if self.config.network_config.p2p_listener_type == P2pListenerType.deactive:
            return
        manual_peers = self.config.network_config.get_manual_peers()
        discovered_peers = Peers(self.config.network_config.discovered_peers)
        for peer in manual_peers:
            if peer not in discovered_peers:
                discovered_peers.append(peer)
        self.p2p_listener = P2pListener(
            network=self.config.network,
            discovered_peers=discovered_peers,
            loop_in_thread=self.loop_in_thread,
            autodiscover_additional_peers=self.config.network_config.p2p_autodiscover_additional_peers,
            max_parallel_peers=self.config.network_config.p2p_listener_parallel_connections,
        )
        self.p2p_listener.signal_tx.connect(self.p2p_listening_on_tx)
        self.p2p_listener.signal_block.connect(self.p2p_listening_on_block)
        self.p2p_listener.start(
            preferred_peers=manual_peers if manual_peers else None,
            proxy_info=(
                ProxyInfo.parse(self.config.network_config.proxy_url)
                if self.config.network_config.proxy_url
                else None
            ),
        )
        self.signals.any_wallet_updated.connect(self.p2p_listening_update_lists)
        self.settings.network_settings_ui.p2p_listener_refresh_button.clicked.connect(
            self.on_p2p_listener_refresh_button
        )
        self.p2p_listening_update_lists(UpdateFilter())

    def on_p2p_listener_refresh_button(self):
        """On p2p listener refresh button."""
        if self.p2p_listener:
            self.p2p_listener.signal_break_current_connection.emit()

    def tab_wallets_show_context_menu(self, node: SidebarNode[object], position: QPoint) -> None:
        """Tab wallets show context menu."""
        menu = Menu()
        self.action_close_tab = menu.add_action(self.tr("Close Tab"), slot=partial(self.close_tab, node))
        self.action_close_tab.setShortcut(self.key_sequence_close_tab)
        self.action_close_all_tx_tabs = menu.add_action(
            self.tr("Close all transactions"), slot=self.on_close_all_tx_tabs
        )

        if isinstance((qt_wallet := node.data), QTWallet):
            menu.addSeparator()
            self.action_reveal_file_explorer = menu.add_action(
                self.tr("Reveal in file explorer"),
                slot=partial(self.reveal_wallet_in_file_explorer, qt_wallet),
            )
            self.action_reveal_file_explorer.setShortcut(self.key_sequence_reveral_wallet_in_file_explorer)

            menu.addSeparator()
            self.context_menu_action_rename_wallet = menu.add_action(
                self.menu_action_rename_wallet.text(),
                slot=partial(self.change_wallet_id, qt_wallet),
                icon=self.menu_action_rename_wallet.icon(),
            )
            self.context_menu_action_rename_wallet = menu.add_action(
                self.menu_action_change_password.text(),
                slot=partial(self.change_wallet_password, qt_wallet),
                icon=self.menu_action_change_password.icon(),
            )

            menu.addSeparator()
            self.context_menu_action_toggle_tutorial = menu.add_action(
                self.tr("&Show/Hide Wizard"),
                slot=partial(self.toggle_tutorial, qt_wallet),
            )

        menu.exec(position)

    def reveal_wallet_in_file_explorer(self, qt_wallet: QTWallet | None):
        """Reveal wallet in file explorer."""
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if qt_wallet:
            show_file_in_explorer(filename=Path(qt_wallet.file_path))

    def on_close_all_tx_tabs(self) -> None:
        """On close all tx tabs."""
        self.close_all_tabs_of_type(cls=UITx_Viewer)

    def close_all_tabs_of_type(self, cls) -> None:
        """Close all tabs of type."""
        for root in reversed(self.tab_wallets.roots):
            if isinstance(root.data, cls):
                self.close_tab(root)

    def log_color_palette(self) -> None:
        """Log color palette."""
        pal = self.palette()
        d = {}
        for role in QPalette.ColorRole:
            d[f"{role}"] = f"{pal.color(role).name()}"
        logger.debug(f"QColors QPalette {d}")

    def init_menubar(self) -> None:
        """Init menubar."""
        self.menubar = MenuBar()

        # menu wallet
        self.menu_wallet = self.menubar.add_menu("")
        self.menu_action_new_wallet = self.menu_wallet.add_action("", self.new_wallet)
        self.menu_action_new_wallet.setShortcut(QKeySequence("CTRL+N"))
        self.menu_action_new_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )

        self.menu_action_open_wallet = self.menu_wallet.add_action("", self.open_wallets)
        self.menu_action_open_wallet.setShortcut(QKeySequence("CTRL+O"))
        self.menu_action_open_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )

        self.menu_wallet_recent = self.menu_wallet.add_menu("")

        self.menu_load_transaction = self.menu_wallet.add_menu("")
        self.menu_action_open_tx_file = self.menu_load_transaction.add_action(
            "",
            self.open_tx_file,
            icon=(self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
        )
        self.menu_action_open_tx_from_str = self.menu_load_transaction.add_action(
            "",
            self.dialog_open_tx_from_str,
            icon=(self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_FileIcon),
        )
        self.menu_action_open_tx_from_str.setShortcut(QKeySequence("CTRL+L"))

        self.menu_action_load_tx_from_qr = self.menu_load_transaction.add_action(
            "", self.load_tx_like_from_qr, icon=svg_tools.get_QIcon(KeyStoreImporterTypes.qr.icon_filename)
        )

        self.menu_action_save_current_wallet = self.menu_wallet.add_action("", self.save_qt_wallet)
        self.menu_action_save_current_wallet.setShortcut(QKeySequence("CTRL+S"))
        self.menu_action_save_current_wallet.setIcon(svg_tools.get_QIcon("bi--download.svg"))

        # export wallet
        self.menu_wallet_export = self.menu_wallet.add_menu("")
        self.menu_action_export_pdf = self.menu_wallet_export.add_action(
            "", self.export_wallet_pdf, icon=svg_tools.get_QIcon("descriptor-backup.svg")
        )
        self.menu_action_export_descriptor = self.menu_wallet_export.add_action(
            "", self.show_descriptor_export_window
        )
        self.menu_action_register_multisig = self.menu_wallet_export.add_action(
            "", self.show_register_multisig
        )

        self.menu_action_open_pdf = self.menu_wallet.add_action(
            "", self.open_pdf, icon=svg_tools.get_QIcon("bi--filetype-pdf.svg")
        )
        self.menu_action_open_pdf.setShortcut(QKeySequence("CTRL+P"))

        self.menu_action_close_wallet = self.menu_wallet.add_action("", self.close_current_tab)
        self.key_sequence_close_tab = "Ctrl+W"
        self.menu_action_close_wallet.setShortcut(QKeySequence(self.key_sequence_close_tab))

        self.menu_wallet.addSeparator()
        self.menu_action_quit = self.menu_wallet.add_action("", self.quit_application)
        self.menu_action_quit.setShortcut(QKeySequence.StandardKey.Quit)

        # menu edit
        self.menu_edit = self.menubar.add_menu("")
        self.tab_history_back_shortcut = QKeySequence("Alt+Left")
        self.tab_history_forward_shortcut = QKeySequence("Alt+Right")

        self.menu_action_settings_ui = self.menu_edit.add_action(
            "",
            self.open_settings_ui,
            icon=svg_tools.get_QIcon("bi--gear.svg"),
        )
        self.menu_action_settings_ui.setShortcut(QKeySequence("CTRL+,"))

        self.menu_action_settings_network = self.menu_edit.add_action(
            "",
            self.open_network_settings,
            icon=svg_tools.get_QIcon("bi--gear.svg"),
        )
        self.menu_action_settings_network.setShortcut(QKeySequence("CTRL+."))

        self.menu_edit.addSeparator()

        # change wallet
        self.menu_action_rename_wallet = self.menu_edit.add_action("", self.change_wallet_id)
        self.menu_action_rename_wallet.setIcon(svg_tools.get_QIcon("bi--input-cursor-text.svg"))
        self.menu_action_change_password = self.menu_edit.add_action("", self.change_wallet_password)
        self.menu_action_change_password.setIcon(svg_tools.get_QIcon("ic--outline-password.svg"))

        self.menu_action_category_manager = self.menu_edit.add_action(
            "",
            self.open_category_manager,
        )

        self.menu_edit.addSeparator()
        self.menu_action_search = self.menu_edit.add_action("", self.focus_search_box)
        self.menu_action_search.setShortcut(QKeySequence("CTRL+F"))
        self.menu_action_search.setIcon(svg_tools.get_QIcon("bi--search.svg"))

        self.menu_action_search_next = self.menu_edit.add_action(
            "", self.search_box.shortcut_next.activated.emit
        )
        self.menu_action_search_next.setIcon(svg_tools.get_QIcon("bi--search.svg"))

        self.menu_action_search_previous = self.menu_edit.add_action(
            "", self.search_box.shortcut_next.activated.emit
        )
        self.menu_action_search_previous.setIcon(svg_tools.get_QIcon("bi--search.svg"))

        # menu view
        self.menu_view = self.menubar.add_menu("")

        self.menu_action_tab_history_backward = self.menu_view.add_action(
            "", self.signals.tab_history_backward.emit, icon=svg_tools.get_QIcon("bi--arrow-left-short.svg")
        )
        self.menu_action_tab_history_backward.setShortcut(self.tab_history_back_shortcut)

        self.menu_action_tab_history_forward = self.menu_view.add_action(
            "", self.signals.tab_history_forward.emit, icon=svg_tools.get_QIcon("bi--arrow-right-short.svg")
        )
        self.menu_action_tab_history_forward.setShortcut(self.tab_history_forward_shortcut)

        self.menu_view.addSeparator()

        self.menu_action_current_wallet = self.menu_view.add_action(
            "",
            partial(self.select_wallet_tab, title=None),
        )
        self.menu_action_current_wallet.setShortcut(QKeySequence("CTRL+0"))

        self.menu_current_wallet_tabs = Menu(parent=self.menu_view)
        self.menu_action_current_wallet.setMenu(self.menu_current_wallet_tabs)
        self.wallet_tab_shortcut_actions: list[QAction] = []

        self.menu_action_next_tab = self.menu_view.add_action(
            "",
            partial(self.select_relative_tab, delta=1),
            icon=svg_tools.get_QIcon("bi--arrow-down-short.svg"),
        )
        self.menu_action_next_tab.setShortcut(QKeySequence("CTRL+D"))

        self.menu_action_previous_tab = self.menu_view.add_action(
            "",
            partial(self.select_relative_tab, delta=-1),
            icon=svg_tools.get_QIcon("bi--arrow-up-short.svg"),
        )
        self.menu_action_previous_tab.setShortcut(QKeySequence("CTRL+SHIFT+D"))

        self.menu_view.addSeparator()

        self.menu_action_minimize_to_tray = self.menu_view.add_action(
            "",
            self.tray_controller.minimize_to_tray_from_menu,
        )
        self.menu_action_minimize_to_tray.setShortcut(QKeySequence("CTRL+H"))
        self.menu_action_toggle_fullscreen = self.menu_view.add_action(
            "",
            self.toggle_fullscreen,
        )
        self.menu_action_toggle_fullscreen.setShortcut(QKeySequence("F11"))

        # menu tools
        self.menu_tools = self.menubar.add_menu("")

        self.menu_action_open_qr_scanner = self.menu_tools.add_action(
            "",
            self.dialog_open_qr_scanner,
            icon=svg_tools.get_QIcon(KeyStoreImporterTypes.qr.icon_filename),
        )
        self.menu_action_open_qr_scanner.setShortcut(QKeySequence("CTRL+Y"))
        self.menu_action_message_signatures = self.menu_tools.add_action(
            "", self.show_message_signatures, icon=svg_tools.get_QIcon("material-symbols--signature.svg")
        )
        self.menu_action_open_hwi_manager = self.menu_tools.add_action(
            "",
            self.show_usb_gui,
            icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
        )
        self.menu_action_open_hwi_manager.setShortcut(QKeySequence("CTRL+M"))

        self.menu_action_check_update = self.menu_tools.add_action(
            "",
            self.update_notification_bar.check_and_make_visible,
            icon=svg_tools.get_QIcon("bi--arrow-clockwise.svg"),
        )
        self.menu_action_check_update.setShortcut(QKeySequence("CTRL+U"))

        # menu help
        self.menu_help = self.menubar.add_menu("")

        self.menu_action_about = self.menu_help.add_action("", self.open_about_tab)
        self.menu_action_donate = self.menu_help.add_action("", self.show_donate_dialog)

        self.action_knowledge_website = self.menu_help.add_action(
            "", partial(webopen, "https://bitcoin-safe.org/en/knowledge/")
        )
        self.action_knowledge_website.setShortcut(QKeySequence("F1"))
        self.menu_show_logs = self.menu_help.add_action("", self.menu_action_show_log)

        self.menu_feedback = self.menu_help.add_menu("")
        self.action_chorus = self.menu_feedback.add_action(
            "",
            partial(
                webopen,
                "https://chorus.community/group/34550%3Af8827954feef0092c8afec0be4cae544a9ed93dce9a365596e75b19aa05f0c84%3Abitcoin-safe-meiqbfki",
            ),
        )
        self.action_mail_feedback = self.menu_feedback.add_action("", mail_feedback)
        self.action_open_issue_github = self.menu_feedback.add_action(
            "", partial(webopen, "https://github.com/andreasgriffin/bitcoin-safe/issues/new")
        )

        self.menu_contact = self.menu_help.add_menu("")
        self.action_contact_email = self.menu_contact.add_action(
            "",
            mail_contact,
        )
        self.action_contact_via_nostr = self.menu_contact.add_action(
            "",
            partial(
                webopen,
                "https://yakihonne.com/profile/nprofile1qqsyz7tjgwuarktk88qvlnkzue3ja52c3e64s7pcdwj52egphdfll0cq9934g",
            ),
        )

        self.action_contact_via_X = self.menu_contact.add_action(
            "",
            partial(
                webopen,
                "https://x.com/BitcoinSafeOrg",
            ),
        )

        # assigning menu bar
        self.setMenuBar(self.menubar)

        # other shortcuts (not in menu)

        self.key_sequence_reveral_wallet_in_file_explorer: str = "Ctrl+Alt+R"
        self.shortcut_reveral_wallet_in_file_explorer = QShortcut(
            self.key_sequence_reveral_wallet_in_file_explorer, self
        )
        self.shortcut_reveral_wallet_in_file_explorer.activated.connect(
            partial(self.reveal_wallet_in_file_explorer, None)
        )

    def show_usb_gui(self):
        """Show usb gui."""
        center_on_screen(self.hwi_tool_gui)
        self.hwi_tool_gui.show()
        self.hwi_tool_gui.raise_()

    def show_message_signatures(self):
        """Open the combined message signing and verification tool."""

        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Message Signatures"))
        dialog.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        dialog.setMinimumWidth(520)

        layout = QVBoxLayout(dialog)
        widget = SignAndVerifyMessage(
            network=self.config.network,
            signals_min=self.signals,
            close_all_video_widgets=self.signals.close_all_video_widgets,
            loop_in_thread=self.loop_in_thread,
            wallet_functions=self.wallet_functions,
            parent=dialog,
        )
        layout.addWidget(widget)

        dialog.setLayout(layout)
        center_on_screen(dialog)
        dialog.show()
        dialog.raise_()
        self._message_signature_dialog = dialog

    def on_signed_message_created(self, signed_message: str) -> None:
        """Display and copy a newly signed message."""

        do_copy(signed_message, title=self.tr("Signed Message"))
        show_textedit_message(text=signed_message, label_description="", title=self.tr("Signed Message"))

    def open_category_manager(self):
        """Open category manager."""
        if not (qt_wallet := self.get_qt_wallet(if_none_serve_last_active=True)):
            return
        qt_wallet.category_manager.show()
        qt_wallet.category_manager.raise_()

    def menu_action_show_log(self):
        """Menu action show log."""
        xdg_open_file(get_log_file(), is_text_file=True)

    def quit_application(self) -> None:
        """Quit the application and terminate all processes."""
        self.close()
        QCoreApplication.quit()

    def show_donate_dialog(self) -> None:
        d = DonateDialog(
            fx=self.fx,
            loop_in_thread=self.loop_in_thread,
            signal_currency_changed=self.signals.currency_switch,
            signal_language_switch=self.signals.language_switch,
            on_about_to_close=self.signal_remove_attached_widget,
        )

        self._register_attached_widget(d)
        d.aboutToClose.connect(self.signal_remove_attached_widget)
        d.show()
        d.raise_()
        center_on_screen(d)

    def prefill_donate_onchain(self):
        """Prefill donate onchain."""
        txinfos = TxUiInfos()
        txinfos.recipients.append(Recipient(DONATION_ADDRESS, 0, label="Donation to Bitcoin Safe"))
        self.signals.open_tx_like.emit(txinfos)

    def close_current_tab(self):
        """Close current tab."""
        current_node = self.tab_wallets.currentNode()
        if not current_node:
            return

        if current_node.closable:
            self.close_tab(current_node)
            return

        if current_node.hidable:
            current_node.hideClicked.emit(current_node)
            current_node.setVisible(False)
            return

        if qt_wallet := self.get_qt_wallet(if_none_serve_last_active=False):
            self._remove_qt_wallet(qt_wallet)
            return

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        # self.updateUI()

    def updateUI(self) -> None:
        # menu
        """UpdateUI."""
        self.menu_wallet.setTitle(self.tr("&File"))
        self.menu_action_new_wallet.setText(self.tr("&New Wallet"))
        self.menu_action_open_wallet.setText(self.tr("&Open Wallet"))
        self.menu_wallet_recent.setTitle(self.tr("Open &Recent"))
        self.menu_action_save_current_wallet.setText(self.tr("&Save"))
        self.menu_action_search.setText(self.tr("&Search"))
        self.menu_action_search_next.setText(
            self.tr("Search &next\t{shortcut}").format(
                shortcut=self.search_box.shortcut_next.key().toString()
            )
        )
        self.menu_action_search_previous.setText(
            self.tr("Search &previous\t{shortcut}").format(
                shortcut=self.search_box.shortcut_prev.key().toString()
            )
        )
        self.menu_edit.setTitle(self.tr("&Edit"))
        self.menu_view.setTitle(self.tr("&View"))
        self.menu_action_tab_history_backward.setText(
            self.tr("Tab history: &Backward\t{shortcut}").format(
                shortcut=self.tab_history_back_shortcut.toString()
            )
        )
        self.menu_action_tab_history_forward.setText(
            self.tr("Tab history: &Forward\t{shortcut}").format(
                shortcut=self.tab_history_forward_shortcut.toString()
            )
        )
        self.menu_wallet_export.setTitle(self.tr("&Export"))
        self.menu_action_rename_wallet.setText(self.tr("&Wallet name"))
        self.menu_action_change_password.setText(self.tr("&Wallet password"))
        self.menu_action_export_pdf.setText(self.tr("&PDF Wallet"))
        self.menu_action_open_pdf.setText(self.tr("Print"))
        self.menu_action_close_wallet.setText(self.tr("&Close"))
        self.menu_action_export_descriptor.setText(self.tr("&Descriptor for hardware signers"))
        self.menu_action_register_multisig.setText(self.tr("&Register Multisig with hardware signers"))
        self.menu_tools.setTitle(self.tr("&Tools"))
        self.menu_action_open_hwi_manager.setText(self.tr("&USB Signer Tools"))
        self.menu_action_minimize_to_tray.setText(self.tr("&Minimize to tray"))
        self.update_fullscreen_action_text()
        self.menu_load_transaction.setTitle(self.tr("&Load Transaction or PSBT"))
        self.menu_action_open_tx_file.setText(self.tr("From &file"))
        self.menu_action_open_qr_scanner.setText(self.tr("QR &Scanner"))
        self.menu_action_message_signatures.setText(self.tr("&Message Signatures"))
        self.menu_action_open_tx_from_str.setText(self.tr("From &text"))
        self.menu_action_load_tx_from_qr.setText(self.tr("From &QR Code"))
        self.menu_action_settings_ui.setText(self.tr("&Settings"))
        self.menu_action_settings_network.setText(self.tr("&Network"))
        self.menu_action_category_manager.setText(self.tr("&Manage Categories"))
        self.menu_action_current_wallet.setText(self.tr("&Current Wallet"))
        self.rebuild_current_wallet_tab_menu()
        self.menu_action_next_tab.setText(self.tr("&Next Wallet/Tab"))
        self.menu_action_previous_tab.setText(self.tr("&Previous Wallet/Tab"))
        self.menu_action_check_update.setText(self.tr("&Check for update"))
        self.menu_show_logs.setText(self.tr("&Show Logs"))
        self.menu_action_quit.setText(self.tr("Quit"))

        self.menu_feedback.setTitle(self.tr("&Feedback"))
        self.menu_contact.setTitle(self.tr("&Contact"))
        self.action_chorus.setText(self.tr("&Community forum"))
        self.action_contact_email.setText(self.tr("&Send Email"))
        self.action_contact_via_nostr.setText(self.tr("&Nostr DM"))
        self.action_contact_via_X.setText(self.tr("&X/Twitter DM"))
        self.action_open_issue_github.setText(self.tr("&Open issue in github"))
        self.action_mail_feedback.setText(self.tr("&Send via Email"))

        self.menu_help.setTitle(self.tr("&Help"))
        self.action_knowledge_website.setText(self.tr("&Documentation"))
        self.menu_action_about.setText(self.tr("&About"))

        self.menu_action_donate.setText(self.tr("&Donate"))

        self.notification_bar_testnet.updateUi()
        self.update_notification_bar.updateUi()
        self.notification_bar_cbf.updateUi()

        self.search_box.updateUi()

    def focus_search_box(self):
        """Focus search box."""
        self.search_box.search_field.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def toggle_fullscreen(self) -> None:
        """Toggle between full screen and the previous window state."""

        if self.isFullScreen():
            self.showNormal()
            if self._was_maximized_before_fullscreen:
                self.showMaximized()
        else:
            self._was_maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()

    def rebuild_current_wallet_tab_menu(self) -> None:
        """Rebuild the Current Wallet submenu from the active wallet's tabs."""

        self.menu_current_wallet_tabs.clear()
        self.wallet_tab_shortcut_actions = []

        if not (qt_wallet := self.get_qt_wallet(if_none_serve_last_active=True)):
            return

        tab_nodes = [node for node in qt_wallet.tabs.child_nodes if node.widget and not node.isHidden()]

        for idx, node in enumerate(tab_nodes, start=1):
            action = self.menu_current_wallet_tabs.add_action(
                node.title,
                partial(self.select_wallet_tab, title=node.title),
            )
            action.setShortcut(QKeySequence(f"CTRL+{idx}"))
            self.wallet_tab_shortcut_actions.append(action)

    def select_wallet_tab(self, title: str | None) -> None:
        """Select a tab for the currently active wallet."""

        if not (qt_wallet := self.get_qt_wallet(if_none_serve_last_active=True)):
            return

        if title is None:
            qt_wallet.hist_node.select()
            return

        qt_wallet.tabs.set_current_tab_by_text(title)

    def select_relative_tab(self, delta: int) -> None:
        """Select the next or previous *top-level* tab."""

        roots = self.tab_wallets.roots
        if not roots:
            return

        current = self.tab_wallets.currentNode()
        top_level = current

        # Climb to the immediate child of the hidden master root
        while top_level and top_level.parent_node and top_level.parent_node.parent_node:
            top_level = top_level.parent_node

        try:
            current_idx = roots.index(top_level) if top_level else -1
        except ValueError:
            current_idx = -1

        if current_idx < 0:
            roots[0].select()
            return

        new_idx = (current_idx + delta) % len(roots)
        roots[new_idx].select()

    def update_fullscreen_action_text(self) -> None:
        """Update the label for the full screen menu action."""

        if hasattr(self, "menu_action_toggle_fullscreen"):
            self.menu_action_toggle_fullscreen.setText(
                self.tr("&Exit Full Screen") if self.isFullScreen() else self.tr("&Full Screen")
            )

    def populate_recent_wallets_menu(self, recently_open_wallets: Iterable[str]) -> None:
        """Populate recent wallets menu."""
        self.menu_wallet_recent.clear()

        for filepath in reversed(list(recently_open_wallets)):
            if not Path(filepath).exists():
                continue
            action = partial(self.signals.open_file_path.emit, filepath)
            self.menu_wallet_recent.add_action(os.path.basename(filepath), action)

    def change_wallet_id(self, qt_wallet: QTWallet | None = None) -> str | None:
        """Change wallet id."""
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please select the wallet"), parent=self)
            return None

        old_id = qt_wallet.wallet.id

        # ask for wallet name
        dialog = WalletIdDialog(Path(self.config.wallet_dir), prefilled=old_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_wallet_id = dialog.wallet_id
            logger.info(f"new wallet name: {new_wallet_id}")
        else:
            return None

        new_file_path = qt_wallet.change_wallet_id(new_wallet_id)
        if not new_file_path:
            logger.warning("Failed change_wallet_id")
            return None

        self.save_qt_wallet(qt_wallet)
        logger.info(f"Moved wallet to {qt_wallet.file_path}")
        self.set_title()
        return new_wallet_id

    def change_wallet_password(self, qt_wallet: QTWallet | None = None) -> None:
        """Change wallet password."""
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please select the wallet"), parent=self)
            return

        qt_wallet.change_password()

    def on_signal_broadcast_tx(self, transaction: bdk.Transaction) -> None:
        """On signal broadcast tx."""
        last_qt_wallet_involved: QTWallet | None = None
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.transaction_related_to_my_addresses(transaction):
                last_qt_wallet_involved = qt_wallet

        if last_qt_wallet_involved:
            last_qt_wallet_involved.hist_node.select()
            last_qt_wallet_involved.history_list.select_row_by_key(
                str(transaction.compute_txid()), scroll_to_last=True
            )

        # due to fulcrum delay,
        # syncing immediately after broadcast will not see the new tx.
        # So I have to wait until it is taken into the electrum server index
        QTimer.singleShot(2000, self.sync_all)
        # # the second sync is a backup, in case the first didnt catch
        # QTimer.singleShot(6000, self.sync_all)

    def sync_all(self):
        """Sync all."""
        for qt_wallet in self.qt_wallets.values():
            qt_wallet.sync()

    def _init_tray(self) -> None:
        """Init tray."""
        self.tray_controller = TrayController(parent=self)
        self.tray_controller.signal_on_close.connect(self.on_tray_close)
        self.signals.notification.connect(self.tray_controller.show_message)

    def _show_settings_window(self):
        self.settings.set_update_status(self._get_update_status())
        self.settings.show()
        self.settings.raise_()

    def open_settings_ui(self) -> None:
        """Open settings."""
        self._show_settings_window()
        self.settings.setCurrentWidget(self.settings.langauge_ui)

    def open_network_settings(self) -> None:
        self._show_settings_window()
        self.settings.setCurrentWidget(self.settings.network_settings_ui)

    def open_about_tab(self) -> None:
        """Open the About tab in settings."""
        self._show_settings_window()
        self.settings.setCurrentWidget(self.settings.about_tab)

    def show_descriptor_export_window(self, wallet: Wallet | None = None) -> None:
        """Show descriptor export window."""
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning, parent=self)
            return

        edit = qt_wallet.wallet_descriptor_ui.edit_descriptor
        d = DescriptorExport(
            convert_to_multipath_descriptor(edit.edit.text().strip(), qt_wallet.wallet.network),
            qt_wallet.signals,
            parent=self,
            network=self.config.network,
            loop_in_thread=self.loop_in_thread,
            wallet_id=qt_wallet.wallet.id,
        )
        self._register_attached_widget(d)
        d.aboutToClose.connect(self.signal_remove_attached_widget)
        d.show()
        d.raise_()

    def show_register_multisig(self, wallet: Wallet | None = None) -> None:
        """Show register multisig."""
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning, parent=self)
            return
        if not qt_wallet.wallet.is_multisig():
            Message(
                self.tr("Please select a Multisignature wallet first"), type=MessageType.Warning, parent=self
            )
            return

        edit = qt_wallet.wallet_descriptor_ui.edit_descriptor
        edit.show_register_multisig()

    def on_signal_remove_attached_widget(self, widget: QWidget):
        """On signal remove attached widget."""
        if widget in self.attached_widgets:
            self.attached_widgets.remove(widget)

    def open_pdf(self, wallet: Wallet | None = None) -> None:
        """Open a PDF export for the active view."""
        current_widget = self.tab_wallets.currentWidget()
        if isinstance(current_widget, UITx_Viewer):
            current_widget.export_data_simple.button_export_file.export_to_pdf()
            return

        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning, parent=self)
            return
        qt_wallet.export_pdf_statement()

    def export_wallet_pdf(self, wallet: Wallet | None = None) -> None:
        """Export wallet pdf."""
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning, parent=self)
            return

        make_and_open_pdf(qt_wallet.wallet, lang_code=QLocale().name())

    def open_tx_file(self, file_path: str | None = None) -> None:
        """Open tx file."""
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open Transaction/PSBT"),
                "",
                self.tr("All Files (*);;PSBT (*.psbt);;Transaction (*.tx)"),
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return

        logger.info(self.tr("Selected file: {file_path}").format(file_path=file_path))
        string_content = file_to_str(file_path)
        self.signals.open_tx_like.emit(string_content)

    def fetch_txdetails(self, txid: str) -> TransactionDetails | None:
        """Fetch txdetails."""
        for qt_wallet in self.qt_wallets.values():
            tx_details = qt_wallet.wallet.get_tx(txid)
            if tx_details:
                return tx_details
        return None

    def apply_txs_to_wallets(self, txs: list[bdk.Transaction], last_seen: int) -> None:
        for qt_wallet in self.qt_wallets.values():
            qt_wallet.apply_txs(txs, last_seen=last_seen)

    def apply_txs_to_wallets_and_highlight(self, txs: list[bdk.Transaction], last_seen: int) -> None:
        """Apply txs to wallets."""

        self.apply_txs_to_wallets(txs=txs, last_seen=last_seen)

        for qt_wallet in self.qt_wallets.values():
            txids = [str(tx.compute_txid()) for tx in txs]
            for txid in txids:
                if qt_wallet.wallet.get_tx(txid=txid):
                    self.tab_wallets.setCurrentWidget(qt_wallet)
                    qt_wallet.hist_node.select()

                    qt_wallet.history_list.select_rows(
                        txids,
                        qt_wallet.history_list.key_column,
                        role=MyItemDataRole.ROLE_KEY,
                        scroll_to_last=True,
                    )

    def apply_evicted_txs(self, txids: list[str], wallet_id: str, last_seen: int):
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return
        qt_wallet.apply_evicted_txs(txids=txids, last_seen=last_seen)

    def open_tx_like_in_tab(
        self,
        txlike: TransactionDetails
        | bdk.Transaction
        | bdk.Psbt
        | PackagedTxLike
        | TxBuilderInfos
        | TxUiInfos
        | bdk.Txid
        | bytes
        | str,
    ) -> None:
        """Open tx like in tab."""
        logger.info(f"Trying to open tx with type {type(txlike)}")
        focus_ui_element = UiElements.none

        # unpackage PackagedTxLike
        if isinstance(txlike, PackagedTxLike):
            focus_ui_element = txlike.focus_ui_elements
            txlike = txlike.tx_like

        # first do the bdk instance cases
        if isinstance(txlike, (TransactionDetails, bdk.Transaction)):
            self.open_tx_in_tab(txlike, focus_ui_element=focus_ui_element)
            return None

        if isinstance(txlike, (bdk.Psbt, TxBuilderInfos)):
            self.open_psbt_in_tab(txlike)
            return None

        if isinstance(txlike, TxUiInfos):
            wallet = ToolsTxUiInfo.get_likely_source_wallet(txlike, self.wallet_functions)

            if not wallet:
                logger.info(
                    "Could not identify the wallet belonging to the transaction inputs. Trying to open anyway..."
                )
                current_qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
                wallet = current_qt_wallet.wallet if current_qt_wallet else None
            if not wallet:
                Message(
                    self.tr("No wallet open. Please open the sender wallet to edit this transaction."),
                    parent=self,
                )
                return None

            qt_wallet = self.qt_wallets.get(wallet.id)
            if not qt_wallet:
                Message(self.tr(" Please open the sender wallet to edit this transaction."), parent=self)
                return None
            self.tab_wallets.setCurrentWidget(qt_wallet)
            qt_wallet.tabs.setCurrentWidget(qt_wallet.uitx_creator)

            ToolsTxUiInfo.pop_change_recipient(txlike, wallet)

            qt_wallet.uitx_creator.set_ui(txlike)
            return None

        # try to convert a bytes like object to a string
        if isinstance(txlike, bytes):
            if txlike[:5] == b"psbt\xff":
                # convert a psbt in the default base64 encoding
                txlike = base64.encodebytes(txlike).decode()
                txlike = txlike.replace("\n", "").strip()
            else:
                # try to convert to str
                txlike = str(txlike)

        if isinstance(txlike, bdk.Txid):
            txlike = str(txlike)

        if isinstance(txlike, str):
            try:
                res = Data.from_str(txlike, network=self.config.network)
            except Exception as e:
                logger.debug(f"{self.__class__.__name__}: {e}")
                Message(self.tr("Could not decode this string"), type=MessageType.Error, parent=self)
                return None
            if res.data_type == DataType.Txid:
                txdetails = self.fetch_txdetails(res.data)
                if txdetails:
                    self.open_tx_in_tab(txdetails, focus_ui_element=focus_ui_element)
                    return None
                if not txlike:
                    raise Exception(f"txid {res.data} could not be found in wallets")
            elif res.data_type == DataType.PSBT:
                self.open_psbt_in_tab(res.data)
                return None
            elif res.data_type == DataType.Tx:
                self.open_tx_in_tab(res.data, focus_ui_element=focus_ui_element)
                return None
            else:
                logger.warning(f"DataType {res.data_type.name} was not handled.")
        return None

    def _result_callback_load_tx_like_from_qr(self, data: Data) -> None:
        """Result callback load tx like from qr."""
        if data.data_type in [
            DataType.PSBT,
            DataType.Tx,
            DataType.Txid,
        ]:
            self.signals.open_tx_like.emit(data.data)

    def load_tx_like_from_qr(self) -> None:
        """Load tx like from qr."""
        self.signals.close_all_video_widgets.emit()
        d = BitcoinVideoWidget()
        d.aboutToClose.connect(self.signal_remove_attached_widget)
        self._register_attached_widget(d)
        d.signal_data.connect(self._result_callback_load_tx_like_from_qr)
        d.signal_recognize_exception.connect(self._load_tx_like_from_qr_exception_callback)
        center_on_screen(d)
        d.show()
        d.raise_()
        return None

    def _load_tx_like_from_qr_exception_callback(self, e: Exception) -> None:
        """Load tx like from qr exception callback."""
        if isinstance(e, DecodingException):
            if question_dialog(self.tr("Could not recognize the input. Do you want to scan again?")):
                self.load_tx_like_from_qr()
            else:
                return
        else:
            Message(f"{type(e).__name__}\n{e}", type=MessageType.Error, parent=self)

    def dialog_open_qr_scanner(self) -> None:
        """Dialog open qr scanner."""
        self._qr_scanner = SimpleQrScanner(
            network=self.config.network,
            close_all_video_widgets=self.signals.close_all_video_widgets,
            title=self.tr("QR Scanner"),
        )
        self._register_attached_widget(self._qr_scanner)
        self._qr_scanner.aboutToClose.connect(self.signal_remove_attached_widget)

    def dialog_open_tx_from_str(self) -> ImportDialog:
        """Dialog open tx from str."""
        tx_dialog = ImportDialog(
            network=self.config.network,
            on_open=self.signals.open_tx_like.emit,
            window_title=self.tr("Open Transaction or PSBT"),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr(
                "Please paste your Bitcoin Transaction or PSBT in here, or drop a file"
            ),
            text_placeholder=self.tr("Paste your Bitcoin Transaction or PSBT in here or drop a file"),
            close_all_video_widgets=self.signals.close_all_video_widgets,
        )
        tx_dialog.aboutToClose.connect(self.signal_remove_attached_widget)
        self._register_attached_widget(tx_dialog)
        tx_dialog.show()
        tx_dialog.raise_()
        return tx_dialog

    def get_tx_viewer(self, txid: str) -> UITx_Viewer | None:
        """Get tx viewer."""
        for root in self.tab_wallets.roots:
            if isinstance(root.data, UITx_Viewer) and txid == root.data.txid():
                return root.data
        return None

    def open_tx_in_tab(self, txlike: bdk.Transaction | TransactionDetails, focus_ui_element=UiElements.none):
        """Open tx in tab."""
        tx: bdk.Transaction | None = None
        fee = None
        chain_position = None

        if isinstance(txlike, bdk.Transaction):
            # try to get all details from wallets
            tx_details = self.fetch_txdetails(str(txlike.compute_txid()))
            if tx_details and are_txs_identical(tx_details.transaction, txlike):
                txlike = tx_details

        if isinstance(txlike, TransactionDetails):
            logger.debug("Got a PartiallySignedTransaction")
            tx = txlike.transaction
            fee = txlike.fee
            if fee is None and txlike.transaction.is_coinbase():
                fee = 0
            chain_position = txlike.chain_position
        elif isinstance(txlike, bdk.Transaction):
            tx = txlike

        if not tx:
            logger.error("could not open tx")
            return None

        data = Data.from_tx(tx, network=self.config.network)
        existing_tx_viewer = self.get_tx_viewer(txid=str(tx.compute_txid()))

        # check if the same tab with exactly the same data is open already
        if existing_tx_viewer:
            # if the tab_data is a tx, then just dismiss the tx
            if existing_tx_viewer.data.data_type == DataType.Tx:
                existing_tx_viewer.set_tab_focus(focus_ui_element=focus_ui_element)
                self.tab_wallets.setCurrentWidget(existing_tx_viewer)
                return None
            # if tab_data is a psbt, then add the signature from tx
            if existing_tx_viewer.data.data_type == DataType.PSBT:
                existing_tx_viewer.tx_received(tx)
                existing_tx_viewer.set_tab_focus(focus_ui_element=focus_ui_element)
                self.tab_wallets.setCurrentWidget(existing_tx_viewer)
                return None

        utxo_list = UTXOList(
            config=self.config,
            wallet_functions=self.wallet_functions,
            outpoints=get_prev_outpoints(tx),
            fx=self.fx,
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                # UTXOList.Columns.PARENTS,
            ],
            # the ADDRESS. ROLE SORT ORDER saves the order of the get_outpoints
            sort_column=UTXOList.Columns.ADDRESS,
            sort_order=Qt.SortOrder.AscendingOrder,
        )

        widget_utxo_with_toolbar = UtxoListWithToolbar(utxo_list, self.config, self.tab_wallets)

        viewer = UITx_Viewer(
            self.config,
            self.wallet_functions,
            self.fx,
            widget_utxo_with_toolbar,
            network=self.config.network,
            mempool_manager=self.mempool_manager,
            fee_info=(
                FeeInfo(fee, tx.vsize(), vsize_is_estimated=False, fee_amount_is_estimated=False)
                if fee is not None
                else None
            ),
            chain_position=chain_position,
            client=self.get_client_of_any_wallet(),
            data=data,
            parent=self,
            focus_ui_element=focus_ui_element,
        )

        self.tab_wallets.root.addChildNode(
            SidebarNode(icon=None, title="", data=viewer, widget=viewer, closable=True)
        )
        viewer.set_tab_properties(chain_position=chain_position)

    def open_psbt_in_tab(
        self,
        tx: bdk.Psbt | TxBuilderInfos | str | TransactionDetails,
    ):
        """Open psbt in tab."""
        psbt: bdk.Psbt | None = None
        fee_info: FeeInfo | None = None

        logger.debug(f"tx is of type {type(tx)}")

        try:
            # converting to TxBuilderResult
            if isinstance(tx, TxBuilderInfos):
                if not fee_info and (tx.fee_rate is not None):
                    fee_info = FeeInfo.from_fee_rate(
                        fee_amount=tx.psbt.fee(),
                        fee_rate=tx.fee_rate,
                        fee_rate_is_estimated=False,
                        fee_amount_is_estimated=False,
                    )

                tx = tx.psbt
                logger.debug(f"Converted TxBuilderInfos --> {type(tx)}")

            if isinstance(tx, bdk.Psbt):
                logger.debug("Got a PartiallySignedTransaction")
                psbt = tx
                if not fee_info:
                    fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

            if isinstance(tx, str):
                psbt = bdk.Psbt(tx)
                logger.debug(f"Converted str to {type(tx)}")
                if not fee_info:
                    fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

            if isinstance(tx, TransactionDetails):
                logger.debug("is bdk.TransactionDetails")
                raise Exception("cannot handle TransactionDetails")

            if not psbt:
                logger.error("tx could not be converted to a psbt")
                return None

            data = Data.from_psbt(psbt, network=self.config.network)

            # check if any wallet has all the inputs for the tx, then i can calulate the fee_rate approximately
            if not fee_info:
                for root in self.tab_wallets.roots:
                    if isinstance(root, QTWallet):
                        wallet = root.wallet
                        try:
                            fee_rate = FeeRate.from_fee_rate(
                                wallet.bdkwallet.calculate_fee_rate(tx=psbt.extract_tx())
                            )
                            fee_amount = psbt.fee()
                            fee_info = FeeInfo.from_fee_rate(
                                fee_amount=fee_amount,
                                fee_rate=fee_rate.to_sats_per_vb(),
                                fee_rate_is_estimated=False,
                                fee_amount_is_estimated=False,
                            )
                        except Exception:
                            pass
        except bdk.ExtractTxError.MissingInputValue as e:
            Message(
                self.tr("Could not open PSBT, because it lacks the input UTXOs.")
                + f"\n{type(e).__name__}\n{e}",
                type=MessageType.Error,
                parent=self,
            )
            return None
        except Exception as e:
            Message(
                self.tr("Could not open PSBT") + f"\n{type(e).__name__}\n{e}",
                type=MessageType.Error,
                parent=self,
            )
            return None

        if not isinstance(data.data, bdk.Psbt):
            logger.warning(f"wrong datatype {type(data.data)=}")
            return None

        existing_tx_viewer = self.get_tx_viewer(txid=str(data.data.extract_tx().compute_txid()))
        if existing_tx_viewer:
            # if the tab_data is a tx, then just dismiss the psbt (a tx is better than a psbt)
            if existing_tx_viewer.data.data_type == DataType.Tx:
                self.tab_wallets.setCurrentWidget(existing_tx_viewer)
                return None
            # if tab_data is a psbt, then add the signature from data
            if existing_tx_viewer.data.data_type == DataType.PSBT:
                existing_tx_viewer.import_untrusted_psbt(psbt)
                self.tab_wallets.setCurrentWidget(existing_tx_viewer)
                return None

        utxo_list = UTXOList(
            config=self.config,
            wallet_functions=self.wallet_functions,
            outpoints=get_prev_outpoints(psbt.extract_tx()),
            fx=self.fx,
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                # UTXOList.Columns.PARENTS,
            ],
            txout_dict=SimplePSBT.from_psbt(psbt).get_prev_txouts(),
            # the ADDRESS. ROLE SORT ORDER saves the order of the get_outpoints
            sort_column=UTXOList.Columns.ADDRESS,
            sort_order=Qt.SortOrder.AscendingOrder,
        )

        widget_utxo_with_toolbar = UtxoListWithToolbar(utxo_list, self.config, parent=self.tab_wallets)

        viewer = UITx_Viewer(
            config=self.config,
            wallet_functions=self.wallet_functions,
            fx=self.fx,
            widget_utxo_with_toolbar=widget_utxo_with_toolbar,
            network=self.config.network,
            mempool_manager=self.mempool_manager,
            fee_info=fee_info,
            client=self.get_client_of_any_wallet(),
            data=data,
            parent=self,
        )

        self.tab_wallets.root.addChildNode(
            SidebarNode(icon=None, title="", data=viewer, widget=viewer, closable=True)
        )
        viewer.set_tab_properties(chain_position=None)

    def open_last_opened_wallets(self) -> list[QTWallet]:
        """Open last opened wallets."""
        opened_wallets: list[QTWallet] = []
        wallet_files = self.config.last_wallet_files.get(str(self.config.network), [])
        if platform.system().lower() == "darwin" and len(wallet_files) > MAC_OPEN_WALLET_LIMIT:
            logger.info(
                f"macOS detected. Limiting restored wallets on startup to {MAC_OPEN_WALLET_LIMIT} to avoid file descriptor limits."
            )
            wallet_files = wallet_files[:MAC_OPEN_WALLET_LIMIT]

        for file_path in wallet_files:
            qt_wallet = self.open_wallet(file_path=str(rel_home_path_to_abs_path(file_path)), focus=False)
            if qt_wallet:
                opened_wallets.append(qt_wallet)
        return opened_wallets

    def open_last_opened_tx(self) -> None:
        """Open last opened tx."""
        for serialized in self.config.opened_txlike.get(str(self.config.network), []):
            self.open_tx_like_in_tab(serialized)

    def open_wallets(self, focus=True):
        """Open wallets."""
        if platform.system().lower() == "darwin":
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open Wallet"),
                self.config.wallet_dir,
                self.tr("Wallet Files (*.wallet);;All Files (*)"),
            )
            file_paths = [file_path] if file_path else []
        else:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                self.tr("Open Wallet"),
                self.config.wallet_dir,
                self.tr("Wallet Files (*.wallet);;All Files (*)"),
            )
        if not file_paths:
            logger.info(self.tr("No file selected"))
            return None
        for file_path in file_paths:
            self.open_wallet(file_path=file_path, focus=focus)

    def open_wallet(self, file_path: str | None = None, focus=True) -> QTWallet | None:
        """Open wallet."""
        if platform.system().lower() == "darwin" and len(self.qt_wallets) >= MAC_OPEN_WALLET_LIMIT:
            Message(
                self.tr("On macOS only {n} wallets can be opened at the same time").format(
                    n=MAC_OPEN_WALLET_LIMIT
                ),
                type=MessageType.Warning,
                parent=self,
            )
            return None

        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open Wallet"),
                self.config.wallet_dir,
                self.tr("Wallet Files (*.wallet);;All Files (*)"),
            )
            if not file_path:
                logger.info(self.tr("No file selected"))
                return None

        # make sure this wallet isn't open already by this instance
        opened_file_paths = [qt_wallet.file_path for qt_wallet in self.qt_wallets.values()]
        if file_path in opened_file_paths:
            Message(
                self.tr("The wallet {file_path} is already open.").format(file_path=file_path), parent=self
            )
            return None

        wallet_file_path = Path(file_path)
        wallet_lockfile_path = QTWallet.get_wallet_lockfile_path(wallet_file_path)
        if wallet_lockfile_path.exists():
            if not question_dialog(
                self.tr(
                    "The wallet {file_path} is already open.  Do you want to open the wallet anyway?"
                ).format(file_path=file_path),
                title=self.tr("Wallet already open"),
                true_button=self.tr("Open anyway"),
            ):
                return None

        logger.info(f"Selected file: {file_path}")
        if not os.path.isfile(file_path):
            Message(
                self.tr("There is no such file: {file_path}").format(file_path=file_path),
                type=MessageType.Error,
                parent=self,
            )
            return None

        def try_load_without_error(password: str | None) -> QTWallet | tuple[Exception, OptExcInfo]:
            """Try load without error."""
            try:
                return QTWallet.from_file(
                    file_path=file_path,
                    config=self.config,
                    password=password,
                    wallet_functions=self.wallet_functions,
                    mempool_manager=self.mempool_manager,
                    fx=self.fx,
                    loop_in_thread=self.loop_in_thread,
                )
            except Exception as e:
                return e, sys.exc_info()

        def try_load(file_path: str) -> tuple[QTWallet | None, str | None]:
            """Try load."""

            password = None
            if not Storage().has_password(file_path):
                result = try_load_without_error(password=None)
                if isinstance(result, QTWallet):
                    return result, password

            if password := self.password_cache.get_password("wallet"):
                result = try_load_without_error(password=password)
                if isinstance(result, QTWallet):
                    return result, password

            _, filename = os.path.split(file_path)
            ui_password_question = PasswordQuestion(
                label_text=self.tr("Please enter the password for {filename}:").format(filename=filename)
            )
            while True:
                password = ui_password_question.ask_for_password()
                if password is None:
                    return None, None

                result = try_load_without_error(password=password)
                if isinstance(result, QTWallet):
                    return result, password
                if isinstance(result, tuple):
                    e, exc_info = result
                    # the file could also be corrupted, but the "wrong password" is by far the likliest
                    caught_exception_message(
                        e,
                        "Wrong password. Wallet could not be loaded.",
                        exc_info=exc_info,
                        parent=self,
                    )
                    continue
                return None, password  # type: ignore[unreachable]

        if (_guess_wallet_id := Path(file_path).stem) in self.qt_wallets:
            Message(
                self.tr("A wallet with id {name} is already open. Please close it first.").format(
                    name=_guess_wallet_id
                ),
                parent=self,
            )
            return None

        qt_wallet, password = try_load(file_path=file_path)
        if not qt_wallet:
            return None

        if qt_wallet and password:
            # successfuly load, then cache the password
            self.password_cache.set_password("wallet", password)

        if not QTWallet.get_wallet_lockfile(wallet_file_path):
            logger.warning(
                f"Could not create lock file {wallet_lockfile_path} after loading wallet {file_path}"
            )

        qt_wallet = self.add_qt_wallet(qt_wallet, file_path=file_path, password=password, focus=focus)
        QApplication.processEvents()
        qt_wallet.restore_last_selected_tab()
        qt_wallet.sync()

        self.add_recently_open_wallet(qt_wallet.file_path)
        return qt_wallet

    def save_qt_wallet(self, qt_wallet: QTWallet | None = None) -> None:
        """Save qt wallet."""
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.save()
            self.add_recently_open_wallet(qt_wallet.file_path)

    def save_all_wallets(self) -> None:
        """Save all wallets."""
        for qt_wallet in self.qt_wallets.values():
            self.save_qt_wallet(qt_wallet=qt_wallet)

    def write_current_open_txs_to_config(self) -> None:
        """Write current open txs to config."""
        txs = []

        for root in self.tab_wallets.roots:
            if isinstance(root.data, UITx_Viewer):
                txs.append(root.data.data.data_as_string())

        self.config.opened_txlike[str(self.config.network)] = txs
        if current_node := self.tab_wallets.currentNode():
            self.config.last_tab_title = current_node.get_nested_titles()

    def click_create_single_signature_wallet(self) -> None:
        """Click create single signature wallet."""
        qt_protowallet = self.create_qtprotowallet((1, 1), show_tutorial=True)
        if qt_protowallet:
            qt_protowallet.wallet_descriptor_ui.disable_fields()

    def click_create_multisig_signature_wallet(self) -> None:
        """Click create multisig signature wallet."""
        qt_protowallet = self.create_qtprotowallet((2, 3), show_tutorial=True)
        if qt_protowallet:
            qt_protowallet.wallet_descriptor_ui.disable_fields()

    def click_custom_signature(self) -> None:
        """Click custom signature."""
        self.create_qtprotowallet((3, 5), show_tutorial=False)

    def new_wallet(self) -> None:
        """New wallet."""
        self.welcome_screen.add_new_wallet_welcome_tab(self.tab_wallets)

    def new_wallet_id(self) -> str:
        """New wallet id."""
        return f"{self.tr('new')}{len(self.qt_wallets)}"

    def _ask_if_full_scan(self) -> bool | None:
        return question_dialog(
            text=self.tr("Was this wallet ever used before?"),
            true_button=self.tr("Yes, full scan for transactions"),
            false_button=self.tr("No, quick scan"),
        )

    def create_qtwallet_from_protowallet(
        self, protowallet: ProtoWallet, tutorial_index: int | None
    ) -> QTWallet:
        """Create qtwallet from protowallet."""
        is_new_wallet = False
        if self.config.network_config.server_type == BlockchainType.CompactBlockFilter:
            answer = self._ask_if_full_scan()
            if answer is False:
                is_new_wallet = True
            else:
                is_new_wallet = False

        wallet = Wallet.from_protowallet(
            protowallet,
            self.config,
            default_category=get_default_categories()[0],
            is_new_wallet=is_new_wallet,
            loop_in_thread=self.loop_in_thread,
        )
        file_path = None
        password = None
        qt_wallet = QTWallet(
            wallet,
            self.config,
            self.wallet_functions,
            self.mempool_manager,
            self.fx,
            file_path=file_path,
            password=password,
            tutorial_index=tutorial_index,
            parent=self,
            loop_in_thread=self.loop_in_thread,
        )

        qt_wallet = self.add_qt_wallet(qt_wallet, file_path=file_path, password=password)
        # adding these should only be done at wallet creation
        qt_wallet.category_core.add_default_categories()
        qt_wallet.uitx_creator.clear_ui()  # after the categories are updtaed, this selected the default category in the send tab
        self.save_qt_wallet(qt_wallet)
        qt_wallet.sync()
        return qt_wallet

    def create_qtwallet_from_ui(
        self,
        root_node: SidebarNode,
        protowallet: ProtoWallet,
        keystore_uis: KeyStoreUIs,
        tutorial_index: int | None,
    ) -> None:
        """Create qtwallet from ui."""
        try:
            if keystore_uis.ask_accept_unexpected_origins():
                qt_wallet = self.create_qtwallet_from_protowallet(
                    protowallet=protowallet, tutorial_index=tutorial_index
                )
                self.close_tab(root_node)
                if qt_wallet.history_tab.isVisible():
                    qt_wallet.tabs.setCurrentWidget(qt_wallet.history_tab)

            else:
                return
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            Message(str(e), type=MessageType.Error, parent=self)

    def create_qtwallet_from_qtprotowallet(
        self, root_node: SidebarNode, qt_protowallet: QTProtoWallet
    ) -> None:
        """Create qtwallet from qtprotowallet."""
        self.create_qtwallet_from_ui(
            root_node=root_node,
            protowallet=qt_protowallet.protowallet,
            keystore_uis=qt_protowallet.wallet_descriptor_ui.keystore_uis,
            tutorial_index=(
                qt_protowallet.tutorial_index + 1
                if qt_protowallet.tutorial_index is not None
                else qt_protowallet.tutorial_index
            ),
        )

    def create_qtprotowallet(
        self, m_of_n: tuple[int, int], show_tutorial: bool = False
    ) -> QTProtoWallet | None:
        # ask for wallet name
        """Create qtprotowallet."""
        dialog = WalletIdDialog(Path(self.config.wallet_dir))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            wallet_id = dialog.wallet_id
            logger.info(f"new wallet name: {wallet_id}")
        else:
            return None

        m, n = m_of_n
        protowallet = ProtoWallet(
            threshold=m,
            keystores=[None for i in range(n)],
            network=self.config.network,
            wallet_id=wallet_id,
        )

        qt_protowallet = QTProtoWallet(
            config=self.config,
            wallet_functions=self.wallet_functions,
            protowallet=protowallet,
            loop_in_thread=self.loop_in_thread,
        )

        qt_protowallet.tabs.setIcon(svg_tools.get_QIcon("file.svg"))
        qt_protowallet.tabs.setTitle(qt_protowallet.protowallet.id)

        qt_protowallet.signal_close_wallet.connect(self.on_signal_close_qtprotowallet)
        qt_protowallet.signal_create_wallet.connect(self.on_signal_create_qtprotowallet)
        self.tab_wallets.root.addChildNode(qt_protowallet.tabs)

        # tutorial
        wizard = Wizard(
            qtwalletbase=qt_protowallet,
        )
        qt_protowallet.wizard = wizard
        qt_protowallet.wizard.signal_create_wallet.connect(
            partial(self.create_qtwallet_from_protowallet_from_wizard_keystore, wizard)
        )

        if show_tutorial:
            qt_protowallet.wizard.set_current_index(0)
            qt_protowallet.wizard.set_visibilities()
        else:
            qt_protowallet.tabs.select()

        return qt_protowallet

    def create_qtwallet_from_protowallet_from_wizard_keystore(self, wizard: Wizard, protowallet_id: str):
        """The keystore from the wizard UI are the ones used for walle creation.

        It is checked if qt_protowallet.protowallet  is consitent with the UI of the wizard

        Args:
            protowallet_id (str): _description_

        Returns:
            _type_: _description_
        """
        node = self.get_node(wallet_id=protowallet_id)
        if not node:
            logger.error(f"Could not find node with {protowallet_id=}")
            return
        if not isinstance(node.data, QTProtoWallet):
            logger.error(f"wrong type  {type(node.data)=}. Not wizard")
            return
        qt_protowallet = node.data

        assert qt_protowallet.protowallet.id == protowallet_id

        if not isinstance(
            tab_import_xpub := wizard.tab_generators.get(TutorialStep.import_xpub), ImportXpubs
        ):
            logger.error("tab_import_xpub is not of type ImportXpubs")  # type: ignore[unreachable]
            return None

        if not tab_import_xpub.keystore_uis:
            Message(
                "Cannot create wallet, because no keystores are available",
                type=MessageType.Error,
                parent=self,
            )
            return

        org_protowallet = qt_protowallet.protowallet
        tab_import_xpub.keystore_uis.set_protowallet_from_keystore_ui()
        if org_protowallet.get_differences(qt_protowallet.protowallet).has_impact_on_addresses():
            Message("QtProtowallet inconsitent. Cannot create wallet", type=MessageType.Error, parent=self)
            return

        self.create_qtwallet_from_ui(
            root_node=node,
            protowallet=qt_protowallet.protowallet,
            keystore_uis=tab_import_xpub.keystore_uis,
            tutorial_index=qt_protowallet.tutorial_index,
        )

    def on_signal_close_qtprotowallet(self, wallet_id: str):
        """On signal close qtprotowallet."""
        node = self.get_node(wallet_id=wallet_id)
        if not node:
            logger.error(f"Could not find node with {wallet_id=}")
            return
        self.close_tab(node)

    def on_signal_create_qtprotowallet(self, wallet_id: str):
        """On signal create qtprotowallet."""
        node = self.get_node(wallet_id=wallet_id)
        if not node:
            logger.error(f"Could not find node with {wallet_id=}")
            return

        if not isinstance(node.data, QTProtoWallet):
            logger.error(f"wrong type  {type(node.data)=}. Not QTProtoWallet")
            return

        self.create_qtwallet_from_qtprotowallet(root_node=node, qt_protowallet=node.data)

    def on_set_tab_properties(self, tab: object, tab_text: str, icon_name: str, tooltip: str) -> None:
        """On set tab properties."""
        for root in self.tab_wallets.roots:
            if root.data == tab:
                root.setTitle(tab_text)
                root.setIcon(svg_tools.get_QIcon(icon_name))

                if (
                    isinstance(tab, QTWallet)
                    and self.config.network_config.p2p_listener_type != P2pListenerType.deactive
                ):
                    tooltip += "\n" + (
                        self.tr("Monitoring the p2p bitcoin network via the proxy {proxy}").format(
                            proxy=self.config.network_config.proxy_url
                        )
                        if self.config.network_config.proxy_url
                        else self.tr("Monitoring the p2p bitcoin network")
                    )

                root.setToolTip(tooltip if tooltip else "")
                logger.debug(f"on_set_tab_properties {tab_text=} {icon_name=} {tooltip=}")

    def add_qt_wallet(
        self,
        qt_wallet: QTWallet,
        file_path: str | None = None,
        password: str | None = None,
        focus: bool = True,
    ) -> QTWallet:
        """Add qt wallet."""
        assert qt_wallet.wallet.id not in self.qt_wallets, self.tr(
            "A wallet with id {name} is already open.  "
        ).format(name=qt_wallet.wallet.id)

        qt_wallet.password = password
        if file_path:
            # very important! it saves the (possibly) new location into the qtwallet, such that
            # it can save exactly there again
            qt_wallet.file_path = file_path

        qt_wallet.tabs.setIcon(svg_tools.get_QIcon("status_waiting.svg"))
        qt_wallet.tabs.setTitle(qt_wallet.wallet.id)

        with LoadingWalletTab(self.tab_wallets, qt_wallet.wallet.id, focus=True):
            self.welcome_screen.remove_me()
            # tutorial
            wizard = Wizard(
                qtwalletbase=qt_wallet,
                qt_wallet=qt_wallet,
            )
            qt_wallet.wizard = wizard

        self.tab_wallets.root.addChildNode(qt_wallet.tabs, focus=focus)

        if qt_wallet.tutorial_index is not None:
            qt_wallet.wizard.set_current_index(qt_wallet.tutorial_index)

        if qt_wallet.wizard.should_be_visible:
            qt_wallet.wizard.set_visibilities()
            qt_wallet.wizard.node.select()

        self.language_chooser.add_signal_language_switch(self.signals.language_switch)
        self.wallet_functions.wallet_signals[qt_wallet.wallet.id].show_address.connect(self.show_address)
        self.signals.event_wallet_tab_added.emit()

        self.p2p_listening_update_lists(UpdateFilter())

        # this is a
        self.last_qtwallet = qt_wallet
        return qt_wallet

    def toggle_tutorial(self, qt_wallet: QTWallet | None = None) -> None:
        """Toggle tutorial."""
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please complete the wallet setup."), parent=self)
            return

        if qt_wallet.wizard:
            qt_wallet.wizard.toggle_tutorial()

    def _get_qt_base_wallet(
        self,
        qt_base_wallets: Iterable[QtWalletBase],
        if_none_serve_last_active=False,
    ) -> QtWalletBase | None:
        """Get qt base wallet."""
        widget = self.tab_wallets.currentWidget()
        for qt_base_wallet in qt_base_wallets:
            if widget and qt_base_wallet.tabs.findNodeByWidget(widget):
                return qt_base_wallet
        if if_none_serve_last_active:
            return self.last_qtwallet
        return None

    def get_qt_wallet(self, if_none_serve_last_active: bool = False) -> QTWallet | None:
        """Get qt wallet."""
        base_wallet = self._get_qt_base_wallet(
            self.qt_wallets.values(), if_none_serve_last_active=if_none_serve_last_active
        )
        if isinstance(base_wallet, QTWallet):
            return base_wallet
        return None

    def get_client_of_any_wallet(self) -> Client | None:
        """Get client of any wallet."""
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.client:
                return qt_wallet.wallet.client
        return None

    def show_address(self, addr: str, wallet_id: str, parent: QWidget | None = None) -> None:
        """Show address."""
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return

        d = address_dialog.AddressDialog(
            fx=self.fx,
            config=self.config,
            wallet_functions=self.wallet_functions,
            wallet=qt_wallet.wallet,
            address=addr,
            mempool_manager=self.mempool_manager,
            parent=parent,
            loop_in_thread=self.loop_in_thread,
        )
        d.aboutToClose.connect(self.signal_remove_attached_widget)
        self._register_attached_widget(d)
        d.show()
        d.raise_()

    def event_wallet_tab_closed(self) -> None:
        """Event wallet tab closed."""
        if not self.tab_wallets.count():
            self.welcome_screen.add_new_wallet_welcome_tab(self.tab_wallets)
        # necessary to remove old qt_wallets from memory
        self.rebuild_current_wallet_tab_menu()

    def event_wallet_tab_added(self) -> None:
        """Event wallet tab added."""
        self.rebuild_current_wallet_tab_menu()

    def remove_qt_wallet_by_id(self, wallet_id: str) -> None:
        """Remove qt wallet by id."""
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return
        self._remove_qt_wallet(qt_wallet=qt_wallet)

    def _remove_qt_protowallet(self, qt_protowallet: QTProtoWallet | None) -> None:
        """Remove qt protowallet."""
        if not qt_protowallet:
            return
        for root in self.tab_wallets.roots:
            if root.data == qt_protowallet:
                root.removeNode()

        qt_protowallet.close()
        self.event_wallet_tab_closed()

    def _remove_qt_wallet(self, qt_wallet: QTWallet | None) -> None:
        """Remove qt wallet."""
        if not qt_wallet:
            return
        for root in self.tab_wallets.roots:
            if root.data == qt_wallet:
                root.removeNode()
                root.data = None

        self.add_recently_open_wallet(qt_wallet.file_path)

        if self.last_qtwallet == qt_wallet:
            self.last_qtwallet = None
        qt_wallet.close()
        QTWallet.remove_lockfile(wallet_file_path=Path(qt_wallet.file_path))
        self.event_wallet_tab_closed()
        self.p2p_listening_update_lists(UpdateFilter())

    def add_recently_open_wallet(self, file_path: str) -> None:
        """Add recently open wallet."""
        self.config.add_recently_open_wallet(file_path)
        self.signal_recently_open_wallet_changed.emit(
            list(self.config.recently_open_wallets[self.config.network])
        )

    def remove_all_qt_wallet(self) -> None:
        """Remove all qt wallet."""
        for qt_wallet in self.qt_wallets.copy().values():
            self._remove_qt_wallet(qt_wallet)

    def _ask_if_wallet_should_remain_open(self) -> bool | None:
        return question_dialog(
            text=self.tr(
                "This wallet is still syncing and syncing would need to start from scratch if you close it.\nDo you want to keep the wallet open?",
            ),
            title=self.tr("Wallet syncing"),
            true_button=self.tr("Keep open"),
            false_button=self.tr("Close anyway"),
        )

    def close_tab(self, node: SidebarNode[TT]) -> None:
        """Close tab."""
        if not node.closable and not node.widget == self.welcome_screen:
            return
        tab_data = node.data
        if isinstance(tab_data, QTWallet):
            if tab_data.is_in_cbf_ibd():
                res = self._ask_if_wallet_should_remain_open()
                if res is None:
                    return
                elif res is True:
                    return
                elif res is False:
                    pass
            else:
                if not question_dialog(
                    self.tr("Close wallet {id}?").format(id=tab_data.wallet.id),
                    self.tr("Close wallet"),
                    true_button=self.tr("Close"),
                ):
                    return

            logger.info(f"Closing wallet {tab_data.wallet.id}")
            self.save_qt_wallet(tab_data)
            self._remove_qt_wallet(tab_data)
        elif isinstance(tab_data, QTProtoWallet):
            tab_data.close()
            self._remove_qt_protowallet(tab_data)
        elif isinstance(tab_data, UITx_Viewer):
            if isinstance(tab_data.data.data, bdk.Psbt) and question_dialog(
                self.tr("Do you want to save the PSBT {id}?").format(
                    id=short_tx_id(tab_data.data.data.extract_tx().compute_txid())
                ),
                self.tr("Save PSBT?"),
                true_button=self.tr("Save"),
                false_button=QMessageBox.StandardButton.No,
            ):
                tab_data.export_data_simple.button_export_file.export_to_file()
            logger.info(self.tr("Closing tab {name}").format(name=node.title))
            tab_data.close()
        else:
            logger.info(self.tr("Closing tab {name}").format(name=node.title))

        node.removeNode()
        del node.data

        # other events
        self.event_wallet_tab_closed()

    def manual_sync(self) -> None:
        """Manual sync."""
        self.sync(reason="Manual sync")

    def sync(self, reason: str) -> None:
        """Sync."""
        logger.info(f"{self.__class__.__name__}.sync {reason=}")
        qt_wallet = self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.sync()

    def get_qt_wallets_in_cbf_ibd(self) -> list[QTWallet]:
        """Get qt wallets in cbf ibd."""
        qt_wallets: list[QTWallet] = []
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.is_in_cbf_ibd():
                qt_wallets.append(qt_wallet)
        return qt_wallets

    def on_tray_close(self):
        """On tray close."""
        if not self.isHidden() and self.get_qt_wallets_in_cbf_ibd():
            # if i close it via the tray (hidden), then it shouldnt ask this question
            if self.ask_to_minimize_only_because_cbf_sync():
                self.tray_controller.minimize_to_tray()
                return
        self.close()

    def ask_to_minimize_only_because_cbf_sync(self) -> bool:
        """Ask to minimize only because cbf sync."""
        res = question_dialog(
            text=self.tr(
                "Wallets are still syncing and syncing would need to start from scratch if you close the app.\nDo you want to hide to tray instead?",
            ),
            title=self.tr("Wallets still syncing"),
            true_button=self.tr("Hide to tray"),
            false_button=self.tr("Close anyway"),
        )
        return bool(res)

    def _before_close(self):
        if self._before_close_was_run:
            # don't save the config twice
            return
        self.config.last_wallet_files[str(self.config.network)] = [
            qt_wallet.file_path for qt_wallet in self.qt_wallets.values()
        ]

        if self.p2p_listener:
            self.config.network_config.discovered_peers = self.p2p_listener.discovered_peers
        self.write_current_open_txs_to_config()
        self.config.save()
        self.save_all_wallets()

        self.mempool_manager.close()
        self.fx.close()
        self.loop_in_thread.stop()
        self.remove_all_qt_wallet()
        if self.p2p_listener:
            self.p2p_listener.stop()

        if self.new_startup_network:
            self.config.network = self.new_startup_network
            self.config.save()

        self._disconnect_all_signals_safely()
        self.tray_controller.hide()

        # 3) On close, save both geometry and (optionally) window state
        self.qsettings.setValue("window/geometry", self.saveGeometry())
        self.qsettings.setValue("window/state", self.saveState())
        self.qsettings.sync()

        logger.info(f"Finished close handling of {self.__class__.__name__}")
        self._before_close_was_run = True

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """CloseEvent."""
        if not a0:
            return
        if a0.spontaneous() and not self.isHidden() and self.get_qt_wallets_in_cbf_ibd():
            # event.spontaneous() == True → originated from the window system (user click, Alt+F4, OS session end).
            # if i close it via the tray (hidden), then it shouldnt ask this question
            if self.ask_to_minimize_only_because_cbf_sync():
                a0.ignore()
                self.tray_controller.minimize_to_tray()
                return

        self._before_close()

        super().closeEvent(a0)
        QApplication.closeAllWindows()
        QCoreApplication.quit()

    def _disconnect_all_signals_safely(self) -> None:
        """Disconnect Qt signals while ignoring already deleted Qt objects."""

        try:
            SignalTools.disconnect_all_signals_from(self.signals)
        except RuntimeError:
            logger.exception("Failed to disconnect signals from self.signals during shutdown")

        try:
            SignalTools.disconnect_all_signals_from(self)
        except RuntimeError:
            logger.exception("Failed to disconnect signals from self during shutdown")

    def restart(self, new_startup_network: bdk.Network | None = None) -> None:
        """Currently only works in Linux and then it seems that it freezes. So do not
        use.

        Args:
            new_startup_network (bdk.Network | None, optional): _description_. Defaults to None.
        """

        args: list[str] = []  #  sys.argv[1:]
        self.new_startup_network = new_startup_network

        if not self.isHidden() and self.get_qt_wallets_in_cbf_ibd():
            if self.ask_to_minimize_only_because_cbf_sync():
                self.tray_controller.minimize_to_tray()
                return

        self._before_close()
        restart_application(args)

    def shutdown(self, new_startup_network: bdk.Network | None = None) -> None:
        """Shutdown."""
        self.new_startup_network = new_startup_network
        QCoreApplication.quit()

    def signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """Signal handler."""
        logger.info(f"Handling signal: {signum}")
        close_event = QCloseEvent()
        self.closeEvent(close_event)
        logger.info(f"Received signal {signum}, exiting.")
        QCoreApplication.quit()

    def setup_signal_handlers(self) -> None:
        """Setup signal handlers."""
        signals: list[int] = [
            getattr(syssignal, attr)
            for attr in ["SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT"]
            if hasattr(syssignal, attr)
        ]
        for sig in signals:
            syssignal.signal(sig, self.signal_handler)
