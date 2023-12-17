import logging

from bitcoin_safe.config import FEE_RATIO_HIGH_WARNING, MIN_RELAY_FEE, UserConfig
from bitcoin_safe.descriptors import public_descriptor_info
from bitcoin_safe.gui.qt.qr_components.image_widget import QRCodeWidgetSVG
from bitcoin_safe.gui.qt.open_tx_dialog import UTXOAddDialog
from bitcoin_qrreader.bitcoin_qr import Data, DataType

logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from .category_list import CategoryList
from .recipients import Recipients, BTCSpinBox
from .slider import CustomSlider
from ...signals import Signal
import bdkpython as bdk
from typing import List, Dict
from .utxo_list import UTXOList
from ...tx import TxUiInfos
from ...signals import Signals
from .barchart import MempoolBarChart
from ...mempool import TxPrio, fee_to_depth, fee_to_blocknumber
from PySide2.QtGui import QPixmap, QImage
from .qr_components.qr import create_qr_svg
from ...psbt_util import (
    FeeInfo,
    calculate_sent_change_amounts,
    estimate_segwit_fee_rate_from_psbt,
    estimate_tx_weight,
    get_likely_origin_wallet,
    get_sent_and_change_outputs,
    get_psbt_simple_json,
)
from ...keystore import KeyStore
from .util import (
    Message,
    SearchableTab,
    TxTab,
    add_to_buttonbox,
    read_QIcon,
    open_website,
    save_file_dialog,
)
from .keystore_ui import SignedUI, SignerUI
from ...signer import AbstractSigner, FileSigner, SignerWallet, QRSigner
from ...util import (
    NoThread,
    TaskThread,
    hex_to_serialized,
    psbt_to_hex,
    Satoshis,
    remove_duplicates_keep_order,
    serialized_to_hex,
    block_explorer_URL,
)
from .block_buttons import ConfirmedBlock, MempoolButtons, MempoolProjectedBlock
from ...mempool import MempoolData, fees_of_depths
from ...pythonbdk_types import OutPoint, Recipient, TxOut
from PySide2.QtCore import Signal, QObject
from ...wallet import UtxosForInputs, Wallet
import json
from ...pythonbdk_types import robust_address_str_from_script
from .util import ShowCopyLineEdit, ShowCopyTextEdit
from ...psbt_util import get_psbt_simple_json
from .debug_widget import generate_debug_class
from ...pythonbdk_types import OutPoint


def create_button_bar(layout, button_texts) -> List[QPushButton]:
    button_bar = QWidget()
    button_bar_layout = QHBoxLayout(button_bar)
    # button_bar_layout.setContentsMargins(
    #         0, 0, 0, 0
    #     )  # Left, Top, Right, Bottom margins

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
        self.data: Data = None
        self.json_str = None
        self.txid = None
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.signal_export_to_file.connect(self.export_to_file)

        # qr
        self.tab_qr = QWidget()
        self.tab_qr_layout = QHBoxLayout(self.tab_qr)
        self.tab_qr_layout.setAlignment(Qt.AlignVCenter)
        self.qr_label = QRCodeWidgetSVG()

        self.tab_qr_layout.addWidget(self.qr_label)
        self.tabs.addTab(self.tab_qr, "QR")

        # right side of qr
        self.tab_qr_right_side = QWidget()
        self.tab_qr_right_side.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.tab_qr_right_side_layout = QVBoxLayout(self.tab_qr_right_side)
        self.tab_qr_right_side_layout.setAlignment(Qt.AlignCenter)
        self.tab_qr_layout.addWidget(self.tab_qr_right_side)

        self.button_enlarge_qr = QPushButton("Enlarge")
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))
        # self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.tab_qr_right_side_layout.addWidget(self.button_enlarge_qr)

        self.button_save_qr = QPushButton("Save as image")
        self.button_save_qr.setIcon(read_QIcon("download.png"))
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.tab_qr_right_side_layout.addWidget(self.button_save_qr)

        self.button_file2 = QPushButton("Raw file")
        self.button_file2.setIcon(read_QIcon("download.png"))
        self.button_file2.clicked.connect(lambda: self.signal_export_to_file.emit())
        self.tab_qr_right_side_layout.addWidget(self.button_file2)

        # psbt
        self.tab_serialized = QWidget()
        self.form_layout = QFormLayout(self.tab_serialized)
        self.txid_edit = ShowCopyLineEdit()
        self.txid_edit.buttons[0].setStyleSheet("background-color: white;")
        self.form_layout.addRow("TxId", self.txid_edit)
        self.edit_serialized = ShowCopyTextEdit()
        self.edit_serialized.buttons[0].setStyleSheet("background-color: white;")
        if not allow_edit:
            self.edit_serialized.setReadOnly(True)
        self.form_layout.addRow("Tx", self.edit_serialized)

        self.button_file = QPushButton("Raw file")
        self.button_file.setIcon(read_QIcon("download.png"))
        # self.button_file.setIconSize(QSize(30, 30))  # 24x24 pixels
        self.button_file.clicked.connect(lambda: self.signal_export_to_file.emit())
        self.form_layout.addRow("Export", self.button_file)

        self.set_tab_visibility(
            self.tab_serialized, True, self.title_for_serialized, index=1
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
        # self.tab_file = QWidget()
        # self.tab_file.setHidden(True)
        # self.tab_file_layout = QVBoxLayout(self.tab_file)
        # self.tab_file_layout.setAlignment(Qt.AlignHCenter)
        # self.button_file = QToolButton()
        # self.button_file.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        # self.button_file.setIcon(read_QIcon("download.png"))
        # self.button_file.setIconSize(QSize(30, 30))  # 24x24 pixels
        # self.button_file.clicked.connect(lambda: self.signal_export_to_file.emit())
        # self.tab_file_layout.addWidget(self.button_file)
        # self.tabs.addTab(self.tab_file, f"Export {self.title_for_serialized} file")

        self.set_title_for_serialized(title_for_serialized)
        layout.addWidget(self.tabs)

    def export_qrcode(self):
        filename = save_file_dialog(
            name_filters=["Image (*.png)", "All Files (*.*)"], default_suffix="png"
        )
        if not filename:
            return

        # Ensure the file has the .png extension
        if not filename.lower().endswith(".png"):
            filename += ".png"

        self.qr_label.save_file(filename)

    def set_tab_visibility(self, tab, visible, title, index=0):
        if self.tabs.indexOf(tab) == -1 and visible:
            self.tabs.insertTab(index, tab, title)
        elif self.tabs.indexOf(tab) != -1 and not visible:
            self.tabs.removeTab(self.tabs.indexOf(tab))

    def set_title_for_serialized(self, title_for_serialized):
        self.title_for_serialized = title_for_serialized
        self.button_file.setText(f"{self.title_for_serialized} file")
        self.button_file2.setText(f"{self.title_for_serialized} file")

        idx = self.tabs.indexOf(self.tab_serialized)
        if idx != -1:
            self.tabs.setTabText(idx, f"{self.title_for_serialized}")

    def set_data(
        self, txid=None, data: Data = None, json_str=None, title_for_serialized=None
    ):
        self.data = data
        self.json_str = json_str
        self.txid = txid

        if title_for_serialized is not None:
            self.set_title_for_serialized(title_for_serialized)

        self.set_tab_visibility(self.tab_json, bool(json_str), "JSON", index=2)
        self.set_tab_visibility(
            self.tab_serialized, bool(data), self.title_for_serialized, index=2
        )
        if txid:
            self.txid_edit.setText(txid)
        if data:
            self.edit_serialized.setText(data.data_as_string())

            self.lazy_load_qr(data)

        if json_str:
            json_text = json.dumps(json.loads(json_str), indent=4)
            self.edit_json.setText(json_text)

    def lazy_load_qr(self, data: Data, max_length=200):
        def do():
            fragments = data.generate_fragments_for_qr(max_qr_size=max_length)
            images = [create_qr_svg(fragment) for fragment in fragments]
            return images

        def on_done(result):
            pass

        def on_error(packed_error_info):
            Message(packed_error_info).show_error()

        def on_success(result):
            if result:
                self.qr_label.set_images(result)

        TaskThread(self).add_and_start(do, on_success, on_done, on_error)

    def export_to_file(self):
        filename = save_file_dialog(
            name_filters=["PSBT Files (*.psbt)", "All Files (*.*)"],
            default_suffix="psbt",
            default_filename=f"{self.txid}.psbt",
        )
        if not filename:
            return

        with open(filename, "w") as file:
            file.write(self.serialized)


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
        fee_rate=None,
        config: UserConfig = None,
    ) -> None:
        super().__init__()

        self.allow_edit = allow_edit
        self.config = config

        fee_rate = fee_rate if fee_rate else (mempool_data.get_prio_fees()[TxPrio.low])

        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee.setTitle("Fee")
        self.groupBox_Fee.setSizePolicy(
            QSizePolicy.MinimumExpanding, QSizePolicy.Expanding
        )
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
            self.mempool = ConfirmedBlock(
                mempool_data,
                url=url,
                confirmation_time=confirmation_time,
                fee_rate=fee_rate,
            )
        elif is_viewer:
            self.mempool = MempoolProjectedBlock(
                mempool_data, url=url, fee_rate=fee_rate
            )
        else:
            self.mempool = MempoolButtons(mempool_data, button_count=3)

        if allow_edit:
            self.mempool.signal_click.connect(self.set_fee_rate)
        groupBox_Fee_layout.addWidget(
            self.mempool.button_group, alignment=Qt.AlignHCenter
        )

        self.high_fee_rate_warning_label = QLabel(
            "<font color='red'><b>High feerate</b></font>"
        )
        self.high_fee_rate_warning_label.setHidden(True)
        groupBox_Fee_layout.addWidget(
            self.high_fee_rate_warning_label, alignment=Qt.AlignHCenter
        )

        self.high_fee_warning_label = QLabel(
            "<font color='red'><b>High feerate</b></font>"
        )
        self.high_fee_warning_label.setHidden(True)
        groupBox_Fee_layout.addWidget(
            self.high_fee_warning_label, alignment=Qt.AlignHCenter
        )

        self.approximate_fee_label = QLabel(
            "<font color='black'><b>Approximate fee rate</b></font>"
        )
        self.approximate_fee_label.setHidden(True)
        groupBox_Fee_layout.addWidget(
            self.approximate_fee_label, alignment=Qt.AlignHCenter
        )

        self.widget_around_spin_box = QWidget()
        self.widget_around_spin_box_layout = QHBoxLayout(self.widget_around_spin_box)
        self.widget_around_spin_box_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Remove margins
        groupBox_Fee_layout.addWidget(
            self.widget_around_spin_box, alignment=Qt.AlignHCenter
        )

        self.spin_fee_rate = QDoubleSpinBox()
        self.spin_fee_rate.setReadOnly(not allow_edit)
        self.spin_fee_rate.setSingleStep(1)  # Set the step size
        self.spin_fee_rate.setDecimals(1)  # Set the number of decimal places
        self.spin_fee_rate.setMaximumWidth(55)
        if fee_rate:
            self.spin_fee_rate.setValue(fee_rate)
        self.update_spin_fee_range()
        self.spin_fee_rate.editingFinished.connect(
            lambda: self.set_fee_rate(self.spin_fee_rate.value())
        )
        self.spin_fee_rate.valueChanged.connect(
            lambda: self.set_fee_rate(self.spin_fee_rate.value())
        )

        self.widget_around_spin_box_layout.addWidget(self.spin_fee_rate)

        self.spin_label = QLabel()
        self.spin_label.setText("Sat/vB")
        self.widget_around_spin_box_layout.addWidget(self.spin_label)

        self.label_block_number = QLabel()
        groupBox_Fee_layout.addWidget(
            self.label_block_number, alignment=Qt.AlignHCenter
        )

        layout.addWidget(self.groupBox_Fee, alignment=Qt.AlignHCenter)

        self.mempool.mempool_data.signal_data_updated.connect(
            self.update_fee_rate_warning
        )

    def set_fee_to_send_ratio(
        self, fee, sent_amount, network: bdk.Network, fee_is_exact=False
    ):
        too_high = fee / sent_amount > FEE_RATIO_HIGH_WARNING
        self.high_fee_warning_label.setVisible(too_high)
        if too_high:
            self.high_fee_warning_label.setText(
                f"<font color='red'><b>High fee ratio: {round(fee/sent_amount*100)}%</b></font>"
            )
            self.high_fee_warning_label.setToolTip(
                f"""<html><body>The {'' if fee_is_exact else  'estimated'} transaction fee is:\n{Satoshis(fee,network).str_with_unit()}, which is {round(fee/sent_amount*100)}% of\nthe sending value {Satoshis(sent_amount, self.config.network_settings.network).str_with_unit()}</body></html>"""
            )

    def update_fee_rate_warning(self):
        fee_rate = self.spin_fee_rate.value()
        too_high = fee_rate > self.mempool.mempool_data.max_reasonable_fee_rate()
        self.high_fee_rate_warning_label.setVisible(too_high)
        if too_high:
            self.high_fee_rate_warning_label.setText(
                f"<font color='red'><b>High fee rate!</b></font>"
            )
            self.high_fee_rate_warning_label.setToolTip(
                f"The high prio mempool fee rate is {self.mempool.mempool_data.max_reasonable_fee_rate():.1f} Sat/vB"
            )

    def set_fee_rate(
        self,
        fee_rate,
        url: str = None,
        confirmation_time: bdk.BlockTime = None,
        chain_height=None,
    ):
        self.spin_fee_rate.setHidden(fee_rate is None)
        self.label_block_number.setHidden(fee_rate is None)
        self.spin_label.setHidden(fee_rate is None)

        self.mempool.refresh(
            fee_rate=fee_rate,
            confirmation_time=confirmation_time,
            chain_height=chain_height,
        )
        self._set_value(fee_rate if fee_rate else 0)

        self.label_block_number.setVisible(not bool(confirmation_time))
        if fee_rate is not None:
            self.label_block_number.setText(
                f"in ~{fee_to_blocknumber(self.mempool.mempool_data.data, fee_rate)}. Block"
            )

        if url:
            self.mempool.set_url(url)

        self.update_fee_rate_warning()

        self.signal_set_fee_rate.emit(fee_rate)

    def _set_value(self, value):
        self.update_spin_fee_range(value)
        self.spin_fee_rate.setValue(value)

    def update_spin_fee_range(self, value=0):
        "Set the acceptable range"
        fee_range = self.config.fee_ranges[self.config.network_settings.network].copy()
        fee_range[1] = max(
            fee_range[1],
            value,
            self.spin_fee_rate.value(),
            max(self.mempool.mempool_data.block_fee_borders(1)),
        )
        self.spin_fee_rate.setRange(*fee_range)


class UITX_Base(QObject):
    def __init__(
        self, config: UserConfig, signals: Signals, mempool_data: MempoolData
    ) -> None:
        super().__init__()
        self.signals = signals
        self.mempool_data = mempool_data
        self.config = config

    def create_recipients(self, layout, parent=None, allow_edit=True) -> Recipients:
        recipients = Recipients(self.signals, allow_edit=allow_edit)
        layout.addWidget(recipients)
        recipients.setMinimumWidth(250)
        return recipients


class UITx_Viewer(UITX_Base):
    signal_edit_tx = Signal()
    signal_save_psbt = Signal()

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        utxo_list: UTXOList,
        network: bdk.Network,
        mempool_data: MempoolData,
        blockchain: bdk.Blockchain = None,
        psbt: bdk.PartiallySignedTransaction = None,
        tx: bdk.Transaction = None,
        fee_info: FeeInfo = None,
        confirmation_time: bdk.BlockTime = None,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.psbt: bdk.PartiallySignedTransaction = psbt
        self.tx: bdk.Transaction = tx
        self.network = network
        self.fee_info = fee_info
        self.blockchain = blockchain
        self.utxo_list = utxo_list
        self.confirmation_time = confirmation_time

        self.signers: Dict[str, List[AbstractSigner]] = {}

        ##################
        self.main_widget = TxTab(psbt=psbt, tx=tx)
        self.main_widget.searchable_list = utxo_list
        self.main_widget_layout = QVBoxLayout(self.main_widget)

        self.upper_widget = QWidget()
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)
        self.main_widget_layout.addWidget(self.upper_widget)

        # in out
        self.tabs_inputs_outputs = QTabWidget()
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        # inputs
        self.tab_inputs = QWidget()
        self.tab_inputs_layout = QVBoxLayout(self.tab_inputs)
        self.tab_inputs_layout.addWidget(utxo_list)
        self.tabs_inputs_outputs.addTab(self.tab_inputs, "Inputs")

        # outputs
        self.tab_outputs = QWidget()
        self.tab_outputs_layout = QVBoxLayout(self.tab_outputs)
        self.tabs_inputs_outputs.addTab(self.tab_outputs, "Outputs")
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)

        self.recipients = self.create_recipients(
            self.tab_outputs_layout, allow_edit=False
        )

        # right side bar
        self.right_sidebar = QWidget()
        self.right_sidebar.setFixedWidth(300)
        self.right_sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.upper_widget_layout.addWidget(self.right_sidebar)
        self.right_sidebar_layout = QVBoxLayout(self.right_sidebar)
        self.right_sidebar_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins

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
            url=block_explorer_URL(config.network_settings, "tx", self.txid())
            if tx
            else None,
            config=self.config,
        )

        # # txid and block explorers
        # self.blockexplorer_group = BlockExplorerGroup(tx.txid(), layout=self.right_sidebar_layout)
        self.mid_widget = QWidget()
        self.mid_widget.setMaximumHeight(250)
        self.main_widget_layout.addWidget(self.mid_widget)
        self.mid_widget_layout = QHBoxLayout(self.mid_widget)

        # exports
        self.export_widget = ExportData(
            self.mid_widget_layout,
            allow_edit=False,
            title_for_serialized="Transaction",
        )

        # set sizes
        self.fee_group.groupBox_Fee.setFixedWidth(300)

        # signers
        self.tabs_signers = QTabWidget()
        self.tabs_signers.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.mid_widget_layout.addWidget(self.tabs_signers)

        # buttons

        # Create the QDialogButtonBox
        self.buttonBox = QDialogButtonBox()

        # Create custom buttons
        self.button_edit_tx = add_to_buttonbox(
            self.buttonBox, "Edit", "pen.svg", on_clicked=self.edit
        )
        self.button_save_tx = add_to_buttonbox(self.buttonBox, "Save", "sd-card.svg")
        self.button_broadcast_tx = add_to_buttonbox(
            self.buttonBox, "Send", "send.svg", on_clicked=self.broadcast
        )
        self.button_broadcast_tx.setToolTip(
            "Sending a transaction after all necessary signatures are collected."
        )

        self.main_widget_layout.addWidget(self.buttonBox)
        ##################

        self.button_save_tx.setVisible(False)
        self.button_broadcast_tx.setEnabled(False)

        self.reload()
        self.utxo_list.update()
        self.signals.finished_open_wallet.connect(self.reload)

    def edit(self):

        tx = self.tx if self.tx else self.psbt.extract_tx()
        outpoints = [OutPoint.from_bdk(inp.previous_output) for inp in tx.input()]

        txinfos = TxUiInfos()
        # inputs
        txinfos.fill_utxo_dict_from_outpoints(
            outpoints, wallets=self.signals.get_wallets().values()
        )
        txinfos.spend_all_utxos = True
        # outputs
        checked_max_amount = (
            len(tx.output()) == 1
        )  # if there is only 1 recipient, there is no change address
        for txout in tx.output():
            out_address = robust_address_str_from_script(
                txout.script_pubkey, self.network
            )
            if out_address is None:
                Message(f"No addres of {txout} could be calculated").show_message()
                continue

            txinfos.recipients.append(
                Recipient(
                    out_address, txout.value, checked_max_amount=checked_max_amount
                )
            )
        # fee rate
        txinfos.fee_rate = self.fee_group.spin_fee_rate.value()

        self.signals.open_tx_like.emit(txinfos)

    def reload(self):
        if self.psbt:
            self.set_psbt(self.psbt, fee_info=self.fee_info)
        elif self.tx:
            self.set_tx(
                self.tx,
                fee_info=self.fee_info,
                confirmation_time=self.confirmation_time,
            )

    def txid(self):
        if self.tx:
            return self.tx.txid()
        else:
            return self.psbt.txid()

    def broadcast(self):
        logger.debug(f"broadcasting {self.tx.serialize()}")
        if self.blockchain:
            self.blockchain.broadcast(self.tx)
            self.signals.signal_broadcast_tx.emit(self.tx)
        else:
            logger.error("No blockchain set")

    def get_fingerprints_signed_unsigned(self):
        def get_wallet_of_outpoint(outpoint: bdk.OutPoint) -> Wallet:
            for wallet in wallets_dict.values():
                utxo = wallet.utxo_of_outpoint(outpoint)
                if utxo:
                    return wallet

        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()

        simple_json = get_psbt_simple_json(self.psbt)["inputs"]

        # collect all wallets that have input utxos
        inputs: List[bdk.TxIn] = self.psbt.extract_tx().input()

        for this_input, simple_input in zip(inputs, simple_json):
            wallet = get_wallet_of_outpoint(this_input.previous_output)
            simple_input["wallet"] = wallet
            simple_input["fingerprints"] = (
                [k.fingerprint for k in wallet.keystores]
                if simple_input["wallet"]
                else [d["fingerprint"] for pubkey, d in simple_input["summary"].items()]
            )

        # set of all fingerprints of all inputs
        sorted_fingerprints = remove_duplicates_keep_order(
            sum(
                [simple_input["fingerprints"] for simple_input in simple_json],
                [],
            )
        )

        fingerprints_not_fully_signed = set(
            sum(
                [
                    [
                        d["fingerprint"]
                        for d in inp["summary"].values()
                        if not d["partial_sigs"] and not d["signature"]
                    ]
                    for inp in simple_json
                ],
                [],
            )
        )
        fingerprints_fully_signed = set(sorted_fingerprints) - set(
            fingerprints_not_fully_signed
        )
        return (
            simple_json,
            sorted_fingerprints,
            fingerprints_fully_signed,
            fingerprints_not_fully_signed,
        )

    def add_all_signer_tabs(self):
        def get_signing_fingerprints_of_wallet(wallet):
            # check which keys the wallet can sign
            descriptor_contains_keys = public_descriptor_info(
                wallet.descriptor_str, self.network
            ).get("descriptor_contains_keys")

            wallet_signing_fingerprints = set(
                [
                    keystore.fingerprint if contains_key else None
                    for keystore, contains_key in zip(
                        wallet.keystores, descriptor_contains_keys
                    )
                ]
            ) - set([None])
            return wallet_signing_fingerprints

        def get_signing_wallets(fingerprint) -> Wallet:
            result = []
            for wallet in wallets_dict.values():
                signing_fingerprints_of_wallet = get_signing_fingerprints_of_wallet(
                    wallet
                )
                if fingerprint in signing_fingerprints_of_wallet:
                    result.append(wallet)
            return result

        def get_label(fingerprint) -> Wallet:
            for simple_input in simple_json:
                if fingerprint in simple_input["fingerprints"]:
                    if not simple_input.get("wallet"):
                        continue
                    for keystore in simple_input["wallet"].keystores:
                        if keystore.fingerprint == fingerprint:
                            return keystore.label
            return f"Fingerprint {fingerprint}"

        self.remove_signers()
        self.tabs_signers.setHidden(False)
        wallets_dict: Dict[str, Wallet] = self.signals.get_wallets()
        (
            simple_json,
            sorted_fingerprints,
            fingerprints_fully_signed,
            fingerprints_not_fully_signed,
        ) = self.get_fingerprints_signed_unsigned()

        #
        self.signers: Dict[str, List[AbstractSigner]] = {}
        for fingerprint in sorted_fingerprints:
            l = self.signers.setdefault(
                fingerprint, []
            )  # sets self.signers[fingerprint] = []  if key doesn't exists

            # check if any wallet has keys for this fingerprint
            signing_wallets = get_signing_wallets(fingerprint)
            if signing_wallets:
                l.append(SignerWallet(signing_wallets[0], self.network))

            # always offer the qr option
            l.append(
                QRSigner(
                    "Read Signature",
                    self.network,
                    blockchain=self.blockchain,
                    dummy_wallet=list(wallets_dict.values())[0],
                )
            )

            # always offer the file option
            l.append(
                FileSigner(
                    "Import Signature",
                    self.network,
                    blockchain=self.blockchain,
                    dummy_wallet=list(wallets_dict.values())[0],
                )
            )

        self.signeruis = []
        for fingerprint, signer_list in self.signers.items():
            if fingerprint in fingerprints_fully_signed:
                signerui = SignedUI(
                    f"Transaction signed with the private key belonging to fingerprint {fingerprint}",
                    self.psbt,
                    self.tabs_signers,
                    self.network,
                    key_label=get_label(fingerprint),
                )
            else:
                signerui = SignerUI(
                    signer_list,
                    self.psbt,
                    self.tabs_signers,
                    self.network,
                    key_label=get_label(fingerprint),
                    wallet_id=signer_list[0].label if signer_list else None,
                )
                signerui.signal_signature_added.connect(
                    lambda psbt: self.signature_added(psbt)
                )
            self.signeruis.append(signerui)

    def remove_signers(self):
        self.tabs_signers.setHidden(True)
        for i in reversed(list(range(self.tabs_signers.count()))):
            self.tabs_signers.removeTab(i)

    def signature_added(self, psbt_with_signatures: bdk.PartiallySignedTransaction):
        tx = None
        if isinstance(psbt_with_signatures, bdk.Transaction):
            tx = psbt_with_signatures
        else:
            all_inputs_fully_signed = [
                inp.get("signature")
                for inp in get_psbt_simple_json(psbt_with_signatures)["inputs"]
            ]
            if all(all_inputs_fully_signed):
                tx = psbt_with_signatures.extract_tx()

        if tx:
            sent_values, change_values = calculate_sent_change_amounts(
                psbt_with_signatures
            )
            self.set_tx(
                tx,
                fee_info=FeeInfo(
                    psbt_with_signatures.fee_amount(),
                    psbt_with_signatures.extract_tx().weight() / 4,
                ),
                sent_amount=sum(sent_values),
            )
        else:
            self.set_psbt(
                psbt_with_signatures,
                fee_info=FeeInfo(
                    psbt_with_signatures.fee_amount(),
                    psbt_with_signatures.extract_tx().weight() / 4,
                ),
            )
            # TODO: assume here after 1 signing it is ready to be broadcasted
            self.tx = self.psbt.extract_tx()
        self.button_broadcast_tx.setEnabled(True)

    def check_if_valid_tx(self, tx: bdk.Transaction):
        for wallet in self.signals.get_wallets().values():
            conflicting_input_utxos = wallet.get_conflicting_tx_inputs(tx)
            if conflicting_input_utxos:
                Message(
                    f"The following tx inputs are already spent {[OutPoint.from_bdk( utxo.outpoint) for utxo in conflicting_input_utxos]}, which makes this tx invalid."
                ).show_message()
                break

    def set_tx(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo = None,
        confirmation_time: bdk.BlockTime = None,
        sent_amount: int = None,
    ):
        self.tx: bdk.Transaction = tx

        # if i have a transaction that is not confirmed, then check if the utxos exist
        if not confirmation_time:
            self.check_if_valid_tx(tx)

        self.remove_signers()
        self.export_widget.set_data(
            data=Data(tx, DataType.Tx),
            txid=tx.txid(),
            title_for_serialized="Transaction",
        )

        if fee_info is not None:
            self.fee_info = fee_info
            self.fee_group.set_fee_rate(
                fee_rate=self.fee_info.fee_rate(),
                url=block_explorer_URL(self.config.network_settings, "tx", tx.txid()),
                confirmation_time=confirmation_time,
                chain_height=self.blockchain.get_height() if self.blockchain else None,
            )
            # calcualte the fee warning. However since in a tx I don't know what is a change address,
            # it is not possible to give  fee warning for the sent (vs. change) amount
            sent_amount = (
                sent_amount
                if sent_amount
                else sum([txout.value for txout in tx.output()])
            )
            self.fee_group.set_fee_to_send_ratio(
                fee_info.fee_amount,
                sent_amount,
                self.config.network_settings.network,
                fee_is_exact=True,
            )

        self.fee_group.approximate_fee_label.setVisible(fee_info.is_estimated)
        self.fee_group.approximate_fee_label.setToolTip(
            f'<html><body>The {"approximate " if fee_info.is_estimated else "" }fee is {Satoshis( fee_info.fee_amount, self.network).str_with_unit()}</body></html>'
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

        self.button_edit_tx.setHidden(bool(confirmation_time))
        self.button_save_tx.setHidden(True)
        self.button_broadcast_tx.setHidden(bool(confirmation_time))

    def set_psbt(self, psbt: bdk.PartiallySignedTransaction, fee_info: FeeInfo = None):
        """_summary_

        Args:
            psbt (bdk.PartiallySignedTransaction): _description_
            fee_rate (_type_, optional): This is the exact fee_rate chosen in txbuilder. If not given it has
                                        to be estimated with estimate_segwit_tx_size_from_psbt.
        """
        self.psbt: bdk.PartiallySignedTransaction = psbt

        self.check_if_valid_tx(psbt.extract_tx())

        self.export_widget.set_data(
            txid=psbt.txid(),
            json_str=psbt.json_serialize(),
            data=Data(psbt, DataType.PSBT),
            title_for_serialized="PSBT",
        )
        self.export_widget.qr_label.set_always_animate(True)

        # if fee_rate is set, it means the

        if fee_info is None:
            fee_info = estimate_segwit_fee_rate_from_psbt(psbt)
        self.fee_group.approximate_fee_label.setVisible(fee_info.is_estimated)
        self.fee_group.approximate_fee_label.setToolTip(
            f'<html><body>The {"approximate " if fee_info.is_estimated else "" }fee is {Satoshis( fee_info.fee_amount, self.network).str_with_unit()} Sat</body></html>'
        )

        self.fee_group.set_fee_rate(
            fee_rate=fee_info.fee_rate(),
            url=block_explorer_URL(self.config.network_settings, "tx", psbt.txid()),
        )

        outputs: List[bdk.TxOut] = psbt.extract_tx().output()

        # set fee warning
        sent_values, change_values = calculate_sent_change_amounts(psbt)
        if sum(sent_values):
            self.fee_group.set_fee_to_send_ratio(
                psbt.fee_amount(),
                sum(sent_values),
                self.network,
            )

        self.recipients.recipients = [
            Recipient(
                address=bdk.Address.from_script(
                    output.script_pubkey, self.network
                ).as_string(),
                amount=output.value,
            )
            for output in outputs
        ]

        self.add_all_signer_tabs()


class UITX_Creator(UITX_Base):
    signal_create_tx = Signal(TxUiInfos)

    def __init__(
        self,
        wallet: Wallet,
        mempool_data: MempoolData,
        categories: List[str],
        utxo_list: UTXOList,
        config: UserConfig,
        signals: Signals,
        get_sub_texts,
        enable_opportunistic_merging_fee_rate=5,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.wallet = wallet
        self.categories = categories
        self.utxo_list = utxo_list
        self.get_sub_texts = get_sub_texts
        self.enable_opportunistic_merging_fee_rate = (
            enable_opportunistic_merging_fee_rate
        )

        self.additional_outpoints = []
        utxo_list.get_outpoints = self.get_outpoints
        utxo_list.selectionModel().selectionChanged.connect(self.update_labels)

        self.main_widget = SearchableTab()
        self.main_widget.searchable_list = utxo_list
        self.main_widget_layout = QHBoxLayout(self.main_widget)

        self.splitter = QSplitter()
        self.main_widget_layout.addWidget(self.splitter)
        self.create_inputs_selector(self.splitter)

        self.widget_right_hand_side = QWidget()
        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)
        self.widget_right_hand_side_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins

        self.widget_right_top = QWidget(self.main_widget)
        self.widget_right_top_layout = QHBoxLayout(self.widget_right_top)
        self.widget_right_top_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins

        self.recipients: Recipients = self.create_recipients(
            self.widget_right_top_layout
        )

        self.recipients.signal_clicked_send_max_button.connect(
            lambda recipient_group_box: self.set_max_amount(
                recipient_group_box.amount_spin_box
            )
        )
        self.recipients.add_recipient()

        self.fee_group = FeeGroup(
            mempool_data, self.widget_right_top_layout, config=self.config
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

        self.splitter.addWidget(self.widget_right_hand_side)

        self.retranslateUi()

        self.tab_changed(0)
        self.tabs_inputs.currentChanged.connect(self.tab_changed)
        self.mempool_data.signal_data_updated.connect(self.update_fee_rate_to_mempool)

    def update_fee_rate_to_mempool(self):
        "Do this only ONCE after the mempool data is fetched"
        if self.fee_group.spin_fee_rate.value() == MIN_RELAY_FEE:
            self.fee_group.set_fee_rate(self.mempool_data.get_prio_fees()[TxPrio.low])
        self.mempool_data.signal_data_updated.disconnect(
            self.update_fee_rate_to_mempool
        )

    def get_outpoints(self):
        return [
            OutPoint.from_bdk(utxo.outpoint) for utxo in self.wallet.list_unspent()
        ] + self.additional_outpoints

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
            "Select a category that fits the recipient best"
        )
        self.label_select_input_categories.setWordWrap(True)
        self.checkBox_reduce_future_fees = QCheckBox(self.tab_inputs_categories)
        self.checkBox_reduce_future_fees.setChecked(True)

        # Taglist
        self.category_list = CategoryList(
            self.categories, self.signals, self.get_sub_texts, immediate_release=False
        )
        # select the first one with !=0 balance
        category_utxo_dict = self.wallet.get_category_utxo_dict()
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox_reduce_future_fees)

        # tab utxos
        self.tab_inputs_utxos = QWidget(self.main_widget)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, "Manual")

        self.uxto_selected_label = QLabel(self.main_widget)
        self.verticalLayout_inputs_utxos.addWidget(self.uxto_selected_label)
        self.verticalLayout_inputs_utxos.addWidget(self.utxo_list)

        # utxo list
        if hasattr(bdk.TxBuilder(), "add_foreign_utxo"):
            self.button_add_utxo = QPushButton("Add foreign UTXOs")
            self.button_add_utxo.clicked.connect(self.click_add_utxo)
            self.verticalLayout_inputs_utxos.addWidget(self.button_add_utxo)

        layout.addWidget(self.tabs_inputs)

        def sum_value(category):
            utxos = category_utxo_dict.get(category)
            if not utxos:
                return 0
            return sum([utxo.txout.value for utxo in utxos])

        def get_idx_non_zero_category():
            for i, category in enumerate(self.category_list.categories):
                if sum_value(category) > 0:
                    return i

        idx_non_zero_category = get_idx_non_zero_category()
        if idx_non_zero_category is not None:
            self.category_list.item(idx_non_zero_category).setSelected(True)

    def add_outpoints(self, outpoints: List[OutPoint]):
        old_outpoints = self.get_outpoints()
        for outpoint in outpoints:
            if outpoint not in old_outpoints:
                self.additional_outpoints.append(outpoint)

    def click_add_utxo(self):
        def process_input(s: str):
            outpoints = [
                OutPoint.from_str(row.strip()) for row in s.strip().split("\n")
            ]
            logger.debug(f"Adding outpoints {outpoints}")
            self.add_outpoints(outpoints)
            self.utxo_list.update()
            self.utxo_list.select_rows(
                outpoints, self.utxo_list.key_column, self.utxo_list.ROLE_KEY
            )

        UTXOAddDialog(on_open=process_input).show()

    def on_set_fee_rate(self, fee_rate):
        self.checkBox_reduce_future_fees.setChecked(
            fee_rate <= self.enable_opportunistic_merging_fee_rate
        )

        sent_values = [r.amount for r in self.recipients.recipients]
        if fee_rate is not None and sum(sent_values):
            minimalistic_utxos_for_inputs = self.wallet.minimalistic_coin_select(
                self.get_ui_tx_infos().utxo_dict.values(), sum(sent_values)
            )
            num_inputs = max(1, len(minimalistic_utxos_for_inputs.utxos))
            # assume all inputs come from this wallet
            fee = (
                fee_rate
                * estimate_tx_weight(
                    [self.wallet.get_mn_tuple() for i in range(num_inputs)],
                    len(sent_values) + 1,
                )
                / 4
            )
            self.fee_group.set_fee_to_send_ratio(
                fee,
                sum(sent_values),
                self.config.network_settings.network,
            )

    def get_ui_tx_infos(self, use_this_tab=None) -> TxUiInfos:
        infos = TxUiInfos()
        infos.opportunistic_merge_utxos = self.checkBox_reduce_future_fees.isChecked()

        for recipient in self.recipients.recipients:
            infos.add_recipient(recipient)

        logger.debug(
            f"set psbt builder fee_rate {self.fee_group.spin_fee_rate.value()}"
        )
        infos.set_fee_rate(self.fee_group.spin_fee_rate.value())

        if not use_this_tab:
            use_this_tab = self.tabs_inputs.currentWidget()

        wallets = (
            [self.wallet]
            if use_this_tab == self.tab_inputs_categories
            else self.signals.get_wallets().values()
        )

        if use_this_tab == self.tab_inputs_categories:
            infos.fill_utxo_dict_from_categories(
                self.category_list.get_selected(), wallets
            )

        if use_this_tab == self.tab_inputs_utxos:
            infos.fill_utxo_dict_from_outpoints(
                self.utxo_list.get_selected_outpoints(), wallets
            )
            infos.spend_all_utxos = True

        return infos

    def set_max_amount(self, spin_box: BTCSpinBox):
        txinfos = self.get_ui_tx_infos()

        total_input_value = sum(
            [utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo]
        )

        total_output_value = sum(
            [recipient.amount for recipient in txinfos.recipients]
        )  # this includes the old value of the spinbox

        logger.debug(str((total_input_value, total_output_value, spin_box.value())))

        max_available_amount = total_input_value - total_output_value
        spin_box.setValue(spin_box.value() + max_available_amount)

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
            self.splitter.setSizes([200, 600])
        elif index == 1:
            self.splitter.setSizes([400, 600])

            # take the coin selection from the category to the utxo tab (but only if one is selected)
            self.set_coin_selection_in_sent_tab(
                self.get_ui_tx_infos(self.tab_inputs_categories)
            )

    def set_coin_selection_in_sent_tab(self, txinfos: TxUiInfos):
        utxos_for_input = self.wallet.handle_opportunistic_merge_utxos(txinfos)

        model = self.utxo_list.model()
        # Get the selection model from the view
        selection = self.utxo_list.selectionModel()

        utxo_names = [self.wallet.get_utxo_name(utxo) for utxo in utxos_for_input.utxos]

        # Select rows with an ID in id_list
        for row in range(model.rowCount()):
            index = model.index(row, self.utxo_list.Columns.OUTPOINT)
            utxo_name = model.data(index)
            if utxo_name in utxo_names:
                selection.select(
                    index, QItemSelectionModel.Select | QItemSelectionModel.Rows
                )
            else:
                selection.select(
                    index, QItemSelectionModel.Deselect | QItemSelectionModel.Rows
                )

    def set_ui(self, txinfos: TxUiInfos):
        self.recipients.recipients = txinfos.recipients

        outpoints = [OutPoint.from_str(s) for s in txinfos.utxo_dict.keys()]
        self.tabs_inputs.setCurrentWidget(self.tab_inputs_utxos)
        self.utxo_list.select_rows(
            outpoints,
            self.utxo_list.key_column,
            self.utxo_list.ROLE_KEY,
        )

        if txinfos.fee_rate:
            self.fee_group.set_fee_rate(txinfos.fee_rate)
