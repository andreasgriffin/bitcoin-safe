import logging

logger = logging.getLogger(__name__)

from PySide2.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QComboBox,
    QStackedWidget,
    QFormLayout,
    QLineEdit,
)
from PySide2.QtWidgets import QHBoxLayout, QPushButton

from bitcoin_safe.util import block_explorer_info
from ...config import UserConfig
from PySide2.QtCore import Signal
from ...pythonbdk_types import *
from ...config import NetworkConfig, get_default_port
from PySide2.QtCore import Qt
from .util import ResetLineEdit
from PySide2.QtWidgets import (
    QApplication,
    QLabel,
    QTextEdit,
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QWidget,
)
from PySide2.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QDialogButtonBox,
)


class NetworkSettingsUI(QWidget):
    signal_new_network_settings = Signal()

    def __init__(self, config: UserConfig, parent=None):
        super().__init__(parent)

        self.config = config
        self.layout = QVBoxLayout(self)

        self.network_combobox = QComboBox(self)
        for network in bdk.Network:
            self.network_combobox.addItem(str(network))
        self.layout.addWidget(self.network_combobox)

        self.groupbox_connection = QGroupBox("Blockchain data source", self)
        self.layout.addWidget(self.groupbox_connection)
        self.groupbox_connection_layout = QVBoxLayout(self.groupbox_connection)

        self.server_type_comboBox = QComboBox(self)
        self.server_type_comboBox.addItem(
            BlockchainType.to_text(BlockchainType.CompactBlockFilter)
        )
        self.server_type_comboBox.addItem(BlockchainType.to_text(BlockchainType.RPC))
        self.server_type_comboBox.addItem(
            BlockchainType.to_text(BlockchainType.Electrum)
        )
        self.server_type_comboBox.addItem(
            BlockchainType.to_text(BlockchainType.Esplora)
        )

        self.groupbox_connection_layout.addWidget(self.server_type_comboBox)

        self.stackedWidget = QStackedWidget(self)
        self.groupbox_connection_layout.addWidget(self.stackedWidget)

        # Compact Block Filters
        self.compactBlockFiltersTab = QWidget()
        self.compactBlockFiltersLayout = QFormLayout(self.compactBlockFiltersTab)

        self.cbf_server_typeComboBox = QComboBox(self.compactBlockFiltersTab)
        self.cbf_server_typeComboBox.addItem("Manual")
        self.cbf_server_typeComboBox.addItem("Automatic")
        self.cbf_server_typeComboBox.setCurrentIndex(1)

        self.compactBlockFiltersLayout.addRow("Mode:", self.cbf_server_typeComboBox)

        self.compactblockfilters_ip_address_edit = QLineEdit()
        self.compactblockfilters_ip_address_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow(
            "IP Address:", self.compactblockfilters_ip_address_edit
        )

        self.compactblockfilters_port_edit = ResetLineEdit(
            lambda: str(
                get_default_port(self.network, BlockchainType.CompactBlockFilter)
            )
        )
        self.compactblockfilters_port_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow(
            "Port:", self.compactblockfilters_port_edit
        )

        self.stackedWidget.addWidget(self.compactBlockFiltersTab)

        # Electrum Server
        self.electrumServerTab = QWidget()
        self.electrumServerLayout = QFormLayout(self.electrumServerTab)
        self.electrum_url_edit = QLineEdit(self.electrumServerTab)

        self.electrumServerLayout.addRow("URL:", self.electrum_url_edit)

        self.stackedWidget.addWidget(self.electrumServerTab)

        # Esplora Server
        self.esploraServerTab = QWidget()
        self.esploraServerLayout = QFormLayout(self.esploraServerTab)
        self.esplora_url_edit = QLineEdit(self.esploraServerTab)

        self.esploraServerLayout.addRow("URL:", self.esplora_url_edit)

        self.stackedWidget.addWidget(self.esploraServerTab)

        # RPC
        self.rpcTab = QWidget()
        self.rpcTabLayout = QFormLayout(self.rpcTab)

        self.rpc_ip_address_edit = QLineEdit(self.rpcTab)
        self.rpc_port_edit = ResetLineEdit(
            lambda: str(get_default_port(self.network, BlockchainType.RPC))
        )
        self.rpc_username_edit = QLineEdit(self.rpcTab)
        self.rpc_password_edit = QLineEdit(self.rpcTab)

        self.rpcTabLayout.addRow("IP Address:", self.rpc_ip_address_edit)
        self.rpcTabLayout.addRow("Port:", self.rpc_port_edit)
        self.rpcTabLayout.addRow("Username:", self.rpc_username_edit)
        self.rpcTabLayout.addRow("Password:", self.rpc_password_edit)

        self.stackedWidget.addWidget(self.rpcTab)

        self.groupbox_blockexplorer = QGroupBox("Block Explorer URL")
        self.groupbox_blockexplorer_layout = QVBoxLayout(self.groupbox_blockexplorer)
        self.blockchain_explorer_combobox = QComboBox(self)
        for name, d in block_explorer_info(config.network_settings.network).items():
            self.blockchain_explorer_combobox.addItem(name)
        self.groupbox_blockexplorer_layout.addWidget(self.blockchain_explorer_combobox)
        self.layout.addWidget(self.groupbox_blockexplorer)

        # Create buttons and layout
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.on_apply_click)
        self.button_box.rejected.connect(self.on_cancel_click)

        self.layout.addWidget(self.button_box)

        # Signals and Slots
        self.network_combobox.currentIndexChanged.connect(self.on_network_change)
        self.server_type_comboBox.currentIndexChanged.connect(
            self.set_server_type_comboBox
        )
        self.cbf_server_typeComboBox.currentIndexChanged.connect(
            self.enableIPPortLineEdit
        )

        # set the ui before the signals for update_button_text
        self.set_ui(self.config.network_settings)

        # for the update of the button
        for combobox in [
            self.network_combobox,
            self.server_type_comboBox,
            self.cbf_server_typeComboBox,
        ]:
            combobox.currentIndexChanged.connect(self.update_button_text)

        for edit in [
            self.electrum_url_edit,
            self.rpc_port_edit,
            self.esplora_url_edit,
            self.rpc_password_edit,
            self.electrum_url_edit,
            self.rpc_ip_address_edit,
            self.compactblockfilters_port_edit,
            self.compactblockfilters_ip_address_edit,
        ]:
            edit.textChanged.connect(self.update_button_text)

    def update_button_text(self):
        self.button_box.button(QDialogButtonBox.Ok).setText(
            "Apply && Restart" if self.does_it_need_restart() else "Apply"
        )

    def set_server_type_comboBox(self, new_index: int):
        if self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(
            BlockchainType.CompactBlockFilter
        ):
            self.stackedWidget.setCurrentWidget(self.compactBlockFiltersTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(
            BlockchainType.Electrum
        ):
            self.stackedWidget.setCurrentWidget(self.electrumServerTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(
            BlockchainType.Esplora
        ):
            self.stackedWidget.setCurrentWidget(self.esploraServerTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(
            BlockchainType.RPC
        ):
            self.stackedWidget.setCurrentWidget(self.rpcTab)

    def on_network_change(self, new_index: int):
        new_network = self.network_str_to_bdk(self.network_combobox.itemText(new_index))

        if (
            self.compactblockfilters_port_edit.text().strip()
            == self.compactblockfilters_port_edit.placeholderText()
        ):
            self.compactblockfilters_port_edit.setText(
                str(get_default_port(self.network, BlockchainType.CompactBlockFilter))
            )

        if self.rpc_port_edit.text().strip() == self.rpc_port_edit.placeholderText():
            self.rpc_port_edit.setText(
                str(get_default_port(self.network, BlockchainType.RPC))
            )

        if new_network == bdk.Network.TESTNET:
            self.electrum_url_edit.setPlaceholderText(
                "ssl://electrum.blockstream.info:60002"
            )
        else:
            self.electrum_url_edit.setPlaceholderText(
                f"127.0.0.1:{get_default_port(self.network, BlockchainType.Electrum)}"
            )

        self.compactblockfilters_port_edit.setPlaceholderText(
            str(get_default_port(self.network, BlockchainType.CompactBlockFilter))
        )
        self.rpc_port_edit.setPlaceholderText(
            str(get_default_port(self.network, BlockchainType.RPC))
        )

        # set the block explorers
        while self.blockchain_explorer_combobox.count():
            self.blockchain_explorer_combobox.removeItem(0)
        for name, d in block_explorer_info(new_network).items():
            self.blockchain_explorer_combobox.addItem(name)

    def on_apply_click(self):
        self.signal_new_network_settings.emit()

    def on_cancel_click(self):
        self.set_ui(self.config.network_settings)
        self.close()

    def set_config_from_ui(self):
        self.config.network_settings = self.get_network_settings_from_ui()

    def network_str_to_bdk(self, network_str):
        for network in bdk.Network:
            if str(network) == network_str:
                return network

    # Override keyPressEvent method
    def keyPressEvent(self, event):
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key_Escape:
            # Close the widget
            self.on_cancel_click()

    def get_network_settings_from_ui(self) -> NetworkConfig:
        "returns current ui as NetworkConfig"
        network_config = NetworkConfig()
        for name in vars(network_config):
            if name.startswith("_"):
                continue
            if not hasattr(self, name):
                logger.error(
                    f"get_network_settings_from_ui: {name} not present in {self.__class__.__name__}"
                )
                continue
            setattr(network_config, name, getattr(self, name))

        return network_config

    def set_ui(self, network_config: NetworkConfig):
        "Sets the ui from a NetworkConfig"

        for name in vars(network_config):
            if name.startswith("_"):
                continue
            if not hasattr(self, name):
                logger.error(f"set_ui: {name} not present in {self.__class__.__name__}")
                continue
            setattr(self, name, getattr(network_config, name))

    def does_it_need_restart(self):
        "Compares current Ui and the config setting, if it needs a restarts"
        ui_network_config = self.get_network_settings_from_ui()
        changed_names = []
        for name in vars(ui_network_config):
            if name.startswith("_"):
                continue
            if not hasattr(self, name):
                logger.error(
                    f"does_it_need_restart: {name} not present in {self.__class__.__name__}"
                )
                continue
            if getattr(self.config.network_settings, name) != getattr(
                ui_network_config, name
            ):
                changed_names.append(name)

        for restart_name in [
            "network",
            "server_type",
            "cbf_server_type",
            "compactblockfilters_ip",
            "compactblockfilters_port",
            "electrum_url",
            "rpc_ip",
            "rpc_port",
            "rpc_username",
            "rpc_password",
            "esplora_url",
        ]:
            if restart_name in changed_names:
                return True
        return False

    def enableIPPortLineEdit(self, index):
        if self.cbf_server_typeComboBox.itemText(index) == "Manual":
            self.compactblockfilters_ip_address_edit.setEnabled(True)
            self.compactblockfilters_port_edit.setEnabled(True)
        else:
            self.compactblockfilters_ip_address_edit.setEnabled(False)
            self.compactblockfilters_port_edit.setEnabled(False)

    # Properties for all user entries

    @property
    def block_explorer(self):
        return self.blockchain_explorer_combobox.currentText()

    @block_explorer.setter
    def block_explorer(self, value: str):
        self.blockchain_explorer_combobox.setCurrentText(value)

    @property
    def network(self):
        return self.network_str_to_bdk(self.network_combobox.currentText())

    @network.setter
    def network(self, value: bdk.Network):
        self.network_combobox.setCurrentText(str(value))

    @property
    def server_type(self) -> BlockchainType:
        return BlockchainType.from_text(self.server_type_comboBox.currentText())

    @server_type.setter
    def server_type(self, server_type: BlockchainType):
        self.server_type_comboBox.setCurrentText(BlockchainType.to_text(server_type))

    @property
    def cbf_server_type(self):
        return CBFServerType.from_text(self.cbf_server_typeComboBox.currentText())

    @cbf_server_type.setter
    def cbf_server_type(self, cbf_server_type: CBFServerType):
        index = self.cbf_server_typeComboBox.findText(
            CBFServerType.to_text(cbf_server_type)
        )
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
    def electrum_url(self):
        return self.electrum_url_edit.text()

    @electrum_url.setter
    def electrum_url(self, url):
        self.electrum_url_edit.setText(url if url else "")

    @property
    def esplora_url(self):
        url = self.esplora_url_edit.text()
        if "//" not in url:
            url = "http://" + url
        return url

    @esplora_url.setter
    def esplora_url(self, url):
        self.esplora_url_edit.setText(url if url else "")

    @property
    def rpc_ip(self):
        return self.rpc_ip_address_edit.text()

    @rpc_ip.setter
    def rpc_ip(self, ip):
        self.rpc_ip_address_edit.setText(ip if ip else "")

    @property
    def rpc_port(self):
        return self.rpc_port_edit.text()

    @rpc_port.setter
    def rpc_port(self, port):
        self.rpc_port_edit.setText(str(port))

    @property
    def rpc_username(self):
        return self.rpc_username_edit.text()

    @rpc_username.setter
    def rpc_username(self, username):
        self.rpc_username_edit.setText(username if username else "")

    @property
    def rpc_password(self):
        return self.rpc_password_edit.text()

    @rpc_password.setter
    def rpc_password(self, password):
        self.rpc_password_edit.setText(password if password else "")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = NetworkSettingsUI()
    window.show()
    sys.exit(app.exec_())
