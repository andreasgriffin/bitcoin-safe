from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *

from .category_list import CategoryList
from .recipients import Recipients
from .slider import CustomSlider
from ...signals import Signal
import bdkpython as bdk
from typing import List
from .utxo_list import UTXOList
from ...tx import TXInfos
from ...signals import Signals
from .barchart import MempoolBarChart
from ...mempool import get_prio_fees, fee_to_color

class UITX(object):
    def __init__(self, categories:List[str], utxo_list:UTXOList, get_receiving_addresses, get_change_addresses, signals:Signals, get_sub_texts) -> None:
        self.categories = categories
        self.utxo_list = utxo_list
        self.signals = signals
        self.get_sub_texts = get_sub_texts
        
        self.get_receiving_addresses = get_receiving_addresses
        self.get_change_addresses = get_change_addresses
        
        
        self.signal_create_tx = Signal('signal_create_tx')
        self.signal_edit_tx = Signal('signal_edit_tx')
        
        self.tab = QWidget()
        self.horizontalLayout = QHBoxLayout(self.tab)
        
        self.create_inputs(self.horizontalLayout)
        

        self.widget_right_hand_side = QWidget(self.tab)
        
        self.widget_right_hand_side_layout = QVBoxLayout(self.widget_right_hand_side)        
        
        self.widget_right_top = QWidget(self.tab)
        self.widget_right_top_layout = QHBoxLayout(self.widget_right_top)        
        self.create_outputs(self.widget_right_top_layout)
        self.create_fee_box(self.widget_right_top_layout)
        
        self.widget_right_hand_side_layout.addWidget(self.widget_right_top)


        self.create_button_bar(self.widget_right_hand_side_layout)



        self.horizontalLayout.addWidget(self.widget_right_hand_side)


        self.retranslateUi()

        QMetaObject.connectSlotsByName(self.tab)

        self.tab_changed(0)
        self.tabs_inputs.currentChanged.connect(self.tab_changed)
        self.button_create_tx.clicked.connect(lambda : self.signal_create_tx(self.get_ui_tx_infos))

    def create_button_bar(self, layout):
        self.button_bar = QWidget(self.widget_right_hand_side)
        self.button_bar_layout = QHBoxLayout(self.button_bar)

        self.button_save_tx = QPushButton(self.button_bar)
        self.button_save_tx.setMinimumHeight(30)
        self.button_bar_layout.addWidget(self.button_save_tx)

        self.button_create_tx = QPushButton(self.button_bar)
        self.button_create_tx.setMinimumHeight(30)
        self.button_bar_layout.addWidget(self.button_create_tx)


        layout.addWidget(self.button_bar)        


    def update_spin_fee(self):
        self.spin_fee.setRange(1, self.mempool.data[:,0].max())  # Set the acceptable range 

    def set_spin_fee(self, fee):
        self.spin_fee.setValue(fee)
        

    def create_fee_box(self, layout):


        # add the groupBox_Fee
        self.groupBox_Fee = QGroupBox()
        self.groupBox_Fee.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.groupBox_Fee.setAlignment(Qt.AlignTop)
        self.layout_h_fee = QHBoxLayout(self.groupBox_Fee)                
        # self.layout_h_fee.setContentsMargins(0, layout.contentsMargins().top(), 0, layout.contentsMargins().bottom())  # Remove margins

        #  add the mempool bar on the left
        self.mempool = MempoolBarChart()
        self.mempool.signal_click.connect(self.set_spin_fee)
        self.mempool.set_data_from_file('data.csv')
        self.mempool.chart.setMaximumWidth(25)
        self.layout_h_fee.addWidget(self.mempool.chart)
        
        # and the rest on the right
        self.widget_right_hand_side_fees = QWidget(self.groupBox_Fee)
        self.widget_right_hand_side_fees_layout = QVBoxLayout(self.widget_right_hand_side_fees)                
        self.widget_right_hand_side_fees_layout.setContentsMargins(0, layout.contentsMargins().top(), 0, layout.contentsMargins().bottom())  # Remove margins
        self.widget_right_hand_side_fees_layout.setAlignment(Qt.AlignVCenter)
        self.layout_h_fee.addWidget(self.widget_right_hand_side_fees)
                
        self.spin_fee = QDoubleSpinBox()
        self.spin_fee.setRange(0.0, 100.0)  # Set the acceptable range
        self.spin_fee.setSingleStep(1)  # Set the step size
        self.spin_fee.setDecimals(1)  # Set the number of decimal places
        self.mempool.signal_data_updated.connect(self.update_spin_fee)
        
        self.spin_fee.setMaximumWidth(45)
        self.widget_right_hand_side_fees_layout.addWidget(self.spin_fee)        

        self.spin_label = QLabel()
        self.spin_label.setText("sat/vB")
        self.widget_right_hand_side_fees_layout.addWidget(self.spin_label)        

            

        for fee, text in zip(get_prio_fees(self.mempool.data), ["High", "Mid", "Low"]):
            button = QPushButton()
            button.setStyleSheet("QPushButton { color: "+ fee_to_color(fee) +"; }")            
            button.setMaximumWidth(30)
            button.setText(text)
            def onclick(*args, value=fee):
                return self.spin_fee.setValue(value)
            button.clicked.connect(onclick)
            self.widget_right_hand_side_fees_layout.addWidget(button)        


        layout.addWidget(self.groupBox_Fee)

    def create_inputs(self, layout):

        self.tabs_inputs = QTabWidget(self.tab)
        self.tabs_inputs.setMinimumWidth(200)
        self.tab_inputs_categories = QWidget(self.tab)
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
        self.tab_inputs_utxos = QWidget(self.tab)
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
        infos.set_fee_rate(self.spin_fee.value())

        if self.tabs_inputs.currentWidget() == self.tab_inputs_categories:
            infos.categories = self.category_list.get_selected()
        
        if self.tabs_inputs.currentWidget() == self.tab_inputs_utxos:
            infos.utxo_strings = [self.utxo_list.item_from_index(idx).text()
                                  for idx in self.utxo_list.selected_in_column(self.utxo_list.Columns.OUTPOINT)]
            
        return infos



    def create_outputs(self, layout, parent=None):
        self.groupBox_outputs = QGroupBox(parent)
        self.vertical_in_groupBox_outputs = QVBoxLayout(self.groupBox_outputs)

        # recipients        
        self.recipients =  Recipients(self.get_receiving_addresses, self.get_change_addresses)
        self.vertical_in_groupBox_outputs.addWidget(self.recipients)


        self.groupBox_outputs.setMinimumWidth(300)
        self.groupBox_outputs.setMaximumWidth(800)
        
        
        layout.addWidget(self.groupBox_outputs)




    def update_categories(self):
        self.category_list.clear()
        for category in self.categories:
            self.category_list.add(category, sub_text=self.get_sub_texts())
        

    def retranslateUi(self):
        self.tab.setWindowTitle(QCoreApplication.translate("self.tab", u"self.tab", None))   
        self.checkBox__reduce_future_fees.setText(QCoreApplication.translate("self.tab", u"Reduce future fees\n"
"by merging small inputs now", None))
        self.groupBox_outputs.setTitle(QCoreApplication.translate("self.tab", u"Outputs", None))
        self.groupBox_Fee.setTitle(QCoreApplication.translate("self.tab", u"Fee", None))
        self.button_save_tx.setText(QCoreApplication.translate("self.tab", u"Save transaction", None))
        self.button_create_tx.setText(QCoreApplication.translate("self.tab", u"Next Step: Sign Transaction with hardware signers", None))
    # retranslateUi





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


