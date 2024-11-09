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


import logging
import signal as syssignal
from collections import deque
from pathlib import Path

from bitcoin_usb.tool_gui import ToolGui

from bitcoin_safe import __version__
from bitcoin_safe.descriptors import MultipathDescriptor
from bitcoin_safe.gui.qt.about_dialog import LicenseDialog
from bitcoin_safe.gui.qt.category_list import CategoryEditor
from bitcoin_safe.gui.qt.descriptor_edit import DescriptorExport
from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.gui.qt.language_chooser import LanguageChooser
from bitcoin_safe.gui.qt.notification_bar_regtest import NotificationBarRegtest
from bitcoin_safe.gui.qt.update_notification_bar import UpdateNotificationBar
from bitcoin_safe.gui.qt.wrappers import Menu, MenuBar
from bitcoin_safe.keystore import KeyStoreImporterTypes
from bitcoin_safe.pdfrecovery import make_and_open_pdf
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.util import rel_home_path_to_abs_path

logger = logging.getLogger(__name__)

import base64
import os
import sys
from typing import Deque, Dict, Iterable, List, Literal, Optional, Tuple, Union

import bdkpython as bdk
from bitcoin_qr_tools.bitcoin_video_widget import BitcoinVideoWidget
from bitcoin_qr_tools.data import Data, DataType
from PyQt6.QtCore import QCoreApplication, QProcess, Qt, QTimer
from PyQt6.QtGui import QCloseEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.search_tree_view import SearchWallets
from bitcoin_safe.gui.qt.wallet_steps import ImportXpubs, TutorialStep, WalletSteps

from ...config import UserConfig
from ...fx import FX
from ...mempool import MempoolData
from ...psbt_util import FeeInfo, SimplePSBT
from ...pythonbdk_types import get_outpoints
from ...signals import Signals
from ...storage import Storage
from ...tx import TxBuilderInfos, TxUiInfos, short_tx_id
from ...wallet import ProtoWallet, ToolsTxUiInfo, Wallet
from . import address_dialog
from .dialog_import import ImportDialog, file_to_str
from .dialogs import PasswordQuestion, WalletIdDialog, question_dialog
from .extended_tabwidget import ExtendedTabWidget, LoadingWalletTab
from .network_settings.main import NetworkSettingsUI
from .new_wallet_welcome_screen import NewWalletWelcomeScreen
from .qt_wallet import QTProtoWallet, QTWallet, QtWalletBase
from .ui_tx import UITx_Viewer, UITx_ViewerTab
from .util import (
    Message,
    MessageType,
    caught_exception_message,
    delayed_execution,
    read_QIcon,
    webopen,
)
from .utxo_list import UTXOList, UtxoListWithToolbar


class MainWindow(QMainWindow):
    def __init__(
        self,
        network: Literal["bitcoin", "regtest", "signet", "testnet"] | None = None,
        config: UserConfig | None = None,
        open_files_at_startup: List[str] | None = None,
        **kwargs,
    ) -> None:
        "If netowrk == None, then the network from the user config will be taken"
        super().__init__()
        self.open_files_at_startup = open_files_at_startup if open_files_at_startup else []
        config_present = UserConfig.exists() or config
        self.config = config if config else UserConfig.from_file()
        self.config.network = bdk.Network[network.upper()] if network else self.config.network
        self.new_startup_network: bdk.Network | None = None
        self.address_dialogs: Deque[address_dialog.AddressDialog] = deque(maxlen=1000)
        self._temp_bitcoin_video_widget: BitcoinVideoWidget | None = None
        self.setMinimumSize(600, 600)

        self.signals = Signals()
        self.qt_wallets: Dict[str, QTWallet] = {}
        self.threading_manager = ThreadingManager(threading_manager_name=self.__class__.__name__)

        self.fx = FX(threading_parent=self.threading_manager)
        self.language_chooser = LanguageChooser(self, self.config, [self.signals.language_switch])
        if not config_present:
            self.config.language_code = self.language_chooser.dialog_choose_language(self)
        self.language_chooser.set_language(self.config.language_code)
        self.hwi_tool_gui = ToolGui(self.config.network)
        self.setupUi(self)

        self.mempool_data = MempoolData(
            network_config=self.config.network_config,
            signals_min=self.signals,
            threading_parent=self.threading_manager,
        )
        self.mempool_data.set_data_from_mempoolspace()

        self.last_qtwallet: Optional[QTWallet] = None
        # connect the listeners
        self.signals.open_file_path.connect(self.open_file_path)
        self.signals.open_tx_like.connect(self.open_tx_like_in_tab)
        self.signals.get_network.connect(self.get_network)
        self.signals.get_mempool_url.connect(self.get_mempool_url)

        self.network_settings_ui = NetworkSettingsUI(
            self.config.network, self.config.network_configs, signals=self.signals
        )
        self.network_settings_ui.signal_apply_and_shutdown.connect(self.shutdown)
        self.signals.show_network_settings.connect(self.open_network_settings)

        self.welcome_screen = NewWalletWelcomeScreen(
            self.tab_wallets, network=self.config.network, signals=self.signals
        )

        # signals
        self.welcome_screen.signal_onclick_single_signature.connect(self.click_create_single_signature_wallet)
        self.welcome_screen.signal_onclick_multisig_signature.connect(
            self.click_create_multisig_signature_wallet
        )
        self.welcome_screen.signal_onclick_custom_signature.connect(self.click_custom_signature)
        self.signals.create_qt_wallet_from_wallet.connect(self.add_qt_wallet)
        self.signals.close_qt_wallet.connect(
            lambda wallet_id: self.remove_qt_wallet(self.qt_wallets.get(wallet_id))
        )

        self.signals.event_wallet_tab_added.connect(self.event_wallet_tab_added)
        self.signals.event_wallet_tab_closed.connect(self.event_wallet_tab_closed)
        self.signals.chain_data_changed.connect(self.sync)
        self.signals.request_manual_sync.connect(self.sync)
        self.signals.open_wallet.connect(self.open_wallet)
        self.signals.signal_broadcast_tx.connect(self.on_signal_broadcast_tx)
        self.signals.language_switch.connect(self.updateUI)

        self._init_tray()

        self.search_box = SearchWallets(
            get_qt_wallets=self.get_qt_wallets,
            signal_min=self.signals,
            parent=self.tab_wallets,
        )
        self.tab_wallets.set_top_right_widget(self.search_box)

        self.updateUI()
        self.setup_signal_handlers()

        delayed_execution(self.load_last_state, self)

    def get_qt_wallets(self) -> List[QTWallet]:
        return list(self.qt_wallets.values())

    def get_mempool_url(self) -> str:
        return self.config.network_config.mempool_url

    def get_network(self) -> bdk.Network:
        return self.config.network

    def load_last_state(self) -> None:

        opened_qt_wallets = self.open_last_opened_wallets()
        if not opened_qt_wallets:
            self.welcome_screen.add_new_wallet_welcome_tab()

        self.open_last_opened_tx()
        for file_path in self.open_files_at_startup:
            self.open_file_path(file_path=file_path)

    def open_file_path(self, file_path: str):
        if file_path and Path(file_path).exists():
            if file_path.endswith(".wallet"):
                self.open_wallet(file_path=file_path)
            else:
                self.signals.open_tx_like.emit(file_to_str(file_path))

    def set_title(self) -> None:
        title = "Bitcoin Safe"
        if self.config.network != bdk.Network.BITCOIN:
            title += f" - {self.config.network.name}"
        if qt_wallet := self.get_qt_wallet():
            title += f" - {qt_wallet.wallet.id}"
        self.setWindowTitle(title)

    def setupUi(self, MainWindow: QWidget) -> None:
        logger.debug(f"start setupUi")
        # sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # sizePolicy.setHorizontalStretch(0)
        # sizePolicy.setVerticalStretch(0)
        # sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        # MainWindow.setSizePolicy(sizePolicy)
        MainWindow.setWindowIcon(read_QIcon("logo.svg"))
        w, h = 900, 600
        MainWindow.resize(w, h)
        MainWindow.setMinimumSize(w, h)

        #####
        self.tab_wallets = ExtendedTabWidget(object, parent=self)
        self.tab_wallets.tabBar().setExpanding(True)  # type: ignore[union-attr]  # This will expand tabs to fill the tab widget width
        self.tab_wallets.setTabBarAutoHide(False)
        self.tab_wallets.setMovable(True)  # Enable tab reordering
        self.tab_wallets.setTabsClosable(True)
        self.tab_wallets.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tab_wallets.signal_tab_bar_visibility.connect(self.updateUI)
        # Connect signals to slots
        self.tab_wallets.tabCloseRequested.connect(self.close_tab)
        self.tab_wallets.currentChanged.connect(self.set_title)

        # central_widget
        central_widget = QScrollArea()
        vbox = QVBoxLayout(central_widget)
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        # header bar about testnet coins
        if self.config.network != bdk.Network.BITCOIN:
            notification_bar = NotificationBarRegtest(
                open_network_settings=self.open_network_settings,
                network=self.config.network,
                signals_min=self.signals,
            )
            vbox.addWidget(notification_bar)

        self.update_notification_bar = UpdateNotificationBar(
            signals_min=self.signals, threading_parent=self.threading_manager
        )
        self.update_notification_bar.check()  # TODO: disable this, after it got more stable
        vbox.addWidget(self.update_notification_bar)

        vbox.addWidget(self.tab_wallets)
        self.setCentralWidget(central_widget)

        self.setMinimumWidth(640)
        self.setMinimumHeight(400)
        if self.config.is_maximized:
            self.showMaximized()

        # self.setWindowIcon(read_QIcon("electrum.png"))
        self.init_menubar()
        self.set_title()
        logger.debug(f"done setupUi")

    def init_menubar(self) -> None:
        self.menubar = MenuBar()
        # menu wallet
        self.menu_wallet = self.menubar.add_menu("")
        self.menu_action_new_wallet = self.menu_wallet.add_action("", self.new_wallet)
        self.menu_action_new_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        )

        self.menu_action_open_wallet = self.menu_wallet.add_action("", self.open_wallet)
        self.menu_action_open_wallet.setShortcut(QKeySequence("CTRL+O"))
        self.menu_action_open_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )

        self.menu_wallet_recent = self.menu_wallet.add_menu("")

        self.menu_action_save_current_wallet = self.menu_wallet.add_action("", self.save_qt_wallet)
        self.menu_action_save_current_wallet.setShortcut(QKeySequence("CTRL+S"))
        self.menu_action_save_current_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        self.menu_wallet.addSeparator()

        self.menu_action_search = self.menu_wallet.add_action("", self.focus_search_box)
        self.menu_action_search.setShortcut(QKeySequence("CTRL+F"))
        self.menu_action_search.setIcon(read_QIcon("search.svg"))

        # change wallet
        self.menu_wallet_change = self.menu_wallet.add_menu("")
        self.menu_wallet_change.setIcon(read_QIcon("password.svg"))
        self.menu_action_rename_wallet = self.menu_wallet_change.add_action("", self.change_wallet_id)
        self.menu_action_change_password = self.menu_wallet_change.add_action("", self.change_wallet_password)
        self.menu_action_change_password.setIcon(read_QIcon("password.svg"))

        # export wallet
        self.menu_wallet_export = self.menu_wallet.add_menu("")
        self.menu_action_export_pdf = self.menu_wallet_export.add_action(
            "", self.export_wallet_pdf, icon=read_QIcon("descriptor-backup.svg")
        )
        self.menu_action_export_for_coldcard = self.menu_wallet_export.add_action(
            "", self.export_wallet_for_coldcard, icon=read_QIcon("coldcard-only.svg")
        )
        self.menu_action_export_descriptor = self.menu_wallet_export.add_action(
            "", self.export_wallet_for_coldcard_q
        )

        self.menu_wallet.addSeparator()
        self.menu_action_refresh_wallet = self.menu_wallet.add_action(
            "", self.signals.request_manual_sync.emit
        )
        self.menu_action_refresh_wallet.setShortcut(QKeySequence("F5"))
        self.menu_action_refresh_wallet.setIcon(
            (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )

        # menu transaction
        self.menu_tools = self.menubar.add_menu("")

        self.menu_action_open_hwi_manager = self.menu_tools.add_action(
            "",
            self.hwi_tool_gui.show,
            icon=read_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
        )

        self.menu_load_transaction = self.menu_tools.add_menu("")
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
            "", self.load_tx_like_from_qr, icon=read_QIcon("qr-code.svg")
        )

        # menu settings
        self.menu_settings = self.menubar.add_menu("")
        self.menu_action_network_settings = self.menu_settings.add_action(
            "",
            self.open_network_settings,
            icon=(self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon),
        )
        self.menu_action_network_settings.setShortcut(QKeySequence("CTRL+P"))
        self.menu_action_toggle_tutorial = self.menu_settings.add_action("", self.toggle_tutorial)
        self.language_menu = self.menu_settings.add_menu("")

        # menu about
        self.menu_about = self.menubar.add_menu("")
        self.menu_action_version = self.menu_about.add_action(
            "", lambda: webopen("https://github.com/andreasgriffin/bitcoin-safe/releases")
        )
        self.menu_action_check_update = self.menu_about.add_action(
            "", self.update_notification_bar.check_and_make_visible
        )
        self.menu_action_check_update.setShortcut(QKeySequence("CTRL+U"))

        def menu_action_license():
            LicenseDialog().exec()

        self.menu_action_license = self.menu_about.add_action("", menu_action_license)

        # assigning menu bar
        self.setMenuBar(self.menubar)

        # Populate recent wallets menu
        self.populate_recent_wallets_menu()

        # other shortcuts
        self.shortcut_close_tab = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close_tab.activated.connect(lambda: self.close_tab(self.tab_wallets.currentIndex()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # self.updateUI()

    def updateUI(self) -> None:

        # menu
        self.menu_wallet.setTitle(self.tr("&Wallet"))
        self.menu_action_new_wallet.setText(self.tr("&New Wallet"))
        self.menu_action_open_wallet.setText(self.tr("&Open Wallet"))
        self.menu_wallet_recent.setTitle(self.tr("Open &Recent"))
        self.menu_action_save_current_wallet.setText(self.tr("&Save Current Wallet"))
        self.menu_action_search.setText(self.tr("&Search"))
        self.menu_wallet_change.setTitle(self.tr("&Change"))
        self.menu_wallet_export.setTitle(self.tr("&Export"))
        self.menu_action_rename_wallet.setText(self.tr("&Rename Wallet"))
        self.menu_action_change_password.setText(self.tr("&Change Password"))
        self.menu_action_export_for_coldcard.setText(self.tr("&Export Coldcard txt file"))
        self.menu_action_export_pdf.setText(self.tr("&Export Wallet PDF"))
        self.menu_action_export_descriptor.setText(self.tr("&Export Descriptor"))
        self.menu_action_refresh_wallet.setText(self.tr("Re&fresh"))
        self.menu_tools.setTitle(self.tr("&Tools"))
        self.menu_action_open_hwi_manager.setText(self.tr("&USB Signer Tools"))
        self.menu_load_transaction.setTitle(self.tr("&Load Transaction or PSBT"))
        self.menu_action_open_tx_file.setText(self.tr("From &file"))
        self.menu_action_open_tx_from_str.setText(self.tr("From &text"))
        self.menu_action_load_tx_from_qr.setText(self.tr("From &QR Code"))
        self.menu_settings.setTitle(self.tr("&Settings"))
        self.menu_action_network_settings.setText(self.tr("&Network Settings"))
        self.menu_action_toggle_tutorial.setText(self.tr("&Show/Hide Tutorial"))
        languages = "&Languages"
        local_languages = self.tr("&Languages")
        if local_languages != languages:
            languages += f" - {local_languages}"
        self.language_menu.setTitle(languages)
        self.language_chooser.populate_language_menu(self.language_menu)
        self.menu_about.setTitle(self.tr("&About"))
        self.menu_action_version.setText(self.tr("&Version: {}").format(__version__))
        self.menu_action_check_update.setText(self.tr("&Check for update"))
        self.menu_action_license.setText(self.tr("&License"))

        # the search fields
        for qt_wallet in self.qt_wallets.values():
            if self.tab_wallets.top_right_widget:
                main_search_field_hidden = (
                    self.tab_wallets.count() <= 1
                ) and self.tab_wallets.tabBarAutoHide()
                self.tab_wallets.top_right_widget.setVisible(not main_search_field_hidden)
                if qt_wallet.tabs.top_right_widget:
                    qt_wallet.tabs.top_right_widget.setVisible(main_search_field_hidden)

    def focus_search_box(self):
        self.search_box.search_field.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def populate_recent_wallets_menu(self) -> None:
        self.menu_wallet_recent.clear()

        def factory(filepath):
            def f(*args):
                self.open_wallet(file_path=filepath)

            return f

        for filepath in reversed(self.config.recently_open_wallets[self.config.network]):
            if not Path(filepath).exists():
                continue
            self.menu_wallet_recent.add_action(os.path.basename(filepath), factory(filepath=filepath))

    def change_wallet_id(self) -> Optional[str]:
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please select the wallet"))
            return None

        old_id = qt_wallet.wallet.id

        # ask for wallet name
        dialog = WalletIdDialog(Path(self.config.wallet_dir), prefilled=old_id)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_wallet_id = dialog.wallet_id
            new_wallet_filename = dialog.filename
            logger.info(f"new wallet name: {new_wallet_id}")
        else:
            return None

        # in the wallet
        qt_wallet.wallet.set_wallet_id(new_wallet_id)
        # change dict key
        self.qt_wallets[new_wallet_id] = qt_wallet
        del self.qt_wallets[old_id]

        # tab text
        self.tab_wallets.setTabText(self.tab_wallets.indexOf(qt_wallet.tab), new_wallet_id)

        # save under new filename
        old_filepath = qt_wallet.file_path
        directory, old_filename = os.path.split(old_filepath)

        new_file_path = os.path.join(directory, new_wallet_filename)

        qt_wallet.move_wallet_file(new_file_path)
        self.save_qt_wallet(qt_wallet)
        logger.info(f"Saved {old_filepath} under new name {qt_wallet.file_path}")
        self.set_title()
        return new_wallet_id

    def change_wallet_password(self) -> None:
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please select the wallet"))
            return

        qt_wallet.change_password()

    def on_signal_broadcast_tx(self, transaction: bdk.Transaction) -> None:
        def f_sync_all(qt_wallets: List[QTWallet]):
            for qt_wallet in qt_wallets:
                qt_wallet.sync()

        qt_wallets_to_sync: List[QTWallet] = []

        last_qt_wallet_involved: Optional[QTWallet] = None
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.transaction_related_to_my_addresses(transaction):
                qt_wallets_to_sync.append(qt_wallet)
                last_qt_wallet_involved = qt_wallet

        if last_qt_wallet_involved:
            self.tab_wallets.setCurrentWidget(last_qt_wallet_involved.tab)
            last_qt_wallet_involved.tabs.setCurrentWidget(last_qt_wallet_involved.history_tab)

        QTimer.singleShot(500, lambda: f_sync_all(qt_wallets_to_sync))

    def on_tab_changed(self, index: int) -> None:
        qt_wallet = self.get_qt_wallet(self.tab_wallets.widget(index))
        if qt_wallet:
            self.last_qtwallet = qt_wallet

    def _init_tray(self) -> None:
        self.tray = QSystemTrayIcon(read_QIcon("logo.svg"), self)
        self.tray.setToolTip("Bitcoin Safe")

        menu = Menu(self)
        menu.add_action(text="&Exit", slot=self.close)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.onTrayIconActivated)

        self.signals.notification.connect(self.show_message_as_tray_notification)
        self.tray.show()

    def show_message_as_tray_notification(self, message: Message) -> None:
        icon, _ = message.get_icon_and_title()
        title = message.title or "Bitcoin Safe"
        if message.msecs:
            self.tray.showMessage(title, message.msg, Message.system_tray_icon(icon), message.msecs)
            return
        self.tray.showMessage(title, message.msg, Message.system_tray_icon(icon))

    def onTrayIconActivated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Attempts to bring the window to the foreground
        self.raise_()
        self.activateWindow()
        # if reason == QSystemTrayIcon.ActivationReason.Trigger:
        #     Message(self.tr("test"), no_show=True).emit_with(self.signals.notification)

    def open_network_settings(self) -> None:
        self.network_settings_ui.exec()

    def export_wallet_for_coldcard(self, wallet: Wallet | None = None) -> None:
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning)
            return

        qt_wallet.export_wallet_for_coldcard()

    def export_wallet_for_coldcard_q(self, wallet: Wallet | None = None) -> None:
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning)
            return

        edit = qt_wallet.wallet_descriptor_ui.edit_descriptor
        dialog = DescriptorExport(
            MultipathDescriptor.from_descriptor_str(edit.text(), qt_wallet.wallet.network),
            qt_wallet.signals,
            parent=self,
            network=self.config.network,
            threading_parent=self.threading_manager,
        )
        dialog.show()

    def export_wallet_pdf(self, wallet: Wallet | None = None) -> None:
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message(self.tr("Please select the wallet first."), type=MessageType.Warning)
            return

        make_and_open_pdf(qt_wallet.wallet, lang_code=self.language_chooser.get_current_lang_code())

    def open_tx_file(self, file_path: Optional[str] = None) -> None:
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open Transaction/PSBT"),
                "",
                self.tr("All Files (*);;PSBT (*.psbt);;Transation (*.tx)"),
            )
            if not file_path:
                logger.info("No file selected")
                return

        logger.info(self.tr("Selected file: {file_path}").format(file_path=file_path))
        with open(file_path, "rb") as file:
            string_content = file.read()

        self.signals.open_tx_like.emit(string_content)

    def fetch_txdetails(self, txid: str) -> Optional[bdk.TransactionDetails]:
        for qt_wallet in self.qt_wallets.values():
            tx_details = qt_wallet.wallet.get_tx(txid)
            if tx_details:
                return tx_details
        return None

    def open_tx_like_in_tab(
        self,
        txlike: Union[
            bdk.TransactionDetails,
            bdk.Transaction,
            bdk.PartiallySignedTransaction,
            TxBuilderInfos,
            TxUiInfos,
            bytes,
            str,
        ],
    ) -> None:
        logger.info(f"Trying to open tx with type {type(txlike)}")

        # first do the bdk instance cases
        if isinstance(txlike, (bdk.TransactionDetails, bdk.Transaction)):
            self.open_tx_in_tab(txlike)
            return None

        if isinstance(txlike, (bdk.PartiallySignedTransaction, TxBuilderInfos)):
            self.open_psbt_in_tab(txlike)
            return None

        if isinstance(txlike, TxUiInfos):
            wallet = ToolsTxUiInfo.get_likely_source_wallet(txlike, self.signals)

            if not wallet:
                logger.info(
                    f"Could not identify the wallet belonging to the transaction inputs. Trying to open anyway..."
                )
                current_qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
                wallet = current_qt_wallet.wallet if current_qt_wallet else None
            if not wallet:
                Message(self.tr("No wallet open. Please open the sender wallet to edit this thransaction."))
                return None

            qt_wallet = self.qt_wallets.get(wallet.id)
            if not qt_wallet:
                Message(self.tr(" Please open the sender wallet to edit this thransaction."))
                return None
            self.tab_wallets.setCurrentWidget(qt_wallet.tab)
            qt_wallet.tabs.setCurrentWidget(qt_wallet.send_tab)

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

        if isinstance(txlike, str):
            try:
                res = Data.from_str(txlike, self.config.network)
            except:
                Message(self.tr("Could not decode this string"), type=MessageType.Error)
                return None
            if res.data_type == DataType.Txid:
                txdetails = self.fetch_txdetails(res.data)
                if txdetails:
                    self.open_tx_in_tab(txdetails)
                    return None
                if not txlike:
                    raise Exception(f"txid {res.data} could not be found in wallets")
            elif res.data_type == DataType.PSBT:
                self.open_psbt_in_tab(res.data)
                return None
            elif res.data_type == DataType.Tx:
                self.open_tx_in_tab(res.data)
                return None
            else:
                logger.warning(f"DataType {res.data_type.name} was not handled.")
        return None

    def load_tx_like_from_qr(self) -> None:
        def result_callback(data: Data) -> None:
            if data.data_type in [
                DataType.PSBT,
                DataType.Tx,
                DataType.Txid,
            ]:
                self.open_tx_like_in_tab(data.data)

        if self._temp_bitcoin_video_widget:
            self._temp_bitcoin_video_widget.close()
        self._temp_bitcoin_video_widget = BitcoinVideoWidget()
        self._temp_bitcoin_video_widget.signal_data.connect(result_callback)
        self._temp_bitcoin_video_widget.show()
        return None

    def dialog_open_tx_from_str(self) -> None:
        def process_input(s: str) -> None:
            self.open_tx_like_in_tab(s)

        tx_dialog = ImportDialog(
            network=self.config.network,
            on_open=process_input,
            window_title=self.tr("Open Transaction or PSBT"),
            text_button_ok=self.tr("OK"),
            text_instruction_label=self.tr(
                "Please paste your Bitcoin Transaction or PSBT in here, or drop a file"
            ),
            text_placeholder=self.tr("Paste your Bitcoin Transaction or PSBT in here or drop a file"),
        )
        tx_dialog.show()

    def get_tab_with_title(self, tab_widget: QTabWidget, title) -> Optional[int]:
        for i in range(tab_widget.count()):
            if title == tab_widget.tabText(i):
                return i
        return None

    def open_tx_in_tab(
        self, txlike: Union[bdk.Transaction, bdk.TransactionDetails]
    ) -> Optional[Tuple[UITx_ViewerTab, UITx_Viewer]]:
        tx: bdk.Transaction | None = None
        fee = None
        confirmation_time = None

        if isinstance(txlike, bdk.Transaction):
            # try to get all details from wallets
            tx_details = self.fetch_txdetails(txlike.txid())
            if tx_details:
                txlike = tx_details

        if isinstance(txlike, bdk.TransactionDetails):
            logger.debug(f"Got a PartiallySignedTransaction")
            tx = txlike.transaction
            fee = txlike.fee
            if fee is None and txlike.transaction.is_coin_base():
                fee = 0
            confirmation_time = txlike.confirmation_time
        elif isinstance(txlike, bdk.Transaction):
            tx = txlike

        if not tx:
            logger.error(f"could not open {tx}")
            return None

        title = self.tr("Transaction {txid}").format(txid=short_tx_id(tx.txid()))
        data = Data.from_tx(tx)

        # check if the same tab with exactly the same data is open already
        tab_idx = self.get_tab_with_title(self.tab_wallets, title)
        if tab_idx is not None and isinstance(tab_data := self.tab_wallets.tabData(tab_idx), UITx_Viewer):
            # if the tab_data is a tx, then just dismiss the tx
            if tab_data.data.data_type == DataType.Tx:
                self.tab_wallets.setCurrentIndex(tab_idx)
                return None
            # if tab_data is a psbt, then add the signature from tx
            if tab_data.data.data_type == DataType.PSBT:
                tab_data.tx_received(tx)
                self.tab_wallets.setCurrentIndex(tab_idx)
                return None

        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=lambda: get_outpoints(tx),
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
            ],
            keep_outpoint_order=True,
            # the ADDRESS. ROLE SORT ORDER saves the order of the get_outpoints
            sort_column=UTXOList.Columns.ADDRESS,
            sort_order=Qt.SortOrder.AscendingOrder,
        )

        widget_utxo_with_toolbar = UtxoListWithToolbar(utxo_list, self.config, self.tab_wallets)

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            self.fx,
            widget_utxo_with_toolbar,
            network=self.config.network,
            mempool_data=self.mempool_data,
            fee_info=FeeInfo(fee, tx.vsize(), is_estimated=False) if fee is not None else None,
            confirmation_time=confirmation_time,
            blockchain=self.get_blockchain_of_any_wallet(),
            data=data,
            parent=self,
            threading_parent=self.threading_manager,
        )

        self.tab_wallets.add_tab(
            tab=viewer,
            icon=read_QIcon("send.svg"),
            description=title,
            focus=True,
            data=viewer,
        )

        return viewer, viewer

    def open_psbt_in_tab(
        self,
        tx: Union[
            bdk.PartiallySignedTransaction, TxBuilderInfos, bdk.TxBuilderResult, str, bdk.TransactionDetails
        ],
    ) -> Optional[Tuple[UITx_ViewerTab, UITx_Viewer]]:
        psbt: bdk.PartiallySignedTransaction | None = None
        fee_info: Optional[FeeInfo] = None

        logger.debug(f"tx is of type {type(tx)}")

        # converting to TxBuilderResult
        if isinstance(tx, TxBuilderInfos):
            tx = tx.builder_result  # then it is processed in the next if stament
            logger.debug(f"Converted TxBuilderInfos --> {type(tx)}")

        if isinstance(tx, bdk.TxBuilderResult):
            psbt = tx.psbt
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
            logger.debug(f"Converted TxBuilderResult --> {type(psbt)}")

        if isinstance(tx, bdk.PartiallySignedTransaction):
            logger.debug(f"Got a PartiallySignedTransaction")
            psbt = tx
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

        if isinstance(tx, str):
            psbt = bdk.PartiallySignedTransaction(tx)
            logger.debug(f"Converted str to {type(tx)}")
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

        if isinstance(tx, bdk.TransactionDetails):
            logger.debug("is bdk.TransactionDetails")
            raise Exception("cannot handle TransactionDetails")

        if not psbt:
            logger.error(f"{tx} could not be converted to a psbt")
            return None

        data = Data.from_psbt(psbt)
        title = self.tr("PSBT {txid}").format(txid=short_tx_id(psbt.txid()))

        # check if the same tab with exactly the same data is open already
        tab_idx = self.get_tab_with_title(self.tab_wallets, title)
        if tab_idx is not None and isinstance(tab_data := self.tab_wallets.tabData(tab_idx), UITx_Viewer):
            # if the tab_data is a tx, then just dismiss the psbt (a tx is better than a psbt)
            if tab_data.data.data_type == DataType.Tx:
                self.tab_wallets.setCurrentIndex(tab_idx)
                return None
            # if tab_data is a psbt, then add the signature from data
            if tab_data.data.data_type == DataType.PSBT:
                tab_data.signature_added(psbt)
                self.tab_wallets.setCurrentIndex(tab_idx)
                return None

        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=lambda: get_outpoints(psbt.extract_tx()),
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
            ],
            txout_dict=SimplePSBT.from_psbt(psbt).get_prev_txouts(),
            keep_outpoint_order=True,
            # the ADDRESS. ROLE SORT ORDER saves the order of the get_outpoints
            sort_column=UTXOList.Columns.ADDRESS,
            sort_order=Qt.SortOrder.AscendingOrder,
        )

        widget_utxo_with_toolbar = UtxoListWithToolbar(utxo_list, self.config, parent=self.tab_wallets)

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            self.fx,
            widget_utxo_with_toolbar,
            network=self.config.network,
            mempool_data=self.mempool_data,
            fee_info=fee_info,
            blockchain=self.get_blockchain_of_any_wallet(),
            data=data,
            parent=self,
            threading_parent=self.threading_manager,
        )

        self.tab_wallets.add_tab(
            tab=viewer,
            icon=read_QIcon("qr-code.svg"),
            description=title,
            focus=True,
            data=viewer,
        )

        return viewer, viewer

    def open_last_opened_wallets(self) -> List[QTWallet]:
        opened_wallets: List[QTWallet] = []
        for file_path in self.config.last_wallet_files.get(str(self.config.network), []):
            qt_wallet = self.open_wallet(file_path=str(rel_home_path_to_abs_path(file_path)))
            if qt_wallet:
                opened_wallets.append(qt_wallet)
        return opened_wallets

    def open_last_opened_tx(self) -> None:
        for serialized in self.config.opened_txlike.get(str(self.config.network), []):
            self.open_tx_like_in_tab(serialized)

    # def advance_tips_in_background(self, wallet: Wallet):
    #     def do():
    #         return wallet.get_address()

    #     def on_error(packed_error_info):
    #         logger.error("Exception in advance_tips_in_background")

    #     def on_done(data):
    #         pass

    #     def on_success(data):
    #         pass

    #     TaskThread( signals_min=self.signals).add_and_start(do, on_success, on_done, on_error)

    def open_wallet(self, file_path: Optional[str] = None) -> Optional[QTWallet]:
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self.tr("Open Wallet"),
                self.config.wallet_dir,
                self.tr("Wallet Files (*.wallet);;All Files (*)"),
            )
            if not file_path:
                logger.info("No file selected")
                return None

        # make sure this wallet isn't open already by this instance
        opened_file_paths = [qt_wallet.file_path for qt_wallet in self.qt_wallets.values()]
        if file_path in opened_file_paths:
            Message(self.tr("The wallet {file_path} is already open.").format(file_path=file_path))
            return None

        if not QTWallet.get_wallet_lockfile(Path(file_path)):
            if not question_dialog(
                self.tr(
                    "The wallet {file_path} is already open.  Do you want to open the wallet anyway?"
                ).format(file_path=file_path),
                title=self.tr("Wallet already open"),
            ):
                return None

        logger.info(f"Selected file: {file_path}")
        if not os.path.isfile(file_path):
            Message(
                self.tr("There is no such file: {file_path}").format(file_path=file_path),
                type=MessageType.Error,
            )
            return None
        password = None
        if Storage().has_password(file_path):
            direcory, filename = os.path.split(file_path)
            ui_password_question = PasswordQuestion(
                label_text=self.tr("Please enter the password for {filename}:").format(filename=filename)
            )
            password = ui_password_question.ask_for_password()
        try:
            wallet: Wallet = Wallet.from_file(file_path, self.config, password)
        except Exception as e:
            # the file could also be corrupted, but the "wrong password" is by far the likliest
            caught_exception_message(e, "Wrong password. Wallet could not be loaded.")
            QTWallet.remove_lockfile(Path(file_path))
            return None
        # self.advance_tips_in_background(wallet)

        if wallet.id in self.qt_wallets:
            Message(
                self.tr("A wallet with id {name} is already open. Please close it first.").format(
                    name=wallet.id
                )
            )
            return None

        qt_wallet = self.add_qt_wallet(wallet)
        qt_wallet.password = password
        qt_wallet.file_path = file_path
        qt_wallet.sync()

        self.add_recently_open_wallet(qt_wallet.file_path)

        self.signals.finished_open_wallet.emit(wallet.id)
        return qt_wallet

    def save_qt_wallet(self, qt_wallet: QTWallet | None = None) -> None:
        qt_wallet = qt_wallet if qt_wallet else self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.save()
            self.add_recently_open_wallet(qt_wallet.file_path)

    def save_all_wallets(self) -> None:
        for qt_wallet in self.qt_wallets.values():
            self.save_qt_wallet(qt_wallet=qt_wallet)

    def write_current_open_txs_to_config(self) -> None:
        l = []

        for index in range(self.tab_wallets.count()):
            # Get the widget for the current tab
            tab = self.tab_wallets.widget(index)
            if isinstance(tab, UITx_ViewerTab):
                l.append(tab.serialize())

        self.config.opened_txlike[str(self.config.network)] = l

    def click_create_single_signature_wallet(self) -> None:
        qtprotowallet = self.create_qtprotowallet((1, 1), show_tutorial=True)
        if qtprotowallet:
            qtprotowallet.wallet_descriptor_ui.disable_fields()

    def click_create_multisig_signature_wallet(self) -> None:
        qtprotowallet = self.create_qtprotowallet((2, 3), show_tutorial=True)
        if qtprotowallet:
            qtprotowallet.wallet_descriptor_ui.disable_fields()

    def click_custom_signature(self) -> None:
        qtprotowallet = self.create_qtprotowallet((3, 5), show_tutorial=False)

    def new_wallet(self) -> None:
        self.welcome_screen.add_new_wallet_welcome_tab()

    def new_wallet_id(self) -> str:
        return f'{self.tr("new")}{len(self.qt_wallets)}'

    def create_qtwallet_from_protowallet(self, protowallet: ProtoWallet) -> QTWallet:
        wallet = Wallet.from_protowallet(
            protowallet, self.config, default_category=CategoryEditor.get_default_categories()[0]
        )

        qt_wallet = self.add_qt_wallet(wallet)
        # adding these should only be done at wallet creation
        qt_wallet.address_list_tags.add_default_categories()
        self.save_qt_wallet(qt_wallet)
        qt_wallet.sync()
        return qt_wallet

    def create_qtwallet_from_ui(
        self,
        wallet_tab: QWidget,
        protowallet: ProtoWallet,
        keystore_uis: KeyStoreUIs,
    ) -> None:
        try:
            if keystore_uis.ask_accept_unexpected_origins():
                qt_wallet = self.create_qtwallet_from_protowallet(protowallet=protowallet)
                self.tab_wallets.removeTab(self.tab_wallets.indexOf(wallet_tab))
                qt_wallet.tabs.setCurrentWidget(qt_wallet.history_tab)

            else:
                return
        except Exception as e:
            Message(str(e), type=MessageType.Error)

    def create_qtwallet_from_qtprotowallet(self, qtprotowallet: QTProtoWallet) -> None:
        self.create_qtwallet_from_ui(
            wallet_tab=qtprotowallet.tab,
            protowallet=qtprotowallet.protowallet,
            keystore_uis=qtprotowallet.wallet_descriptor_ui.keystore_uis,
        )

    def create_qtprotowallet(
        self, m_of_n: Tuple[int, int], show_tutorial: bool = False
    ) -> Optional[QTProtoWallet]:

        # ask for wallet name
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

        qtprotowallet = QTProtoWallet(
            config=self.config,
            signals=self.signals,
            protowallet=protowallet,
            threading_parent=self.threading_manager,
            get_lang_code=self.language_chooser.get_current_lang_code,
        )

        qtprotowallet.signal_close_wallet.connect(
            lambda: self.close_tab(self.tab_wallets.indexOf(qtprotowallet.tab))
        )
        qtprotowallet.signal_create_wallet.connect(
            lambda: self.create_qtwallet_from_qtprotowallet(qtprotowallet)
        )

        # tutorial
        wallet_steps = WalletSteps(
            wallet_tabs=qtprotowallet.tabs,
            qtwalletbase=qtprotowallet,
        )
        if show_tutorial:
            protowallet.tutorial_index = 0
            wallet_steps.set_current_index(protowallet.tutorial_index)
            wallet_steps.set_visibilities()
        qtprotowallet.wallet_steps = wallet_steps

        tab_import_xpub = wallet_steps.tab_generators[TutorialStep.import_xpub]
        if not isinstance(tab_import_xpub, ImportXpubs):
            logger.error(f"{tab_import_xpub} is not of type ImportXpubs")
            return None

        def create_qtwallet_from_ui():
            if not isinstance(tab_import_xpub, ImportXpubs):
                logger.error(f"{tab_import_xpub} is not of type ImportXpubs")  # type: ignore[unreachable]
                return None

            if not tab_import_xpub.keystore_uis:
                Message("Cannot create wallet, because no keystores are available", type=MessageType.Error)
                return
            self.create_qtwallet_from_ui(
                wallet_tab=qtprotowallet.tab,
                protowallet=protowallet,
                keystore_uis=tab_import_xpub.keystore_uis,
            )

        wallet_steps.signal_create_wallet.connect(create_qtwallet_from_ui)

        # add to tabs
        self.tab_wallets.add_tab(
            tab=qtprotowallet.tab,
            icon=read_QIcon("file.png"),
            description=qtprotowallet.protowallet.id,
            focus=True,
            data=qtprotowallet,
        )

        return qtprotowallet

    def add_qt_wallet(
        self, wallet: Wallet, file_path: str | None = None, password: str | None = None
    ) -> QTWallet:
        def set_tab_widget_icon(tab: QWidget, icon: QIcon) -> None:
            idx = self.tab_wallets.indexOf(tab)
            if idx != -1:
                self.tab_wallets.setTabIcon(idx, icon)

        assert wallet.id not in self.qt_wallets, self.tr("A wallet with id {name} is already open.  ").format(
            name=wallet.id
        )

        with LoadingWalletTab(self.tab_wallets, wallet.id, focus=True):
            self.welcome_screen.remove_tab()
            qt_wallet = QTWallet(
                wallet,
                self.config,
                self.signals,
                self.mempool_data,
                self.fx,
                set_tab_widget_icon=set_tab_widget_icon,
                file_path=file_path,
                password=password,
                threading_parent=self.threading_manager,
                get_lang_code=self.language_chooser.get_current_lang_code,
            )

            # tutorial
            qt_wallet.wallet_steps = WalletSteps(
                wallet_tabs=qt_wallet.tabs,
                qtwalletbase=qt_wallet,
                qt_wallet=qt_wallet,
            )

        # add to tabs
        self.qt_wallets[wallet.id] = qt_wallet
        self.tab_wallets.add_tab(
            tab=qt_wallet.tab,
            icon=read_QIcon("status_waiting.svg"),
            description=qt_wallet.wallet.id,
            focus=True,
            data=qt_wallet,
        )

        # search_box = SearchWallets(
        #     lambda: list(self.qt_wallets.values()),
        #     signal_min=self.signals,
        #     parent=self.tab_wallets,
        # )
        # qt_wallet.tabs.set_top_right_widget(search_box)

        qt_wallet.wallet_steps.set_visibilities()
        self.language_chooser.add_signal_language_switch(
            self.signals.wallet_signals[qt_wallet.wallet.id].language_switch
        )
        self.signals.wallet_signals[qt_wallet.wallet.id].show_address.connect(self.show_address)
        self.signals.event_wallet_tab_added.emit()

        # this is a
        self.last_qtwallet = qt_wallet
        return qt_wallet

    def toggle_tutorial(self) -> None:
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message(self.tr("Please complete the wallet setup."))
            return

        if qt_wallet.wallet_steps:
            if qt_wallet.wallet.tutorial_index is None:
                qt_wallet.wallet.tutorial_index = qt_wallet.wallet_steps.step_bar.number_of_steps - 1
            else:
                qt_wallet.wallet.tutorial_index = None

            qt_wallet.wallet_steps.set_visibilities()

    def _get_qt_base_wallet(
        self,
        qt_base_wallets: Iterable[QtWalletBase],
        tab: QWidget | None = None,
        if_none_serve_last_active=False,
    ) -> Optional[QtWalletBase]:
        tab = self.tab_wallets.currentWidget() if tab is None else tab
        for qt_base_wallet in qt_base_wallets:
            if tab == qt_base_wallet.tab:
                return qt_base_wallet
        if if_none_serve_last_active:
            return self.last_qtwallet
        return None

    def get_qt_wallet(
        self, tab: QWidget | None = None, if_none_serve_last_active: bool = False
    ) -> Optional[QTWallet]:
        base_wallet = self._get_qt_base_wallet(
            self.qt_wallets.values(), tab=tab, if_none_serve_last_active=if_none_serve_last_active
        )
        if isinstance(base_wallet, QTWallet):
            return base_wallet
        return None

    def get_blockchain_of_any_wallet(self) -> Optional[bdk.Blockchain]:
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.blockchain:
                return qt_wallet.wallet.blockchain
        return None

    def show_address(self, addr: str, wallet_id: str, parent: QWidget | None = None) -> None:
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return

        d = address_dialog.AddressDialog(
            self.fx,
            self.config,
            self.signals,
            qt_wallet.wallet,
            addr,
            self.mempool_data,
            parent=parent,
        )
        self.address_dialogs.append(d)
        d.show()

    def event_wallet_tab_closed(self) -> None:
        if not self.tab_wallets.count():
            self.welcome_screen.add_new_wallet_welcome_tab()

    def event_wallet_tab_added(self) -> None:
        pass

    def remove_qt_wallet(self, qt_wallet: Optional[QTWallet]) -> None:
        if not qt_wallet:
            return
        for i in range(self.tab_wallets.count()):
            if self.tab_wallets.widget(i) == qt_wallet.tab:
                self.tab_wallets.removeTab(i)

        self.add_recently_open_wallet(qt_wallet.file_path)

        qt_wallet.close()
        QTWallet.remove_lockfile(wallet_file_path=Path(qt_wallet.file_path))
        del self.qt_wallets[qt_wallet.wallet.id]
        self.event_wallet_tab_closed()

    def add_recently_open_wallet(self, file_path: str) -> None:
        self.config.add_recently_open_wallet(file_path)
        self.populate_recent_wallets_menu()

    def remove_all_qt_wallet(self) -> None:

        for qt_wallet in self.qt_wallets.copy().values():
            self.remove_qt_wallet(qt_wallet)

    def close_tab(self, index: int) -> None:
        self.tab_wallets.jump_to_last_active_tab()

        # qt_wallet
        qt_wallet = self.get_qt_wallet(tab=self.tab_wallets.widget(index))
        if qt_wallet:
            if not question_dialog(
                self.tr("Close wallet {id}?").format(id=qt_wallet.wallet.id), self.tr("Close wallet")
            ):
                return
            logger.info(self.tr("Closing wallet {id}").format(id=qt_wallet.wallet.id))
            self.save_qt_wallet(qt_wallet)
        else:
            logger.info(self.tr("Closing tab {name}").format(name=self.tab_wallets.tabText(index)))

        # get the tabdata before removing the tab
        tab_data = self.tab_wallets.tabData(index)
        self.tab_wallets.removeTab(index)
        if isinstance(tab_data, ThreadingManager):
            # this is necessary to ensure the closeevent
            # and with it the thread cleanup is called
            tab_data.end_threading_manager()

        if qt_wallet:
            self.remove_qt_wallet(qt_wallet)

        # other events
        self.event_wallet_tab_closed()

    def sync(self) -> None:
        qt_wallet = self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.sync()

    def closeEvent(self, event: Optional[QCloseEvent]) -> None:
        self.config.last_wallet_files[str(self.config.network)] = [
            qt_wallet.file_path for qt_wallet in self.qt_wallets.values()
        ]

        self.write_current_open_txs_to_config()
        self.config.save()
        self.save_all_wallets()

        self.threading_manager.end_threading_manager()

        self.remove_all_qt_wallet()

        if self.new_startup_network:
            self.config.network = self.new_startup_network
            self.config.save()

        logger.info(f"Finished close handling of {self}")
        super().closeEvent(event)

    def restart(self, new_startup_network: bdk.Network | None = None) -> None:
        """
        Currently only works in Linux
        and then it seems that it freezes. So do not use

        Args:
            new_startup_network (bdk.Network | None, optional): _description_. Defaults to None.
        """
        args: List[str] = []  #  sys.argv[1:]
        self.new_startup_network = new_startup_network
        QCoreApplication.quit()

        status = QProcess.startDetached(sys.executable, ["-m", "bitcoin_safe"] + args)
        if not status:
            sys.exit(-1)

    def shutdown(self, new_startup_network: bdk.Network | None = None) -> None:
        self.new_startup_network = new_startup_network
        QCoreApplication.quit()

    def signal_handler(self, signum, frame) -> None:
        logger.info(f"Handling signal: {signum}")
        close_event = QCloseEvent()
        self.closeEvent(close_event)
        logger.info(f"Received signal {signum}, exiting.")
        QCoreApplication.quit()

    def setup_signal_handlers(self) -> None:
        for sig in [
            getattr(syssignal, attr)
            for attr in ["SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT"]
            if hasattr(syssignal, attr)
        ]:
            syssignal.signal(sig, self.signal_handler)
