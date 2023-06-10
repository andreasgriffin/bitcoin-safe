from PySide2.QtWidgets import (QApplication, QWidget, QVBoxLayout, QComboBox,
                               QStackedWidget, QFormLayout, QLineEdit)
from PySide2.QtWidgets import QHBoxLayout, QPushButton
from ...config import UserConfig
from ...signals import Signal
from ...pythonbdk_types import *
from ...config import NetworkConfig, get_default_port

class NetworkSettingsUI(QWidget):
    def __init__(self, config:UserConfig, parent=None):
        super().__init__(parent)
        
        self.config = config
        self.layout = QVBoxLayout(self)

        self.network_combobox = QComboBox(self)
        self.network_combobox.addItem(str(bdk.Network.BITCOIN))
        self.network_combobox.addItem(str(bdk.Network.TESTNET))
        self.network_combobox.addItem(str(bdk.Network.SIGNET))
        self.network_combobox.addItem(str(bdk.Network.REGTEST))
        self.layout.addWidget(self.network_combobox)

        self.server_type_comboBox = QComboBox(self)
        self.server_type_comboBox.addItem(BlockchainType.to_text(BlockchainType.CompactBlockFilter))
        self.server_type_comboBox.addItem(BlockchainType.to_text(BlockchainType.Electrum))
        
        self.layout.addWidget(self.server_type_comboBox)

        self.stackedWidget = QStackedWidget(self)
        self.layout.addWidget(self.stackedWidget)

        # Compact Block Filters
        self.compactBlockFiltersTab = QWidget()
        self.compactBlockFiltersLayout = QFormLayout(self.compactBlockFiltersTab)

        self.cbf_server_typeComboBox = QComboBox(self.compactBlockFiltersTab)
        self.cbf_server_typeComboBox.addItem("Manual")
        self.cbf_server_typeComboBox.addItem("Automatic")
        self.cbf_server_typeComboBox.setCurrentIndex(1)

        self.compactBlockFiltersLayout.addRow("Mode:", self.cbf_server_typeComboBox)

        self.compactblockfilters_ip_address_edit = QLineEdit(self.compactBlockFiltersTab)
        self.compactblockfilters_ip_address_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow("IP Address:", self.compactblockfilters_ip_address_edit)

        self.compactblockfilters_port_edit = QLineEdit(self.compactBlockFiltersTab)
        self.compactblockfilters_port_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow("Port:", self.compactblockfilters_port_edit)

        self.stackedWidget.addWidget(self.compactBlockFiltersTab)

        # Electrum Server
        self.electrumServerTab = QWidget()
        self.electrumServerLayout = QFormLayout(self.electrumServerTab)

        self.electrum_ip_address_edit = QLineEdit(self.electrumServerTab)
        self.electrum_port_edit = QLineEdit(self.electrumServerTab)

        self.electrumServerLayout.addRow("IP Address:", self.electrum_ip_address_edit)
        self.electrumServerLayout.addRow("Port:", self.electrum_port_edit)

        self.stackedWidget.addWidget(self.electrumServerTab)
        
        

        # Create buttons and layout
        self.buttonLayout = QHBoxLayout()
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.on_cancel_click)
        self.applyButton = QPushButton(u"Apply && Restart")
        self.applyButton.clicked.connect(self.on_apply_click)
        
        self.signal_new_network_settings = Signal('signal_new_network_settings')
        

        self.buttonLayout.addWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.applyButton)

        self.layout.addLayout(self.buttonLayout)
        
        
        self.set_ui(self.config.network_settings)
        

        # Signals and Slots
        self.network_combobox.currentIndexChanged.connect(self.on_network_change)
        self.server_type_comboBox.currentIndexChanged.connect(self.set_server_type_comboBox)
        self.cbf_server_typeComboBox.currentIndexChanged.connect(self.enableIPPortLineEdit)


    def set_server_type_comboBox(self, new_index:int):
        if self.server_type_comboBox.currentIndex() != new_index:
            self.server_type_comboBox.setCurrentIndex(new_index)   
        self.stackedWidget.setCurrentIndex(new_index)
        
    def on_network_change(self, new_index:int):        
        self.electrum_port_edit.setPlaceholderText(str(get_default_port(self.network, BlockchainType.Electrum)) )
        self.compactblockfilters_port_edit.setPlaceholderText(str(get_default_port(self.network, BlockchainType.CompactBlockFilter)) )

    def on_apply_click(self):
        self.set_config_from_ui()
        self.signal_new_network_settings()

    def on_cancel_click(self):
        self.set_ui(self.config.network_settings)
        self.close()


    def set_config_from_ui(self):
        self.config.network_settings = self.get_network_settings_from_ui()

    def network_str_to_bdk(self, network_str):
        for network in bdk.Network:
            if str(network) == network_str:
                return network


    def get_network_settings_from_ui(self):
        network_config = NetworkConfig()
        network_config.network = self.network
        network_config.server_type = self.server_type
        network_config.cbf_server_type = self.cbf_server_type
        network_config.compactblockfilters_ip = self.compactblockfilters_ip
        network_config.compactblockfilters_port = self.compactblockfilters_port
        network_config.electrum_ip = self.electrum_ip
        network_config.electrum_port = self.electrum_port

        return network_config

    def set_ui(self, network_config:NetworkConfig):
        self.network = network_config.network
        self.server_type = network_config.server_type
        self.cbf_server_type = network_config.cbf_server_type
        self.compactblockfilters_ip = network_config.compactblockfilters_ip
        self.compactblockfilters_port = network_config.compactblockfilters_port
        self.electrum_ip = network_config.electrum_ip
        self.electrum_port = network_config.electrum_port

    def enableIPPortLineEdit(self, index):
        if self.cbf_server_typeComboBox.itemText(index) == "Manual":
            self.compactblockfilters_ip_address_edit.setEnabled(True)
            self.compactblockfilters_port_edit.setEnabled(True)
        else:
            self.compactblockfilters_ip_address_edit.setEnabled(False)
            self.compactblockfilters_port_edit.setEnabled(False)

    # Properties for all user entries

    @property
    def network(self):
        return self.network_str_to_bdk(self.network_combobox.currentText())

    @network.setter
    def network(self, value:bdk.Network):
        self.network_combobox.setCurrentText(str(value))

    @property
    def server_type(self) -> BlockchainType:
        return BlockchainType.from_text( self.server_type_comboBox.currentText())

    @server_type.setter
    def server_type(self, server_type:BlockchainType):
        index = self.server_type_comboBox.findText(BlockchainType.to_text(server_type))
        if index != -1:
            self.set_server_type_comboBox(index)

    @property
    def cbf_server_type(self):
        return CBFServerType.from_text(self.cbf_server_typeComboBox.currentText())

    @cbf_server_type.setter
    def cbf_server_type(self, cbf_server_type:CBFServerType):        
        index = self.cbf_server_typeComboBox.findText(CBFServerType.to_text( cbf_server_type))
        if index != -1:
            self.cbf_server_typeComboBox.setCurrentIndex(index)
            self.enableIPPortLineEdit(index)

    @property
    def compactblockfilters_ip(self):
        return self.compactblockfilters_ip_address_edit.text()

    @compactblockfilters_ip.setter
    def compactblockfilters_ip(self, ip):
        self.compactblockfilters_ip_address_edit.setText(ip if ip else "")


    @property
    def compactblockfilters_port(self):
        return self.compactblockfilters_port_edit.text()

    @compactblockfilters_port.setter
    def compactblockfilters_port(self, port):
        self.compactblockfilters_port_edit.setText(str(port))


    @property
    def electrum_ip(self):
        return self.electrum_ip_address_edit.text()

    @electrum_ip.setter
    def electrum_ip(self, ip):
        self.electrum_ip_address_edit.setText(ip if ip else "")


    @property
    def electrum_port(self):
        return self.electrum_port_edit.text()

    @electrum_port.setter
    def electrum_port(self, port):
        self.electrum_port_edit.setText(str(port))




if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = NetworkSettingsUI()
    window.show()
    sys.exit(app.exec_())
