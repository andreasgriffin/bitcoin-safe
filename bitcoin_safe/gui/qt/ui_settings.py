from curses import keyname
import enum
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from qtrangeslider import QRangeSlider
from PySide2.QtSvg import QSvgWidget
from .util import  icon_path, center_in_widget, qresize, add_tab_to_tabs, read_QIcon
from ...wallet import AddressTypes, AddressType, Wallet
from ...descriptors import  get_default_address_type, generate_bdk_descriptors, generate_output_descriptors_from_keystores, descriptor_infos
from ...keystore import KeyStoreTypes, KeyStoreType, KeyStore
from ...signals import Signals, QTWalletSignals,  Signal
from .keystore_ui import KeyStoreUI
from typing import List, Tuple
from enum import Enum, auto
from .block_change_signals import BlockChangesSignals
from .custom_edits import MyTextEdit

class WalletSettingsUI():
        def __init__(self, wallet:Wallet) -> None:
                self.wallet = wallet
                self.cloned_wallet:Wallet = None  # any temporary changes (before apply) are applied to this cloned_wallet. If it is None, then no change was made
                self.tab = QWidget()
                self.verticalLayout_2 = QVBoxLayout(self.tab)

                self.keystore_uis : List[KeyStoreUI] = []
                self.signal_descriptor_pasted = Signal('signal_descriptor_pasted')
                self.signal_descriptor_pasted.connect(self.on_descriptor_pasted)
                self.signal_descriptor_change_apply = Signal('signal_descriptor_change_apply')
                self.signal_descriptor_change_apply.connect(self.on_descriptor_change)
                self.signal_qtwallet_apply_setting_changes = Signal('signal_qtwallet_apply_setting_changes')
                self.signal_qtwallet_cancel_setting_changes = Signal('signal_qtwallet_cancel_setting_changes')
                
                self.create_wallet_type_and_descriptor()                    
                self.tabs_widget_signers = QTabWidget(self.tab)
                self.verticalLayout_2.addWidget(self.tabs_widget_signers)
                
                for keystore in wallet.keystores:
                        keystore_ui = KeyStoreUI(keystore, self.tabs_widget_signers, self.wallet.network)
                        self.keystore_uis.append(keystore_ui) 

                self.block_change_signals = BlockChangesSignals(
                        own_widgets=[self.spin_gap, self.spin_req, self.spin_signers, self.edit_descriptor],
                )
                
                for signal in (
                                [ui.keystore_ui_default.signal_xpub_changed for ui in self.keystore_uis]+
                                [ui.keystore_ui_default.signal_fingerprint_changed for ui in self.keystore_uis]+
                                [ui.keystore_ui_default.signal_derivation_path_changed for ui in self.keystore_uis]
                                ):
                        signal.connect(self.ui_keystore_ui_change)
                self.disable_fields()
                self.set_all_ui_from_wallet(self.wallet)                            

                self.box_button_bar = self.create_button_bar()
        
                # self.tab_wallet_xpub_tab = self.create_wallet_xpub_tab()
                # self.tabs_widget_signers.addTab(self.tab_wallet_xpub_tab, "Signer Settings")


        def ui_keystore_ui_change(self, *args):
                self.set_wallet_from_keystore_ui(self.get_cloned_wallet())
                self.set_ui_descriptor(self.get_cloned_wallet())


        def get_cloned_wallet(self) -> Wallet:
                if not self.cloned_wallet:
                        self.cloned_wallet = self.wallet.clone()
                return self.cloned_wallet
                
                
        def on_wallet_ui_changes(self):
                cloned_wallet = self.get_cloned_wallet()
                self.set_wallet_from_keystore_ui(cloned_wallet)                

                self.set_ui_descriptor(cloned_wallet)                                        
                self.set_keystore_ui_from_wallet(cloned_wallet)
                self.set_wallet_ui_from_wallet(cloned_wallet)
                assert len(cloned_wallet.keystores) == len(self.keystore_uis)
                
                
        def get_ui_values_as_keystores(self):
                return [keystore_ui.keystore_ui_default.get_ui_values_as_keystore() for keystore_ui in self.keystore_uis]

        def on_descriptor_pasted(self, new_value):
                self.on_descriptor_change(new_value)
                self.set_ui_descriptor(self.get_cloned_wallet())
                
        def on_descriptor_change(self, new_value):
                cloned_wallet = self.get_cloned_wallet()
                                
                # self.set_wallet_from_keystore_ui(cloned_wallet)
                if hasattr(self, '_edit_descriptor_cache') and self._edit_descriptor_cache == new_value:
                        # no change
                        return
                self._edit_descriptor_cache = new_value

                cloned_wallet.set_wallet_from_descriptor(new_value, recreate_bdk_wallet=False)
                self.set_wallet_ui_from_wallet(cloned_wallet)                                        
                self.set_keystore_ui_from_wallet(cloned_wallet)                     
                self.disable_fields()                   
                assert len(cloned_wallet.keystores) == len(self.keystore_uis)


        def on_spin_threshold_changed(self, new_value):
                self.on_wallet_ui_changes()

        def on_spin_signer_changed(self, new_value):
                self.on_wallet_ui_changes()


        def _set_keystore_tabs(self, wallet:Wallet):
                # add keystore_ui if necessary
                if len(self.keystore_uis) < len(wallet.keystores):
                        for i in range(len(self.keystore_uis), len(wallet.keystores)):
                                self.keystore_uis.append(KeyStoreUI(wallet.keystores[i], self.tabs_widget_signers, self.wallet.network))
                # remove keystore_ui if necessary
                elif  len(self.keystore_uis) > len(wallet.keystores):
                        for i in range(len(wallet.keystores), len(self.keystore_uis)):
                                self.keystore_uis[-1].remove_tab()
                                self.keystore_uis.pop()
                                
                # now make a second pass and connect point the keystore_ui.keystore correctly
                for keystore, keystore_ui in zip(self.wallet.keystores, self.keystore_uis):
                        keystore_ui.keystore.from_other_keystore(keystore)


        def set_keystore_ui_from_wallet(self, wallet:Wallet):
                self._set_keystore_tabs(wallet)                      
                for keystore, keystore_ui in zip(wallet.keystores, self.keystore_uis):
                        keystore_ui.set_ui_from_keystore(keystore)                
                        
                        
        
        def set_wallet_ui_from_wallet(self, wallet:Wallet):
                self.cloned_wallet = wallet.clone()
                with self.block_change_signals:
                        self.spin_req.setMinimum(1)
                        self.spin_req.setMaximum(len(wallet.keystores))
                        self.spin_req.setValue(wallet.threshold)           

                        self.spin_signers.setMinimum(wallet.threshold)
                        self.spin_signers.setMaximum(10)
                        self.spin_signers.setValue(len( wallet.keystores))                
                        
                        if self.spin_req.value() < self.spin_signers.value():
                                labels_of_recovery_signers = [f"\"{keystore.label}\"" for keystore in wallet.keystores][self.spin_req.value():]
                                self.spin_req.setToolTip(f'In the chosen multisig setup, you need {self.spin_req.value()} devices (signers) to sign every outgoing transaction.\n'
                                                        f'In case of loss of 1 of the devices, you can recover your funds using\n {" or ".join(labels_of_recovery_signers)} and send the funds to a new wallet.')     
                        if self.spin_req.value() == self.spin_signers.value()  != 1:
                                self.spin_req.setToolTip(f'Warning!  Choosing a multisig setup where ALL signers need to sign every transaction\n is very RISKY and does not offer ynay benefits of multisig. Recommended multisig setups are 2-of-3 or 3-of-5')     
                        if self.spin_req.value() == self.spin_signers.value()  == 1:
                                self.spin_req.setToolTip(f'A single signing device can sign outgoing transactions.')     

                        self.spin_gap.setValue(wallet.gap)
                        
        
        
        def set_all_ui_from_wallet(self, wallet:Wallet):
                """
                Updates the 3 parts
                - wallet ui (e.g. gap)
                - Keystore UI  (e.g. xpubs)
                - descriptor ui 
                """
                with self.block_change_signals:
                        self.set_wallet_ui_from_wallet(wallet)
                        self.set_keystore_ui_from_wallet(wallet)
                        self.set_ui_descriptor(wallet)




    
        def set_wallet_from_keystore_ui(self, wallet:Wallet=None):
                if wallet is None:
                        wallet = self.wallet
                
                for keystore, keystore_ui in zip(wallet.keystores, self.keystore_uis):
                        keystore_ui.set_keystore_from_ui_values(keystore) 
                wallet.set_address_type(self.get_address_type_from_ui())
                wallet.set_gap(self.get_gap_from_ui())

                m,n = self.get_m_of_n_from_ui()
                wallet.set_threshold(m)
                
                assert len(wallet.keystores) == len(self.keystore_uis)
                # if len(wallet.keystores) != len(self.keystore_uis):
                #         print(wallet.keystores, self.keystore_uis)
        
                wallet.set_number_of_keystores(n, cloned_reference_keystores=[k.clone() for k in self.wallet.keystores] )
                
                for i, keystore in enumerate(wallet.keystores):
                        keystore.label = wallet.signer_names(wallet.threshold, i)
                
                # print([k.serialize() for k in wallet.keystores])
                # print([k.serialize() for k in self.wallet.keystores])
                
        
        def set_combo_box_address_type_default(self):
                address_types = self.wallet.get_address_types()
                self.comboBox_address_type.setCurrentIndex(address_types.index(get_default_address_type(self.wallet.is_multisig())))
        
        def get_address_type_from_ui(self) -> AddressType:
                address_types = self.wallet.get_address_types()
                
                address_type = address_types[self.comboBox_address_type.currentIndex()]
                
                assert address_type.name == self.comboBox_address_type.currentText()
                return address_type        
        
        def get_m_of_n_from_ui(self) -> Tuple[int, int]:
                return (self.spin_req.value(), self.spin_signers.value())
        
        def get_gap_from_ui(self) -> int:
                return self.spin_gap.value()
        
        
        
        # def get_descriptor_string_from_keystore_ui(self, use_html=False):
        #         temp_ui_keystores = [ui.keystore_ui_default.get_ui_values_as_keystore() for ui in  self.keystore_uis]
        #         descriptors = generate_output_descriptors_from_keystores(self.get_m_of_n_from_ui()[0],
        #                                                                 self.get_address_type_from_ui(),
        #                                                                 temp_ui_keystores,
        #                                                                 self.wallet.network,
        #                                                                 replace_keystore_with_dummy=False,
        #                                                                 use_html=use_html,
        #                                                                 combined_descriptors=True
        #                                                                 )        
        #         return descriptors
                                        
        def set_ui_descriptor(self,  wallet:Wallet):
                # check if the descriptor actually CAN be calculated to a reasonable degree
                
                descriptors = generate_output_descriptors_from_keystores(wallet.threshold,
                                                                                 wallet.address_type,
                                                                                 wallet.keystores,
                                                                                 wallet.network,
                                                                                 replace_keystore_with_dummy=True,
                                                                                 use_html=True,
                                                                                 combined_descriptors=True
                                                                                 )
                with self.block_change_signals:
                        self.edit_descriptor.setText(descriptors[0])
                                        
        
        def disable_fields(self):
                with self.block_change_signals:
                        self.set_combo_box_address_type_default()
                        self.spin_signers.setValue(len(self.wallet.keystores))                
                
                if self.wallet.is_multisig():
                        self.label_of.setEnabled(True)
                        self.spin_signers.setEnabled(True)
                else:
                        self.label_of.setDisabled(True)
                        self.spin_signers.setDisabled(True)
                  
                
        
        def create_wallet_type_and_descriptor(self):
                box_wallet_type_and_descriptor = QWidget(self.tab)
                box_wallet_type_and_descriptor.setMaximumHeight(200)
                
                h_wallet_type_and_descriptor = QHBoxLayout(box_wallet_type_and_descriptor)
                box_wallet_type = QGroupBox(box_wallet_type_and_descriptor)
                v_wallet_type = QVBoxLayout(box_wallet_type)
                
                # box_signers_with_slider
                box_signers_with_slider = QWidget(box_wallet_type)
                h_signers_with_slider = QHBoxLayout(box_signers_with_slider)
                label_signers = QLabel(box_signers_with_slider)
                label_signers.setText(QCoreApplication.translate("tab", u"Signers", None))
                h_signers_with_slider.addWidget(label_signers)
                self.spin_req = QSpinBox(box_signers_with_slider)
                self.spin_req.setMinimum(1)
                self.spin_req.setMaximum(10)
                h_signers_with_slider.addWidget(self.spin_req)
                self.label_of = QLabel(box_signers_with_slider)
                self.label_of.setText(QCoreApplication.translate("tab", u"of", None))
                self.label_of.setAlignment(Qt.AlignVCenter)
                h_signers_with_slider.addWidget(self.label_of)
                self.spin_signers = QSpinBox(box_signers_with_slider)
                self.spin_signers.setMinimum(1)
                self.spin_signers.setMaximum(10)
                h_signers_with_slider.addWidget(self.spin_signers)
                v_wallet_type.addWidget(box_signers_with_slider)


                box_address_type = QWidget(box_wallet_type)
                h_address_type = QHBoxLayout(box_address_type)
                label_address_type = QLabel(box_address_type)

                h_address_type.addWidget(label_address_type)

                self.comboBox_address_type = QComboBox(box_address_type)
                address_types = self.wallet.get_address_types()
                addres_type_names = [a.name for a in address_types]
                self.comboBox_address_type.addItems(addres_type_names)
                h_address_type.addWidget(self.comboBox_address_type)


                v_wallet_type.addWidget(box_address_type)
                
                
                
                box_gap = QWidget(box_wallet_type)
                h_gap = QHBoxLayout(box_gap)
                label_gap = QLabel(box_gap)
                label_gap.setWordWrap(True)
                label_gap.setText( "Pregenerate " )
                self.spin_gap = QSpinBox(box_gap)
                self.spin_gap.setMinimum(20)
                self.spin_gap.setMaximum(int(1e6))
                label_gap2 = QLabel(box_gap)
                label_gap2.setText( " unused Addresses" )
                # self.label_gap2.setTextAlignment(Qt.AlignVCenter)
                h_gap.addWidget(label_gap)
                h_gap.addWidget(self.spin_gap)
                h_gap.addWidget(label_gap2)

                v_wallet_type.addWidget(box_gap)

                
                h_wallet_type_and_descriptor.addWidget(box_wallet_type)


                # now the descriptor
                groupBox_wallet_descriptor = QGroupBox(box_wallet_type_and_descriptor)
                # below is an example how to highlight the box
                # groupBox_wallet_descriptor.setStyleSheet("""
                # QGroupBox {
                #         font-weight: bold;
                #         border: 2px solid red;
                #         border-radius: 5px;
                #         margin-top: 12px;
                # }
                # QGroupBox::title {
                #         color: red;
                #         subcontrol-origin: margin;
                #         left: 10px;
                #         padding: 0 5px 0 5px;
                # }
                # """)                                
                self.horizontalLayout_4 = QHBoxLayout(groupBox_wallet_descriptor)
                self.edit_descriptor = MyTextEdit(groupBox_wallet_descriptor)
                self.edit_descriptor.setToolTip(f"This \"descriptor\" contains all information to reconstruct the wallet. \nPlease back up this descriptor to be able to recover the funds!")
                self.edit_descriptor.signal_key_press.connect(self.signal_descriptor_change_apply)                
                self.edit_descriptor.signal_pasted_text.connect(self.signal_descriptor_pasted)

                self.horizontalLayout_4.addWidget(self.edit_descriptor)


                h_wallet_type_and_descriptor.addWidget(groupBox_wallet_descriptor)


                self.verticalLayout_2.addWidget(box_wallet_type_and_descriptor)

                
                box_wallet_type.setTitle(QCoreApplication.translate("tab", u"Wallet Type", None))
                label_address_type.setText(QCoreApplication.translate("tab", u"Address Type", None))
                groupBox_wallet_descriptor.setTitle(QCoreApplication.translate("tab", u"Wallet Descriptor", None))


                # self.edit_descriptor.textChanged.connect(self.signal_descriptor_change_apply)
                self.spin_signers.valueChanged.connect(self.on_spin_signer_changed)
                self.spin_req.valueChanged.connect(self.on_spin_threshold_changed)




        def create_button_bar(self):
                box_button_bar = QWidget(self.tab)
                layout_buttonbar = QHBoxLayout(box_button_bar)
                layout_buttonbar.setContentsMargins(0, 0, 0, 0)
                self.button_cancel = QPushButton(box_button_bar)
                self.button_cancel.setMinimumSize(QSize(150, 0))
                layout_buttonbar.addWidget(self.button_cancel)

                self.button_apply = QPushButton(box_button_bar)
                self.button_apply.setMinimumSize(QSize(150, 0))
                self.button_apply.clicked.connect(self.signal_qtwallet_apply_setting_changes)
                layout_buttonbar.addWidget(self.button_apply)                
                self.verticalLayout_2.addWidget(box_button_bar, 0, Qt.AlignRight)
        
                self.button_cancel.setText(QCoreApplication.translate("tab", u"Cancel changes", None))
                self.button_cancel.clicked.connect(self.signal_qtwallet_cancel_setting_changes)
                self.button_apply.setText(QCoreApplication.translate("tab", u"Apply changes", None))

                
