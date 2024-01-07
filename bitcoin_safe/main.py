import logging

from .logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


import base64
import os
import sys
from typing import Dict, Optional, Tuple

import bdkpython as bdk
from bitcoin_qrreader import bitcoin_qr, bitcoin_qr_gui
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import QAction, QDialog, QFileDialog, QMenu, QSystemTrayIcon

from .gui.qt.dialogs import PasswordQuestion, WalletIdDialog, question_dialog
from .gui.qt.network_settings import NetworkSettingsUI
from .gui.qt.new_wallet_welcome_screen import NewWalletWelcomeScreen
from .gui.qt.open_tx_dialog import TransactionDialog
from .gui.qt.qt_wallet import QTProtoWallet, QTWallet
from .gui.qt.ui_tx import UITx_Viewer, UITx_ViewerTab
from .gui.qt.util import (
    Message,
    add_tab_to_tabs,
    read_QIcon,
    save_file_dialog,
)
from .gui.qt.utxo_list import UTXOList
from .mempool import MempoolData
from .psbt_util import (
    FeeInfo,
    estimate_segwit_fee_rate_from_psbt,
    get_txouts_from_inputs,
)
from .pythonbdk_types import OutPoint
from .signals import Signals, UpdateFilter
from .storage import Storage
from .tx import TxBuilderInfos, TxUiInfos
from .ui_mainwindow import Ui_MainWindow
from .wallet import (
    ProtoWallet,
    ToolsTxUiInfo,
    Wallet,
)


class MainWindow(Ui_MainWindow):
    def __init__(self):
        super().__init__()

        self.setMinimumSize(800, 650)

        self.qt_wallets: Dict[QTWallet] = {}
        self.fx = None
        self.mempool_data = MempoolData(config=self.config)
        if os.path.isfile("data.csv"):
            self.mempool_data.set_data_from_file("data.csv")
        else:
            self.mempool_data.set_data_from_mempoolspace()

        self.signals = Signals()
        self.last_qtwallet = None
        # connect the listeners
        self.signals.show_address.connect(self.show_address)
        self.signals.open_tx_like.connect(self.open_tx_like_in_tab)
        self.signals.get_network.connect(lambda: self.config.network_config.network)

        self.network_settings_ui = NetworkSettingsUI(self.config)
        self.signals.show_network_settings.connect(self.open_network_settings)

        def callback_post_save():
            self.network_settings_ui.set_config_from_ui()
            self.save_config()
            self.network_settings_ui.close()
            self.mempool_data.set_data_from_mempoolspace(force=True)

        def do_new_network_settings():
            if self.network_settings_ui.does_it_need_restart():
                self.restart(callback_post_save=callback_post_save)
            else:
                callback_post_save()

        self.network_settings_ui.signal_new_network_settings.connect(do_new_network_settings)

        self.welcome_screen = NewWalletWelcomeScreen(
            self.tab_wallets, network=self.config.network_config.network
        )
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

        opened_qt_wallets = self.open_last_opened_wallets()
        if not opened_qt_wallets:
            self.welcome_screen.add_new_wallet_welcome_tab()

        self.open_last_opened_tx()

    def on_signal_broadcast_tx(self, transaction: bdk.Transaction):
        last_qt_wallet_involved: Optional[QTWallet] = None
        for qt_wallet in self.qt_wallets.values():
            if qt_wallet.wallet.transaction_involves_wallet(transaction):
                qt_wallet.sync()
                last_qt_wallet_involved = qt_wallet

        if last_qt_wallet_involved:
            self.tab_wallets.setCurrentWidget(last_qt_wallet_involved.tab)
            last_qt_wallet_involved.tabs.setCurrentWidget(last_qt_wallet_involved.history_tab)

    def on_tab_changed(self, index):
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

    def onTrayIconActivated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            # self.tray.showMessage("This is a test notification")
            Message("test").emit_with(self.signals.notification)

    def open_network_settings(self):
        self.network_settings_ui.show()

    def export_wallet_for_coldcard(self):
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet.wallet:
            return

        filename = save_file_dialog(
            name_filters=["Text (*.txt)", "All Files (*.*)"],
            default_suffix="txt",
            default_filename=f"descriptor_{qt_wallet.wallet.id}.txt",
        )
        if not filename:
            return

        text = f"""# Coldcard descriptor export of wallet {qt_wallet.wallet.id}\n{qt_wallet.wallet.multipath_descriptor.bdk_descriptors[0].as_string() }
        """
        with open(filename, "w") as file:
            file.write(text)

    def open_tx_file(self, file_path=None):
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

    def fetch_txdetails(self, txid) -> Optional[Tuple[Wallet, bdk.TransactionDetails]]:
        for qt_wallet in self.qt_wallets.values():
            tx_details = qt_wallet.wallet.get_tx(txid)
            if tx_details:
                return tx_details
        return None

    def open_tx_like_in_tab(self, txlike):
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
                qt_wallet = self.get_qt_wallet(if_none_serve_last_active=True)
                wallet = qt_wallet.wallet if qt_wallet else None
            if not wallet:
                Message(
                    f"No wallet open. Please open the sender wallet to edit this thransaction."
                ).show_message()
                return

            qt_wallet: QTWallet = self.qt_wallets.get(wallet.id)
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
            res = bitcoin_qr.Data.from_str(txlike, self.config.network_config.network)
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

        tx_dialog = TransactionDialog(network=self.config.network_config.network, on_open=process_input)
        tx_dialog.show()

    def open_tx_in_tab(self, txlike):
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

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            utxo_list,
            network=self.config.network_config.network,
            mempool_data=self.mempool_data,
            fee_info=FeeInfo(fee, tx.vsize(), is_estimated=False) if fee is not None else None,
            confirmation_time=confirmation_time,
            blockchain=self.get_blockchain_of_any_wallet(),
            tx=tx,
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

    def open_psbt_in_tab(self, tx):
        psbt: bdk.PartiallySignedTransaction = None
        fee_info: FeeInfo = None

        logger.debug(f"tx is of type {type(tx)}")

        # converting to TxBuilderResult
        if isinstance(tx, TxBuilderInfos):
            tx = tx.builder_result  # then it is processed in the next if stament
            logger.debug(f"Converted TxBuilderInfos --> {type(tx)}")

        if isinstance(tx, bdk.TxBuilderResult):
            psbt = tx.psbt
            fee_info = estimate_segwit_fee_rate_from_psbt(psbt)
            logger.debug(f"Converted TxBuilderResult --> {type(psbt)}")

        if isinstance(tx, bdk.PartiallySignedTransaction):
            logger.debug(f"Got a PartiallySignedTransaction")
            psbt = tx
            fee_info = estimate_segwit_fee_rate_from_psbt(psbt)

        if isinstance(tx, str):
            psbt = bdk.PartiallySignedTransaction(tx)
            logger.debug(f"Converted str to {type(tx)}")
            fee_info = estimate_segwit_fee_rate_from_psbt(psbt)

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
            txout_dict=get_txouts_from_inputs(psbt=psbt),
            keep_outpoint_order=True,
        )

        viewer = UITx_Viewer(
            self.config,
            self.signals,
            utxo_list,
            network=self.config.network_config.network,
            mempool_data=self.mempool_data,
            fee_info=fee_info,
            blockchain=self.get_blockchain_of_any_wallet(),
            psbt=psbt,
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
        for file_path in self.config.last_wallet_files.get(str(self.config.network_config.network), []):
            qt_wallet = self.open_wallet(file_path=file_path)
            if qt_wallet:
                opened_wallets.append(qt_wallet)
        return opened_wallets

    def open_last_opened_tx(self):
        for serialized in self.config.opened_txlike.get(str(self.config.network_config.network), []):
            self.open_tx_like_in_tab(serialized)

    def open_wallet(self, file_path=None):
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

        logger.debug(f"Selected file: {file_path}")
        if not os.path.isfile(file_path):
            logger.debug(f"There is no such file: {file_path}")
            return
        password = None
        if Storage().has_password(file_path):
            self.ui_password_question = PasswordQuestion()
            password = self.ui_password_question.ask_for_password()
        try:
            wallet: Wallet = Wallet.load(file_path, self.config, password)
        except Exception:
            error_type, error_value, error_traceback = sys.exc_info()
            error_message = f"Error. Wallet could not be loaded. Error: {error_type.__name__}: {error_value}, {error_traceback}"
            self.show_error(error_message)
            raise

        qt_wallet = self.add_qt_wallet(wallet)
        qt_wallet.password = password
        qt_wallet.file_path = file_path
        qt_wallet.sync()

        self.signals.finished_open_wallet.emit(wallet.id)
        return qt_wallet

    def export_bip329_labels(self, wallet_id):
        qt_wallet: QTWallet = self.qt_wallets.get(wallet_id)
        if not qt_wallet:
            return
        s = qt_wallet.wallet.labels.get_bip329_json_str()
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

    def import_bip329_labels(self, wallet_id):
        qt_wallet: QTWallet = self.qt_wallets.get(wallet_id)
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
            lines = file.readlines()

        qt_wallet.wallet.labels.set_data_from_bip329_json_str(lines)
        self.signals.labels_updated.emit(UpdateFilter(refresh_all=True))

    def save_current_wallet(self):
        return self.get_qt_wallet().save()

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

        self.config.opened_txlike[str(self.config.network_config.network)] = l

    def click_create_single_signature_wallet(self):
        qtwallet = self.create_qtprotowallet((1, 1))
        qtwallet.wallet_descriptor_ui.disable_fields()

    def click_create_multisig_signature_wallet(self):
        qtprotowallet = self.create_qtprotowallet((2, 3))
        if qtprotowallet:
            qtprotowallet.wallet_descriptor_ui.disable_fields()

    def click_custom_signature(self):
        return self.create_qtprotowallet((3, 5))

    def new_wallet(self):
        self.welcome_screen.add_new_wallet_welcome_tab()

    def new_wallet_id(self) -> str:
        return "new" + str(len(self.qt_wallets))

    def create_qtprotowallet(self, m_of_n) -> Optional[QTProtoWallet]:
        def create_wallet():
            wallet = Wallet.from_protowallet(
                qtprotowallet.protowallet,
                qtprotowallet.wallet_id,
                self.config,
                tutorial_step=qtprotowallet.step_progress_container.step_bar.current_step,
            )

            for address in wallet.get_addresses():
                wallet.labels.set_addr_category(address, "Friends")

            self.tab_wallets.removeTab(self.tab_wallets.indexOf(qtprotowallet.tab))
            qt_wallet = self.add_qt_wallet(wallet)
            qt_wallet.address_list_tags.add("Friends")
            qt_wallet.address_list_tags.add("KYC-Exchange")
            qt_wallet.save()
            qt_wallet.sync()

        m, n = m_of_n
        protowallet = ProtoWallet(threshold=m, signers=n, network=self.config.network_config.network)

        # ask for wallet name
        dialog = WalletIdDialog(self.config.wallet_dir)
        if dialog.exec_() == QDialog.Accepted:
            wallet_id = dialog.name_input.text()
            print(f"Creating wallet: {wallet_id}")
        else:
            return None

        qtprotowallet = QTProtoWallet(
            wallet_id, config=self.config, signals=self.signals, protowallet=protowallet
        )
        qtprotowallet.signal_close_wallet.connect(
            lambda: self.close_tab(self.tab_wallets.indexOf(qtprotowallet.tab))
        )
        qtprotowallet.signal_create_wallet.connect(create_wallet)

        add_tab_to_tabs(
            self.tab_wallets,
            qtprotowallet.tab,
            read_QIcon("file.png"),
            qtprotowallet.wallet_id,
            qtprotowallet.wallet_id,
            focus=True,
        )

        return qtprotowallet

    def add_qt_wallet(self, wallet: Wallet) -> QTWallet:
        def set_tab_widget_icon(tab, icon):
            idx = self.tab_wallets.indexOf(tab)
            if idx != -1:
                self.tab_wallets.setTabIcon(idx, icon)

        qt_wallet = QTWallet(
            wallet,
            self.config,
            self.signals,
            self.mempool_data,
            set_tab_widget_icon=set_tab_widget_icon,
        )
        qt_wallet.signal_close_wallet.connect(lambda: self.remove_qt_wallet(qt_wallet))

        self.qt_wallets[wallet.id] = qt_wallet
        add_tab_to_tabs(
            self.tab_wallets,
            qt_wallet.tab,
            read_QIcon("file.png"),
            qt_wallet.wallet.id,
            qt_wallet.wallet.id,
            focus=True,
        )
        self.signals.event_wallet_tab_added.emit()
        # this is a
        self.last_qtwallet = qt_wallet
        return qt_wallet

    def toggle_tutorial(self):
        qt_wallet = self.get_qt_wallet()
        if not qt_wallet:
            return
        if not qt_wallet.tabs.isVisible():
            return
        show_tutorial = not qt_wallet.step_progress_container.isVisible()
        qt_wallet.step_progress_container.setVisible(show_tutorial)
        qt_wallet.tabs.setVisible(not show_tutorial)

    def get_qt_wallet(self, tab=None, if_none_serve_last_active=False) -> Optional[QTWallet]:
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

    def toggle_search(self):
        self.get_qt_wallet().toggle_search()

    def show_address(self, addr: str, parent=None):
        from .gui.qt import address_dialog

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
        d.exec_()

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
        del self.qt_wallets[qt_wallet.wallet.id]
        self.event_wallet_tab_closed()

    def close_tab(self, index):
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

    def closeEvent(self, event):
        self.config.last_wallet_files[str(self.config.network_config.network)] = [
            os.path.join(self.config.wallet_dir, qt_wallet.file_path)
            for qt_wallet in self.qt_wallets.values()
        ]
        self.save_config()
        self.save_all_wallets()
        super().closeEvent(event)

    def save_config(self):
        self.write_current_open_txs_to_config()
        self.config.save()

    def restart(self, callback_post_save=None):
        close_event = QCloseEvent()
        self.closeEvent(close_event)

        if close_event.isAccepted():
            if callback_post_save:
                callback_post_save()
            QCoreApplication.quit()  # equivalent to QCoreApplication.exit(0)
            status = QProcess.startDetached(sys.executable, ["-m", "bitcoin_safe"] + sys.argv[1:])
            if not status:
                sys.exit(-1)
        else:
            # The close event was not accepted, so the application will not quit.
            pass
