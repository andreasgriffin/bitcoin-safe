import logging
from typing import Optional

import requests

from bitcoin_safe.gui.qt.custom_edits import QCompleterLineEdit
from bitcoin_safe.gui.qt.util import (
    Message,
    ensure_scheme,
    get_host_and_port,
    remove_scheme,
)
from bitcoin_safe.network_config import (
    NetworkConfig,
    NetworkConfigs,
    get_default_electrum_url,
    get_default_mempool_url,
    get_default_port,
    get_description,
)
from bitcoin_safe.pythonbdk_types import BlockchainType, CBFServerType, bdk

logger = logging.getLogger(__name__)

import json
import socket
import ssl

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


def test_mempool_space_server(url: str):
    try:
        response = requests.get(f"{url}/api/blocks/tip/height", timeout=2)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Mempool.space server connection test failed: {e}")
        return False


def get_electrum_server_version(host: str, port: int, use_ssl: bool = True, timeout=2) -> Optional[str]:
    try:
        # Connect to the server
        with socket.create_connection((host, port), timeout=timeout) as sock:
            # Wrap the socket with SSL if required
            ssock: Optional[socket.socket] = None
            if use_ssl:
                context = ssl.create_default_context()
                ssock = context.wrap_socket(sock, server_hostname=host)
            else:
                ssock = sock

            # Prepare and send the JSON-RPC request
            request = json.dumps({"id": 1, "method": "server.version", "params": ["1.4", "1.4"]}) + "\n"
            ssock.sendall(request.encode())

            # Receive the response
            response = ssock.recv(4096).decode()  # Assuming the response won't exceed 4096 bytes
            response_json = json.loads(response.split("\n")[0])  # Handling potential extra newlines

            # Close the SSL socket if used
            if use_ssl:
                ssock.close()

            # Check and print the server version
            if "result" in response_json:
                logger.debug(f"Server version: {response_json['result']}")
                return response_json["result"]
            else:
                logger.debug(f"Failed to retrieve server version of {host , port , use_ssl}.")
                return None
    except Exception as e:
        logger.debug(f"Connection or communication error: {e}")
        return None


def test_connection(network_config: NetworkConfig) -> Optional[str]:
    if network_config.server_type == BlockchainType.Electrum:

        host, port = get_host_and_port(network_config.electrum_url)

        if host is None or port is None:
            logger.warning(f"No host or port given")
            return None
        return get_electrum_server_version(host=host, port=port, use_ssl=network_config.electrum_use_ssl)

    elif network_config.server_type == BlockchainType.Esplora:
        try:
            # Assuming Esplora's REST API for testing connection
            response = requests.get(f"{network_config.esplora_url}/blocks/tip/height", timeout=2)
            if response.status_code == 200:
                return response.json()
            else:
                return None

        except Exception as e:
            logger.warning(f"Esplora API connection test failed: {e}")
            return None

    elif network_config.server_type == BlockchainType.RPC:
        try:
            # Assuming Bitcoin RPC interface for testing connection
            headers = {"content-type": "application/json"}
            payload = {"jsonrpc": "1.0", "id": "curltest", "method": "getblockchaininfo", "params": []}
            response = requests.post(
                f"{network_config.rpc_ip}:{network_config.rpc_port}",
                json=payload,
                headers=headers,
                auth=(network_config.rpc_username, network_config.rpc_password),
                timeout=2,
            )
            if response.status_code == 200 and "result" in response.json():
                return response.json()
            else:
                return None
        except Exception as e:
            logger.warning(f"RPC connection test failed: {e}")
            return None

    elif network_config.server_type == BlockchainType.CompactBlockFilter:
        # This case might require a different approach depending on how you intend to connect to the p2p network.
        # This is a placeholder as testing p2p connections is more complex and out of scope for this example.
        raise Exception("Not implemented yet")

    else:
        logger.warning("Invalid blockchain type.")
        return None


class NetworkSettingsUI(QDialog):
    signal_apply_and_restart = pyqtSignal(str)
    signal_cancel = pyqtSignal()

    def __init__(self, network: bdk.Network, network_configs: NetworkConfigs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Network Settings")
        self.network_configs = network_configs
        self.layout = QVBoxLayout(self)

        self.network_combobox = QComboBox(self)
        for _network in bdk.Network:
            self.network_combobox.addItem(_network.name)
        self.layout.addWidget(self.network_combobox)

        self.groupbox_connection = QGroupBox("Blockchain data source", self)
        self.layout.addWidget(self.groupbox_connection)
        self.groupbox_connection.setLayout(QVBoxLayout())

        self.server_type_comboBox = QComboBox(self)
        for blockchain_type in BlockchainType.active_types():
            self.server_type_comboBox.addItem(BlockchainType.to_text(blockchain_type))

        self.groupbox_connection.layout().addWidget(self.server_type_comboBox)

        self.stackedWidget = QStackedWidget(self)
        self.groupbox_connection.layout().addWidget(self.stackedWidget)

        # Compact Block Filters
        self.compactBlockFiltersTab = QWidget()
        self.compactBlockFiltersLayout = QFormLayout(self.compactBlockFiltersTab)

        self.cbf_server_typeComboBox = QComboBox(self.compactBlockFiltersTab)
        self.cbf_server_typeComboBox.addItem("Manual")
        self.cbf_server_typeComboBox.addItem("Automatic")
        self.cbf_server_typeComboBox.setCurrentIndex(1)

        self.compactBlockFiltersLayout.addRow("Mode:", self.cbf_server_typeComboBox)

        self.compactblockfilters_ip_address_edit = QCompleterLineEdit(network=network)
        self.compactblockfilters_ip_address_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow("IP Address:", self.compactblockfilters_ip_address_edit)

        self.compactblockfilters_port_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: [str(get_default_port(network, server_type=BlockchainType.CompactBlockFilter))]
                for network in bdk.Network
            },
        )
        self.compactblockfilters_port_edit.setEnabled(False)
        self.compactBlockFiltersLayout.addRow("Port:", self.compactblockfilters_port_edit)

        self.cbf_description = QLabel("")
        self.cbf_description.setWordWrap(True)
        self.cbf_description.setTextFormat(Qt.TextFormat.RichText)
        self.cbf_description.setOpenExternalLinks(True)  # Enable opening links
        self.compactBlockFiltersLayout.addRow("", self.cbf_description)

        self.stackedWidget.addWidget(self.compactBlockFiltersTab)

        # Electrum Server
        self.electrumServerTab = QWidget()
        self.electrumServerLayout = QFormLayout(self.electrumServerTab)
        #
        self.electrum_url_edit = QCompleterLineEdit(
            network=network,
            suggestions={network: [get_default_electrum_url(network)] for network in bdk.Network},
        )
        self.electrum_use_ssl_checkbox = QCheckBox()
        self.electrum_use_ssl_checkbox.setText("Enable SSL")

        self.electrumServerLayout.addRow("URL:", self.electrum_url_edit)
        self.electrumServerLayout.addRow("SSL:", self.electrum_use_ssl_checkbox)

        self.electrum_description = QLabel("")
        self.electrum_description.setWordWrap(True)
        self.electrum_description.setTextFormat(Qt.TextFormat.RichText)
        self.electrum_description.setOpenExternalLinks(True)  # Enable opening links
        self.electrumServerLayout.addRow("", self.electrum_description)

        self.stackedWidget.addWidget(self.electrumServerTab)

        # Esplora Server
        self.esploraServerTab = QWidget()
        self.esploraServerLayout = QFormLayout(self.esploraServerTab)
        self.esplora_url_edit = QCompleterLineEdit(network=network)

        self.esploraServerLayout.addRow("URL:", self.esplora_url_edit)

        self.esplora_description = QLabel("")
        self.esplora_description.setWordWrap(True)
        self.esplora_description.setTextFormat(Qt.TextFormat.RichText)
        self.esplora_description.setOpenExternalLinks(True)  # Enable opening links
        self.esploraServerLayout.addRow("", self.esplora_description)

        self.stackedWidget.addWidget(self.esploraServerTab)

        # RPC
        self.rpcTab = QWidget()
        self.rpcTabLayout = QFormLayout(self.rpcTab)

        self.rpc_ip_address_edit = QCompleterLineEdit(network=network)
        self.rpc_port_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: [str(get_default_port(network, server_type=BlockchainType.CompactBlockFilter))]
                for network in bdk.Network
            },
        )
        self.rpc_username_edit = QCompleterLineEdit(network=network)
        self.rpc_password_edit = QCompleterLineEdit(network=network)

        self.rpcTabLayout.addRow("IP Address:", self.rpc_ip_address_edit)
        self.rpcTabLayout.addRow("Port:", self.rpc_port_edit)
        self.rpcTabLayout.addRow("Username:", self.rpc_username_edit)
        self.rpcTabLayout.addRow("Password:", self.rpc_password_edit)

        self.rpc_description = QLabel("")
        self.rpc_description.setWordWrap(True)
        self.rpc_description.setTextFormat(Qt.TextFormat.RichText)
        self.rpc_description.setOpenExternalLinks(True)  # Enable opening links
        self.rpcTabLayout.addRow("", self.rpc_description)

        self.stackedWidget.addWidget(self.rpcTab)

        self.groupbox_blockexplorer = QGroupBox("Mempool Instance URL")
        self.groupbox_blockexplorer_layout = QVBoxLayout(self.groupbox_blockexplorer)
        self.edit_mempool_url = QCompleterLineEdit(
            network=network,
            suggestions={network: [get_default_mempool_url(network)] for network in bdk.Network},
        )
        self.groupbox_blockexplorer_layout.addWidget(self.edit_mempool_url)
        self.layout.addWidget(self.groupbox_blockexplorer)

        # Create buttons and layout
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Help
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Apply && Restart")
        self.button_box.accepted.connect(self.on_apply_click)
        self.button_box.rejected.connect(self.on_cancel_click)

        self.button_box.button(QDialogButtonBox.StandardButton.Help).setText("Test Connection")
        self.button_box.helpRequested.connect(self.test_connection)

        self.layout.addWidget(self.button_box)

        # Signals and Slots
        self.network_combobox.currentIndexChanged.connect(self.on_network_change)
        self.server_type_comboBox.currentIndexChanged.connect(self.set_server_type_comboBox)
        self.cbf_server_typeComboBox.currentIndexChanged.connect(self.enableIPPortLineEdit)

        self.network = network
        self.set_ui(self.network_config)

        self._edits_set_network(self.network)

    @property
    def network_config(self) -> NetworkConfig:
        return self.network_configs.configs[self.network.name]

    @network_config.setter
    def network_config(self, value: NetworkConfig):
        self.network_configs.configs[self.network.name] = value

    def test_connection(self):
        network_config = self.get_network_settings_from_ui()
        server_connection = test_connection(network_config=network_config)

        mempool_server = test_mempool_space_server(url=network_config.mempool_url)

        def format_status(response):
            return "Success" if response else "Failed"

        Message(
            f"Responses:\n    {network_config.server_type.name}: {format_status(server_connection)}\n    Mempool Instance: {format_status(mempool_server)}"
        )

    def set_server_type_comboBox(self, new_index: int):
        if self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(
            BlockchainType.CompactBlockFilter
        ):
            self.stackedWidget.setCurrentWidget(self.compactBlockFiltersTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(BlockchainType.Electrum):
            self.stackedWidget.setCurrentWidget(self.electrumServerTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(BlockchainType.Esplora):
            self.stackedWidget.setCurrentWidget(self.esploraServerTab)
        elif self.server_type_comboBox.itemText(new_index) == BlockchainType.to_text(BlockchainType.RPC):
            self.stackedWidget.setCurrentWidget(self.rpcTab)

    def on_network_change(self, new_index: int):
        new_network = bdk.Network._member_map_[self.network_combobox.itemText(new_index)]

        self._edits_set_network(new_network)
        self.set_ui(self.network_configs.configs[new_network.name])

    def _edits_set_network(self, network: bdk.Network):
        self.compactblockfilters_ip_address_edit.set_network(network)
        self.electrum_url_edit.set_network(network)
        self.esplora_url_edit.set_network(network)
        self.rpc_ip_address_edit.set_network(network)
        self.rpc_username_edit.set_network(network)
        self.rpc_password_edit.set_network(network)
        self.edit_mempool_url.set_network(network)

    def add_to_completer_memory(self):
        self.compactblockfilters_ip_address_edit.add_current_to_memory()
        self.electrum_url_edit.add_current_to_memory()
        self.esplora_url_edit.add_current_to_memory()
        self.rpc_ip_address_edit.add_current_to_memory()
        self.rpc_username_edit.add_current_to_memory()
        self.rpc_password_edit.add_current_to_memory()
        self.edit_mempool_url.add_current_to_memory()

    def on_apply_click(self):
        new_network = self.network

        self.add_to_completer_memory()

        self.network_config = self.get_network_settings_from_ui()

        self.close()
        self.signal_apply_and_restart.emit(f"--network {new_network.name.lower()}")

    def on_cancel_click(self):
        self.set_ui(self.network_config)
        self.signal_cancel.emit()
        self.close()

    # Override keyPressEvent method
    def keyPressEvent(self, event: QKeyEvent):
        # Check if the pressed key is 'Esc'
        if event.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.on_cancel_click()

    def get_network_settings_from_ui(self) -> NetworkConfig:
        "returns current ui as NetworkConfig"
        network_config = NetworkConfig(network=self.network)
        for name in vars(network_config):
            if name.startswith("_"):
                continue
            if not hasattr(self, name):
                logger.error(f"get_network_settings_from_ui: {name} not present in {self.__class__.__name__}")
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

        self.set_server_type_comboBox(self.server_type_comboBox.currentIndex())
        self._edits_set_network(self.network)

        # set the descriptions
        self.cbf_description.setText(
            get_description(network=self.network, server_type=BlockchainType.CompactBlockFilter)
        )
        self.rpc_description.setText(get_description(network=self.network, server_type=BlockchainType.RPC))
        self.esplora_description.setText(
            get_description(network=self.network, server_type=BlockchainType.Esplora)
        )
        self.electrum_description.setText(
            get_description(network=self.network, server_type=BlockchainType.Electrum)
        )

    def enableIPPortLineEdit(self, index: int):
        if self.cbf_server_typeComboBox.itemText(index) == "Manual":
            self.compactblockfilters_ip_address_edit.setEnabled(True)
            self.compactblockfilters_port_edit.setEnabled(True)
        else:
            self.compactblockfilters_ip_address_edit.setEnabled(False)
            self.compactblockfilters_port_edit.setEnabled(False)

    # Properties for all user entries

    @property
    def mempool_url(self) -> str:
        url = self.edit_mempool_url.text()
        url = url if url.endswith("/") else f"{url}/"
        url = url.replace("api/", "") if url.endswith("api/") else url
        return ensure_scheme(url)

    @mempool_url.setter
    def mempool_url(self, value: str):
        self.edit_mempool_url.setText(value)

    @property
    def network(self) -> bdk.Network:
        return bdk.Network._member_map_[self.network_combobox.currentText()]

    @network.setter
    def network(self, value: bdk.Network):
        self.network_combobox.setCurrentText(value.name)

    @property
    def server_type(self) -> BlockchainType:
        return BlockchainType.from_text(self.server_type_comboBox.currentText())

    @server_type.setter
    def server_type(self, server_type: BlockchainType):
        self.server_type_comboBox.setCurrentText(BlockchainType.to_text(server_type))

    @property
    def cbf_server_type(self) -> CBFServerType:
        return CBFServerType.from_text(self.cbf_server_typeComboBox.currentText())

    @cbf_server_type.setter
    def cbf_server_type(self, cbf_server_type: CBFServerType):
        index = self.cbf_server_typeComboBox.findText(cbf_server_type.name)
        if index != -1:
            self.cbf_server_typeComboBox.setCurrentIndex(index)
            self.enableIPPortLineEdit(index)

    @property
    def compactblockfilters_ip(self) -> str:
        return self.compactblockfilters_ip_address_edit.text()

    @compactblockfilters_ip.setter
    def compactblockfilters_ip(self, ip):
        self.compactblockfilters_ip_address_edit.setText(ip if ip else "")

    @property
    def compactblockfilters_port(self) -> int:
        try:
            return int(self.compactblockfilters_port_edit.text())
        except:
            return self.network_config.compactblockfilters_port

    @compactblockfilters_port.setter
    def compactblockfilters_port(self, port):
        self.compactblockfilters_port_edit.setText(str(port))

    @property
    def electrum_url(self) -> str:
        text = self.electrum_url_edit.text()
        return remove_scheme(text)

    @electrum_url.setter
    def electrum_url(self, url: str):
        self.electrum_url_edit.setText(url if url else "")

    @property
    def electrum_use_ssl(self) -> bool:
        return self.electrum_use_ssl_checkbox.isChecked()

    @electrum_use_ssl.setter
    def electrum_use_ssl(self, value: bool):
        self.electrum_use_ssl_checkbox.setChecked(value)

    @property
    def esplora_url(self) -> str:
        url = self.esplora_url_edit.text()
        if "//" not in url:
            url = "http://" + url
        return url

    @esplora_url.setter
    def esplora_url(self, url: str):
        self.esplora_url_edit.setText(url if url else "")

    @property
    def rpc_ip(self) -> str:
        return self.rpc_ip_address_edit.text()

    @rpc_ip.setter
    def rpc_ip(self, ip: str):
        self.rpc_ip_address_edit.setText(ip if ip else "")

    @property
    def rpc_port(self) -> int:
        try:
            return int(self.rpc_port_edit.text())
        except:
            return self.network_config.rpc_port

    @rpc_port.setter
    def rpc_port(self, port: int):
        self.rpc_port_edit.setText(str(port))

    @property
    def rpc_username(self) -> str:
        return self.rpc_username_edit.text()

    @rpc_username.setter
    def rpc_username(self, username: str):
        self.rpc_username_edit.setText(username if username else "")

    @property
    def rpc_password(self) -> str:
        return self.rpc_password_edit.text()

    @rpc_password.setter
    def rpc_password(self, password: str):
        self.rpc_password_edit.setText(password if password else "")
