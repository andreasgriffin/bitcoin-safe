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

from bitcoin_qrreader.bitcoin_qr import Data, DataType
from bitcoin_usb.psbt_finalizer import PSBTFinalizer

from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.block_change_signals import BlockChangesSignals
from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.gui.qt.fee_group import FeeGroup
from bitcoin_safe.gui.qt.mytabwidget import ExtendedTabWidget
from bitcoin_safe.gui.qt.tx_signing_steps import TxSigningSteps
from bitcoin_safe.keystore import KeyStore

from ...config import MIN_RELAY_FEE, UserConfig
from .dialog_import import ImportDialog
from .my_treeview import SearchableTab
from .nLockTimePicker import nLocktimePicker

logger = logging.getLogger(__name__)

from typing import Callable, Dict, List, Optional, Set

import bdkpython as bdk
from PyQt6.QtCore import QItemSelectionModel, QObject, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...mempool import MempoolData, TxPrio
from ...psbt_util import FeeInfo, PubKeyInfo, SimpleInput, SimplePSBT
from ...pythonbdk_types import (
    OutPoint,
    PythonUtxo,
    Recipient,
    UtxosForInputs,
    python_utxo_balance,
    robust_address_str_from_script,
)
from ...signals import Signals, pyqtSignal
from ...signer import (
    AbstractSignatureImporter,
    SignatureImporterClipboard,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from ...tx import TxUiInfos, calc_minimum_rbf_fee_info
from ...util import Satoshis, block_explorer_URL, format_fee_rate, serialized_to_hex
from ...wallet import ToolsTxUiInfo, TxStatus, Wallet, get_wallets
from .category_list import CategoryList
from .recipients import RecipientGroupBox, Recipients
from .util import (
    Message,
    MessageType,
    add_to_buttonbox,
    caught_exception_message,
    clear_layout,
)
from .utxo_list import UTXOList, UtxoListWithToolbar


class UITx_Base(QObject):
    def __init__(self, config: UserConfig, signals: Signals, mempool_data: MempoolData) -> None:
        super().__init__()
        self.signals = signals
        self.mempool_data = mempool_data
        self.config = config

    def create_recipients(self, layout: QLayout, parent=None, allow_edit=True) -> Recipients:
        recipients = Recipients(self.signals, network=self.config.network, allow_edit=allow_edit)

        layout.addWidget(recipients)
        recipients.setMinimumWidth(250)
        return recipients


class UITx_ViewerTab(SearchableTab):
    def __init__(
        self,
        serialize: Callable,
    ) -> None:
        super().__init__()
        self.serialize = serialize


class UITx_Viewer(UITx_Base):
    signal_edit_tx = pyqtSignal()
    signal_save_psbt = pyqtSignal()

    def __init__(
        self,
        config: UserConfig,
        signals: Signals,
        fx: FX,
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        network: bdk.Network,
        mempool_data: MempoolData,
        data: Data,
        blockchain: bdk.Blockchain = None,
        fee_info: FeeInfo = None,
        confirmation_time: bdk.BlockTime = None,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.data = data
        self.network = network
        self.fee_info = fee_info
        self.blockchain = blockchain
        self.utxo_list = widget_utxo_with_toolbar.utxo_list
        self.confirmation_time = confirmation_time

        ##################
        self.main_widget = UITx_ViewerTab(serialize=lambda: self.serialize())
        self.main_widget.setLayout(QVBoxLayout())
        self.main_widget.searchable_list = widget_utxo_with_toolbar.utxo_list

        self.upper_widget = QWidget()
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)
        self.main_widget.layout().addWidget(self.upper_widget)

        # in out
        self.tabs_inputs_outputs = ExtendedTabWidget()
        # button = QPushButton("Edit")
        # button.setFixedHeight(button.sizeHint().height())
        # button.setIcon(QIcon(icon_path("pen.svg")))
        # button.setIconSize(QSize(16, 16))  # 24x24 pixels
        # button.clicked.connect(lambda: self.edit())
        # self.tabs_inputs_outputs.set_top_right_widget(button)
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        # inputs
        self.tab_inputs = QWidget()
        self.tab_inputs.setLayout(QVBoxLayout())
        self.tabs_inputs_outputs.addTab(self.tab_inputs, "")
        self.tab_inputs.layout().addWidget(widget_utxo_with_toolbar)

        # outputs
        self.tab_outputs = QWidget()
        self.tab_outputs.setLayout(QVBoxLayout())
        self.tabs_inputs_outputs.addTab(self.tab_outputs, "")
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)

        self.recipients = self.create_recipients(self.tab_outputs.layout(), allow_edit=False)

        # right side bar
        self.right_sidebar = QWidget()
        self.upper_widget_layout.addWidget(self.right_sidebar)
        self.right_sidebar.setLayout(QVBoxLayout())
        self.right_sidebar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.right_sidebar.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

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
            self.right_sidebar.layout(),
            self.config,
            vsize=fee_info.vsize if fee_info else None,
            allow_edit=False,
            is_viewer=True,
            confirmation_time=confirmation_time,
            url=block_explorer_URL(config.network_config.mempool_url, "tx", self.extract_tx().txid()),
        )
        self.signals.language_switch.connect(self.fee_group.updateUi)

        # progress bar  import export  flow container
        self.tx_singning_steps_container = QWidget()
        self.tx_singning_steps_container.setLayout(QVBoxLayout())
        self.tx_singning_steps_container.layout().setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins
        self.main_widget.layout().addWidget(self.tx_singning_steps_container)
        self.tx_singning_steps: Optional[TxSigningSteps] = None

        # # txid and block explorers
        # self.blockexplorer_group = BlockExplorerGroup(tx.txid(), layout=self.right_sidebar.layout())
        self.export_widget_container = QWidget()
        self.export_widget_container.setLayout(QVBoxLayout())
        self.export_widget_container.layout().setContentsMargins(
            0, 0, 0, 0
        )  # Left, Top, Right, Bottom margins
        self.export_widget_container.setMaximumHeight(220)
        self.main_widget.layout().addWidget(self.export_widget_container)

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
        self.button_save_tx = add_to_buttonbox(self.buttonBox, "Save", "sd-card.svg")
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
            "send.svg",
            on_clicked=lambda: self.broadcast(),
            role=QDialogButtonBox.ButtonRole.AcceptRole,
        )

        self.main_widget.layout().addWidget(self.buttonBox)
        ##################

        self.button_save_tx.setVisible(False)
        self.button_send.setVisible(self.data.data_type == DataType.Tx)

        self.updateUi()
        self.reload()
        self.utxo_list.update()
        self.signals.finished_open_wallet.connect(self.reload)
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self):
        self.tabs_inputs_outputs.setTabText(
            self.tabs_inputs_outputs.indexOf(self.tab_inputs), self.tr("Inputs")
        )
        self.tabs_inputs_outputs.setTabText(
            self.tabs_inputs_outputs.indexOf(self.tab_outputs), self.tr("Recipients")
        )
        self.button_edit_tx.setText(self.tr("Edit"))
        self.button_rbf.setText(self.tr("Edit with increased fee (RBF)"))
        self.button_previous.setText(self.tr("Previous step"))
        self.button_next.setText(self.tr("Next step"))
        self.button_send.setText(self.tr("Send"))
        self.button_send.setToolTip("Broadcasts the transaction to the bitcoin network.")

    def extract_tx(self) -> bdk.Transaction:
        assert self.data.data_type in [DataType.Tx, DataType.PSBT]
        if self.data.data_type == DataType.Tx:
            return self.data.data
        if self.data.data_type == DataType.PSBT:
            assert isinstance(self.data.data, bdk.PartiallySignedTransaction)
            return self.data.data.extract_tx()

    def go_to_next_index(self):
        if self.tx_singning_steps:
            self.tx_singning_steps.go_to_next_index()

    def go_to_previous_index(self):
        if self.tx_singning_steps:
            self.tx_singning_steps.go_to_previous_index()

    def serialize(self) -> str:
        return self.data.data_as_string()

    def edit(self):

        txinfos = ToolsTxUiInfo.from_tx(
            self.extract_tx(), self.fee_info, self.network, get_wallets(self.signals)
        )

        self.signals.open_tx_like.emit(txinfos)

    def reload(self):
        if self.data.data_type == DataType.PSBT:

            # check if the tx can be finalized and then open the final tx:
            finalized_tx = PSBTFinalizer.finalize(self.data.data)
            if finalized_tx:
                assert (
                    finalized_tx.txid() == self.data.data.txid()
                ), "bitcoin_tx libary error. The txid should not be changed during finalizing"
                self.set_tx(
                    finalized_tx,
                    fee_info=self.fee_info,
                    confirmation_time=self.confirmation_time,
                )
                return

            self.set_psbt(self.data.data, fee_info=self.fee_info)
        elif self.data.data_type == DataType.Tx:
            self.set_tx(
                self.data.data,
                fee_info=self.fee_info,
                confirmation_time=self.confirmation_time,
            )

    def txid(self) -> str:
        return self.extract_tx().txid()

    def broadcast(self):
        if not self.data.data_type == DataType.Tx:
            return
        assert isinstance(self.data.data, bdk.Transaction)
        tx = self.data.data

        logger.debug(f"broadcasting {serialized_to_hex( self.data.data.serialize())}")
        if self.blockchain:
            try:
                self.blockchain.broadcast(tx)
                self.signals.signal_broadcast_tx.emit(tx)
            except Exception as e:
                caught_exception_message(
                    e,
                    title=self.tr("Invalid Signatures")
                    if "non-mandatory-script-verify-flag" in str(e)
                    else None,
                )
        else:
            logger.error("No blockchain set")

    def enrich_simple_psbt_with_wallet_data(self, simple_psbt: SimplePSBT) -> SimplePSBT:
        def get_wallet_of_outpoint(outpoint: bdk.OutPoint) -> Optional[Wallet]:
            for wallet in get_wallets(self.signals):
                python_utxo = wallet.utxo_of_outpoint(outpoint)
                if python_utxo:
                    return wallet
            return None

        def get_keystore(fingerprint: str, keystores: List[KeyStore]) -> Optional[KeyStore]:
            for keystore in keystores:
                if keystore.fingerprint == fingerprint:
                    return keystore
            return None

        # collect all wallets that have input utxos
        inputs: List[bdk.TxIn] = self.extract_tx().input()

        # fill fingerprints, if not available
        for this_input, simple_input in zip(inputs, simple_psbt.inputs):
            wallet = get_wallet_of_outpoint(this_input.previous_output)
            if not wallet:
                continue

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

    def get_signature_importers_for_each_signers(
        self, psbt: bdk.PartiallySignedTransaction
    ) -> Dict[str, List[AbstractSignatureImporter]]:
        signature_importers: Dict[str, List[AbstractSignatureImporter]] = {}

        def get_signing_fingerprints_of_wallet(wallet: Wallet):
            # check which keys the wallet can sign

            wallet_signing_fingerprints = set(
                [keystore.fingerprint if keystore.mnemonic else None for keystore in wallet.keystores]
            ) - set([None])
            return wallet_signing_fingerprints

        def get_wallets_with_seed(fingerprint: str) -> List[Wallet]:
            result = []
            for wallet in wallets:
                signing_fingerprints_of_wallet = get_signing_fingerprints_of_wallet(wallet)
                if fingerprint in signing_fingerprints_of_wallet:
                    result.append(wallet)
            return result

        simple_psbt = SimplePSBT.from_psbt(psbt)
        simple_psbt = self.enrich_simple_psbt_with_wallet_data(simple_psbt)

        wallets: List[Wallet] = get_wallets(self.signals)

        # {bool_signed: [fingerprint0, .....]}
        shown_fingerprints: Dict[bool, List[str]] = {True: [], False: []}
        for input in simple_psbt.inputs:
            for pubkey in input.pubkeys:
                has_signature = input.fingerprint_has_signature(pubkey.fingerprint)
                if pubkey.fingerprint in shown_fingerprints[has_signature]:
                    # no need to add the same signer multiple times  (which will happen for multiple input utxos)
                    continue
                shown_fingerprints[has_signature].append(pubkey.fingerprint)

                # sets signature_importers[fingerprint] = []  if key doesn't exists
                l = signature_importers.setdefault(pubkey.fingerprint, [])

                # check if any wallet has keys for this fingerprint
                wallets_with_seed = get_wallets_with_seed(pubkey.fingerprint)
                if wallets_with_seed:
                    l.append(
                        SignatureImporterWallet(
                            wallets_with_seed[0],
                            self.network,
                            signature_available=has_signature,
                            key_label=pubkey.label,
                        )
                    )

                # always offer the qr option
                l.append(
                    SignatureImporterQR(
                        self.network,
                        blockchain=self.blockchain,
                        signature_available=has_signature,
                        key_label=pubkey.label,
                    )
                )

                # always offer the file option
                l.append(
                    SignatureImporterFile(
                        self.network,
                        blockchain=self.blockchain,
                        signature_available=has_signature,
                        key_label=pubkey.label,
                    )
                )
                # always offer the usb option
                l.append(
                    SignatureImporterUSB(
                        self.network,
                        blockchain=self.blockchain,
                        signature_available=has_signature,
                        key_label=pubkey.label,
                    )
                )
        return signature_importers

    def get_wallet_inputs(self, simple_psbt: SimplePSBT) -> Dict[str, List[SimpleInput]]:
        "structures the inputs into categories, usually wallet_ids, such that all the inputs are sure to belong to 1 wallet"
        wallet_inputs: Dict[str, List[SimpleInput]] = {}
        for i, inp in enumerate(simple_psbt.inputs):

            if inp.wallet_id and inp.m_of_n:
                id = inp.wallet_id
            elif inp.pubkeys:
                id = ", ".join(
                    [(pubkey.fingerprint if pubkey.fingerprint else pubkey.pubkey) for pubkey in inp.pubkeys]
                )
            else:
                id = f"Input {i}"

            l = wallet_inputs.setdefault(id, [])
            l.append(inp)

        return wallet_inputs

    def get_combined_signature_importers(
        self, psbt: bdk.PartiallySignedTransaction
    ) -> Dict[str, List[AbstractSignatureImporter]]:
        signature_importers: Dict[str, List[AbstractSignatureImporter]] = {}

        def get_signing_fingerprints_of_wallet(wallet: Wallet) -> Set[str]:
            # check which keys the wallet can sign

            wallet_signing_fingerprints = set(
                [keystore.fingerprint if keystore.mnemonic else None for keystore in wallet.keystores]
            ) - set([None])
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
                            blockchain=self.blockchain,
                            signature_available=True,
                            key_label=pubkeys_with_signature[i].fingerprint,
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
                                blockchain=self.blockchain,
                                signature_available=False,
                                key_label=wallet_id,
                                pub_keys_without_signature=pub_keys_without_signature,
                            )
                        )
        # connect signals
        for importers in signature_importers.values():
            for importer in importers:
                importer.signal_signature_added.connect(self.signature_added)
                importer.signal_final_tx_received.connect(self.tx_received)
        return signature_importers

    def update_tx_progress(self) -> Optional[TxSigningSteps]:
        if self.data.data_type != DataType.PSBT:
            return None
        assert isinstance(self.data.data, bdk.PartiallySignedTransaction)

        # this approach to clearning the layout
        # and then recreating the ui object is prone
        # to problems with multithreading.
        clear_layout(self.tx_singning_steps_container.layout())

        signature_importers = self.get_combined_signature_importers(self.data.data)

        tx_singning_steps = TxSigningSteps(
            signature_importer_dict=signature_importers,
            psbt=self.data.data,
            network=self.network,
            signals=self.signals,
        )

        self.tx_singning_steps_container.layout().addWidget(tx_singning_steps)
        return tx_singning_steps

    def create_tx_export(self) -> ExportDataSimple:

        # this approach to clearning the layout
        # and then recreating the ui object is prone
        # to problems with multithreading.
        clear_layout(self.tx_singning_steps_container.layout())

        widget = ExportDataSimple(
            data=self.data,
            sync_tabs={
                wallet_id: qt_wallet.sync_tab
                for wallet_id, qt_wallet in self.signals.get_qt_wallets().items()
            },
            signals_min=self.signals,
        )

        widget.qr_label.set_always_animate(False)
        self.export_widget_container.layout().addWidget(widget)
        return widget

    def tx_received(self, tx: bdk.Transaction):

        if self.data.data_type != DataType.PSBT:
            return
        assert isinstance(self.data.data, bdk.PartiallySignedTransaction)

        if self.data.data and tx.txid() != self.data.data.txid():
            Message(
                self.tr("The txid of the signed psbt doesnt match the original txid"), type=MessageType.Error
            )
            return

        self.set_tx(
            tx,
            fee_info=FeeInfo(
                self.data.data.fee_amount(),
                self.data.data.extract_tx().weight() / 4,
            ),
        )

    def _get_total_output_amount(self, simple_psbt: SimplePSBT):
        total_output_amount = sum([output.value for output in simple_psbt.outputs])
        return total_output_amount

    def signature_added(self, psbt_with_signatures: bdk.PartiallySignedTransaction):
        simple_psbt = SimplePSBT.from_psbt(psbt_with_signatures)

        if all([inp.is_fully_signed() for inp in simple_psbt.inputs]):
            self.set_tx(
                psbt_with_signatures.extract_tx(),
                fee_info=FeeInfo(
                    psbt_with_signatures.fee_amount(),
                    psbt_with_signatures.extract_tx().weight() / 4,
                ),
                sent_amount=self._get_total_output_amount(simple_psbt),
            )
        else:
            self.set_psbt(
                psbt_with_signatures,
                fee_info=FeeInfo(
                    psbt_with_signatures.fee_amount(),
                    psbt_with_signatures.extract_tx().weight() / 4,
                ),
            )

    def is_in_mempool(self, txid: str):
        # TODO: Currently in mempool and is in wallet is the same thing. In the future I have to differentiate here
        wallets = get_wallets(self.signals)
        for wallet in wallets:
            if wallet.is_in_mempool(txid):
                return True
        return False

    def set_tx(
        self,
        tx: bdk.Transaction,
        fee_info: FeeInfo = None,
        confirmation_time: bdk.BlockTime = None,
        sent_amount: int = None,
    ):
        self.data = Data(tx, DataType.Tx)
        self.fee_info = fee_info

        if fee_info is not None:
            self.fee_group.set_fee_rate(
                fee_rate=fee_info.fee_rate(),
                url=block_explorer_URL(self.config.network_config.mempool_url, "tx", tx.txid()),
                confirmation_time=confirmation_time,
                chain_height=self.blockchain.get_height() if self.blockchain else None,
            )
            # calcualte the fee warning. However since in a tx I don't know what is a change address,
            # it is not possible to give  fee warning for the sent (vs. change) amount
            sent_amount = sent_amount if sent_amount else sum([txout.value for txout in tx.output()])
            self.fee_group.set_fee_to_send_ratio(
                fee_info.fee_amount,
                sent_amount,
                self.config.network,
                fee_is_exact=True,
            )
            self.fee_group.set_vsize(fee_info.vsize)

            self.fee_group.approximate_fee_label.setVisible(fee_info.is_estimated)
            self.fee_group.approximate_fee_label.setToolTip(
                f'<html><body>The {"approximate " if fee_info.is_estimated else "" }fee is {Satoshis( fee_info.fee_amount, self.network).str_with_unit()}</body></html>'
            )

        outputs: List[bdk.TxOut] = tx.output()

        self.recipients.recipients = [
            Recipient(
                address=robust_address_str_from_script(output.script_pubkey, self.network),
                amount=output.value,
            )
            for output in outputs
        ]
        self.set_visibility(confirmation_time)
        self.create_tx_export()

    def set_visibility(self, confirmation_time: bdk.BlockTime = None):
        if self.data.data_type == DataType.PSBT:
            self.export_widget_container.setVisible(False)
            self.tx_singning_steps_container.setVisible(True)
        else:
            self.export_widget_container.setVisible(True)
            self.tx_singning_steps_container.setVisible(False)

        tx_status = TxStatus(
            self.extract_tx(),
            confirmation_time,
            self.mempool_data.fetch_block_tip_height,
            self.is_in_mempool(self.extract_tx().txid()),
        )

        show_send = bool(tx_status.can_do_initial_broadcast() and self.data.data_type == DataType.Tx)
        self.button_send.setVisible(show_send)
        self.button_next.setVisible(self.data.data_type == DataType.PSBT)
        self.button_previous.setVisible(self.data.data_type == DataType.PSBT)
        # if is_unconfirmed then it makes sense to also edit it before
        self.button_save_tx.setHidden(True)

        self.button_edit_tx.setVisible(tx_status.is_unconfirmed() and not tx_status.can_rbf())
        self.button_rbf.setVisible(tx_status.can_rbf())

    def set_psbt(self, psbt: bdk.PartiallySignedTransaction, fee_info: FeeInfo = None):
        """_summary_

        Args:
            psbt (bdk.PartiallySignedTransaction): _description_
            fee_rate (_type_, optional): This is the exact fee_rate chosen in txbuilder. If not given it has
                                        to be estimated with estimate_segwit_tx_size_from_psbt.
        """
        self.data = Data(psbt, DataType.PSBT)
        self.fee_info = fee_info

        # if fee_rate is set, it means the
        if fee_info is None:
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(psbt)
        self.fee_group.approximate_fee_label.setVisible(fee_info.is_estimated)
        self.fee_group.approximate_fee_label.setToolTip(
            f'<html><body>The {"approximate " if fee_info.is_estimated else "" }fee is {Satoshis( fee_info.fee_amount, self.network).str_with_unit()} Sat</body></html>'
        )

        self.fee_group.set_fee_rate(
            fee_rate=fee_info.fee_rate(),
        )

        outputs: List[bdk.TxOut] = psbt.extract_tx().output()

        # set fee warning
        self.fee_group.set_fee_to_send_ratio(
            psbt.fee_amount(),
            total_output_amount=self._get_total_output_amount(SimplePSBT.from_psbt(psbt)),
            network=self.network,
        )

        self.recipients.recipients = [
            Recipient(
                address=bdk.Address.from_script(output.script_pubkey, self.network).as_string(),
                amount=output.value,
            )
            for output in outputs
        ]

        self.tx_singning_steps = self.update_tx_progress()
        self.set_visibility(None)


class UITx_Creator(UITx_Base):
    signal_create_tx = pyqtSignal(TxUiInfos)

    def __init__(
        self,
        wallet: Wallet,
        mempool_data: MempoolData,
        fx: FX,
        categories: List[str],
        widget_utxo_with_toolbar: UtxoListWithToolbar,
        utxo_list: UTXOList,
        config: UserConfig,
        signals: Signals,
    ) -> None:
        super().__init__(config=config, signals=signals, mempool_data=mempool_data)
        self.wallet = wallet
        self.categories = categories
        self.utxo_list = utxo_list
        self.widget_utxo_with_toolbar = widget_utxo_with_toolbar

        self.additional_outpoints: List[OutPoint] = []
        utxo_list.get_outpoints = self.get_outpoints

        self.main_widget = SearchableTab()
        self.main_widget.searchable_list = utxo_list
        self.main_widget.setLayout(QVBoxLayout())

        self.outer_widget_sub = QWidget()
        self.outer_widget_sub.setLayout(QHBoxLayout())
        self.outer_widget_sub.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins
        self.main_widget.layout().addWidget(self.outer_widget_sub)

        self.splitter = QSplitter()
        self.outer_widget_sub.layout().addWidget(self.splitter)
        self.create_inputs_selector(self.splitter)

        self.widget_right_hand_side = QWidget()
        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)
        self.widget_right_hand_side_layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.widget_right_top = QWidget(self.main_widget)
        self.widget_right_top.setLayout(QHBoxLayout())
        self.widget_right_top.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.widget_middle = QWidget(self.main_widget)
        self.widget_middle.setLayout(QVBoxLayout())
        self.widget_right_top.layout().addWidget(self.widget_middle)

        self.balance_label = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.balance_label.setFont(font)

        self.widget_middle.layout().addWidget(self.balance_label)

        self.recipients: Recipients = self.create_recipients(self.widget_middle.layout())

        self.recipients.signal_clicked_send_max_button.connect(self.updateUi)
        self.recipients.add_recipient()

        self.fee_group = FeeGroup(mempool_data, fx, self.widget_right_top.layout(), self.config)
        self.signals.language_switch.connect(self.fee_group.updateUi)
        self.fee_group.signal_set_fee_rate.connect(self.updateUi)

        self.widget_right_hand_side_layout.addWidget(self.widget_right_top)

        self.button_box = QDialogButtonBox()
        self.button_ok = self.button_box.addButton(QDialogButtonBox.StandardButton.Ok)
        self.button_ok.setDefault(True)
        self.button_clear = self.button_box.addButton(QDialogButtonBox.StandardButton.Reset)
        self.main_widget.layout().addWidget(self.button_box)
        self.button_ok.clicked.connect(lambda: self.create_tx())
        self.button_clear.clicked.connect(lambda: self.clear_ui())

        self.splitter.addWidget(self.widget_right_hand_side)

        self.updateUi()
        self.tab_changed(0)

        # signals
        self.tabs_inputs.currentChanged.connect(self.tab_changed)
        self.mempool_data.signal_data_updated.connect(self.update_fee_rate_to_mempool)
        self.utxo_list.on_selection_changed.connect(self.updateUi)
        self.recipients.signal_amount_changed.connect(self.updateUi)
        self.recipients.signal_added_recipient.connect(self.updateUi)
        self.recipients.signal_removed_recipient.connect(self.updateUi)
        self.category_list.signal_tag_clicked.connect(self.updateUi)
        self.signals.utxos_updated.connect(self.updateUi)  # for the balance
        self.signals.language_switch.connect(self.updateUi)

    def updateUi(self):
        # translations
        self.label_select_input_categories.setText(self.tr("Select a category that fits the recipient best"))
        self.checkBox_reduce_future_fees.setText(self.tr("Reduce future fees\nby merging address balances"))
        self.tabs_inputs.setTabText(
            self.tabs_inputs.indexOf(self.tab_inputs_categories), self.tr("Send Category")
        )
        self.tabs_inputs.setTabText(self.tabs_inputs.indexOf(self.tab_inputs_utxos), self.tr("Advanced"))
        self.button_add_utxo.setText(self.tr("Add foreign UTXOs"))

        # infos and warnings
        fee_rate = self.fee_group.spin_fee_rate.value()

        # non-output dependent  values
        opportunistic_merging_threshold = self.opportunistic_merging_threshold()
        self.checkBox_reduce_future_fees.setChecked(fee_rate <= opportunistic_merging_threshold)
        self.checkBox_reduce_future_fees.setToolTip(
            self.tr("This checkbox automatically checks \nbelow {rate}").format(
                rate=format_fee_rate(opportunistic_merging_threshold, self.config.network)
            )
        )

        # set max values
        self.reapply_max_amounts()

        # update fee infos (dependent on output amounts)
        sent_values = [r.amount for r in self.recipients.recipients]

        fee_info = self.estimate_fee_info(fee_rate)
        self.fee_group.set_vsize(fee_info.vsize)
        if bool(sum(sent_values)):

            self.fee_group.set_fee_to_send_ratio(
                fee_info.fee_amount,
                sum(sent_values),
                self.config.network,
            )

        # balance label
        self.balance_label.setText(self.wallet.get_balance().format_short(network=self.config.network))

    def reset_fee_rate(self):
        self.fee_group.set_fee_rate(self.mempool_data.get_prio_fee_rates()[TxPrio.low])

    def clear_ui(self):
        self.additional_outpoints.clear()
        self.set_ui(TxUiInfos())
        self.tabs_inputs.setCurrentIndex(0)
        self.reset_fee_rate()
        self.utxo_list.update()

    def create_tx(self):
        if (
            self.tabs_inputs.currentWidget() == self.tab_inputs_categories
            and not self.category_list.get_selected()
        ):
            Message(
                self.tr("Please select an input category on the left, that fits the transaction recipients.")
            )
            return
        self.signal_create_tx.emit(self.get_ui_tx_infos())

    def update_fee_rate_to_mempool(self):
        "Do this only ONCE after the mempool data is fetched"
        if self.fee_group.spin_fee_rate.value() == MIN_RELAY_FEE:
            self.reset_fee_rate()
        self.mempool_data.signal_data_updated.disconnect(self.update_fee_rate_to_mempool)

    def get_outpoints(self) -> List[OutPoint]:
        return [
            utxo.outpoint for utxo in self.wallet.get_all_txos() if not utxo.is_spent_by_txid
        ] + self.additional_outpoints

    def _get_category_python_utxo_dict(self) -> Dict[str, List[PythonUtxo]]:
        category_python_utxo_dict: Dict[str, List[PythonUtxo]] = {}
        for outpoint in self.get_outpoints():
            python_utxo = self.wallet.get_python_utxo(str(outpoint))
            if not python_utxo:
                continue

            category = self.wallet.labels.get_category(python_utxo.address)
            if not category:
                continue
            if category not in category_python_utxo_dict:
                category_python_utxo_dict[category] = []
            category_python_utxo_dict[category].append(python_utxo)
        return category_python_utxo_dict

    def _get_sub_texts_for_uitx(self) -> List[str]:
        category_python_utxo_dict = self._get_category_python_utxo_dict()

        return [
            self.tr("{num_inputs} Inputs: {inputs}").format(
                num_inputs=len(category_python_utxo_dict.get(category, [])),
                inputs=Satoshis(
                    python_utxo_balance(category_python_utxo_dict.get(category, [])), self.wallet.network
                ).str_with_unit(),
            )
            for category in self.wallet.labels.categories
        ]

    def create_inputs_selector(self, layout: QLayout):

        self.tabs_inputs = QTabWidget(self.main_widget)
        self.tabs_inputs.setMinimumWidth(200)
        self.tab_inputs_categories = QWidget(self.main_widget)
        self.tabs_inputs.addTab(self.tab_inputs_categories, "")

        # tab categories
        self.verticalLayout_inputs = QVBoxLayout(self.tab_inputs_categories)
        self.label_select_input_categories = QLabel()
        self.label_select_input_categories.setWordWrap(True)
        self.checkBox_reduce_future_fees = QCheckBox(self.tab_inputs_categories)
        self.checkBox_reduce_future_fees.setChecked(True)

        # Taglist
        self.category_list = CategoryList(
            self.categories, self.signals, self._get_sub_texts_for_uitx, immediate_release=False
        )
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox_reduce_future_fees)

        # tab utxos
        self.tab_inputs_utxos = QWidget(self.main_widget)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, "")

        self.verticalLayout_inputs_utxos.addWidget(self.widget_utxo_with_toolbar)

        # utxo list
        self.button_add_utxo = QPushButton()
        if hasattr(bdk.TxBuilder(), "add_foreign_utxo"):
            self.button_add_utxo.clicked.connect(self.click_add_utxo)
            self.verticalLayout_inputs_utxos.addWidget(self.button_add_utxo)

        # nLocktime
        self.nlocktime_picker = nLocktimePicker()
        # TODO actiavte this as soon as https://docs.rs/bdk/latest/bdk/wallet/tx_builder/struct.TxBuilder.html#method.nlocktime is exposed in ffi
        self.nlocktime_picker.setHidden(True)
        self.verticalLayout_inputs_utxos.addWidget(self.nlocktime_picker)

        layout.addWidget(self.tabs_inputs)

        # select the first one with !=0 balance
        # TODO:  this doesnt work however, because the wallet sync happens after this creation
        category_utxo_dict = self._get_category_python_utxo_dict()

        def get_idx_non_zero_category() -> Optional[int]:
            for i, category in enumerate(self.category_list.categories):
                if python_utxo_balance(category_utxo_dict.get(category, [])) > 0:
                    return i
            return None

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
            outpoints = [OutPoint.from_str(row.strip()) for row in s.strip().split("\n")]
            logger.debug(self.tr("Adding outpoints {outpoints}").format(outpoints=outpoints))
            self.add_outpoints(outpoints)
            self.utxo_list.update()
            self.utxo_list.select_rows(outpoints, self.utxo_list.key_column, self.utxo_list.ROLE_KEY)

        ImportDialog(
            self.config.network,
            on_open=process_input,
            window_title=self.tr("Add Inputs"),
            text_button_ok=self.tr("Load UTXOs"),
            text_instruction_label=self.tr(
                "Please paste UTXO here in the format  txid:outpoint\ntxid:outpoint"
            ),
            text_placeholder=self.tr("Please paste UTXO here"),
        ).show()

    def opportunistic_merging_threshold(self) -> float:
        return self.wallet.get_ema_fee_rate()

    def estimate_fee_info(self, fee_rate: float = None):
        sent_values = [r.amount for r in self.recipients.recipients]
        # one more output for the change
        num_outputs = len(sent_values) + 1
        if fee_rate is None:
            fee_rate = self.fee_group.spin_fee_rate.value()

        txinfos = self.get_ui_tx_infos()

        utxos_for_input = UtxosForInputs(
            list(txinfos.utxo_dict.values()), spend_all_utxos=txinfos.spend_all_utxos
        )

        num_inputs = max(1, len(utxos_for_input.utxos))  # assume all inputs come from this wallet
        fee_info = FeeInfo.estimate_from_num_inputs(
            fee_rate,
            input_mn_tuples=[self.wallet.get_mn_tuple() for i in range(num_inputs)],
            num_outputs=num_outputs,
        )
        return fee_info

    def get_ui_tx_infos(self, use_this_tab=None) -> TxUiInfos:
        infos = TxUiInfos()
        infos.opportunistic_merge_utxos = self.checkBox_reduce_future_fees.isChecked()

        for recipient in self.recipients.recipients:
            infos.add_recipient(recipient)

        # logger.debug(
        #     f"set psbt builder fee_rate {self.fee_group.spin_fee_rate.value()}"
        # )
        infos.set_fee_rate(self.fee_group.spin_fee_rate.value())

        if not use_this_tab:
            use_this_tab = self.tabs_inputs.currentWidget()

        wallets = [self.wallet] if use_this_tab == self.tab_inputs_categories else get_wallets(self.signals)

        if use_this_tab == self.tab_inputs_categories:
            ToolsTxUiInfo.fill_utxo_dict_from_categories(infos, self.category_list.get_selected(), wallets)

        if use_this_tab == self.tab_inputs_utxos:
            ToolsTxUiInfo.fill_utxo_dict_from_outpoints(
                infos, self.utxo_list.get_selected_outpoints(), wallets
            )
            infos.spend_all_utxos = True

        return infos

    def reapply_max_amounts(self):
        recipient_group_boxes = self.recipients.get_recipient_group_boxes()
        for recipient_group_box in recipient_group_boxes:
            recipient_group_box.amount_spin_box.setMaximum(self.get_total_input_value())

        recipient_group_boxes_max_checked = [
            recipient_group_box
            for recipient_group_box in recipient_group_boxes
            if recipient_group_box.send_max_button.isChecked()
        ]
        total_change_amount = self.get_total_change_amount(include_max_checked=False)
        for recipient_group_box in recipient_group_boxes_max_checked:
            self.set_max_amount(
                recipient_group_box, total_change_amount // len(recipient_group_boxes_max_checked)
            )

    def get_total_input_value(self) -> int:
        txinfos = self.get_ui_tx_infos()
        total_input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo])
        return total_input_value

    def get_total_change_amount(self, include_max_checked=False) -> int:
        txinfos = self.get_ui_tx_infos()
        total_input_value = sum([utxo.txout.value for utxo in txinfos.utxo_dict.values() if utxo])

        total_output_value = sum(
            [
                recipient.amount
                for recipient in txinfos.recipients
                if (recipient.checked_max_amount and include_max_checked) or not recipient.checked_max_amount
            ]
        )  # this includes the old value of the spinbox

        total_change_amount = total_input_value - total_output_value
        return total_change_amount

    def set_max_amount(self, recipient_group_box: RecipientGroupBox, max_amount: int):
        with BlockChangesSignals([recipient_group_box]):

            recipient_group_box.amount_spin_box.setValue(max_amount)

    def tab_changed(self, index: int):
        # pyqtSlot called when the current tab changes
        # print(f"Tab changed to index {index}")

        if index == 0:
            self.splitter.setSizes([200, 600])
        elif index == 1:
            self.splitter.setSizes([400, 600])

            # take the coin selection from the category to the utxo tab (but only if one is selected)
            self.set_coin_selection_in_sent_tab(self.get_ui_tx_infos(self.tab_inputs_categories))

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
                    index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
                )
            else:
                selection.select(
                    index, QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows
                )

    def set_ui(self, txinfos: TxUiInfos):
        self.recipients.recipients = txinfos.recipients
        if not self.recipients.recipients:
            self.recipients.add_recipient()

        ##################
        # detect and handle rbf
        conflicting_python_utxos = self.wallet.get_conflicting_python_utxos(
            [OutPoint.from_str(s) for s in txinfos.utxo_dict.keys()]
        )

        conflicting_txids = [
            conflicting_python_utxo.is_spent_by_txid for conflicting_python_utxo in conflicting_python_utxos
        ]
        confirmation_times = [
            self.wallet.get_tx(conflicting_txid).confirmation_time for conflicting_txid in conflicting_txids
        ]

        conflicting_confirmed = set(
            [
                conflicting_python_utxo
                for conflicting_python_utxo, confirmation_time in zip(
                    conflicting_python_utxos, confirmation_times
                )
                if confirmation_time
            ]
        )
        if conflicting_confirmed:
            Message(
                self.tr("The inputs {inputs} conflict with these confirmed txids {txids}.").format(
                    inputs=[utxo.outpoint for utxo in conflicting_confirmed],
                    txids=[utxo.is_spent_by_txid for utxo in conflicting_confirmed],
                )
            )
        conflicted_unconfirmed = set(conflicting_python_utxos) - conflicting_confirmed
        if conflicted_unconfirmed:
            # RBF is going on
            # these involved txs i can do rbf

            # for each conflicted_unconfirmed, get all roots and dependents
            dependents_to_be_replaced: List[bdk.TransactionDetails] = []
            for utxo in conflicted_unconfirmed:
                if utxo.is_spent_by_txid:
                    dependents_to_be_replaced += [
                        fulltx.tx
                        for fulltx in self.wallet.get_fulltxdetail_and_dependents(
                            utxo.is_spent_by_txid, include_root_tx=False
                        )
                    ]
            if dependents_to_be_replaced:
                Message(
                    self.tr(
                        "The unconfirmed dependent transactions {txids} will be removed by this new transaction you are creating."
                    ).format(txids=[dependent.txid for dependent in dependents_to_be_replaced])
                )

            # for each conflicted_unconfirmed, get all roots and dependents
            txs_to_be_replaced = []
            for utxo in conflicted_unconfirmed:
                if utxo.is_spent_by_txid:
                    txs_to_be_replaced += [
                        fulltx.tx
                        for fulltx in self.wallet.get_fulltxdetail_and_dependents(utxo.is_spent_by_txid)
                    ]

            fee_amount = sum([tx_details.fee for tx_details in txs_to_be_replaced])

            builder_infos = self.wallet.create_psbt(txinfos)
            fee_info = FeeInfo.estimate_segwit_fee_rate_from_psbt(builder_infos.builder_result.psbt)

            txinfos.fee_rate = calc_minimum_rbf_fee_info(
                fee_amount, fee_info.vsize, self.mempool_data
            ).fee_rate()

            self.fee_group.set_rbf_label(txinfos.fee_rate)
            self.fee_group.set_vsize(fee_info.vsize)

            for python_utxo in txinfos.utxo_dict.values():
                if python_utxo.outpoint not in self.get_outpoints():
                    self.additional_outpoints.append(python_utxo.outpoint)
        else:
            self.fee_group.set_rbf_label(None)

        if txinfos.fee_rate:
            self.fee_group.set_fee_rate(txinfos.fee_rate)

        self.utxo_list.update()
        self.tabs_inputs.setCurrentWidget(self.tab_inputs_utxos)
        self.utxo_list.select_rows(
            txinfos.utxo_dict.keys(),
            self.utxo_list.key_column,
            self.utxo_list.ROLE_KEY,
        )
