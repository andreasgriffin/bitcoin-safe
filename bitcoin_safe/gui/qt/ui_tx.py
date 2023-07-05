import logging

from bitcoin_safe.config import UserConfig

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from .category_list import CategoryList
from .recipients import Recipients, CustomDoubleSpinBox
from .slider import CustomSlider
from ...signals import Signal
import bdkpython as bdk
from typing import List, Dict
from .utxo_list import UTXOList
from ...tx import TXInfos
from ...signals import Signals
from .barchart import MempoolBarChart
from ...mempool import get_prio_fees, fee_to_depth, fee_to_blocknumber
from PySide2.QtGui import QPixmap, QImage
from ...qr import create_qr

from ...keystore import KeyStore
from .util import read_QIcon, open_website
from .keystore_ui import SignerUI
from ...signer import SignerWallet
from ...util import psbt_to_hex, Satoshis, serialized_to_hex, block_explorer_URL
from .block_buttons import ConfirmedBlock, MempoolButtons, MempoolProjectedBlock
from ...mempool import MempoolData, fees_of_depths
from ...pythonbdk_types import Recipient
from PySide2.QtCore import Signal, QObject
from .qrcodewidget import QRLabel
from ...wallet import UtxosForInputs, Wallet
import json
from ...pythonbdk_types import robust_address_str_from_script
from .util import ShowCopyLineEdit, ShowCopyTextEdit

max_reasonable_fee_rate_fallback = 100


def create_button_bar(layout, button_texts) -> List[QPushButton]:
    button_bar = QWidget()
    button_bar_layout = QHBoxLayout(button_bar)

    buttons = []
    for button_text in button_texts:
        button = QPushButton(button_bar)
        button.setText(button_text)
        button.setMinimumHeight(30)
        button_bar_layout.addWidget(button)
        buttons.append(button)

    layout.addWidget(button_bar)
    return buttons


def create_groupbox(layout, title=None):
    g = QGroupBox()
    if title:
        g.setTitle(title)
    g_layout = QVBoxLayout(g)
    layout.addWidget(g)
    return g, g_layout


class ExportData(QObject):
    signal_export_to_file = Signal()

    def __init__(self, layout, allow_edit=False, title_for_serialized="PSBT") -> None:
        super().__init__()
        self.title_for_serialized = title_for_serialized
        self.seralized = None
        self.json_str = None
        self.txid = None
        self.tabs = QTabWidget()
        self.tabs.setMaximumWidth(300)
        self.tabs.setMaximumHeight(200)
        self.signal_export_to_file.connect(self.export_to_file)

        # qr
        self.tab_qr = QWidget()
        self.tab_qr_layout = QHBoxLayout(self.tab_qr)
        self.tab_qr_layout.setAlignment(Qt.AlignVCenter)
        self.qr_label = QRLabel()
        self.qr_label.setWordWrap(True)
        self.tab_qr_layout.addWidget(self.qr_label)
        self.tabs.addTab(self.tab_qr, "QR")

        # right side of qr
        self.tab_qr_right_side = QWidget()
        self.tab_qr_right_side_layout = QVBoxLayout(self.tab_qr_right_side)
        self.tab_qr_right_side_layout.setAlignment(Qt.AlignCenter)
        self.tab_qr_layout.addWidget(self.tab_qr_right_side)

        self.button_enlarge_qr = QToolButton()
        self.button_enlarge_qr.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_enlarge_qr.setText("Enlarge")
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))
        self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.tab_qr_right_side_layout.addWidget(self.button_enlarge_qr)

        self.button_save_qr = QToolButton()
        self.button_save_qr.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_save_qr.setText("Save as image")
        self.button_save_qr.setIcon(read_QIcon("download.png"))
        self.button_save_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.tab_qr_right_side_layout.addWidget(self.button_save_qr)

        # psbt
        self.tab_seralized = QWidget()
        self.form_layout = QFormLayout(self.tab_seralized)
        self.txid_edit = ShowCopyLineEdit()
        self.txid_edit.buttons[0].setStyleSheet("background-color: white;")
        self.form_layout.addRow("TxId", self.txid_edit)
        self.edit_seralized = ShowCopyTextEdit()
        self.edit_seralized.buttons[0].setStyleSheet("background-color: white;")
        if not allow_edit:
            self.edit_seralized.setReadOnly(True)
        self.form_layout.addRow("Tx", self.edit_seralized)

        self.set_tab_visibility(
            self.tab_seralized, True, self.title_for_serialized, index=1
        )

        # json
        self.tab_json = QWidget()
        self.tab_json_layout = QVBoxLayout(self.tab_json)
        self.edit_json = ShowCopyTextEdit()
        self.edit_json.buttons[0].setStyleSheet("background-color: white;")
        if not allow_edit:
            self.edit_json.setReadOnly(True)
        self.tab_json_layout.addWidget(self.edit_json)
        self.set_tab_visibility(self.tab_json, True, "JSON", index=2)

        # file
        self.tab_file = QWidget()
        self.tab_file_layout = QVBoxLayout(self.tab_file)
        self.tab_file_layout.setAlignment(Qt.AlignHCenter)
        self.button_file = QToolButton()
        self.button_file.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_file.setText(f"Export {self.title_for_serialized} file")
        self.button_file.setIcon(read_QIcon("download.png"))
        self.button_file.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_file.clicked.connect(lambda: self.signal_export_to_file.emit())
        self.tab_file_layout.addWidget(self.button_file)
        self.tabs.addTab(self.tab_file, f"Export {self.title_for_serialized} file")

        layout.addWidget(self.tabs)

    def export_qrcode(self):
        filename = self.save_file_dialog(
            name_filters=["Image (*.png)", "All Files (*.*)"], default_suffix="png"
        )
        if not filename:
            return

        # Ensure the file has the .png extension
        if not filename.lower().endswith(".png"):
            filename += ".png"

        self.qr_label.pil_image.save(filename)

    def set_tab_visibility(self, tab, visible, title, index=0):
        if self.tabs.indexOf(tab) == -1 and visible:
            self.tabs.insertTab(index, tab, title)
        elif self.tabs.indexOf(tab) != -1 and not visible:
            self.tabs.removeTab(self.tabs.indexOf(tab))

    def set_data(self, txid=None, seralized=None, json_str=None):
        self.seralized = seralized
        self.json_str = json_str
        self.txid = txid

        self.set_tab_visibility(self.tab_json, bool(json_str), "JSON", index=2)
        self.set_tab_visibility(
            self.tab_seralized, bool(seralized), self.title_for_serialized, index=2
        )
        if txid:
            self.txid_edit.setText(txid)
        if seralized:
            self.edit_seralized.setText(seralized)

            img = create_qr(seralized)
            if img:
                self.qr_label.set_image(img)
            else:
                self.qr_label.setText("Data too large.\nNo QR Code could be generated")

        if json_str:
            json_text = json.dumps(json.loads(json_str), indent=4)
            self.edit_json.setText(json_text)

    def export_to_file(self):
        filename = self.save_file_dialog(
            name_filters=["PSBT Files (*.psbt)", "All Files (*.*)"],
            default_suffix="psbt",
        )
        if not filename:
            return

        with open(filename, "w") as file:
            file.write(self.seralized)

    def save_file_dialog(self, name_filters=None, default_suffix=None):
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog  # Use Qt-based dialog, not native platform dialog

        file_dialog = QFileDialog()
        file_dialog.setOptions(options)
        file_dialog.setWindowTitle("Save File")
        if default_suffix:
            file_dialog.setDefaultSuffix(default_suffix)

        # Set a default filename
        if self.txid:
            file_dialog.selectFile(f"{self.txid}.{default_suffix}")

        file_dialog.setAcceptMode(QFileDialog.AcceptSave)
        file_dialog.setDefaultSuffix(self.title_for_serialized.lower())
        if name_filters:
            file_dialog.setNameFilters(name_filters)

        if file_dialog.exec_() == QFileDialog.Accepted:
            selected_file = file_dialog.selectedFiles()[0]
            # Do something with the selected file path, e.g., save data to the file
            logger.debug(f"Selected save file: {selected_file}")
            return selected_file


class FeeGroup(QObject):
    signal_set_fee_rate = Signal(float)

    def __init__(
        self,
        mempool_data: MempoolData,
        layout,
        allow_edit=True,
        is_viewer=False,
        confirmation_time=None,
        url=None,
    ) -> None:
        super().__init__()

        self.allow_edit = allow_edit
        self.confirmation_time: bdk.BlockTime = None
        self.txid = None

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee.setTitle("Fee")
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.groupBox_Fee.setAlignment(Qt.AlignTop)
        groupBox_Fee_layout = QVBoxLayout(self.groupBox_Fee)
        groupBox_Fee_layout.setAlignment(Qt.AlignHCenter)
        groupBox_Fee_layout.setContentsMargins(
            layout.contentsMargins().left() / 5,
            layout.contentsMargins().top() / 5,
            layout.contentsMargins().right() / 5,
            layout.contentsMargins().bottom() / 5,
        )

        if confirmation_time:
            self.mempool = ConfirmedBlock(mempool_data, url=url)
        elif is_viewer:
            self.mempool = MempoolProjectedBlock(mempool_data, url=url)
        else:
            self.mempool = MempoolButtons(mempool_data, button_count=3)

        if allow_edit:
            self.mempool.signal_click.connect(self.set_fee_rate)
        groupBox_Fee_layout.addWidget(
            self.mempool.button_group, alignment=Qt.AlignHCenter
        )

        self.high_fee_warning_label = QLabel()
        self.high_fee_warning_label.setText(
            "<font color='red'><b>High feerate</b></font>"
        )
        self.high_fee_warning_label.setHidden(True)
        if not confirmation_time:
            groupBox_Fee_layout.addWidget(
                self.high_fee_warning_label, alignment=Qt.AlignHCenter
            )

        self.non_final_fee_label = QLabel()
        self.non_final_fee_label.setText(
            "<font color='black'><b>Non-final feerate</b></font>"
        )
        self.non_final_fee_label.setHidden(True)
        groupBox_Fee_layout.addWidget(
            self.non_final_fee_label, alignment=Qt.AlignHCenter
        )

        self.widget_around_spin_box = QWidget()
        self.widget_around_spin_box_layout = QHBoxLayout(self.widget_around_spin_box)
        self.widget_around_spin_box_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Remove margins
        if not confirmation_time:
            groupBox_Fee_layout.addWidget(
                self.widget_around_spin_box, alignment=Qt.AlignHCenter
            )

        self.spin_fee_rate = QDoubleSpinBox()
        if not allow_edit:
            self.spin_fee_rate.setReadOnly(True)
        self.spin_fee_rate.setRange(0.0, 1000)  # Set the acceptable range
        self.spin_fee_rate.setSingleStep(1)  # Set the step size
        self.spin_fee_rate.setDecimals(1)  # Set the number of decimal places
        self.spin_fee_rate.setMaximumWidth(55)
        self.spin_fee_rate.editingFinished.connect(
            lambda: self.set_fee_rate(self.spin_fee_rate.value())
        )

        self.widget_around_spin_box_layout.addWidget(self.spin_fee_rate)

        self.spin_label = QLabel()
        self.spin_label.setText("Sat/vB")
        if not confirmation_time:
            self.widget_around_spin_box_layout.addWidget(self.spin_label)

        self.spin_label2 = QLabel()
        if not confirmation_time:
            groupBox_Fee_layout.addWidget(self.spin_label2, alignment=Qt.AlignHCenter)

        layout.addWidget(self.groupBox_Fee, alignment=Qt.AlignHCenter)

    def set_fee_rate(
        self, fee_rate, confirmation_time: bdk.BlockTime = None, txid=None
    ):
        self.spin_fee_rate.setValue(fee_rate)
        self.mempool.set_fee_rate(
            fee_rate=fee_rate, confirmation_time=confirmation_time
        )
        self.confirmation_time = confirmation_time

        # warning
        warning = ""

        fees = fees_of_depths(self.mempool.mempool_data.data, [1e6])
        max_reasonable_fee_rate = (
            fees[0] * 2 if fees else max_reasonable_fee_rate_fallback
        )

        self.high_fee_warning_label.setHidden(not (fee_rate > max_reasonable_fee_rate))

        self.spin_label2.setText(
            f"in ~{fee_to_blocknumber(self.mempool.mempool_data.data, fee_rate)}. Block"
        )

        self.signal_set_fee_rate.emit(fee_rate)

    def update_spin_fee(self):
        self.spin_fee_rate.setRange(
            1, self.mempool.data[:, 0].max()
        )  # Set the acceptable range


# class BlockExplorerGroup(QObject):
#     signal_clicked = Signal(float)

#     def __init__(
#         self, txid, layout
#     ) -> None:
#         super().__init__()


#         # add the groupBox
#         self.groupBox = QGroupBox()
#         self.groupBox.setTitle("Block Explorer")
#         self.groupBox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
#         self.groupBox.setAlignment(Qt.AlignTop)

#         groupBox_Fee_layout = QVBoxLayout(self.groupBox)
#         groupBox_Fee_layout.setAlignment(Qt.AlignHCenter)


#         # add edit field with txid
#         self.edit = QLineEdit(self.groupBox)
#         self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
#         self.edit.setReadOnly(True)
#         groupBox_Fee_layout.addWidget(self.edit)
#         # add button
#         self.button = QPushButton(self.groupBox)
#         groupBox_Fee_layout.addWidget(self.button)


#         self.set_txid(txid)
#         layout.addWidget(self.groupBox, alignment=Qt.AlignHCenter)


#     def set_txid(self, txid):
#         self.edit.setText(txid)
#         self.button.clicked.connect(lambda: open_website(f'https://mempool.space/tx/{txid}'))


class UITX_Base(QObject):
    def __init__(
        self, config: UserConfig, signals: Signals, mempool_data: MempoolData
    ) -> None:
        super().__init__()
        self.signals = signals
        self.mempool_data = mempool_data
        self.config = config

    def create_recipients(self, layout, parent=None, allow_edit=True):
        recipients = Recipients(self.signals, allow_edit=allow_edit)
        layout.addWidget(recipients)
        recipients.setMinimumWidth(250)
        return recipients


class UIPSBT_Viewer(UITX_Base):
    signal_edit_tx = Signal()
    signal_save_psbt = Signal()
    signal_broadcast_tx = Signal()

    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        config: UserConfig,
        signals: Signals,
        utxo_list: UTXOList,
        network: bdk.Network,
        mempool_data: MempoolData,
        fee_rate=None,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.psbt: bdk.PartiallySignedTransaction = psbt
        self.network = network
        self.fee_rate = fee_rate
        self.utxo_list = utxo_list

        self.signers: List[SignerWallet] = []

        self.main_widget = QWidget()
        self.main_widget_layout = QVBoxLayout(self.main_widget)

        self.upper_widget = QWidget(self.main_widget)
        self.main_widget_layout.addWidget(self.upper_widget)
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)

        # in out
        self.tabs_inputs_outputs = QTabWidget(self.main_widget)
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        # inputs
        self.tab_inputs = QWidget(self.main_widget)
        self.tab_inputs_layout = QVBoxLayout(self.tab_inputs)
        self.tab_inputs_layout.addWidget(utxo_list)
        self.tabs_inputs_outputs.addTab(self.tab_inputs, "Inputs")

        # outputs
        self.tab_outputs = QWidget(self.main_widget)
        self.tab_outputs_layout = QVBoxLayout(self.tab_outputs)
        self.tabs_inputs_outputs.addTab(self.tab_outputs, "Outputs")
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)

        self.recipients = self.create_recipients(
            self.tab_outputs_layout, allow_edit=False
        )

        # fee_rate
        self.fee_group = FeeGroup(
            self.mempool_data,
            self.upper_widget_layout,
            allow_edit=False,
            is_viewer=True,
            url=block_explorer_URL(config, "tx", psbt.txid()) if psbt else None,
        )

        self.lower_widget = QWidget(self.main_widget)
        self.lower_widget.setMaximumHeight(220)
        self.main_widget_layout.addWidget(self.lower_widget)
        self.lower_widget_layout = QHBoxLayout(self.lower_widget)

        # signers
        self.tabs_signers = QTabWidget(self.main_widget)
        self.lower_widget_layout.addWidget(self.tabs_signers)

        #
        self.add_all_signer_tabs()

        # exports
        self.export_widget = ExportData(self.lower_widget_layout, allow_edit=False)

        # buttons
        (
            self.button_edit_tx,
            self.button_save_tx,
            self.button_broadcast_tx,
        ) = create_button_bar(
            self.main_widget_layout,
            button_texts=[
                "Edit Transaction",
                "Save Transaction",
                "Broadcast Transaction",
            ],
        )
        self.button_broadcast_tx.setEnabled(False)
        self.button_broadcast_tx.clicked.connect(self.broadcast)
        self.set_psbt(psbt, fee_rate=fee_rate)
        self.utxo_list.update()

    def broadcast(self):
        logger.debug(f"broadcasting {psbt_to_hex(self.psbt)}")
        tx = self.psbt.extract_tx()
        self.signers[0].wallet.blockchain.broadcast(tx)
        self.signal_broadcast_tx.emit()

    def add_all_signer_tabs(self):
        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()

        def get_wallet_of_outpoint(outpoint: bdk.OutPoint) -> Wallet:
            for wallet in wallets_dict.values():
                utxo = wallet.utxo_of_outpoint(outpoint)
                if utxo:
                    return wallet

        # collect all wallets
        inputs: List[bdk.TxIn] = self.psbt.extract_tx().input()

        wallet_for_inputs: List[Wallet] = []
        for this_input in inputs:
            wallet_of_input = get_wallet_of_outpoint(this_input.previous_output)
            if wallet_of_input:
                wallet_for_inputs.append(wallet_of_input)

        if None in wallet_for_inputs:
            logger.warning(
                f"Cannot sign for all the inputs {wallet_for_inputs.index(None)} with the currently opened wallets"
            )

        logger.debug(f"wallet_for_inputs {[w.id for w in wallet_for_inputs]}")

        signers: List[SignerWallet] = []
        for wallet in set(wallet_for_inputs):  # removes all duplicate wallets
            for keystore in wallet.keystores:
                # TODO: once the bdk ffi has Signers (also hardware signers), I cann add here the signers
                # for now only mnemonic signers are supported
                # signers.append(SignerKeyStore(....))
                # signers.append(SignerHWI(....))
                pass
            signers.append(SignerWallet(wallet, self.network))
        self.signers = list(set(signers))  # removes all duplicate keystores

        logger.debug(f"signers {[k.label for k in signers]}")
        self.signeruis = []
        for signer in self.signers:
            signerui = SignerUI(signer, self.psbt, self.tabs_signers, self.network)
            signerui.signal_signature_added.connect(
                lambda psbt: self.signature_added(psbt)
            )
            self.signeruis.append(signerui)

    def signature_added(self, psbt_with_signatures: bdk.PartiallySignedTransaction):
        self.set_psbt(psbt_with_signatures, fee_rate=self.fee_rate)
        self.button_broadcast_tx.setEnabled(True)

    def set_psbt(self, psbt: bdk.PartiallySignedTransaction, fee_rate=None):
        self.psbt: bdk.PartiallySignedTransaction = psbt
        self.export_widget.set_data(
            txid=psbt.txid(), json_str=psbt.json_serialize(), seralized=psbt.serialize()
        )

        self.fee_group.non_final_fee_label.setHidden(not (fee_rate is None))
        fee_rate = (
            self.psbt.fee_rate().as_sat_per_vb() if fee_rate is None else fee_rate
        )
        self.fee_group.set_fee_rate(fee_rate)

        outputs: List[bdk.TxOut] = psbt.extract_tx().output()

        self.recipients.recipients = [
            Recipient(
                address=bdk.Address.from_script(
                    output.script_pubkey, self.network
                ).as_string(),
                amount=output.value,
            )
            for output in outputs
        ]


class UITX_Viewer(UITX_Base):
    signal_edit_tx = Signal()
    signal_save_psbt = Signal()
    signal_broadcast_tx = Signal()

    def __init__(
        self,
        tx: bdk.Transaction,
        config: UserConfig,
        signals: Signals,
        utxo_list: UTXOList,
        network: bdk.Network,
        mempool_data: MempoolData,
        blockchain: bdk.Blockchain = None,
        fee=None,
        confirmation_time: bdk.BlockTime = None,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.tx: bdk.Transaction = tx
        self.blockchain = blockchain
        self.network = network
        self.utxo_list = utxo_list
        self.confirmation_time = confirmation_time

        self.main_widget = QWidget()
        self.main_widget_layout = QVBoxLayout(self.main_widget)

        self.upper_widget = QWidget(self.main_widget)
        self.main_widget_layout.addWidget(self.upper_widget)
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)

        # in out
        self.tabs_inputs_outputs = QTabWidget(self.main_widget)
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        # inputs
        self.tab_inputs = QWidget(self.main_widget)
        self.tab_inputs_layout = QVBoxLayout(self.tab_inputs)
        self.tab_inputs_layout.addWidget(utxo_list)
        self.tabs_inputs_outputs.addTab(self.tab_inputs, "Inputs")

        # outputs
        self.tab_outputs = QWidget(self.main_widget)
        self.tab_outputs_layout = QVBoxLayout(self.tab_outputs)
        self.tabs_inputs_outputs.addTab(self.tab_outputs, "Outputs")
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)

        self.recipients = self.create_recipients(
            self.tab_outputs_layout, allow_edit=False
        )

        # right side bar
        self.right_sidebar = QWidget(self.main_widget)
        self.right_sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.upper_widget_layout.addWidget(self.right_sidebar)
        self.right_sidebar_layout = QVBoxLayout(self.right_sidebar)

        # QSizePolicy.Fixed: The widget has a fixed size and cannot be resized.
        # QSizePolicy.Minimum: The widget can be shrunk to its minimum size hint.
        # QSizePolicy.Maximum: The widget can be expanded up to its maximum size hint.
        # QSizePolicy.Preferred: The widget can be resized, but it prefers to be the size of its size hint.
        # QSizePolicy.Expanding: The widget can be resized and prefers to expand to take up as much space as possible.
        # QSizePolicy.MinimumExpanding: The widget can be resized and tries to be as small as possible but can expand if necessary.
        # QSizePolicy.Ignored: The widget's size hint is ignored and it can be any size.

        # fee_rate
        self.fee_group = FeeGroup(
            self.mempool_data,
            self.right_sidebar_layout,
            allow_edit=False,
            is_viewer=True,
            confirmation_time=confirmation_time,
            url=block_explorer_URL(config, "tx", tx.txid()) if tx else None,
        )
        self.fee_group.groupBox_Fee.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Expanding
        )

        # # txid and block explorers
        # self.blockexplorer_group = BlockExplorerGroup(tx.txid(), layout=self.right_sidebar_layout)

        # exports
        self.export_widget = ExportData(
            self.right_sidebar_layout,
            allow_edit=False,
            title_for_serialized="Transaction",
        )

        self.lower_widget = QWidget(self.main_widget)
        self.lower_widget.setMaximumHeight(220)
        self.main_widget_layout.addWidget(self.lower_widget)
        self.lower_widget_layout = QHBoxLayout(self.lower_widget)

        # buttons
        (
            self.button_edit_tx,
            self.button_save_tx,
            self.button_broadcast_tx,
        ) = create_button_bar(
            self.main_widget_layout,
            button_texts=[
                "Edit Transaction",
                "Save Transaction",
                "Broadcast Transaction",
            ],
        )
        self.button_broadcast_tx.setEnabled(False)
        self.button_broadcast_tx.clicked.connect(self.broadcast)
        self.set_tx(tx, fee=fee, confirmation_time=confirmation_time)
        self.utxo_list.update()

    def broadcast(self):
        logger.debug(f"broadcasting {psbt_to_hex(self.tx.serialize())}")
        self.blockchain.broadcast(self.tx)
        self.signal_broadcast_tx.emit()

    def set_tx(
        self, tx: bdk.Transaction, fee=None, confirmation_time: bdk.BlockTime = None
    ):
        self.tx: bdk.Transaction = tx
        self.export_widget.set_data(
            seralized=serialized_to_hex(tx.serialize()), txid=tx.txid()
        )

        fee_rate = fee / self.tx.vsize() if fee is not None else 0

        self.fee_group.set_fee_rate(
            fee_rate=fee_rate, confirmation_time=confirmation_time
        )

        outputs: List[bdk.TxOut] = self.tx.output()

        self.recipients.recipients = [
            Recipient(
                address=robust_address_str_from_script(
                    output.script_pubkey, self.network
                ),
                amount=output.value,
            )
            for output in outputs
        ]

        self.fee_group.set_fee_rate(
            fee_rate=fee_rate, confirmation_time=confirmation_time, txid=tx.txid()
        )


class UITX_Creator(UITX_Base):
    signal_create_tx = Signal(TXInfos)
    signal_set_category_coin_selection = Signal(TXInfos)

    def __init__(
        self,
        mempool_data: MempoolData,
        categories: List[str],
        utxo_list: UTXOList,
        config: UserConfig,
        signals: Signals,
        get_sub_texts,
        enable_opportunistic_merging_fee_rate=5,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.categories = categories
        self.utxo_list = utxo_list
        self.get_sub_texts = get_sub_texts
        self.enable_opportunistic_merging_fee_rate = (
            enable_opportunistic_merging_fee_rate
        )

        utxo_list.selectionModel().selectionChanged.connect(self.update_labels)

        self.main_widget = QWidget()
        self.main_widget_layout = QHBoxLayout(self.main_widget)

        self.create_inputs_selector(self.main_widget_layout)

        self.widget_right_hand_side = QWidget(self.main_widget)

        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)

        self.widget_right_top = QWidget(self.main_widget)
        self.widget_right_top_layout = QHBoxLayout(self.widget_right_top)
        self.widget_right_top_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins

        self.recipients = self.create_recipients(self.widget_right_top_layout)

        self.recipients.signal_clicked_send_max_button.connect(
            lambda recipient_group_box: self.set_max_amount(
                recipient_group_box.amount_spin_box
            )
        )
        self.recipients.add_recipient()

        self.fee_group = FeeGroup(mempool_data, self.widget_right_top_layout)
        self.fee_group.groupBox_Fee.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Expanding
        )
        self.fee_group.signal_set_fee_rate.connect(self.on_set_fee_rate)

        self.widget_right_hand_side_layout.addWidget(self.widget_right_top)

        (self.button_create_tx,) = create_button_bar(
            self.widget_right_hand_side_layout,
            button_texts=["Next Step: Sign Transaction with hardware signers"],
        )
        self.button_create_tx.clicked.connect(
            lambda: self.signal_create_tx.emit(self.get_ui_tx_infos())
        )

        self.main_widget_layout.addWidget(self.widget_right_hand_side)

        self.retranslateUi()

        QMetaObject.connectSlotsByName(self.main_widget)

        self.tab_changed(0)
        self.tabs_inputs.currentChanged.connect(self.tab_changed)

    def sum_amount_selected_utxos(self) -> Satoshis:
        sum_values = 0
        for index in self.utxo_list.selectionModel().selectedRows():
            # Assuming that the column of interest is column 1
            value = index.sibling(index.row(), self.utxo_list.Columns.SATOSHIS).data()
            if value is not None and value.isdigit():
                sum_values += float(value)
        return Satoshis(sum_values, self.signals.get_network())

    def update_labels(self):
        self.uxto_selected_label.setText(
            f"Currently {self.sum_amount_selected_utxos().str_with_unit()} selected"
        )

    def create_inputs_selector(self, layout):

        self.tabs_inputs = QTabWidget(self.main_widget)
        self.tabs_inputs.setMinimumWidth(200)
        self.tab_inputs_categories = QWidget(self.main_widget)
        self.tabs_inputs.addTab(self.tab_inputs_categories, "Input Category")

        # tab categories
        self.verticalLayout_inputs = QVBoxLayout(self.tab_inputs_categories)
        self.label_select_input_categories = QLabel(
            "Select a category that fits best to the recipient"
        )
        self.label_select_input_categories.setWordWrap(True)
        self.checkBox_reduce_future_fees = QCheckBox(self.tab_inputs_categories)
        self.checkBox_reduce_future_fees.setChecked(True)

        # Taglist
        self.category_list = CategoryList(
            self.categories, self.signals, self.get_sub_texts
        )
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox_reduce_future_fees)

        # tab utxos
        self.tab_inputs_utxos = QWidget(self.main_widget)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, "UTXOs")

        # utxo list
        self.uxto_selected_label = QLabel(self.main_widget)
        self.verticalLayout_inputs_utxos.addWidget(self.uxto_selected_label)
        self.verticalLayout_inputs_utxos.addWidget(self.utxo_list)

        layout.addWidget(self.tabs_inputs)

    def on_set_fee_rate(self, fee_rate):
        self.checkBox_reduce_future_fees.setChecked(
            fee_rate <= self.enable_opportunistic_merging_fee_rate
        )

    def get_ui_tx_infos(self, use_this_tab=None):
        infos = TXInfos()
        infos.opportunistic_merge_utxos = self.checkBox_reduce_future_fees.isChecked()

        for recipient in self.recipients.recipients:
            infos.add_recipient(recipient)

        logger.debug(
            f"set psbt builder fee_rate {self.fee_group.spin_fee_rate.value()}"
        )
        infos.set_fee_rate(self.fee_group.spin_fee_rate.value())

        if not use_this_tab:
            use_this_tab = self.tabs_inputs.currentWidget()

        if use_this_tab == self.tab_inputs_categories:
            infos.categories = self.category_list.get_selected()

        if use_this_tab == self.tab_inputs_utxos:
            infos.utxo_strings = [
                self.utxo_list.item_from_index(idx).text()
                for idx in self.utxo_list.selected_in_column(
                    self.utxo_list.Columns.OUTPOINT
                )
            ]

        return infos

    def set_max_amount(self, spin_box: CustomDoubleSpinBox):
        wallets: List[Wallet] = self.signals.get_wallets().values()

        txinfos = self.get_ui_tx_infos()

        utxos = sum([wallet.get_all_input_utxos(txinfos) for wallet in wallets], [])

        total_input_value = sum([utxo.txout.value for utxo in utxos])

        total_output_value = sum(
            [recipient.amount for recipient in txinfos.recipients]
        )  # this includes the old value of the spinbox

        logger.debug(str((total_input_value, total_output_value, spin_box.value())))

        max_available_amount = total_input_value - total_output_value
        spin_box.setValue(spin_box.value() + max_available_amount)

    def update_categories(self):
        self.category_list.clear()
        for category in self.categories:
            self.category_list.add(category, sub_text=self.get_sub_texts())

    def retranslateUi(self):
        self.main_widget.setWindowTitle(
            QCoreApplication.translate("self.main_widget", "self.main_widget", None)
        )
        self.checkBox_reduce_future_fees.setText(
            QCoreApplication.translate(
                "self.main_widget",
                "Reduce future fees\n" "by merging small inputs now",
                None,
            )
        )

    @Slot(int)
    def tab_changed(self, index):
        # Slot called when the current tab changes
        # print(f"Tab changed to index {index}")

        if index == 0:
            self.tabs_inputs.setMaximumWidth(200)
            self.recipients.setMaximumWidth(80000)
        elif index == 1:
            self.tabs_inputs.setMaximumWidth(80000)
            self.recipients.setMaximumWidth(500)

            # take the coin selection from the category to the utxo tab
            self.signal_set_category_coin_selection.emit(
                self.get_ui_tx_infos(self.tab_inputs_categories)
            )
