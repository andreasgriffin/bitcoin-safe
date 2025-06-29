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
from typing import Dict, Optional, Tuple

import bdkpython as bdk
import numpy as np
import requests
import socks  # Import the socks module from PySocks
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.custom_edits import QCompleterLineEdit
from bitcoin_safe.gui.qt.dialogs import question_dialog
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import (
    Message,
    adjust_bg_color_for_darkmode,
    ensure_scheme,
    generate_help_website_open,
    get_host_and_port,
    remove_scheme,
    svg_tools,
)
from bitcoin_safe.network_config import (
    NetworkConfig,
    NetworkConfigs,
    get_default_port,
    get_default_rpc_hosts,
    get_description,
    get_electrum_configs,
    get_esplora_urls,
    get_mempool_url,
)
from bitcoin_safe.network_utils import (
    ProxyInfo,
    ensure_scheme,
    get_electrum_server_version,
    get_host_and_port,
)
from bitcoin_safe.pythonbdk_types import BlockchainType
from bitcoin_safe.signals import Signals
from bitcoin_safe.typestubs import TypedPyQtSignal
from bitcoin_safe.util_os import webopen

from ....signals import TypedPyQtSignalNo

logger = logging.getLogger(__name__)


def test_mempool_space_server(url: str, proxies: Dict | None) -> bool:
    timeout = 10 if proxies else 2
    try:
        response = requests.get(f"{url}/api/blocks/tip/height", timeout=timeout, proxies=proxies)
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Mempool.space server connection test failed: {e}")
        return False


def test_connection(network_config: NetworkConfig) -> Optional[str]:
    proxy_info = ProxyInfo.parse(network_config.proxy_url) if network_config.proxy_url else None
    timeout = 10 if proxy_info else 2

    if network_config.server_type == BlockchainType.Electrum:
        try:
            host, port = get_host_and_port(network_config.electrum_url)
            if host is None or port is None:
                logger.warning(f"No host or port given")
                return None
            return get_electrum_server_version(
                host=host,
                port=port,
                use_ssl=network_config.electrum_use_ssl,
                proxy_info=proxy_info,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(f"Electrum connection test failed: {e}")
            return None

    elif network_config.server_type == BlockchainType.Esplora:
        try:
            # Assuming Esplora's REST API for testing connection
            response = requests.get(
                f"{network_config.esplora_url}/blocks/tip/height",
                timeout=timeout,
                proxies=(proxy_info.get_requests_proxy_dict() if proxy_info else None),
            )
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
                timeout=timeout,
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
    raise Exception(f"Invalud {network_config.server_type}")


class NetworkSettingsUI(QDialog):
    signal_apply_and_restart: TypedPyQtSignal[bdk.Network] = pyqtSignal(bdk.Network)  # type: ignore
    signal_apply_and_shutdown: TypedPyQtSignal[bdk.Network] = pyqtSignal(bdk.Network)  # type: ignore
    signal_cancel: TypedPyQtSignalNo = pyqtSignal()  # type: ignore

    def __init__(
        self,
        network: bdk.Network,
        network_configs: NetworkConfigs,
        signals: Optional[Signals],
        parent=None,
    ):
        super().__init__(parent)
        self.signals = signals
        self.network_configs = network_configs
        self._layout = QVBoxLayout(self)

        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self.network_combobox = QComboBox(self)
        for _network in bdk.Network:
            self.network_combobox.addItem(
                svg_tools.get_QIcon(f"bitcoin-{_network.name.lower()}.svg"), _network.name, userData=_network
            )
        self._layout.addWidget(self.network_combobox)

        self.groupbox_connection = QGroupBox(parent=self)
        self._layout.addWidget(self.groupbox_connection)
        self.groupbox_connection_layout = QVBoxLayout(self.groupbox_connection)

        self.server_type_comboBox = QComboBox(self)
        for blockchain_type in BlockchainType.active_types():
            self.server_type_comboBox.addItem(BlockchainType.to_text(blockchain_type))

        self.groupbox_connection_layout.addWidget(self.server_type_comboBox)

        self.stackedWidget = QStackedWidget(self)
        self.groupbox_connection_layout.addWidget(self.stackedWidget)

        # Compact Block Filters
        self.compactBlockFiltersTab = QWidget()
        self.compactBlockFiltersLayout = QFormLayout(self.compactBlockFiltersTab)
        self.compactBlockFiltersLayout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.cbf_description = QLabel()
        self.cbf_description.setWordWrap(True)
        self.cbf_description.setTextFormat(Qt.TextFormat.RichText)
        self.cbf_description.setOpenExternalLinks(True)  # Enable opening links
        self.compactBlockFiltersLayout.addRow("", self.cbf_description)

        self.stackedWidget.addWidget(self.compactBlockFiltersTab)

        # Electrum Server
        self.electrumServerTab = QWidget()
        self.electrumServerLayout = QFormLayout(self.electrumServerTab)
        self.electrumServerLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        #
        self.electrum_url_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: list(
                    np.unique(
                        [electrum_config.url for electrum_config in get_electrum_configs(network).values()]
                    )
                )
                for network in bdk.Network
            },
        )
        self.electrum_url_edit.editingFinished.connect(self.on_electrum_url_editing_finished)
        self.electrum_use_ssl_checkbox = QCheckBox()

        self.electrum_url_edit_url_label = QLabel()
        self.electrumServerLayout.addRow(self.electrum_url_edit_url_label, self.electrum_url_edit)
        self.electrum_use_ssl_checkbox_label = QLabel()
        self.electrumServerLayout.addRow(self.electrum_use_ssl_checkbox_label, self.electrum_use_ssl_checkbox)

        self.electrum_description = QLabel()
        self.electrum_description.setWordWrap(True)
        self.electrum_description.setTextFormat(Qt.TextFormat.RichText)
        self.electrum_description.setOpenExternalLinks(True)  # Enable opening links
        self.electrumServerLayout.addRow("", self.electrum_description)

        self.stackedWidget.addWidget(self.electrumServerTab)

        # Esplora Server
        self.esploraServerTab = QWidget()
        self.esploraServerLayout = QFormLayout(self.esploraServerTab)
        self.esploraServerLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.esplora_url_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: list(np.unique(list(get_esplora_urls(network).values()))) for network in bdk.Network
            },
        )

        self.esplora_url_edit_label = QLabel()
        self.esploraServerLayout.addRow(self.esplora_url_edit_label, self.esplora_url_edit)

        self.esplora_description = QLabel()
        self.esplora_description.setWordWrap(True)
        self.esplora_description.setTextFormat(Qt.TextFormat.RichText)
        self.esplora_description.setOpenExternalLinks(True)  # Enable opening links
        self.esploraServerLayout.addRow("", self.esplora_description)

        self.stackedWidget.addWidget(self.esploraServerTab)

        # RPC
        self.rpcTab = QWidget()
        self.rpcTabLayout = QFormLayout(self.rpcTab)
        self.rpcTabLayout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.rpc_ip_address_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: list(get_default_rpc_hosts(network=network).values()) for network in bdk.Network
            },
        )
        self.rpc_port_edit = QCompleterLineEdit(
            network=network,
            suggestions={
                network: [str(get_default_port(network, server_type=BlockchainType.CompactBlockFilter))]
                for network in bdk.Network
            },
        )
        self.rpc_username_edit = QCompleterLineEdit(network=network)
        self.rpc_password_edit = QCompleterLineEdit(network=network)

        self.rpc_ip_address_edit_label = QLabel()
        self.rpcTabLayout.addRow(self.rpc_ip_address_edit_label, self.rpc_ip_address_edit)
        self.rpc_port_edit_label = QLabel()
        self.rpcTabLayout.addRow(self.rpc_port_edit_label, self.rpc_port_edit)
        self.rpc_username_edit_label = QLabel()
        self.rpcTabLayout.addRow(self.rpc_username_edit_label, self.rpc_username_edit)
        self.rpc_password_edit_label = QLabel()
        self.rpcTabLayout.addRow(self.rpc_password_edit_label, self.rpc_password_edit)

        self.rpc_description = QLabel()
        self.rpc_description.setWordWrap(True)
        self.rpc_description.setTextFormat(Qt.TextFormat.RichText)
        self.rpc_description.setOpenExternalLinks(True)  # Enable opening links
        self.rpcTabLayout.addRow("", self.rpc_description)

        self.stackedWidget.addWidget(self.rpcTab)

        # mempool
        self.groupbox_blockexplorer = QGroupBox()
        self.groupbox_blockexplorer_layout = QHBoxLayout(self.groupbox_blockexplorer)
        button_mempool = QPushButton(self)
        button_mempool.setIcon(svg_tools.get_QIcon("block-explorer.svg"))
        button_mempool.clicked.connect(self.on_button_mempool_clicked)
        self.edit_mempool_url = QCompleterLineEdit(
            network=network,
            suggestions={network: list(get_mempool_url(network).values()) for network in bdk.Network},
        )
        self.groupbox_blockexplorer_layout.addWidget(button_mempool)
        self.groupbox_blockexplorer_layout.addWidget(self.edit_mempool_url)
        self._layout.addWidget(self.groupbox_blockexplorer)

        # proxy
        self.groupbox_proxy = QGroupBox()
        self.groupbox_proxy_layout = QHBoxLayout(self.groupbox_proxy)

        self.proxy_url_edit = QCompleterLineEdit(
            network=network,
            suggestions={network: ["127.0.0.1:9050"] for network in bdk.Network},
        )
        self.proxy_url_edit.textChanged.connect(self.on_proxy_url_changed)
        self.proxy_url_edit_label = QLabel()
        self.groupbox_proxy_layout.addWidget(self.proxy_url_edit_label)
        self.groupbox_proxy_layout.addWidget(self.proxy_url_edit)
        self.proxy_help_button = generate_help_website_open(
            "https://bitcoin-safe.org/en/knowledge/tor-config/",
            title="",
            tooltip=self.tr("Open Tor proxy configuration documentation"),
        )
        self.groupbox_proxy_layout.addWidget(self.proxy_help_button)

        self._layout.addWidget(self.groupbox_proxy)
        self.proxy_warning_label = NotificationBar("")
        self.proxy_warning_label.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.proxy_warning_label.set_icon(svg_tools.get_QIcon("warning.svg"))
        self._layout.addWidget(self.proxy_warning_label)

        # Create buttons and layout
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Help
            | QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.on_apply_click)
        self.button_box.rejected.connect(self.on_cancel_click)

        if help_button := self.button_box.button(QDialogButtonBox.StandardButton.Help):
            help_button.setText(self.tr("Test Connection"))
        self.button_box.helpRequested.connect(self.test_connection)

        self._layout.addWidget(self.button_box)

        # Signals and Slots
        self.network_combobox.currentIndexChanged.connect(self.on_network_change)
        self.server_type_comboBox.currentIndexChanged.connect(self.set_server_type_comboBox)

        self.original_network = network
        self.set_ui(network_configs.configs[network.name])

        self._edits_set_network(self.network)
        if self.signals:
            self.signals.language_switch.connect(self.updateUi)
        self.updateUi()

    def on_button_mempool_clicked(self):
        return webopen(self.edit_mempool_url.text())

    def updateUi(self):
        self.setWindowTitle(self.tr("Network Settings"))
        self.groupbox_connection.setTitle(self.tr("Blockchain data source"))

        self.esplora_url_edit_label.setText(self.tr("URL:"))
        self.esplora_url_edit.setPlaceholderText(self.tr("Press ⬇ arrow key for suggestions"))

        self.electrum_use_ssl_checkbox.setText(self.tr("Enable SSL"))
        self.electrum_url_edit_url_label.setText(self.tr("URL:"))
        self.electrum_url_edit.setPlaceholderText(self.tr("Press ⬇ arrow key for suggestions"))
        self.electrum_use_ssl_checkbox_label.setText(self.tr("SSL:"))

        self.rpc_ip_address_edit_label.setText(self.tr("IP Address:"))
        self.rpc_ip_address_edit.setPlaceholderText(self.tr("Press ⬇ arrow key for suggestions"))
        self.rpc_port_edit_label.setText(self.tr("Port:"))
        self.rpc_port_edit.setPlaceholderText(self.tr("Press ⬇ arrow key for suggestions"))
        self.rpc_username_edit_label.setText(self.tr("Username:"))
        self.rpc_password_edit_label.setText(self.tr("Password:"))

        self.groupbox_blockexplorer.setTitle(self.tr("Mempool Instance URL"))
        self.edit_mempool_url.setPlaceholderText(self.tr("Press ⬇ arrow key for suggestions"))

        self.proxy_warning_label.textLabel.setText(
            self.tr("The proxy does not apply to the Sync&Chat feature!")
        )
        self.proxy_url_edit_label.setText(self.tr("Proxy:"))
        if ok_button := self.button_box.button(QDialogButtonBox.StandardButton.Ok):
            ok_button.setText(self.tr("Apply && Shutdown"))

        self.proxy_warning_label.updateUi()

    def on_electrum_url_editing_finished(self):
        def get_use_ssl(url: str):
            for electrum_config in get_electrum_configs(self.network).values():
                if url.strip() == electrum_config.url.strip():
                    return electrum_config.use_ssl
            return None

        use_ssl = get_use_ssl(self.electrum_url_edit.text())
        if use_ssl is None:
            return
        logger.debug(f"set use_ssl = {use_ssl}")
        self.electrum_use_ssl = use_ssl

    def on_proxy_url_changed(self):
        is_proxy = bool(self.proxy_url_edit.text().strip())
        self.proxy_warning_label.setHidden(not is_proxy)

    def _test_connection(self, network_config: NetworkConfig) -> Tuple[str | None, bool]:
        server_connection = test_connection(network_config=network_config)

        mempool_server = test_mempool_space_server(
            url=network_config.mempool_url,
            proxies=(
                ProxyInfo.parse(network_config.proxy_url).get_requests_proxy_dict()
                if network_config.proxy_url
                else None
            ),
        )
        return server_connection, mempool_server

    def _format_test_responses(
        self, network_config: NetworkConfig, server_connection: str | None, mempool_server: bool
    ) -> str:
        def format_status(response):
            return "Success" if response else "Failed"

        response = self.tr("Responses:\n    {name}: {status}\n    Mempool Instance: {server}").format(
            name=network_config.server_type.name,
            status=format_status(server_connection),
            server=format_status(mempool_server),
        )

        if not server_connection and network_config.server_type == BlockchainType.Electrum:
            if network_config.electrum_url.startswith("https://"):
                response += "\n\n" + self.tr("Please remove the '{scheme}' from the electrum url").format(
                    scheme="https://"
                )
            if network_config.electrum_url.startswith("http://"):
                response += "\n\n" + self.tr("Please remove the '{scheme}' from the electrum url").format(
                    scheme="http://"
                )

        if not server_connection and network_config.server_type == BlockchainType.Esplora:
            if network_config.esplora_url.startswith("https://"):
                response += "\n\n" + self.tr("Are you sure '{scheme}' is correct in the esplora url?").format(
                    scheme="https://"
                )

        if network_config.proxy_url:
            if not server_connection:
                response += "\n\n" + self.tr("The format for tor addresses should be '{scheme}'").format(
                    scheme="xxxxxxx.onion:80"
                )

            if not mempool_server:
                if network_config.mempool_url.startswith("https://"):
                    response += "\n\n" + self.tr(
                        "Please try '{scheme}' at the beginning of the mempool url"
                    ).format(scheme="http://")

        return response

    def test_connection(self):
        new_network_config = self.get_network_settings_from_ui()
        server_connection, mempool_server = self._test_connection(network_config=new_network_config)

        Message(self._format_test_responses(new_network_config, server_connection, mempool_server))

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
        new_network = self.network_combobox.itemData(new_index)

        self._edits_set_network(new_network)
        self.set_ui(self.network_configs.configs[new_network.name])

    def _edits_set_network(self, network: bdk.Network):
        self.electrum_url_edit.set_network(network)
        self.esplora_url_edit.set_network(network)
        self.rpc_ip_address_edit.set_network(network)
        self.rpc_username_edit.set_network(network)
        self.rpc_password_edit.set_network(network)
        self.edit_mempool_url.set_network(network)
        self.proxy_url_edit.set_network(network)

    def add_to_completer_memory(self):
        self.electrum_url_edit.add_current_to_memory()
        self.esplora_url_edit.add_current_to_memory()
        self.rpc_ip_address_edit.add_current_to_memory()
        self.rpc_username_edit.add_current_to_memory()
        self.rpc_password_edit.add_current_to_memory()
        self.edit_mempool_url.add_current_to_memory()
        self.proxy_url_edit.add_current_to_memory()

    def on_apply_click(self):
        new_network_config = self.get_network_settings_from_ui()
        server_connection, mempool_server = self._test_connection(network_config=new_network_config)

        if not all([server_connection, mempool_server]):
            if not question_dialog(
                self.tr("Error in server connection.\n{responses}\n\n Do you want to proceed anyway?").format(
                    responses=self._format_test_responses(
                        new_network_config, server_connection, mempool_server
                    )
                )
            ):
                return

        new_network = self.network

        self.add_to_completer_memory()

        self.network_configs.configs[self.network.name] = new_network_config

        self.close()
        self.signal_apply_and_shutdown.emit(new_network)

    def on_cancel_click(self):
        self.set_ui(self.network_configs.configs[self.original_network.name])
        self.signal_cancel.emit()
        self.close()

    # Override keyPressEvent method
    def keyPressEvent(self, a0: QKeyEvent | None):
        # Check if the pressed key is 'Esc'
        if a0 and a0.key() == Qt.Key.Key_Escape:
            # Close the widget
            self.on_cancel_click()

        super().keyPressEvent(a0)

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

    # Properties for all user entries
    @property
    def network(self) -> bdk.Network:
        return self.network_combobox.currentData()

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
        return ensure_scheme(url)

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
        except Exception as e:
            logger.debug(f"{self.__class__.__name__}: {e}")
            return self.network_configs.configs[self.network.name].rpc_port

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
    def proxy_url(self) -> str | None:
        text = self.proxy_url_edit.text()
        return text if text else None

    @proxy_url.setter
    def proxy_url(self, url: str | None):
        self.proxy_url_edit.setText(url if url else "")
        self.on_proxy_url_changed()
