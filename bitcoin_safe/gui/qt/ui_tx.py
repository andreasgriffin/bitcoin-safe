import logging
logger = logging.getLogger(__name__)

from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from .category_list import CategoryList
from .recipients import Recipients
from .slider import CustomSlider
from ...signals import  Signal
import bdkpython as bdk
from typing import List, Dict
from .utxo_list import UTXOList
from ...tx import TXInfos
from ...signals import Signals
from .barchart import MempoolBarChart
from ...mempool import get_prio_fees, fee_to_color, fee_to_depth
from ...wallets import Wallets
from PySide2.QtGui import QPixmap, QImage
from ...qr import create_psbt_qr
from PIL import Image
from PIL.ImageQt import ImageQt
from ...keystore import KeyStore
from .util import read_QIcon
from .keystore_ui import SignerUI
from ...signer import SignerWallet

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


def create_recipients(layout, get_receiving_addresses,  get_change_addresses, parent=None, allow_edit=True):
    recipients =  Recipients(get_receiving_addresses, get_change_addresses, allow_edit=allow_edit)
    recipients.add_recipient()
    layout.addWidget(recipients)
    recipients.setMinimumWidth(250)    
    
    return recipients




class QRLabel(QLabel):
    def __init__(self, *args, width=200, clickable=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.setScaledContents(True)  # Enable automatic scaling
        self.pil_image = None     
        self.enlarged_image  = None   

    def enlarge_image(self):
        if not self.enlarged_image:
            return

        if self.enlarged_image.isVisible():
            self.enlarged_image.close()
        else:
            self.enlarged_image.show()

    def mousePressEvent(self, event):
        self.enlarge_image()

    def set_image(self, pil_image):
        self.pil_image = pil_image
        self.enlarged_image = EnlargedImage(self.pil_image)
        qpix = QPixmap.fromImage(ImageQt(self.pil_image))
        self.setPixmap(qpix)


    def resizeEvent(self, event):
        size = min(self.width(), self.height())
        self.resize(size, size)

    def sizeHint(self):
        size = min(super().sizeHint().width(), super().sizeHint().height())
        return QSize(size, size)

    def minimumSizeHint(self):
        size = min(super().minimumSizeHint().width(), super().minimumSizeHint().height())
        return QSize(size, size)        
        

class EnlargedImage(QLabel):
    def __init__(self, image):
        super().__init__()
        self.setScaledContents(True)  # Enable automatic scaling

        self.setWindowFlags(Qt.FramelessWindowHint)
        screen_resolution = QApplication.desktop().screenGeometry()
        screen_fraction = 3/4
        self.width = self.height = min(screen_resolution.width() , screen_resolution.height() ) * screen_fraction
        self.setGeometry((screen_resolution.width() -self.width)/2, (screen_resolution.height() - self.height)/2, self.width, self.height)
    
        self.image = image
        qpix = QPixmap.fromImage(ImageQt(self.image))
        self.setPixmap(qpix)

    def mousePressEvent(self, event):
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

                

class ExportPSBT:
    def __init__(self, layout, allow_edit=False) -> None:
        self.psbt = None
        self.tabs = QTabWidget()
        self.tabs.setMaximumWidth(300)
        self.signal_export_psbt_to_file = Signal('signal_export_psbt_to_file')
        self.signal_export_psbt_to_file.connect(self.export_psbt)        

        # qr
        self.tab_qr = QWidget()
        self.tab_qr_layout = QHBoxLayout(self.tab_qr)
        self.tab_qr_layout.setAlignment(Qt.AlignVCenter)
        self.qr_label = QRLabel()
        self.tab_qr_layout.addWidget(self.qr_label)
        self.tabs.addTab(self.tab_qr, 'QR')
        
        # right side of qr
        self.tab_qr_right_side = QWidget()
        self.tab_qr_right_side_layout = QVBoxLayout(self.tab_qr_right_side)
        self.tab_qr_right_side_layout.setAlignment(Qt.AlignCenter)
        self.tab_qr_layout.addWidget(self.tab_qr_right_side)
        
        self.button_enlarge_qr = QToolButton()
        self.button_enlarge_qr.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_enlarge_qr.setText('Enlarge')
        self.button_enlarge_qr.setIcon(read_QIcon("zoom.png"))        
        self.button_enlarge_qr.setIconSize(QSize(30, 30))  # 24x24 pixels      
        self.button_enlarge_qr.clicked.connect(self.qr_label.enlarge_image)
        self.tab_qr_right_side_layout.addWidget(self.button_enlarge_qr)
        
        self.button_save_qr = QToolButton()
        self.button_save_qr.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_save_qr.setText('Save as image')
        self.button_save_qr.setIcon(read_QIcon("download.png"))        
        self.button_save_qr.setIconSize(QSize(30, 30))  # 24x24 pixels      
        self.button_save_qr.clicked.connect(self.export_qrcode)
        self.tab_qr_right_side_layout.addWidget(self.button_save_qr)
        
        
        

        # psbt
        self.tab_psbt = QWidget()
        self.tab_psbt_layout = QVBoxLayout(self.tab_psbt)
        self.edit_psbt = QTextEdit()
        if not allow_edit:
            self.edit_psbt.setReadOnly(True)
        self.tab_psbt_layout.addWidget(self.edit_psbt)
        self.tabs.addTab(self.tab_psbt, 'PSBT')

        # json
        self.tab_json = QWidget()
        self.tab_json_layout = QVBoxLayout(self.tab_json)
        self.edit_json = QTextEdit()
        if not allow_edit:
            self.edit_json.setReadOnly(True)
        self.tab_json_layout.addWidget(self.edit_json)
        self.tabs.addTab(self.tab_json, 'JSON')

        # file
        self.tab_file = QWidget()
        self.tab_file_layout = QVBoxLayout(self.tab_file)
        self.tab_file_layout.setAlignment(Qt.AlignHCenter)
        self.button_file = QToolButton()
        self.button_file.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.button_file.setText('Export PSBT file')
        self.button_file.setIcon(read_QIcon("download.png"))        
        self.button_file.setIconSize(QSize(30, 30))  # 24x24 pixels      
        self.button_file.clicked.connect(self.signal_export_psbt_to_file)        
        self.tab_file_layout.addWidget(self.button_file)
        self.tabs.addTab(self.tab_file, 'Export PSBT file')

        layout.addWidget(self.tabs)        
        
        
    def export_qrcode(self):
        filename = self.save_file_dialog(name_filters=["Image (*.png)", "All Files (*.*)"], default_suffix='png')
        if not filename:
            return        
        self.qr_label.pil_image.save(filename)
        
        
    def set_psbt(self, psbt:bdk.PartiallySignedTransaction):
        self.psbt:bdk.PartiallySignedTransaction = psbt
        self.edit_psbt.setText(psbt.serialize())
        json_text = psbt.json_serialize()
        import json
        json_text = json.dumps( json.loads(json_text), indent=4 )
        self.edit_json.setText(json_text)
        
        
        self.qr_label.set_image( create_psbt_qr(psbt)  )

        
        
    def export_psbt(self):
        filename = self.save_file_dialog(name_filters=["PSBT Files (*.psbt)", "All Files (*.*)"], default_suffix='psbt')
        if not filename:
            return
        
        with open(filename, 'w') as file:
            file.write(self.psbt.serialize())
    
    
    def save_file_dialog(self, name_filters=None, default_suffix='psbt'):
        options = QFileDialog.Options()
        # options |= QFileDialog.DontUseNativeDialog  # Use Qt-based dialog, not native platform dialog

        file_dialog = QFileDialog()
        file_dialog.setOptions(options)
        file_dialog.setWindowTitle("Save File")
        file_dialog.setAcceptMode(QFileDialog.AcceptSave)
        file_dialog.setDefaultSuffix(default_suffix)
        if name_filters:
            file_dialog.setNameFilters(name_filters)

        if file_dialog.exec_() == QFileDialog.Accepted:
            selected_file = file_dialog.selectedFiles()[0]
            # Do something with the selected file path, e.g., save data to the file
            logger.debug(f"Selected save file: {selected_file}")
            return selected_file


class FeeGroup:
    def __init__(self, layout, allow_edit=True) -> None:
        self.allow_edit = allow_edit
        
        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee.setTitle("Fee")
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.groupBox_Fee.setAlignment(Qt.AlignTop)
        layout_h_fee = QHBoxLayout(self.groupBox_Fee)                
        # layout_h_fee.setContentsMargins(0, layout.contentsMargins().top(), 0, layout.contentsMargins().bottom())  # Remove margins

        #  add the mempool bar on the left
        self.mempool = MempoolBarChart()
        if allow_edit:
            self.mempool.signal_click.connect(self.set_fee)
        self.mempool.set_data_from_file('data.csv')
        self.mempool.chart.setMaximumWidth(25)
        layout_h_fee.addWidget(self.mempool.chart)
        
        # and the rest on the right
        widget_right_hand_side_fees = QWidget(self.groupBox_Fee)
        widget_right_hand_side_fees_layout = QVBoxLayout(widget_right_hand_side_fees)                
        widget_right_hand_side_fees_layout.setContentsMargins(0, layout.contentsMargins().top(), 0, layout.contentsMargins().bottom())  # Remove margins
        widget_right_hand_side_fees_layout.setAlignment(Qt.AlignVCenter)
        layout_h_fee.addWidget(widget_right_hand_side_fees)
                
        self.spin_fee = QDoubleSpinBox()
        if not allow_edit:
            self.spin_fee.setReadOnly(True)
        self.spin_fee.setRange(0.0, 100.0)  # Set the acceptable range
        self.spin_fee.setSingleStep(1)  # Set the step size
        self.spin_fee.setDecimals(1)  # Set the number of decimal places
        self.spin_fee.editingFinished.connect(lambda: self._set_chart_fee(self.spin_fee.value()))
        self.mempool.signal_data_updated.connect(self.update_spin_fee)
                
        self.spin_fee.setMaximumWidth(45)
        widget_right_hand_side_fees_layout.addWidget(self.spin_fee)        

        spin_label = QLabel()
        spin_label.setText("sat/vB")
        widget_right_hand_side_fees_layout.addWidget(spin_label)        
            

        for fee, text in zip(get_prio_fees(self.mempool.data), ["High", "Mid", "Low"]):
            button = QPushButton()
            button.setStyleSheet("QPushButton { color: "+ fee_to_color(fee) +"; }")            
            button.setMaximumWidth(30)
            button.setText(text)
            def onclick(*args, value=fee):
                return self.spin_fee.setValue(value)
            button.clicked.connect(onclick)
            if allow_edit:
                widget_right_hand_side_fees_layout.addWidget(button)        


        layout.addWidget(self.groupBox_Fee)

    def _set_chart_fee(self, fee):
        self.mempool.chart.set_current_fee( fee_to_depth(self.mempool.data, fee), fee, color='black' )

            
    def set_fee(self, fee):
        self.spin_fee.setValue(fee)
        self._set_chart_fee(fee)
        
    def update_spin_fee(self):
        self.spin_fee.setRange(1, self.mempool.data[:,0].max())  # Set the acceptable range 
    



class UITX_Viewer():
    def __init__(self, psbt:bdk.PartiallySignedTransaction, wallets:Wallets, signals:Signals, network:bdk.Network) -> None:
        self.psbt:bdk.PartiallySignedTransaction = psbt
        self.wallets = wallets
        self.signals = signals
        self.network = network

        self.signers:List[SignerWallet] = []
        self.signal_edit_tx = Signal('signal_edit_tx')
        self.signal_save_psbt = Signal('signal_save_psbt')
        self.signal_broadcast_tx = Signal('signal_broadcast_tx')

        
        self.main_widget = QWidget()
        self.main_widget_layout = QVBoxLayout(self.main_widget)


        self.upper_widget = QWidget(self.main_widget)
        self.main_widget_layout.addWidget(self.upper_widget)
        self.upper_widget_layout = QHBoxLayout(self.upper_widget)
        
        # in out
        self.tabs_inputs_outputs = QTabWidget(self.main_widget)
        self.upper_widget_layout.addWidget(self.tabs_inputs_outputs)

        #
        self.tab_inputs = QWidget(self.main_widget)
        self.tab_inputs_layout = QVBoxLayout(self.tab_inputs)
        self.tabs_inputs_outputs.addTab(self.tab_inputs, 'Inputs')
        
        self.tab_outputs = QWidget(self.main_widget)
        self.tab_outputs_layout = QVBoxLayout(self.tab_outputs)
        self.tabs_inputs_outputs.addTab(self.tab_outputs, 'Outputs')        
        self.tabs_inputs_outputs.setCurrentWidget(self.tab_outputs)
        
        self.recipients = create_recipients(self.tab_outputs_layout, wallets.get_receiving_addresses_merged, wallets.get_change_addresses_merged, allow_edit=False)


        # fee
        self.fee_group = FeeGroup(self.upper_widget_layout, allow_edit=False)
        
        
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
        self.export_psbt = ExportPSBT(self.lower_widget_layout, allow_edit=False)
        
        

        # buttons
        (self.button_edit_tx,self.button_save_tx,self.button_broadcast_tx,) = create_button_bar(self.main_widget_layout, 
                                                                                                     button_texts=["Edit Transaction",
                                                                                                                   "Save Transaction",
                                                                                                                   "Broadcast Transaction"
                                                                                                                   ])
        self.button_broadcast_tx.setEnabled(False)
        self.button_broadcast_tx.clicked.connect(self.broadcast)
        self.set_psbt(psbt)
        
        
    def broadcast(self):
        self.signers[0].wallet.blockchain.broadcast(self.psbt.extract_tx())
        self.signal_broadcast_tx()


    def add_all_signer_tabs(self):
        # collect all wallets
        inputs:List[bdk.TxIn] = self.psbt.extract_tx().input()
        wallet_for_inputs = [self.wallets.wallet_of_outpoint( this_input.previous_output)   for this_input in inputs]
        if None in wallet_for_inputs:
            logger.warning(f'Cannot sign for all the inputs {wallet_for_inputs.index(None)} with the currently opened wallets')
        
        logger.debug(f'wallet_for_inputs {[w.id for w in wallet_for_inputs]}')
        
        signers = [] 
        for wallet in set(wallet_for_inputs): # removes all duplicate wallets
            for keystore in wallet.keystores:
                # TODO: once the bdk ffi has Signers (also hardware signers), I cann add here the signers
                # for now only mnemonic signers are supported
                # signers.append(SignerKeyStore(....))
                # signers.append(SignerHWI(....))
                pass
            signers.append(SignerWallet(wallet, self.network))
        self.signers = list(set(signers)) # removes all duplicate keystores

        logger.debug(f'signers {[k.label for k in signers]}')
        self.signeruis = []
        for signer in self.signers: 
            signerui = SignerUI(signer, self.psbt, self.tabs_signers, self.network)              
            signerui.signal_is_finalized.connect(self.signing_finalized)
            self.signeruis.append(signerui)
        

    def signing_finalized(self):
        print('endable')
        self.set_psbt(self.psbt)
        self.button_broadcast_tx.setEnabled(True)
        
        

    def set_psbt(self, psbt:bdk.PartiallySignedTransaction):
        self.psbt:bdk.PartiallySignedTransaction = psbt
        self.export_psbt.set_psbt(psbt)
        
        self.fee_group.set_fee(self.psbt.fee_rate().as_sat_per_vb())            
        
        outputs :List[bdk.TxOut] = psbt.extract_tx().output()
        
        
        def get_recipient_dict(i, output):
            address_str = bdk.Address.from_script(output.script_pubkey, self.network).as_string()
            d = {'amount':output.value, 'address':address_str} 
            
            wallet = self.wallets.wallet_of_address(address_str)
            if wallet:
                d['label'] = wallet.get_label_for_address(address_str)
            
            
            d['groupbox_title'] = f'Output {i+1} to wallet {wallet.id}' if wallet else f'Output {i+1}'
            return d
        
        self.recipients.recipients = [get_recipient_dict(i, output) for i, output in enumerate(outputs)]


class UITX_Creator():
    def __init__(self, categories:List[str], utxo_list:UTXOList, get_receiving_addresses, get_change_addresses, signals:Signals, get_sub_texts) -> None:
        self.categories = categories
        self.utxo_list = utxo_list
        self.signals = signals
        self.get_sub_texts = get_sub_texts
        
        self.get_receiving_addresses = get_receiving_addresses
        self.get_change_addresses = get_change_addresses
        
        
        self.signal_create_tx = Signal('signal_create_tx')
        

        self.main_widget = QWidget()
        self.main_widget_layout = QHBoxLayout(self.main_widget)
        
        self.create_inputs_selector(self.main_widget_layout)
        

        self.widget_right_hand_side = QWidget(self.main_widget)
        
        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)        
        
        self.widget_right_top = QWidget(self.main_widget)
        self.widget_right_top_layout = QHBoxLayout(self.widget_right_top)        
        
        self.groupBox_outputs, self.groupBox_outputs_layout = create_groupbox(self.widget_right_top_layout)
        self.recipients = create_recipients(self.groupBox_outputs_layout, get_receiving_addresses, get_change_addresses)

        self.fee_group = FeeGroup(self.widget_right_top_layout)
        
        self.widget_right_hand_side_layout.addWidget(self.widget_right_top)


        (self.button_create_tx,) = create_button_bar(self.widget_right_hand_side_layout, button_texts=["Next Step: Sign Transaction with hardware signers"])
        self.button_create_tx.clicked.connect(lambda : self.signal_create_tx(self.get_ui_tx_infos))



        self.main_widget_layout.addWidget(self.widget_right_hand_side)


        self.retranslateUi()

        QMetaObject.connectSlotsByName(self.main_widget)

        self.tab_changed(0)
        self.tabs_inputs.currentChanged.connect(self.tab_changed)

        


    def create_inputs_selector(self, layout):

        self.tabs_inputs = QTabWidget(self.main_widget)
        self.tabs_inputs.setMinimumWidth(200)
        self.tab_inputs_categories = QWidget(self.main_widget)
        self.tabs_inputs.addTab(self.tab_inputs_categories, 'Input Category')
    
        # tab categories        
        self.verticalLayout_inputs = QVBoxLayout(self.tab_inputs_categories)
        self.label_select_input_categories = QLabel('Select a category that fits best to the recipient')
        self.label_select_input_categories.setWordWrap(True)
        self.checkBox__reduce_future_fees = QCheckBox(self.tab_inputs_categories)
        self.checkBox__reduce_future_fees.setChecked(True)


        # Taglist
        self.category_list = CategoryList(self.categories, self.signals, self.get_sub_texts) 
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox__reduce_future_fees)


        # tab utxos
        self.tab_inputs_utxos = QWidget(self.main_widget)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, 'UTXOs')


        # utxo list
        self.verticalLayout_inputs_utxos.addWidget(self.utxo_list)

        layout.addWidget(self.tabs_inputs)        


    @property
    def get_ui_tx_infos(self):
        infos = TXInfos()

        for recipient in self.recipients.recipients:
            infos.add_recipient(**recipient)        
        infos.set_fee_rate(self.fee_group.spin_fee.value())

        if self.tabs_inputs.currentWidget() == self.tab_inputs_categories:
            infos.categories = self.category_list.get_selected()
        
        if self.tabs_inputs.currentWidget() == self.tab_inputs_utxos:
            infos.utxo_strings = [self.utxo_list.item_from_index(idx).text()
                                  for idx in self.utxo_list.selected_in_column(self.utxo_list.Columns.OUTPOINT)]
            
        return infos






    def update_categories(self):
        self.category_list.clear()
        for category in self.categories:
            self.category_list.add(category, sub_text=self.get_sub_texts())
        

    def retranslateUi(self):
        self.main_widget.setWindowTitle(QCoreApplication.translate("self.main_widget", u"self.main_widget", None))   
        self.checkBox__reduce_future_fees.setText(QCoreApplication.translate("self.main_widget", u"Reduce future fees\n"
"by merging small inputs now", None))




    @Slot(int)
    def tab_changed(self, index):
        # Slot called when the current tab changes
        # print(f"Tab changed to index {index}")

        if index == 0:
            self.tabs_inputs.setMaximumWidth(200)
            self.groupBox_outputs.setMaximumWidth(80000)
        elif index == 1:
            self.tabs_inputs.setMaximumWidth(80000)
            self.groupBox_outputs.setMaximumWidth(500)


