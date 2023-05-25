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
        self.category_list = CategoryList(self.categories, self.signals, get_sub_texts) 
        self.verticalLayout_inputs.addWidget(self.label_select_input_categories)
        self.verticalLayout_inputs.addWidget(self.category_list)

        self.verticalLayout_inputs.addWidget(self.checkBox__reduce_future_fees)


        # tab utxos
        self.tab_inputs_utxos = QWidget(self.tab)
        self.verticalLayout_inputs_utxos = QVBoxLayout(self.tab_inputs_utxos)
        self.tabs_inputs.addTab(self.tab_inputs_utxos, 'UTXOs')


        # utxo list
        self.verticalLayout_inputs_utxos.addWidget(self.utxo_list)



        self.horizontalLayout.addWidget(self.tabs_inputs)

        self.widget_right_hand_side = QWidget(self.tab)
        self.widget_right_hand_side.setMinimumWidth(500)
        self.widget_right_hand_side.setMaximumWidth(800)
        
        self.verticalLayout = QVBoxLayout(self.widget_right_hand_side)
        self.groupBox_outputs = QGroupBox(self.widget_right_hand_side)
        self.vertical_in_groupBox_outputs = QVBoxLayout(self.groupBox_outputs)

        # recipients        
        self.recipients =  Recipients(self.get_receiving_addresses, self.get_change_addresses)
        self.vertical_in_groupBox_outputs.addWidget(self.recipients)
        
        

        self.verticalLayout.addWidget(self.groupBox_outputs)

        self.groupBox_Fee = QGroupBox(self.widget_right_hand_side)
        self.groupBox_Fee.setAlignment(Qt.AlignVCenter)
        self.groupBox_Fee.setMinimumHeight(90)
        # self.groupBox_Fee.setMaximumHeight(200)
                
                
        self.slider_fee = CustomSlider(unit="Sats/vByte", label_text='Amount: ', parent=self.groupBox_Fee)
        
        self.label_mempool_feelist = QLabel(self.groupBox_Fee)
        self.label_mempool_feelist.setAlignment(Qt.AlignLeading|Qt.AlignLeft|Qt.AlignVCenter)

        # add the widget with the slider on the left, and the fee list on the right
        self.layout_h_fee = QHBoxLayout(self.groupBox_Fee)
        self.layout_h_fee.addWidget(self.slider_fee)
        self.layout_h_fee.addWidget(self.label_mempool_feelist)

        self.verticalLayout.addWidget(self.groupBox_Fee)

        self.widget_2 = QWidget(self.widget_right_hand_side)
        self.widget_2.setMaximumSize(QSize(16777215, 50))
        self.horizontalLayout_2 = QHBoxLayout(self.widget_2)

        self.button_create_tx = QPushButton(self.widget_2)

        self.horizontalLayout_2.addWidget(self.button_create_tx)


        self.verticalLayout.addWidget(self.widget_2)


        self.horizontalLayout.addWidget(self.widget_right_hand_side)


        self.retranslateUi()

        QMetaObject.connectSlotsByName(self.tab)

        self.set_fee_rates(1, 2,10,30,100)
        self.tab_changed(0)
        self.tabs_inputs.currentChanged.connect(self.tab_changed)
        self.button_create_tx.clicked.connect(lambda : self.signal_create_tx(self.get_ui_tx_infos))

    @property
    def get_ui_tx_infos(self):
        infos = TXInfos()

        for recipient in self.recipients.recipients:
            infos.add_recipient(**recipient)        
        infos.set_fee_rate(self.slider_fee.value)

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
        self.tab.setWindowTitle(QCoreApplication.translate("self.tab", u"self.tab", None))   
        self.checkBox__reduce_future_fees.setText(QCoreApplication.translate("self.tab", u"Reduce future fees\n"
"by merging small inputs now", None))
        self.groupBox_outputs.setTitle(QCoreApplication.translate("self.tab", u"Outputs", None))
        self.groupBox_Fee.setTitle(QCoreApplication.translate("self.tab", u"Fee", None))
        self.label_mempool_feelist.setText(QCoreApplication.translate("self.tab", u"Low prio fee:  xx Sat\n"
"Mid prio fee:  xx Sat\n"
"High prio fee:  xx Sat\n"
"", None))
        self.button_create_tx.setText(QCoreApplication.translate("self.tab", u"Create Transaction (PSBT)", None))
    # retranslateUi



    def set_fee_rates(self, min_relay_fee, low, mid, high, max_fee):
        self.slider_fee.min_val = min_relay_fee
        self.slider_fee.max_val = max_fee
        self.slider_fee.tick_interval = max_fee // 50
        self.slider_fee.color_ranges = [[low, mid, '#7cb342'],
                                                [mid, high, '#fb8c00'],
                                                [high, max_fee, '#d81b60']]
                                                
        self.label_mempool_feelist.setText(f"Low prio: <font color='#7cb342'>{low}</font> {self.slider_fee.unit}<br>Mid prio: <font color='#fb8c00'>{mid}</font> {self.slider_fee.unit}<br>High prio: <font color='#d81b60'>{high}</font> {self.slider_fee.unit}")
        




    @Slot(int)
    def tab_changed(self, index):
        # Slot called when the current tab changes
        # print(f"Tab changed to index {index}")

        if index == 0:
            self.tabs_inputs.setMaximumWidth(200)
            self.widget_right_hand_side.setMaximumWidth(80000)
        elif index == 1:
            self.tabs_inputs.setMaximumWidth(80000)
            self.widget_right_hand_side.setMaximumWidth(500)


