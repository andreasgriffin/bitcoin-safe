import logging
from collections import deque

from bitcoin_safe.gui.qt.descriptor_ui import KeyStoreUIs
from bitcoin_safe.util import path_to_rel_home_path, rel_home_path_to_abs_path

logger = logging.getLogger(__name__)

import base64
import os
import shlex
import sys
from typing import Deque, Dict, Literal, Optional, Tuple, Union

import bdkpython as bdk
from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui
from bitcoin_qrreader.bitcoin_qr import Data, DataType
from PyQt6.QtCore import QCoreApplication, QProcess
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMenuBar,
    QScrollArea,
    QSizePolicy,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.my_treeview import _create_list_with_toolbar
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.search_tree_view import SearchWallets
from bitcoin_safe.gui.qt.tutorial import WalletSteps

from ...config import UserConfig
from ...fx import FX
from ...i18n import _
from ...mempool import MempoolData
from ...psbt_util import FeeInfo, SimplePSBT
from ...pythonbdk_types import OutPoint
from ...signals import Signals, UpdateFilter
from ...storage import Storage
from ...tx import TxBuilderInfos, TxUiInfos
from ...wallet import ProtoWallet, ToolsTxUiInfo, Wallet, filename_clean
from . import address_dialog
from .dialog_import import ImportDialog
from .dialogs import PasswordQuestion, WalletIdDialog, question_dialog
from .mytabwidget import ExtendedTabWidget
from .network_settings.main import NetworkSettingsUI
from .new_wallet_welcome_screen import NewWalletWelcomeScreen
from .qt_wallet import QTProtoWallet, QTWallet
from .ui_tx import UITx_Viewer, UITx_ViewerTab
from .util import (
    Message,
    MessageType,
    add_tab_to_tabs,
    caught_exception_message,
    icon_path,
    read_QIcon,
)
from .utxo_list import UTXOList


class MainWindow(QMainWindow):
    def __init__(self, network: Literal["bitcoin", "regtest", "signet", "testnet"] = None):
        "If netowrk == None, then the network from the user config will be taken"
        super().__init__()
        self.config = UserConfig.from_file()

        self.config.network = bdk.Network._member_map_[network.upper()] if network else self.config.network
        self.address_dialogs: Deque[address_dialog.AddressDialog] = deque(maxlen=1000)

        self.setupUi(self)

        self.setMinimumSize(600, 450)

        self.qt_wallets: Dict[str, QTWallet] = {}

        self.signals = Signals()

        self.fx = FX()

        self.mempool_data = MempoolData(network_config=self.config.network_config)
        self.mempool_data.set_data_from_mempoolspace()

        self.last_qtwallet = None
        # connect the listeners
        self.signals.show_address.connect(self.show_address)
        self.signals.open_tx_like.connect(self.open_tx_like_in_tab)
        self.signals.get_network.connect(lambda: self.config.network)

        self.network_settings_ui = NetworkSettingsUI(self.config.network, self.config.network_configs)
        self.network_settings_ui.signal_apply_and_restart.connect(self.save_and_restart)
        self.signals.show_network_settings.connect(self.open_network_settings)

        self.welcome_screen = NewWalletWelcomeScreen(self.tab_wallets, network=self.config.network)
        self.welcome_screen.signal_onclick_single_signature.connect(self.click_create_single_signature_wallet)
        self.welcome_screen.signal_onclick_multisig_signature.connect(
            self.click_create_multisig_signature_wallet
        )
        self.welcome_screen.signal_onclick_custom_signature.connect(self.click_custom_signature)
        self.signals.event_wallet_tab_added.connect(self.event_wallet_tab_added)
        self.signals.event_wallet_tab_closed.connect(self.event_wallet_tab_closed)
        self.signals.chain_data_changed.connect(self.sync)
        self.signals.export_bip329_labels.connect(self.export_bip329_labels)
        self.signals.import_bip329_labels.connect(self.import_bip329_labels)
        self.signals.open_wallet.connect(self.open_wallet)
        self.signals.signal_broadcast_tx.connect(self.on_signal_broadcast_tx)

        self._init_tray()

        self.search_box = SearchWallets(
            lambda: list(self.qt_wallets.values()),
            parent=self,
        )
        self.tab_wallets.set_top_right_widget(self.search_box)

        opened_qt_wallets = self.open_last_opened_wallets()
        if not opened_qt_wallets:
            self.welcome_screen.add_new_wallet_welcome_tab()

        self.open_last_opened_tx()

    def set_title(self, network: bdk.Network):
        title = "Bitcoin Safe"
        if network != bdk.Network.BITCOIN:
            title += f" - {network.name}"
        self.setWindowTitle(title)

    def setupUi(self, MainWindow: QWidget):
        # sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        # sizePolicy.setHorizontalStretch(0)
        # sizePolicy.setVerticalStretch(0)
        # sizePolicy.setHeightForWidth(MainWindow.sizePolicy().hasHeightForWidth())
        # MainWindow.setSizePolicy(sizePolicy)
        self.set_title(self.config.network)
        MainWindow.setWindowIcon(read_QIcon("logo.svg"))
        w, h = 900, 600
        MainWindow.resize(w, h)
        MainWindow.setMinimumSize(w, h)

        #####
        self.tab_wallets = ExtendedTabWidget(self)
        self.tab_wallets.setMovable(True)  # Enable tab reordering
        self.tab_wallets.setTabsClosable(True)
        self.tab_wallets.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Connect signals to slots
        self.tab_wallets.tabCloseRequested.connect(self.close_tab)

        # central_widget
        central_widget = QScrollArea()
        vbox = QVBoxLayout(central_widget)
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        # header bar about testnet coins
        if self.config.network != bdk.Network.BITCOIN:
            notification_bar = NotificationBar(
                f"Network = {self.config.network.name.capitalize()}. The coins are worthless!",
                optional_button_text="Change Network",
                callback_optional_button_text=lambda: self.open_network_settings(),
            )
            notification_bar.set_background_color("lightblue")
            notification_bar.set_icon(QIcon(icon_path("bitcoin-testnet.png")))
            vbox.addWidget(notification_bar)

        vbox.addWidget(self.tab_wallets)
        self.setCentralWidget(central_widget)

        self.setMinimumWidth(640)
        self.setMinimumHeight(400)
        if self.config.is_maximized:
            self.showMaximized()

        # self.setWindowIcon(read_QIcon("electrum.png"))
        self.init_menubar()
        ####

    def init_menubar(self):
        # menu
        self.menubar = QMenuBar()
        # menu wallet
        self.menu_wallet = self.menubar.addMenu(_("&Wallet"))

        self.menu_wallet.addAction(_("New Wallet"), self.new_wallet).setShortcut(QKeySequence("Ctrl+N"))
        self.menu_wallet.addAction("Open wallet", self.open_wallet).setShortcut(QKeySequence("Ctrl+O"))
        self.menu_wallet_recent = self.menu_wallet.addMenu(_("&Recent"))

        def factory(file_path: str):
            def f(file_path=file_path):
                self.open_wallet(file_path=file_path)

            return f

        for filepath in self.config.recently_open_wallets:
            self.menu_wallet_recent.addAction(os.path.basename(filepath), factory(filepath))
        self.menu_wallet.addAction("Save Current wallet", self.save_current_wallet).setShortcut(
            QKeySequence("Ctrl+S")
        )
        self.menu_wallet.addSeparator()

        # export wallet
        self.menu_wallet_export = self.menu_wallet.addMenu(_("&Change"))
        self.menu_wallet_export.addAction(_("Rename wallet"), self.change_wallet_id)
        self.menu_wallet_export.addAction(_("Change password"), self.change_wallet_password)

        # export wallet
        self.menu_wallet_export = self.menu_wallet.addMenu(_("&Export"))
        self.menu_wallet_export.addAction(_("Export for Coldcard"), self.export_wallet_for_coldcard)

        self.menu_wallet.addSeparator()

        self.menu_wallet.addAction(_("Refresh"), self.sync).setShortcut(QKeySequence("F5"))

        # menu transaction
        self.menu_transaction = self.menubar.addMenu(_("&Import"))
        self.menu_load_transaction = self.menu_transaction.addMenu(_("&Transaction and PSBT"))
        self.menu_load_transaction.addAction("From file", self.open_tx_file)
        self.menu_load_transaction.addAction("From text", self.dialog_open_tx_from_str).setShortcut(
            QKeySequence("Ctrl+L")
        )
        self.menu_load_transaction.addAction("From QR Code", self.load_tx_like_from_qr).setShortcut(
            QKeySequence("Ctrl+R")
        )

        # menu settings
        self.menu_transaction = self.menubar.addMenu(_("&Settings"))
        self.menu_transaction.addAction("Network Settings", self.open_network_settings).setShortcut(
            QKeySequence("Ctrl+I")
        )

        self.menu_transaction.addAction("Show/Hide Tutorial", self.toggle_tutorial).setShortcut(
            QKeySequence("Ctrl+T")
        )

        # other shortcuts
        self.shortcut_close_tab = QShortcut(QKeySequence("Ctrl+W"), self)
        self.shortcut_close_tab.activated.connect(lambda: self.close_tab(self.tab_wallets.currentIndex()))

        # assigne menu bar
        self.setMenuBar(self.menubar)

    def change_wallet_id(self):
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message("Please select the wallet")
            return

        # ask for wallet name
        dialog = WalletIdDialog(self.config.wallet_dir)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_wallet_id = dialog.name_input.text()
            logger.info(f"new wallet name: {new_wallet_id}")
        else:
            return None

        old_id = qt_wallet.wallet.id

        # in the wallet
        qt_wallet.wallet.id = new_wallet_id
        # change dict key
        self.qt_wallets[new_wallet_id] = qt_wallet
        del self.qt_wallets[old_id]

        # tab text
        self.tab_wallets.setTabText(self.tab_wallets.indexOf(qt_wallet.tab), new_wallet_id)

        # save under new filename
        old_filepath = qt_wallet.file_path
        directory, old_filename = os.path.split(old_filepath)

        new_file_path = os.path.join(directory, filename_clean(new_wallet_id))

        qt_wallet.move_wallet_file(new_file_path)
        qt_wallet.save()
        logger.info(f"Saved {old_filepath} under new name {qt_wallet.file_path}")

    def change_wallet_password(self):
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message("Please select the wallet")
            return

        qt_wallet.change_password()

    def on_signal_broadcast_tx(self, transaction: bdk.Transaction):
        last_qt_wallet_involved: Optional[QTWallet] = None
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.transaction_involves_wallet(transaction):
                qt_wallet.sync()
                last_qt_wallet_involved = qt_wallet

        if last_qt_wallet_involved:
            self.tab_wallets.setCurrentWidget(last_qt_wallet_involved.tab)
            last_qt_wallet_involved.tabs.setCurrentWidget(last_qt_wallet_involved.history_tab)

    def on_tab_changed(self, index: int):
        qt_wallet = self.get_qt_wallet(self.tab_wallets.widget(index))
        if qt_wallet:
            self.last_qtwallet = qt_wallet

    def _init_tray(self):
        self.tray = QSystemTrayIcon(read_QIcon("logo.svg"), None)
        self.tray.setToolTip("Bitcoin Safe")

        menu = QMenu(self)
        exitAction = QAction("&Exit", self, triggered=self.close)
        menu.addAction(exitAction)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.onTrayIconActivated)

        self.signals.notification.connect(self.show_message_as_tray_notification)
        self.tray.show()

    def show_message_as_tray_notification(self, message: Message):
        title = message.title if message.title else "Bitcoin Safe"
        if message.icon:
            if message.msecs:
                return self.tray.showMessage(title, message.msg, message.icon, message.msecs)
            return self.tray.showMessage(title, message.msg, message.icon)
        return self.tray.showMessage(title, message.msg)

    def onTrayIconActivated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            # self.tray.showMessage("This is a test notification")
            Message("test", no_show=True).emit_with(self.signals.notification)

    def open_network_settings(self):
        self.network_settings_ui.exec()

    def export_wallet_for_coldcard(self, wallet: Wallet = None):
        qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
        if not qt_wallet or not qt_wallet.wallet:
            Message("Please select the wallet first.", type=MessageType.Warning)
            return

        qt_wallet.export_wallet_for_coldcard()

    def open_tx_file(self, file_path: Optional[str] = None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Transaction/PSBT",
                "",
                "All Files (*);;PSBT (*.psbt);;Transation (*.tx)",
            )
            if not file_path:
                logger.debug("No file selected")
                return

        logger.debug(f"Selected file: {file_path}")
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
    ):
        logger.debug(f"Trying to open tx with type {type(txlike)}")

        # first do the bdk instance cases
        if isinstance(txlike, (bdk.TransactionDetails, bdk.Transaction)):
            return self.open_tx_in_tab(txlike)

        if isinstance(txlike, (bdk.PartiallySignedTransaction, TxBuilderInfos)):
            return self.open_psbt_in_tab(txlike)

        if isinstance(txlike, TxUiInfos):
            wallet = ToolsTxUiInfo.get_likely_source_wallet(txlike, self.signals)

            if not wallet:
                logger.debug(
                    f"Could not identify the wallet belonging to the transaction inputs. Trying to open anyway..."
                )
                current_qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
                wallet = current_qt_wallet.wallet if current_qt_wallet else None
            if not wallet:
                Message(f"No wallet open. Please open the sender wallet to edit this thransaction.")
                return

            qt_wallet = self.qt_wallets.get(wallet.id)
            if not qt_wallet:
                Message(" Please open the sender wallet to edit this thransaction.")
                return
            self.tab_wallets.setCurrentWidget(qt_wallet.tab)
            qt_wallet.tabs.setCurrentWidget(qt_wallet.send_tab)

            ToolsTxUiInfo.pop_change_recipient(txlike, wallet)
            return qt_wallet.uitx_creator.set_ui(txlike)

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
            res = bitcoin_qr.Data.from_str(txlike, self.config.network)
            if res.data_type == bitcoin_qr.DataType.Txid:
                txdetails = self.fetch_txdetails(res.data)
                if txdetails:
                    return self.open_tx_in_tab(txdetails)
                if not txlike:
                    raise Exception(f"txid {res.data} could not be found in wallets")
            elif res.data_type == bitcoin_qr.DataType.PSBT:
                return self.open_psbt_in_tab(res.data)
            elif res.data_type == bitcoin_qr.DataType.Tx:
                return self.open_tx_in_tab(res.data)
            else:
                logger.warning(f"DataType {res.data_type.name} was not handled.")

    def load_tx_like_from_qr(self):
        def result_callback(data: bitcoin_qr.Data):
            if data.data_type in [
                bitcoin_qr.DataType.PSBT,
                bitcoin_qr.DataType.Tx,
                bitcoin_qr.DataType.Txid,
            ]:
                self.open_tx_like_in_tab(data.data)

        window = bitcoin_qr_gui.BitcoinVideoWidget(result_callback=result_callback)
        window.show()

    def dialog_open_tx_from_str(self):
        def process_input(s: str):
            self.open_tx_like_in_tab(s)

        tx_dialog = ImportDialog(network=self.config.network, on_open=process_input)
        tx_dialog.show()

    def open_tx_in_tab(self, txlike: Union[bdk.Transaction, bdk.TransactionDetails]):
        tx: bdk.Transaction = None
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

        def get_outpoints():
            return [OutPoint.from_bdk(input.previous_output) for input in tx.input()]

        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=get_outpoints,
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
            ],
            keep_outpoint_order=True,
        )

        widget_utxo_with_toolbar = _create_list_with_toolbar(utxo_list, self.tab_wallets, self.config)

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            self.fx,
            widget_utxo_with_toolbar,
            utxo_list,
            network=self.config.network,
            mempool_data=self.mempool_data,
            fee_info=FeeInfo(fee, tx.vsize(), is_estimated=False) if fee is not None else None,
            confirmation_time=confirmation_time,
            blockchain=self.get_blockchain_of_any_wallet(),
            data=Data(tx, data_type=DataType.Tx),
        )

        add_tab_to_tabs(
            self.tab_wallets,
            viewer.main_widget,
            read_QIcon("send.svg"),
            f"Transaction {tx.txid()[:4]}...{tx.txid()[-4:]}",
            f"Transaction {tx.txid()[:4]}...{tx.txid()[-4:]}",
            focus=True,
        )

        return viewer.main_widget, viewer

    def open_psbt_in_tab(
        self,
        tx: Union[
            bdk.PartiallySignedTransaction, TxBuilderInfos, bdk.TxBuilderResult, str, bdk.TransactionDetails
        ],
    ):
        psbt: bdk.PartiallySignedTransaction = None
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
            print("is bdk.TransactionDetails")
            raise Exception("cannot handle TransactionDetails")

        def get_outpoints():
            return [OutPoint.from_bdk(input.previous_output) for input in psbt.extract_tx().input()]

        utxo_list = UTXOList(
            self.config,
            self.signals,
            get_outpoints=get_outpoints,
            hidden_columns=[
                UTXOList.Columns.OUTPOINT,
                UTXOList.Columns.PARENTS,
            ],
            txout_dict=SimplePSBT.from_psbt(psbt).get_prev_txouts(),
            keep_outpoint_order=True,
        )

        widget_utxo_with_toolbar = _create_list_with_toolbar(utxo_list, self.tab_wallets, self.config)

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            self.fx,
            widget_utxo_with_toolbar,
            utxo_list,
            network=self.config.network,
            mempool_data=self.mempool_data,
            fee_info=fee_info,
            blockchain=self.get_blockchain_of_any_wallet(),
            data=Data(psbt, data_type=DataType.PSBT),
        )

        txid = psbt.extract_tx().txid()
        add_tab_to_tabs(
            self.tab_wallets,
            viewer.main_widget,
            read_QIcon("qr-code.svg"),
            f"PSBT {txid[:4]}...{txid[-4:]}",
            f"PSBT {txid[:4]}...{txid[-4:]}",
            focus=True,
        )

        return viewer.main_widget, viewer

    def open_last_opened_wallets(self):
        opened_wallets = []
        for file_path in self.config.last_wallet_files.get(str(self.config.network), []):
            qt_wallet = self.open_wallet(file_path=rel_home_path_to_abs_path(file_path))
            if qt_wallet:
                opened_wallets.append(qt_wallet)
        return opened_wallets

    def open_last_opened_tx(self):
        for serialized in self.config.opened_txlike.get(str(self.config.network), []):
            self.open_tx_like_in_tab(serialized)

    def open_wallet(self, file_path: Optional[str] = None):
        if not file_path:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open Wallet",
                self.config.wallet_dir,
                "All Files (*);;Text Files (*.bitcoinsafe)",
            )
            if not file_path:
                logger.debug("No file selected")
                return

        # make sure this wallet isn't open already
        opened_file_paths = [qt_wallet.file_path for qt_wallet in self.qt_wallets.values()]
        if file_path in opened_file_paths:
            Message(f"The wallet {file_path} is already open.")
            return

        logger.debug(f"Selected file: {file_path}")
        if not os.path.isfile(file_path):
            logger.debug(f"There is no such file: {file_path}")
            return
        password = None
        if Storage().has_password(file_path):
            direcory, filename = os.path.split(file_path)
            ui_password_question = PasswordQuestion(label_text=f"Please enter the password for {filename}:")
            password = ui_password_question.ask_for_password()
        try:
            wallet: Wallet = Wallet.from_file(file_path, self.config, password)
        except Exception as e:
            caught_exception_message(e, "Error. Wallet could not be loaded.")
            return

        qt_wallet = self.add_qt_wallet(wallet)
        qt_wallet.password = password
        qt_wallet.file_path = file_path
        qt_wallet.sync()

        # ensure that the newest open file moves to the top of the queue, but isn't added multiple times
        if qt_wallet.file_path in self.config.recently_open_wallets:
            self.config.recently_open_wallets.remove(qt_wallet.file_path)
        self.config.recently_open_wallets.append(qt_wallet.file_path)

        self.signals.finished_open_wallet.emit(wallet.id)
        return qt_wallet

    def export_bip329_labels(self, wallet_id: str):
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return
        s = qt_wallet.wallet.labels.export_bip329_jsonlines()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export labels",
            f"{wallet_id}_labels.jsonl",
            "All Files (*);;JSON Files (*.jsonl);;JSON Files (*.json)",
        )
        if not file_path:
            logger.debug("No file selected")
            return

        with open(file_path, "w") as file:
            file.write(s)

    def import_bip329_labels(self, wallet_id: str):
        qt_wallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Export labels",
            "",
            "All Files (*);;JSON Files (*.jsonl);;JSON Files (*.json)",
        )
        if not file_path:
            logger.debug("No file selected")
            return

        with open(file_path, "r") as file:
            lines = file.read()

        qt_wallet.wallet.labels.import_bip329_jsonlines(lines)
        self.signals.labels_updated.emit(UpdateFilter(refresh_all=True))

    def save_current_wallet(self):
        qt_wallet = self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.save()

    def save_all_wallets(self):
        for qt_wallet in self.qt_wallets.values():
            qt_wallet.save()

    def write_current_open_txs_to_config(self):
        l = []

        for index in range(self.tab_wallets.count()):
            # Get the widget for the current tab
            tab = self.tab_wallets.widget(index)
            if isinstance(tab, UITx_ViewerTab):
                l.append(tab.serialize())

        self.config.opened_txlike[str(self.config.network)] = l

    def click_create_single_signature_wallet(self):
        qtwallet = self.create_qtprotowallet((1, 1), show_tutorial=True)
        if qtwallet:
            qtwallet.wallet_descriptor_ui.disable_fields()

    def click_create_multisig_signature_wallet(self):
        qtprotowallet = self.create_qtprotowallet((2, 3), show_tutorial=True)
        if qtprotowallet:
            qtprotowallet.wallet_descriptor_ui.disable_fields()

    def click_custom_signature(self):
        return self.create_qtprotowallet((3, 5), show_tutorial=False)

    def new_wallet(self):
        self.welcome_screen.add_new_wallet_welcome_tab()

    def new_wallet_id(self) -> str:
        return "new" + str(len(self.qt_wallets))

    def create_qtwallet_from_protowallet(self, protowallet: ProtoWallet):

        wallet = Wallet.from_protowallet(
            protowallet,
            self.config,
        )

        qt_wallet = self.add_qt_wallet(wallet)
        # adding these should only be done at wallet creation
        qt_wallet.address_list_tags.add("Friends")
        qt_wallet.address_list_tags.add("KYC-Exchange")
        qt_wallet.save()
        qt_wallet.sync()

    def create_qtwallet_from_ui(
        self,
        wallet_tab: QWidget,
        protowallet: ProtoWallet,
        keystore_uis: KeyStoreUIs,
        wallet_steps: WalletSteps,
    ):
        if keystore_uis.ask_accept_unexpected_origins():
            self.tab_wallets.removeTab(self.tab_wallets.indexOf(wallet_tab))
            self.create_qtwallet_from_protowallet(protowallet=protowallet)
        else:
            wallet_steps.set_current_index(wallet_steps.current_index() - 1)
            return

    def create_qtwallet_from_qtprotowallet(self, qtprotowallet: QTProtoWallet):
        self.create_qtwallet_from_ui(
            wallet_tab=qtprotowallet.tab,
            protowallet=qtprotowallet.protowallet,
            keystore_uis=qtprotowallet.wallet_descriptor_ui.keystore_uis,
            wallet_steps=qtprotowallet.wallet_steps,
        )

    def create_qtprotowallet(self, m_of_n: Tuple[int, int], show_tutorial=False) -> Optional[QTProtoWallet]:

        # ask for wallet name
        dialog = WalletIdDialog(self.config.wallet_dir)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            wallet_id = dialog.name_input.text()
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

        qtprotowallet = QTProtoWallet(config=self.config, signals=self.signals, protowallet=protowallet)
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

        wallet_steps.signal_create_wallet.connect(
            lambda: self.create_qtwallet_from_ui(
                wallet_tab=qtprotowallet.tab,
                protowallet=protowallet,
                keystore_uis=wallet_steps.keystore_uis,
                wallet_steps=wallet_steps,
            )
        )

        # add to tabs
        add_tab_to_tabs(
            self.tab_wallets,
            qtprotowallet.tab,
            read_QIcon("file.png"),
            qtprotowallet.protowallet.id,
            qtprotowallet.protowallet.id,
            focus=True,
        )

        return qtprotowallet

    def add_qt_wallet(self, wallet: Wallet) -> QTWallet:
        def set_tab_widget_icon(tab: QWidget, icon: QIcon):
            idx = self.tab_wallets.indexOf(tab)
            if idx != -1:
                self.tab_wallets.setTabIcon(idx, icon)

        assert wallet.id not in self.qt_wallets, f"A wallet with id {wallet.id} is already open.  "

        qt_wallet = QTWallet(
            wallet,
            self.config,
            self.signals,
            self.mempool_data,
            self.fx,
            set_tab_widget_icon=set_tab_widget_icon,
        )
        qt_wallet.signal_close_wallet.connect(lambda: self.remove_qt_wallet(qt_wallet))

        # tutorial
        qt_wallet.wallet_steps = WalletSteps(
            wallet_tabs=qt_wallet.tabs,
            qtwalletbase=qt_wallet,
            qt_wallet=qt_wallet,
        )
        # save after every step
        qt_wallet.wallet_steps.signal_set_current_widget.connect(lambda widget: qt_wallet.save())

        # add to tabs
        self.qt_wallets[wallet.id] = qt_wallet
        add_tab_to_tabs(
            self.tab_wallets,
            qt_wallet.tab,
            read_QIcon("file.png"),
            qt_wallet.wallet.id,
            qt_wallet.wallet.id,
            focus=True,
        )
        qt_wallet.wallet_steps.set_visibilities()
        self.signals.event_wallet_tab_added.emit()
        # this is a
        self.last_qtwallet = qt_wallet
        return qt_wallet

    def toggle_tutorial(self):
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            Message("Please complete the wallet setup.")
            return

        if qt_wallet.wallet_steps:
            if qt_wallet.wallet.tutorial_index is None:
                qt_wallet.wallet.tutorial_index = qt_wallet.wallet_steps.step_bar.number_of_steps - 1
            else:
                qt_wallet.wallet.tutorial_index = None

            qt_wallet.wallet_steps.set_visibilities()

    def get_qt_wallet(self, tab: QTabWidget = None, if_none_serve_last_active=False) -> Optional[QTWallet]:
        wallet_tab = self.tab_wallets.currentWidget() if tab is None else tab
        for qt_wallet in self.qt_wallets.values():
            if wallet_tab == qt_wallet.tab:
                return qt_wallet
        if if_none_serve_last_active:
            return self.last_qtwallet
        return None

    def get_blockchain_of_any_wallet(self) -> bdk.Blockchain:
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.blockchain:
                return qt_wallet.wallet.blockchain

    def show_address(self, addr: str, parent=None):

        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            return

        d = address_dialog.AddressDialog(
            self.fx,
            self.config,
            self.signals,
            qt_wallet.wallet,
            addr,
            parent=parent,
        )
        self.address_dialogs.append(d)
        d.show()

    def event_wallet_tab_closed(self):
        if not self.tab_wallets.count():
            self.welcome_screen.add_new_wallet_welcome_tab()

    def event_wallet_tab_added(self):
        pass

    def remove_qt_wallet(self, qt_wallet: QTWallet):
        if not qt_wallet:
            return
        for i in range(self.tab_wallets.count()):
            if self.tab_wallets.widget(i) == qt_wallet.tab:
                self.tab_wallets.removeTab(i)

        qt_wallet.disconnect_signals()
        qt_wallet.stop_sync_timer()
        del self.qt_wallets[qt_wallet.wallet.id]
        self.event_wallet_tab_closed()

    def close_tab(self, index: int):
        qt_wallet = self.get_qt_wallet(tab=self.tab_wallets.widget(index))
        if qt_wallet:
            if not question_dialog(f"Close wallet {qt_wallet.wallet.id}?", "Close wallet"):
                return
            logger.debug(f"Closing wallet {qt_wallet.wallet.id}")
            qt_wallet.save()
        else:
            logger.debug(f"Closing tab {self.tab_wallets.tabText(index)}")
        self.tab_wallets.removeTab(index)
        if qt_wallet:
            self.remove_qt_wallet(qt_wallet)
        self.event_wallet_tab_closed()

    def sync(self):
        qt_wallet = self.get_qt_wallet()
        if qt_wallet:
            qt_wallet.sync()

    def closeEvent(self, event: QCloseEvent):
        self.config.last_wallet_files[str(self.config.network)] = [
            path_to_rel_home_path(os.path.join(self.config.wallet_dir, qt_wallet.file_path))
            for qt_wallet in self.qt_wallets.values()
        ]
        self.save_config()
        self.save_all_wallets()
        super().closeEvent(event)

    def save_config(self):
        self.write_current_open_txs_to_config()
        self.config.save()

    def save_and_restart(self, params: str):
        self.save_config()
        self.restart(params=params)

    def restart(self, params: str):
        # Use shlex.split to properly handle spaces and special characters in arguments
        params_list = shlex.split(params)

        # Prepare the command line arguments, excluding the first one which is the script name
        # and add the new params_list
        args = sys.argv[1:] + params_list

        # Trigger the close event
        close_event = QCloseEvent()
        self.closeEvent(close_event)

        if close_event.isAccepted():
            # Quit the current application
            QCoreApplication.quit()

            # Start a new instance of the application with the updated arguments
            status = QProcess.startDetached(sys.executable, ["-m", "bitcoin_safe"] + args)

            # If the application failed to restart, exit with an error code
            if not status:
                sys.exit(-1)
        else:
            # The close event was not accepted, so the application will not quit.
            pass
