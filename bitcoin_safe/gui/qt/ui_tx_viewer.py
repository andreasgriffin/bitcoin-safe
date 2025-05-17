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
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.address_comparer import AddressComparer
from bitcoin_safe.client import Client
from bitcoin_safe.execute_config import GENERAL_RBF_AVAILABLE
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.extended_tabwidget import ExtendedTabWidget
from bitcoin_safe.gui.qt.fee_group import FeeGroup
from bitcoin_safe.gui.qt.labeledit import WalletLabelAndCategoryEdit
from bitcoin_safe.gui.qt.packaged_tx_like import UiElements
from bitcoin_safe.gui.qt.sankey_bitcoin import SankeyBitcoin
from bitcoin_safe.gui.qt.tx_export import TxExport
from bitcoin_safe.gui.qt.tx_signing_steps import TxSigningSteps
from bitcoin_safe.gui.qt.tx_tools import TxTools
from bitcoin_safe.gui.qt.ui_tx_base import UITx_Base
from bitcoin_safe.gui.qt.warning_bars import LinkingWarningBar, PoisoningWarningBar
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.labels import LabelType
from bitcoin_safe.signal_tracker import SignalTools
from bitcoin_safe.threading_manager import TaskThread, ThreadingManager
from bitcoin_safe.typestubs import TypedPyQtSignal

from ...config import UserConfig
from ...mempool import MempoolData
from ...psbt_util import FeeInfo, PubKeyInfo, SimpleInput, SimplePSBT
from ...pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    TransactionDetails,
    get_prev_outpoints,
    robust_address_str_from_script,
)
from ...signals import Signals, TypedPyQtSignalNo, UpdateFilter
from ...signer import (
    AbstractSignatureImporter,
    SignatureImporterClipboard,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from ...wallet import (
    ToolsTxUiInfo,
    TxConfirmationStatus,
    TxStatus,
    Wallet,
    get_wallet_of_address,
    get_wallets,
)
from .util import (
    Message,
    MessageType,
    add_to_buttonbox,
    block_explorer_URL,
    caught_exception_message,
    clear_layout,
    svg_tools,
)
from .utxo_list import UtxoListWithToolbar

logger = logging.getLogger(__name__)


class UITx_Viewer(UITx_Base, ThreadingManager):
    signal_updated_content: TypedPyQtSignal[Data] = pyqtSignal(Data)  # type: ignore
    signal_edit_tx: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        fx: FX,
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        network: bdk.Network,
        mempool_data: MempoolData,
        data: Data,
        client: Client | None = None,
        fee_info: FeeInfo | None = None,
        chain_position: bdk.ChainPosition | None = None,
        parent=None,
        threading_parent: ThreadingManager | None = None,
        focus_ui_element: UiElements = UiElements.none,
    ) -> None:
        super().__init__(
            parent=parent,
            config=config,
            signals=signals,
            mempool_data=mempool_data,
            threading_parent=threading_parent,
        )
        self.focus_ui_element = focus_ui_element
        self.data = data
        self.network = network
        self.fee_info = fee_info
        self.client = client
        self.utxo_list = widget_utxo_with_toolbar.utxo_list
        self.chain_position = chain_position

        ##################
        self.searchable_list = widget_utxo_with_toolbar.utxo_list

        # category_linking_warning_bar
        self.category_linking_warning_bar = LinkingWarningBar(signals_min=self.signals)
        self._layout.addWidget(self.category_linking_warning_bar)

        # address_poisoning
        self.address_poisoning_warning_bar = PoisoningWarningBar(signals_min=self.signals)
        self._layout.addWidget(self.address_poisoning_warning_bar)

        # tx label
        self.container_label = QWidget(self)
        container_label_layout = QHBoxLayout(self.container_label)
        container_label_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.label_label = QLabel("")
        self.label_line_edit = WalletLabelAndCategoryEdit(
            signals=self.signals,
            get_label_ref=self.txid,
            label_type=LabelType.tx,
            parent=self,
            dismiss_label_on_focus_loss=False,
        )
        container_label_layout.addWidget(self.label_label)
        container_label_layout.addWidget(self.label_line_edit)
        self._layout.addWidget(self.container_label)

        # upper widget
        self.upper_widget = QWidget()
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)
        self.upper_widget_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self._layout.addWidget(self.upper_widget)

        # in out
        self.tabs_inputs_outputs = ExtendedTabWidget[object](parent=self)
        self.tabs_inputs_outputs.setObjectName(f"member of {self.__class__.__name__}")
        # button = QPushButton("Edit")
        # button.setFixedHeight(button.sizeHint().height())
        # button.setIcon(QIcon(icon_path("pen.svg")))
        # button.setIconSize(QSize(16, 16))  # 24x24 pixels
        # button.clicked.connect(lambda: self.edit())
        # self.tabs_inputs_outputs.set_top_right_widget(button)
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        # inputs
        self.tab_inputs = QWidget()
        self.tab_inputs_layout = QVBoxLayout(self.tab_inputs)
        self.tabs_inputs_outputs.addTab(
            self.tab_inputs, description="", icon=svg_tools.get_QIcon("bi--inputs.svg")
        )
        self.tab_inputs_layout.addWidget(widget_utxo_with_toolbar)

        # outputs
        self.tab_outputs = QWidget()
        self.tab_outputs_layout = QVBoxLayout(self.tab_outputs)
        self.tabs_inputs_outputs.addTab(
            self.tab_outputs, description="", icon=svg_tools.get_QIcon("bi--recipients.svg")
        )
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)

        self.recipients = self.create_recipients(
            self.tab_outputs_layout,
            allow_edit=False,
        )

        # sankey
        self.sankey_bitcoin = SankeyBitcoin(network=self.network, signals=self.signals)

        # right side bar
        self.right_sidebar = QWidget()
        self.right_sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.right_sidebar_layout = QVBoxLayout(self.right_sidebar)
        self.right_sidebar_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.upper_widget_layout.addWidget(self.right_sidebar)

        # QSizePolicy.Policy.Fixed: The widget has a fixed size and cannot be resized.
        # QSizePolicy.Policy.Minimum: The widget can be shrunk to its minimum size hint.
        # QSizePolicy.Policy.Maximum: The widget can be expanded up to its maximum size hint.
        # QSizePolicy.Policy.Preferred: The widget can be resized, but it prefers to be the size of its size hint.
        # QSizePolicy.Policy.Expanding: The widget can be resized and prefers to expand to take up as much space as possible.
        # QSizePolicy.Policy.MinimumExpanding: The widget can be resized and tries to be as small as possible but can expand if necessary.
        # QSizePolicy.Policy.Ignored: The widget's size hint is ignored and it can be any size.

        # fee_rate
        self.fee_group = FeeGroup(
            self.mempool_data,
            fx,
            self.config,
            fee_info=fee_info,
            allow_edit=False,
            is_viewer=True,
            chain_position=chain_position,
            url=block_explorer_URL(config.network_config.mempool_url, "tx", self.extract_tx().compute_txid()),
        )
        self.right_sidebar_layout.addWidget(
            self.fee_group.groupBox_Fee, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        # progress bar  import export  flow container
        self.tx_singning_steps_container = QWidget()
        self.tx_singning_steps_container.setMaximumHeight(400)
        self.tx_singning_steps_container_layout = QVBoxLayout(self.tx_singning_steps_container)
        self.tx_singning_steps_container_layout.setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins
        self._layout.addWidget(self.tx_singning_steps_container)
        self.tx_singning_steps: Optional[TxSigningSteps] = None

        # # txid and block explorers
        # self.blockexplorer_group = BlockExplorerGroup(tx.txid(), layout=self.right_sidebar_layout)
        self.export_widget_container = QWidget()
        self.export_widget_container_layout = QVBoxLayout(self.export_widget_container)
        self.export_widget_container_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.export_widget_container.setMaximumHeight(220)
        self.export_data_simple = TxExport(
            data=self.data,
            network=self.network,
            signals_min=self.signals,
            threading_parent=self,
            parent=self,
            sync_tabs=self.get_synctabs(),
        )
        self.export_widget_container_layout.addWidget(self.export_data_simple)
        self._layout.addWidget(self.export_widget_container)

        # buttons

        # Create the QDialogButtonBox
        self.buttonBox = QDialogButtonBox()

        # Create custom buttons
        # if i do  on_clicked=  self.edit    it doesnt reliably trigger the signal. Why???
        self.button_edit_tx = add_to_buttonbox(
            self.buttonBox,
            "",
            "pen.svg",
            on_clicked=self.edit,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        # I can just call self.edit(), because the TX Creator  should automatically detect that it must increase fee to rbf
        self.button_rbf = add_to_buttonbox(
            self.buttonBox,
            "",
            "pen.svg",
            on_clicked=self.edit,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        # I can just call self.edit(), because the TX Creator  should automatically detect that it must increase fee to rbf
        self.button_cpfp_tx = add_to_buttonbox(
            self.buttonBox,
            "",
            "",
            on_clicked=self.cpfp,
            role=QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.button_save_tx = add_to_buttonbox(self.buttonBox, "Save", "bi--sd-card.svg")
        self.button_previous = add_to_buttonbox(
            self.buttonBox,
            "",
            None,
            on_clicked=self.go_to_previous_index,
            role=QDialogButtonBox.ButtonRole.RejectRole,
        )
        self.button_next = add_to_buttonbox(
            self.buttonBox,
            "",
            None,
            on_clicked=self.go_to_next_index,
            role=QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.button_send = add_to_buttonbox(
            self.buttonBox,
            "",
            "bi--send.svg",
            on_clicked=self.broadcast,
            role=QDialogButtonBox.ButtonRole.AcceptRole,
        )

        self._layout.addWidget(self.buttonBox)
        ##################

        self.button_save_tx.setVisible(False)
        self.button_send.setEnabled(self.data.data_type == DataType.Tx)

        self.updateUi()
        self.reload(UpdateFilter(refresh_all=True))
        self.utxo_list.update_content()

        # signals
        self.signal_tracker.connect(self.signals.language_switch, self.updateUi)
        # after the wallet loads the transactions, then i have to reload again to
        # ensure that the linking warning bar appears (needs all tx loaded)
        self.signal_tracker.connect(self.signals.any_wallet_updated, self.reload)

    def updateUi(self) -> None:
        self.tabs_inputs_outputs.setTabText(
            self.tabs_inputs_outputs.indexOf(self.tab_inputs), self.tr("Inputs")
        )
        self.tabs_inputs_outputs.setTabText(
            self.tabs_inputs_outputs.indexOf(self.tab_outputs), self.tr("Recipients")
        )
        index = self.tabs_inputs_outputs.indexOf(self.sankey_bitcoin)
        if index >= 0:
            self.tabs_inputs_outputs.setTabText(
                self.tabs_inputs_outputs.indexOf(self.sankey_bitcoin), self.tr("Diagram")
            )
        self.button_edit_tx.setText(self.tr("Edit"))
        self.button_cpfp_tx.setText(self.tr("Receive faster (CPFP)"))
        if GENERAL_RBF_AVAILABLE:
            self.button_rbf.setText(self.tr("Edit with increased fee (RBF)"))
        else:
            self.button_rbf.setText(self.tr("Increase fee (RBF)"))
        self.button_previous.setText(self.tr("Previous step"))
        self.button_next.setText(self.tr("Next step"))
        self.button_send.setText(self.tr("Send"))
        self.button_send.setToolTip("Broadcasts the transaction to the bitcoin network.")
        self.label_label.setText(self.tr("Label: "))
        self.category_linking_warning_bar.updateUi()
        self.address_poisoning_warning_bar.updateUi()

    def extract_tx(self) -> bdk.Transaction:
        if self.data.data_type == DataType.Tx:
            if not isinstance(self.data.data, bdk.Transaction):
                raise Exception(f"{self.data.data} is not of type bdk.Transaction")
            return self.data.data
        if self.data.data_type == DataType.PSBT:
            if not isinstance(self.data.data, bdk.Psbt):
                raise Exception(f"{self.data.data} is not of type bdk.Psbt")
            return self.data.data.extract_tx()
        raise Exception(f"invalid data type {self.data.data}")

    def _step_allows_forward(self, index: int) -> bool:
        if not self.tx_singning_steps:
            return False
        if index == self.tx_singning_steps.count() - 1:
            return False
        return index in self.tx_singning_steps.sub_indices

    def _step_allows_backward(self, index: int) -> bool:
        if not self.tx_singning_steps:
            return False
        if index == 0:
            return False
        return index - 1 in self.tx_singning_steps.sub_indices

    def set_next_prev_button_enabledness(self):
        if not self.tx_singning_steps:
            return
        next_enabled = self._step_allows_forward(self.tx_singning_steps.current_index())
        prev_enabled = self._step_allows_backward(self.tx_singning_steps.current_index())
        self.button_next.setEnabled(next_enabled)
        self.button_previous.setEnabled(prev_enabled)
        self.button_next.setHidden(not next_enabled and not prev_enabled)
        self.button_previous.setHidden(not next_enabled and not prev_enabled)

    def go_to_next_index(self) -> None:
        if not self.tx_singning_steps:
            return
        self.tx_singning_steps.go_to_next_index()

        self.set_next_prev_button_enabledness()

    def go_to_previous_index(self) -> None:
        if not self.tx_singning_steps:
            return
        self.tx_singning_steps.go_to_previous_index()

        self.set_next_prev_button_enabledness()

    def get_tx_details(self, txid: str) -> Tuple[TransactionDetails | None, Wallet | None]:
        for wallet in get_wallets(self.signals):
            tx = wallet.get_tx(txid=txid)
            if tx:
                return tx, wallet
        return None, None

    def can_cpfp(self, tx_status: TxStatus) -> bool:
        tx = self.extract_tx()
        tx_details, wallet = self.get_tx_details(txid=tx.compute_txid())
        if not wallet:
            return False
        return TxTools.can_cpfp(tx=tx, wallet=wallet, tx_status=tx_status)

    def cpfp(self) -> None:
        tx = self.extract_tx()
        tx_details, wallet = self.get_tx_details(txid=tx.compute_txid())
        if not wallet or not tx_details:
            return
        TxTools.cpfp_tx(tx_details=tx_details, wallet=wallet, signals=self.signals)

    def edit(self) -> None:
        tx = self.extract_tx()
        txinfos = ToolsTxUiInfo.from_tx(tx, self.fee_info, self.network, get_wallets(self.signals))
        tx_details, wallet = self.get_tx_details(txid=tx.compute_txid())
        if tx_details:
            TxTools.edit_tx(replace_tx=tx_details, txinfos=txinfos, signals=self.signals)
        else:
            Message(
                self.tr("Transaction to be replaced could not be found in open wallets"),
                type=MessageType.Error,
            )

    def reload(self, update_filter: UpdateFilter) -> None:
        should_update = False
        if should_update or update_filter.refresh_all:
            should_update = True
        if should_update or update_filter.outpoints:
            should_update = True

        if not should_update:
            return
        logger.debug(f"{self.__class__.__name__} update_with_filter")

        if self.data.data_type == DataType.PSBT:
            self.set_psbt(self.data.data, fee_info=self.fee_info)

            # TODO: Check if I can remove the threading here. Or if it becomes too slow for big transactions
            def do() -> bdk.Transaction | None:
                if not isinstance(self.data.data, bdk.Psbt):
                    return None
                result = self.data.data.finalize()
                return result.psbt.extract_tx() if result.could_finalize else None

            def on_done(result) -> None:
                pass

            def on_error(packed_error_info) -> None:
                pass

            def on_success(finalized_tx: bdk.Transaction) -> None:
                if finalized_tx and isinstance(self.data.data, bdk.Psbt):
                    assert (
                        finalized_tx.compute_txid() == self.data.data.extract_tx().compute_txid()
                    ), "error. The txid should not be changed during finalizing/reloading"
                    self.set_tx(
                        finalized_tx,
                        fee_info=self.fee_info,
                        chain_position=self.chain_position,
                    )
                    return

            self.append_thread(TaskThread().add_and_start(do, on_success, on_done, on_error))

        elif self.data.data_type == DataType.Tx:
            self.set_tx(
                self.data.data,
                fee_info=self.fee_info,
                chain_position=self.chain_position,
            )

    def txid(self) -> str:
        return self.extract_tx().compute_txid()

    def _get_height(self) -> int | None:
        for wallet in get_wallets(self.signals):
            return wallet.get_height()
        return None

    def _broadcast(self, tx: bdk.Transaction) -> bool:
        if self.client:
            try:
                self.client.broadcast(tx)
                self.signals.signal_broadcast_tx.emit(tx)
                return True
            except Exception as e:
                caught_exception_message(
                    e,
                    title=(
                        self.tr("Invalid Signatures")
                        if "non-mandatory-script-verify-flag" in str(e)
                        else None
                    ),
                )
        else:
            logger.error("No blockchain set")

        return False

    def _set_blockchain(self):
        for wallet in get_wallets(self.signals):
            if wallet.client:
                self.client = wallet.client
                logger.error(f"Using {self.client} from wallet {wallet.id}")

    def broadcast(self) -> None:
        if not self.data.data_type == DataType.Tx:
            return
        if not isinstance(self.data.data, bdk.Transaction):
            logger.error(f"data is not of type bdk.Transaction and cannot be broadcastet")
            return
        tx = self.data.data

        if not self.client:
            self._set_blockchain()

        logger.debug(f"broadcasting tx {tx.compute_txid()[:4]=}")
        success = self._broadcast(tx)
        if success:
            logger.info(f"Successfully broadcasted tx {tx.compute_txid()[:4]=}")
        else:
            Message(
                self.tr("Failed to broadcast {txid}. Consider broadcasting via {url}").format(
                    txid=self.data.data.compute_txid(), url="https://blockstream.info/tx/push"
                ),
                type=MessageType.Error,
            )

    def enrich_simple_psbt_with_wallet_data(self, simple_psbt: SimplePSBT) -> SimplePSBT:
        def get_keystore(fingerprint: str, keystores: List[KeyStore]) -> Optional[KeyStore]:
            for keystore in keystores:
                if keystore.fingerprint == fingerprint:
                    return keystore
            return None

        # collect all wallets that have input utxos
        inputs: List[bdk.TxIn] = self.extract_tx().input()

        outpoint_dict = {
            outpoint_str: (python_utxo, wallet)
            for wallet in get_wallets(self.signals)
            for outpoint_str, python_utxo in wallet.get_all_txos_dict().items()
        }

        # fill fingerprints, if not available
        for this_input, simple_input in zip(inputs, simple_psbt.inputs):
            outpoint_str = str(this_input.previous_output)
            if outpoint_str not in outpoint_dict:
                continue
            python_utxo, wallet = outpoint_dict[outpoint_str]

            simple_input.wallet_id = wallet.id
            simple_input.m_of_n = wallet.get_mn_tuple()

            if not simple_input.pubkeys:
                # fill with minimal info
                simple_input.pubkeys = [
                    PubKeyInfo(fingerprint=keystore.fingerprint) for keystore in wallet.keystores
                ]

            # fill additional info (label) if available
            for pubkey in simple_input.pubkeys:
                keystore = get_keystore(pubkey.fingerprint, wallet.keystores)
                if not keystore:
                    continue
                pubkey.label = keystore.label

        return simple_psbt

    def get_wallet_inputs(self, simple_psbt: SimplePSBT) -> Dict[str, List[SimpleInput]]:
        "structures the inputs into categories, usually wallet_ids, such that all the inputs are sure to belong to 1 wallet"
        wallet_inputs: Dict[str, List[SimpleInput]] = {}
        for i, inp in enumerate(simple_psbt.inputs):

            if inp.wallet_id and inp.m_of_n:
                id = inp.wallet_id
            elif inp.pubkeys:
                id = ", ".join(
                    sorted([(pubkey.fingerprint or pubkey.pubkey or pubkey.label) for pubkey in inp.pubkeys])
                )
            else:
                id = f"Input {i}"

            l = wallet_inputs.setdefault(id, [])
            l.append(inp)

        return wallet_inputs

    def get_combined_signature_importers(self, psbt: bdk.Psbt) -> Dict[str, List[AbstractSignatureImporter]]:
        signature_importers: Dict[str, List[AbstractSignatureImporter]] = {}

        def get_signing_fingerprints_of_wallet(wallet: Wallet) -> Set[str]:
            # check which keys the wallet can sign

            wallet_signing_fingerprints = set(
                [keystore.fingerprint for keystore in wallet.keystores if keystore.mnemonic]
            )
            return wallet_signing_fingerprints

        def get_wallets_with_seed(fingerprints: List[str]) -> List[Wallet]:
            result = []
            for wallet in wallets:
                signing_fingerprints_of_wallet = get_signing_fingerprints_of_wallet(wallet)
                if set(fingerprints).intersection(signing_fingerprints_of_wallet):
                    if wallet not in result:
                        result.append(wallet)
            return result

        simple_psbt = SimplePSBT.from_psbt(psbt)
        simple_psbt = self.enrich_simple_psbt_with_wallet_data(simple_psbt)

        wallet_inputs = self.get_wallet_inputs(simple_psbt)

        wallets: List[Wallet] = get_wallets(self.signals)

        pub_keys_without_signature = sum(
            [input.get_pub_keys_without_signature() for inputs in wallet_inputs.values() for input in inputs],
            [],
        )

        for wallet_id, inputs in wallet_inputs.items():
            if not inputs:
                continue
            m, n = inputs[0].get_estimated_m_of_n()
            pubkeys_with_signature = inputs[0].get_pub_keys_with_signature()

            # only add a maximum of m *(all_signature_importers) for each wallet
            for i in range(m):
                l = signature_importers.setdefault(f"{wallet_id}.{i}", [])
                if i < len(pubkeys_with_signature):

                    l.append(
                        SignatureImporterFile(
                            self.network,
                            signature_available=True,
                            key_label=pubkeys_with_signature[i].fingerprint,
                            label=self.tr("Import file"),
                            close_all_video_widgets=self.signals.close_all_video_widgets,
                        )
                    )
                else:
                    # for missing required signatures
                    if inputs[0].pubkeys:
                        # check if any wallet has keys for this fingerprint
                        for wallet_with_seed in get_wallets_with_seed(
                            [pubkey.fingerprint for inp in inputs for pubkey in inp.pubkeys]
                        ):
                            l.append(
                                SignatureImporterWallet(
                                    wallet_with_seed,
                                    self.network,
                                    signature_available=False,
                                    key_label=wallet_id,
                                )
                            )

                    for cls in [
                        SignatureImporterQR,
                        SignatureImporterFile,
                        SignatureImporterClipboard,
                        SignatureImporterUSB,
                    ]:
                        l.append(
                            cls(
                                self.network,
                                signature_available=False,
                                key_label=wallet_id,
                                pub_keys_without_signature=pub_keys_without_signature,
                                close_all_video_widgets=self.signals.close_all_video_widgets,
                            )
                        )
        # connect signals
        for importers in signature_importers.values():
            for importer in importers:
                importer.signal_signature_added.connect(self.import_trusted_psbt)
                importer.signal_final_tx_received.connect(self.tx_received)
        return signature_importers

    def update_tx_progress(self) -> Optional[TxSigningSteps]:
        if self.data.data_type != DataType.PSBT:
            return None
        if not isinstance(self.data.data, bdk.Psbt):
            logger.error(f"data is not of type bdk.Psbt")
            return None

        # this approach to clearning the layout
        # and then recreating the ui object is prone
        # to problems with multithreading.
        clear_layout(self.tx_singning_steps_container_layout)

        signature_importers = self.get_combined_signature_importers(self.data.data)

        tx_singning_steps = TxSigningSteps(
            signature_importer_dict=signature_importers,
            psbt=self.data.data,
            network=self.network,
            signals=self.signals,
            threading_parent=self,
        )

        self.tx_singning_steps_container_layout.addWidget(tx_singning_steps)
        return tx_singning_steps

    def tx_received(self, tx: bdk.Transaction) -> None:
        if self.data.data_type != DataType.PSBT:
            return
        if not isinstance(self.data.data, bdk.Psbt):
            logger.error(f"data is not of type bdk.Psbt")
            return

        if self.data.data and tx.compute_txid() != self.data.data.extract_tx().compute_txid():
            Message(
                self.tr("The txid of the signed psbt doesnt match the original txid"), type=MessageType.Error
            )
            return

        self.set_tx(
            tx,
        )

    def _get_any_signature_importer(self) -> AbstractSignatureImporter | None:
        if not self.tx_singning_steps:
            return None
        for signature_importers in self.tx_singning_steps.signature_importer_dict.values():
            for signature_importer in signature_importers:
                return signature_importer
        return None

    def import_untrusted_psbt(self, import_psbt: bdk.Psbt) -> None:
        if isinstance(self.data.data, bdk.Psbt) and (
            signature_importer := self._get_any_signature_importer()
        ):
            signature_importer.handle_data_input(
                original_psbt=self.data.data, data=Data.from_psbt(psbt=import_psbt, network=self.network)
            )
        elif isinstance(self.data.data, bdk.Transaction):
            logger.info(
                f"Will not open the tx if the transaction, since we cannot verify if all signatures are present"
            )
        else:
            logger.warning("Cannot update the psbt. Unclear if more signatures were added")

    def import_trusted_psbt(self, import_psbt: bdk.Psbt) -> None:
        simple_psbt = SimplePSBT.from_psbt(import_psbt)

        tx = import_psbt.extract_tx()

        if all([inp.is_fully_signed() for inp in simple_psbt.inputs]):
            self.set_tx(
                tx,
            )
        else:
            self.set_psbt(import_psbt)

    def is_in_mempool(self, txid: str) -> bool:
        # TODO: Currently in mempool and is in wallet is the same thing. In the future I have to differentiate here
        wallets = get_wallets(self.signals)
        for wallet in wallets:
            if wallet.is_in_mempool(txid):
                return True
        return False

    def _set_warning_bars(
        self, txins: List[bdk.TxIn], recipient_addresses: List[str], chain_position: bdk.ChainPosition | None
    ):
        self.set_poisoning_warning_bar(txins=txins, recipient_addresses=recipient_addresses)
        self.set_category_warning_bar(txins=txins, recipient_addresses=recipient_addresses)

        tx_status = self.get_tx_status(chain_position=chain_position)
        self.update_high_fee_warning_label(confirmation_status=tx_status.confirmation_status)
        self.high_fee_rate_warning_label.update_fee_rate_warning(
            confirmation_status=tx_status.confirmation_status,
            fee_rate=self.fee_info.fee_rate() if self.fee_info else None,
            max_reasonable_fee_rate=self.mempool_data.max_reasonable_fee_rate(),
        )

    def update_high_fee_warning_label(self, confirmation_status: TxConfirmationStatus):
        if confirmation_status != TxConfirmationStatus.LOCAL:
            self.high_fee_warning_label.setVisible(False)
            return

        wallets: List[Wallet] = list(self.signals.get_wallets.emit().values())

        total_non_change_output_amount = 0
        for wallet in wallets:
            for recipient in self.recipients.recipients:
                if not recipient.address:
                    continue
                if not (wallet.is_my_address(recipient.address) and wallet.is_change(recipient.address)):
                    total_non_change_output_amount += recipient.amount

        self.high_fee_warning_label.set_fee_to_send_ratio(
            fee_info=self.fee_info,
            total_non_change_output_amount=total_non_change_output_amount,
            network=self.config.network,
            # if checked_max_amount, then the user might not notice a 0 output amount, and i better show a warning
            force_show_fee_warning_on_0_amont=any([r.checked_max_amount for r in self.recipients.recipients]),
            chain_position=self.fee_group.visible_mempool_buttons.chain_position,
        )

    def set_poisoning_warning_bar(self, txins: List[bdk.TxIn], recipient_addresses: List[str]):
        # warn if multiple categories are combined
        outpoints = [OutPoint.from_bdk(inp.previous_output) for inp in txins]
        wallets: List[Wallet] = list(self.signals.get_wallets.emit().values())

        all_addresses = set(recipient_addresses)
        for wallet in wallets:

            addresses = [wallet.get_address_of_outpoint(outpoint) for outpoint in outpoints]
            for address in addresses:
                if not address:
                    continue
                all_addresses.add(address)
        poisonous_matches = AddressComparer.poisonous(all_addresses)
        self.address_poisoning_warning_bar.set_poisonous_matches(poisonous_matches)

    def set_category_warning_bar(self, txins: List[bdk.TxIn], recipient_addresses: List[str]):
        # warn if multiple categories are combined
        outpoints = [OutPoint.from_bdk(inp.previous_output) for inp in txins]
        wallets: List[Wallet] = list(self.signals.get_wallets.emit().values())

        category_dict: Dict[str, Set[str]] = defaultdict(set[str])
        for wallet in wallets:
            addresses = [
                wallet.get_address_of_outpoint(outpoint) for outpoint in outpoints
            ] + recipient_addresses
            this_category_dict = self.get_category_dict_of_addresses(
                [address for address in addresses if address], wallets=[wallet]
            )
            for k, v in this_category_dict.items():
                category_dict[k].update(v)

        self.category_linking_warning_bar.set_category_dict(category_dict)

    def calc_finalized_tx_fee_info(self, tx: bdk.Transaction, tx_has_final_size: bool) -> Optional[FeeInfo]:
        "This only should be done for tx, not psbt, since the PSBT.extract_tx size is too low"
        wallets = get_wallets(self.signals)
        # try via tx details
        for wallet_ in wallets:
            txdetails = wallet_.get_tx(tx.compute_txid())
            if txdetails and txdetails.fee:
                return FeeInfo(fee_amount=txdetails.fee, vsize=tx.vsize(), is_estimated=False)

        #  try via utxos
        pythonutxo_dict: Dict[str, PythonUtxo] = {}  # outpoint_str:PythonUTXO
        for wallet_ in wallets:
            pythonutxo_dict.update(wallet_.get_all_txos_dict(include_not_mine=True))

        total_input_value = 0
        for outpoint in get_prev_outpoints(tx):
            python_txo = pythonutxo_dict.get(str(outpoint))
            if not python_txo:
                # ALL inputs must be known with value! Otherwise no fee can be calculated
                return None
            if python_txo.txout.value is None:
                return None
            total_input_value += python_txo.txout.value

        total_output_value = sum([txout.value for txout in tx.output()])
        fee_amount = total_input_value - total_output_value
        return FeeInfo(fee_amount=fee_amount, vsize=tx.vsize(), is_estimated=not tx_has_final_size)

    def get_chain_position(self, txid: str) -> bdk.ChainPosition | None:
        for wallet in get_wallets(self.signals):
            tx_details = wallet.get_tx(txid)
            if tx_details:
                return tx_details.chain_position
        return None

    def set_tx(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo | None = None,
        chain_position: bdk.ChainPosition | None = None,
    ) -> None:
        self.data = Data.from_tx(tx, network=self.network)
        fee_info = fee_info if fee_info else self._fetch_cached_feeinfo(tx.compute_txid())
        if fee_info is None or fee_info.is_estimated:
            fee_info = self.calc_finalized_tx_fee_info(tx, tx_has_final_size=True)
        self.fee_info = fee_info

        if chain_position is None:
            chain_position = self.get_chain_position(tx.compute_txid())
        self.chain_position = chain_position

        # no Fee is unknown if no fee_info was given
        self.fee_group.groupBox_Fee.setVisible(fee_info is not None)
        if fee_info is not None:
            self.fee_group.set_fee_infos(
                fee_info=fee_info,
                url=block_explorer_URL(self.config.network_config.mempool_url, "tx", tx.compute_txid()),
                chain_position=chain_position,
                chain_height=self._get_height(),
            )
            # calcualte the fee warning. However since in a tx I don't know what is a change address,
            # it is not possible to give  fee warning for the sent (vs. change) amount
            self.high_fee_warning_label.set_fee_to_send_ratio(
                fee_info=fee_info,
                total_non_change_output_amount=self.get_total_non_change_output_amount(tx),
                network=self.config.network,
                chain_position=chain_position,
            )
            self.handle_cpfp(tx=tx, this_fee_info=fee_info, chain_position=chain_position)

        outputs: List[bdk.TxOut] = tx.output()

        self.recipients.recipients = [
            Recipient(
                address=robust_address_str_from_script(output.script_pubkey, self.network),
                amount=output.value,
            )
            for output in outputs
        ]
        self.set_visibility(chain_position=chain_position)
        self.export_data_simple.set_data(data=self.data, sync_tabs=self.get_synctabs())

        self._set_warning_bars(
            txins=tx.input(),
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            chain_position=chain_position,
        )
        self.set_sankey(tx, fee_info=fee_info, txo_dict=self._get_python_txos())
        self.label_line_edit.updateUi()
        self.label_line_edit.autofill_label_and_category()
        self.container_label.setHidden(False)
        self.signal_updated_content.emit(self.data)

    def _get_python_txos(self):
        txo_dict: Dict[str, PythonUtxo] = {}  # outpoint_str:PythonUTXO
        for wallet_ in get_wallets(self.signals):
            txo_dict.update(wallet_.get_all_txos_dict(include_not_mine=True))
        return txo_dict

    def get_synctabs(self):
        return {
            wallet_id: qt_wallet.sync_tab for wallet_id, qt_wallet in self.signals.get_qt_wallets().items()
        }

    def set_sankey(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo | None = None,
        txo_dict: Dict[str, PythonUtxo] | None = None,
    ):

        # remove old tab_sankey
        tab_index = self.tabs_inputs_outputs.indexOf(self.sankey_bitcoin)
        if tab_index >= 0:
            self.tabs_inputs_outputs.removeTab(tab_index)

        def do() -> bool:
            try:
                return self.sankey_bitcoin.set_tx(tx, fee_info=fee_info, txo_dict=txo_dict)
            except Exception as e:
                logger.warning(str(e))
            return False

        def on_done(success) -> None:
            pass

        def on_success(success) -> None:
            if success:
                self.tabs_inputs_outputs.addTab(
                    self.sankey_bitcoin, icon=svg_tools.get_QIcon("flows.svg"), description=self.tr("Diagram")
                )
                self.set_tab_focus(self.focus_ui_element)

        def on_error(packed_error_info) -> None:
            logger.warning(str(packed_error_info))

        self.append_thread(
            TaskThread(enable_threading=False).add_and_start(do, on_success, on_done, on_error)
        )

    def set_tab_focus(self, focus_ui_element: UiElements):
        self.focus_ui_element = focus_ui_element
        if self.focus_ui_element == UiElements.default:
            self.tabs_inputs_outputs.setCurrentWidget(self.tab_inputs)
        if self.focus_ui_element == UiElements.diagram:
            self.tabs_inputs_outputs.setCurrentWidget(self.sankey_bitcoin)

        self.focus_ui_element = UiElements.none

    def _get_height_from_mempool(self):
        return self.mempool_data.fetch_block_tip_height()

    def get_tx_status(self, chain_position: bdk.ChainPosition | None) -> TxStatus:
        tx = self.extract_tx()
        return TxStatus(
            tx=tx,
            chain_position=chain_position,
            get_height=self._get_height_from_mempool,
            is_in_mempool=self.is_in_mempool(tx.compute_txid()),
        )

    def set_visibility(self, chain_position: bdk.ChainPosition | None) -> None:
        is_psbt = self.data.data_type == DataType.PSBT
        self.export_widget_container.setVisible(not is_psbt)
        self.tx_singning_steps_container.setVisible(is_psbt)

        tx_status = self.get_tx_status(chain_position=chain_position)

        show_send = bool(tx_status.can_do_initial_broadcast() and self.data.data_type == DataType.Tx)
        self.button_send.setEnabled(show_send)
        self.button_next.setVisible(self.data.data_type == DataType.PSBT)
        self.button_previous.setVisible(self.data.data_type == DataType.PSBT)
        # if is_unconfirmed then it makes sense to also edit it before
        self.button_save_tx.setHidden(True)

        self.button_edit_tx.setVisible(tx_status.is_unconfirmed() and not tx_status.can_rbf())
        self.button_cpfp_tx.setVisible(tx_status.is_unconfirmed() and not tx_status.can_rbf())
        self.button_rbf.setVisible(tx_status.can_rbf())
        self.button_cpfp_tx.setVisible(self.can_cpfp(tx_status=tx_status))
        self.set_next_prev_button_enabledness()

    def _fetch_cached_feeinfo(self, txid: str) -> FeeInfo | None:
        if isinstance(self.data.data, bdk.Psbt) and self.data.data.extract_tx().compute_txid() == txid:
            return self.fee_info
        elif isinstance(self.data.data, bdk.Transaction) and self.data.data.compute_txid() == txid:
            return self.fee_info
        return None

    def set_psbt(self, psbt: bdk.Psbt, fee_info: FeeInfo | None = None) -> None:
        """_summary_

        Args:
            psbt (bdk.Psbt): _description_
            fee_rate (_type_, optional): This is the exact fee_rate chosen in txbuilder. If not given it has
                                        to be estimated with estimate_segwit_tx_size_from_psbt.
        """
        # check if any new signatures were added. If not tell the user

        self.data = Data.from_psbt(psbt, network=self.network)
        fee_info = fee_info if fee_info else self._fetch_cached_feeinfo(psbt.extract_tx().compute_txid())

        # do not use calc_fee_info here, because calc_fee_info is for final tx only.

        # if still no fee_info  available, then estimate it
        if fee_info is None:
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)

        self.fee_info = fee_info

        self.fee_group.set_fee_infos(
            fee_info=fee_info,
            chain_position=self.fee_group.visible_mempool_buttons.chain_position,
        )

        outputs: List[bdk.TxOut] = psbt.extract_tx().output()

        self.recipients.recipients = [
            Recipient(
                address=str(bdk.Address.from_script(output.script_pubkey, self.network)),
                amount=output.value,
            )
            for output in outputs
        ]

        # set fee warning
        self.high_fee_warning_label.set_fee_to_send_ratio(
            fee_info=fee_info,
            total_non_change_output_amount=self.get_total_non_change_output_amount(psbt.extract_tx()),
            network=self.network,
            # if checked_max_amount, then the user might not notice a 0 output amount, and i better show a warning
            force_show_fee_warning_on_0_amont=any([r.checked_max_amount for r in self.recipients.recipients]),
            chain_position=self.fee_group.visible_mempool_buttons.chain_position,
        )

        self.tx_singning_steps = self.update_tx_progress()
        self.set_visibility(None)
        self.handle_cpfp(tx=psbt.extract_tx(), this_fee_info=fee_info, chain_position=None)
        self._set_warning_bars(
            psbt.extract_tx().input(),
            recipient_addresses=[recipient.address for recipient in self.recipients.recipients],
            chain_position=None,
        )
        txo_dict = SimplePSBT.from_psbt(psbt).outpoints_as_python_utxo_dict(self.network)
        txo_dict.update(self._get_python_txos())
        self.set_sankey(psbt.extract_tx(), fee_info=fee_info, txo_dict=txo_dict)
        self.container_label.setHidden(True)
        self.signal_updated_content.emit(self.data)

    def handle_cpfp(
        self, tx: bdk.Transaction, this_fee_info: FeeInfo, chain_position: bdk.ChainPosition | None
    ) -> None:
        parent_txids = set(txin.previous_output.txid for txin in tx.input())
        self.set_fee_group_cpfp_label(
            parent_txids=parent_txids,
            this_fee_info=this_fee_info,
            fee_group=self.fee_group,
            chain_position=chain_position,
        )

    def get_total_non_change_output_amount(self, tx: bdk.Transaction) -> int:
        out_flows: List[Tuple[str, int]] = [
            (robust_address_str_from_script(txout.script_pubkey, network=self.network), txout.value)
            for txout in tx.output()
        ]

        total_non_change_output_amount = 0

        for address, value in out_flows:

            wallet = get_wallet_of_address(address, self.signals)
            if wallet and wallet.is_my_address(address) and wallet.is_change(address):
                continue
            else:
                total_non_change_output_amount += value
        return total_non_change_output_amount

    def close(self):
        self.signal_tracker.disconnect_all()
        SignalTools.disconnect_all_signals_from(self)
        self.setParent(None)
        return super().close()
