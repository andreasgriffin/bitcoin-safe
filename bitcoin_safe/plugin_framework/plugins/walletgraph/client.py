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

from __future__ import annotations

import datetime
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.packaged_tx_like import PackagedTxLike, UiElements
from bitcoin_safe.gui.qt.util import ColorScheme, Message, MessageType, svg_tools
from bitcoin_safe.i18n import translate
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_conditions import PluginConditions
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServerView
from bitcoin_safe.plugin_framework.plugins.walletgraph.wallet_graph_items import (
    ENABLE_WALLET_GRAPH_TOOLTIPS,
)
from bitcoin_safe.plugin_framework.plugins.walletgraph.wallet_graph_view import (
    UtxoEllipseItem,
    WalletGraphView,
)
from bitcoin_safe.pythonbdk_types import FullTxDetail, PythonUtxo
from bitcoin_safe.signals import Signals, UpdateFilter

logger = logging.getLogger(__name__)


class WalletGraphClient(PluginClient):
    plugin_conditions = PluginConditions()
    required_permissions: set[PluginPermission] = {
        PluginPermission.WALLET,
        PluginPermission.WALLET_SIGNALS,
    }
    title = translate("WalletGraphClient", "Wallet Graph")
    description = translate(
        "WalletGraphClient",
        "Visualize how your wallet transactions create and spend UTXOs across time.",
    )
    provider = "Bitcoin Safe"

    @staticmethod
    def cls_kwargs(signals: Signals, network: bdk.Network):
        return {
            "signals": signals,
            "network": network,
        }

    def __init__(
        self,
        signals: Signals,
        network: bdk.Network,
        enabled: bool = False,
    ) -> None:
        """Initialize instance."""
        super().__init__(enabled=enabled, icon=svg_tools.get_QIcon("wallet-graph-icon.svg"))
        self.signals = signals
        self.network = network
        self.wallet_id: str | None = None

        self._forced_update = False
        self._pending_update = False

        self.graph_view = WalletGraphView(network=network)

        self.refresh_button = QPushButton()
        self.refresh_button.setEnabled(enabled)

        self.export_button = QPushButton()
        self.export_button.setEnabled(False)

        self.instructions_label = QLabel(
            translate(
                "WalletGraphClient",
                "Drag to explore the timeline. Click or right-click a "
                "transaction, txid, or UTXO for options.",
            )
        )
        self.instructions_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(self.instructions_label)
        controls.addStretch()
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        layout.addWidget(self.graph_view)

        self.signal_tracker.connect(self.graph_view.transactionClicked, self._on_transaction_clicked)
        self.signal_tracker.connect(cast(SignalProtocol[[]], self.refresh_button.clicked), self.refresh_graph)
        self.signal_tracker.connect(
            cast(SignalProtocol[[]], self.export_button.clicked), self.on_export_graph
        )
        self.updateUi()

    def get_widget(self) -> QWidget:
        """Get widget."""
        return self

    def set_server_view(self, server: PluginServerView) -> None:
        """Save connection details."""
        super().set_server_view(server=server)
        self.wallet_id = server.wallet_id
        if self.enabled:
            self.refresh_graph()

    def load(self) -> None:
        """Load."""
        self._connect_wallet_signal()
        self.refresh_graph()
        logger.debug("WalletGraphClient loaded")

    def unload(self) -> None:
        """Unload."""
        self._disconnect_wallet_signal()
        self.graph_view.clear()
        logger.debug("WalletGraphClient unloaded")

    def set_enabled(self, value: bool) -> None:
        """On set enabled."""
        super().set_enabled(value)
        self.refresh_button.setEnabled(value)

    def maybe_defer_update(self) -> bool:
        """Returns whether we should defer an update/refresh."""
        defer = not self._forced_update and (not self.isVisible())
        # side-effect: if we decide to defer update, the state will become stale:
        self._pending_update = defer
        return defer

    def showEvent(self, a0: QShowEvent | None) -> None:
        """ShowEvent."""
        super().showEvent(a0)
        if a0 and a0.isAccepted() and self._pending_update:
            self._forced_update = True
            self.refresh_graph()
            self._forced_update = False

    def refresh_graph(self) -> None:
        """Refresh graph."""

        if not self.enabled or not self.server or not self.server.wallet_signals:
            return

        if self.maybe_defer_update():
            return

        wallet = self.server.get_wallet()
        if not wallet:
            self.graph_view.clear()
            self.export_button.setEnabled(False)
            return
        details_dict = wallet.get_dict_fulltxdetail()
        # ensure it is sorted, such that parent child relationships can be resolved
        full_tx_details = [
            full_tx_detail
            for tx in wallet.sorted_delta_list_transactions()
            if (full_tx_detail := details_dict.get(tx.txid))
        ]
        if not full_tx_details:
            self.graph_view.clear()
            self.export_button.setEnabled(False)
            return

        self.graph_view.render_graph(
            wallet=wallet, full_tx_details=full_tx_details, wallet_signals=self.server.wallet_signals
        )
        self.export_button.setEnabled(bool(full_tx_details))

    def _on_transaction_clicked(self, txid: str) -> None:
        """On transaction clicked."""
        self.signals.open_tx_like.emit(PackagedTxLike(tx_like=txid, focus_ui_elements=UiElements.diagram))

    def _connect_wallet_signal(self) -> None:
        """Connect wallet signal."""
        if not self.server or not self.wallet_id or not self.server.wallet_signals:
            return
        self.signal_tracker.connect(self.server.wallet_signals.updated, self.on_wallet_updated)

    def _disconnect_wallet_signal(self) -> None:
        """Disconnect wallet signal."""
        if not self.server or not self.server.wallet_signals:
            return
        try:
            self.server.wallet_signals.updated.disconnect(self.on_wallet_updated)
        except TypeError:
            pass

    def on_wallet_updated(self, update_filter: UpdateFilter) -> None:
        """On wallet updated."""
        if not self.enabled:
            return
        logger.debug("WalletGraphClient refreshing after wallet update")
        if self.graph_view.is_drawing:
            return
        self.refresh_graph()

    def on_export_graph(self) -> None:
        """On export graph."""
        if not self.server or not self.graph_view.current_details or not self.graph_view.current_wallet:
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export wallet graph"),
            f"{self.server.wallet_id}.graphml",
            filter="GraphML (*.graphml);;All Files (*.*)",
            initialFilter="GraphML (*.graphml)",
        )
        if not file_path:
            return

        graphml = self._build_graphml(details=self.graph_view.current_details)
        try:
            with open(file_path, "wb") as fp:
                fp.write(graphml)
        except OSError as exc:
            Message(
                self.tr("Could not export the wallet graph: {error}").format(error=str(exc)),
                type=MessageType.Error,
                parent=self,
            )
            logger.exception("Failed to export wallet graph")
            return

        Message(
            self.tr("Wallet graph exported to {path}").format(path=file_path),
            type=MessageType.Info,
            parent=self,
        )

    def _build_graphml(self, details: Iterable[FullTxDetail]) -> bytes:
        # Ensure the default GraphML namespace is registered (avoids ns0 prefixes)
        """Build graphml."""
        ET.register_namespace("", "http://graphml.graphdrawing.org/xmlns")
        root = ET.Element("graphml")

        key_specs = [
            ("d0", "node", "type", "string"),
            ("d1", "node", "timestamp", "string"),
            ("d2", "node", "label", "string"),
            ("d3", "node", "address", "string"),
            ("d4", "node", "status", "string"),
            ("d5", "node", "value_sats", "long"),  # prefer numeric type for sats
            ("d6", "node", "color", "string"),
            ("d7", "node", "is_mine", "boolean"),
            ("d8", "node", "wallet_label", "string"),
            ("d9", "node", "wallet_label_category", "string"),
            ("d10", "node", "wallet_label_last_modified", "string"),
            ("d11", "node", "wallet_label_origin", "string"),
            ("d12", "node", "wallet_label_spendable", "boolean"),
            ("d13", "node", "wallet_categories", "string"),
            ("d14", "node", "wallet_name", "string"),
        ]
        for key_id, domain, name, key_type in key_specs:
            ET.SubElement(
                root,
                "key",
                attrib={"for": domain, "attr.name": name, "attr.type": key_type},
                id=key_id,
            )

        graph = ET.SubElement(root, "graph", id="G", edgedefault="directed")

        utxo_nodes: dict[str, PythonUtxo] = {}
        edge_counter = 0

        def _utxo_id(utxo: PythonUtxo) -> str:
            # Single source of truth for UTXO node ids
            """Utxo id."""
            return str(utxo.outpoint)

        fallback_base = time.time()
        wallet = self.graph_view.current_wallet

        timestamped_details = [
            (detail, self.graph_view._detail_timestamp(detail, fallback_base + idx))
            for idx, detail in enumerate(details)
        ]
        timestamped_details.sort(key=lambda item: item[1])

        for detail, timestamp in timestamped_details:
            tx_node = ET.SubElement(graph, "node", id=detail.txid)
            self._set_data(tx_node, "d0", "transaction")

            # Use explicit UTC ISO-8601 with 'Z'
            ts_iso = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc).isoformat()
            if ts_iso.endswith("+00:00"):
                ts_iso = ts_iso[:-6] + "Z"
            self._set_data(tx_node, "d1", ts_iso)

            self._set_data(tx_node, "d2", detail.txid)

            tx_label = ""
            categories = []
            metadata_ref: str | None = None
            if wallet:
                metadata_ref = detail.txid
                tx_label = wallet.get_label_for_txid(detail.txid) or ""

                categories = wallet.get_categories_for_txid(detail.txid) or []

            self._apply_wallet_label_metadata(
                tx_node,
                metadata_ref,
                wallet_label=tx_label,
                categories=categories,
            )

            # Outputs: edge from transaction -> UTXO
            for _, _utxo in detail.outputs.items():
                if not _utxo:
                    continue
                node_id = _utxo_id(_utxo)
                if node_id not in utxo_nodes:
                    utxo_nodes[node_id] = _utxo
                    self._create_utxo_node(graph, _utxo)  # must create with the same node_id
                ET.SubElement(
                    graph,
                    "edge",
                    id=f"e{edge_counter}",
                    source=detail.txid,
                    target=node_id,
                )
                edge_counter += 1

            # Inputs: edge from UTXO -> transaction
            for index, (_, utxo) in enumerate(detail.inputs.items()):
                if utxo:
                    node_id = _utxo_id(utxo)
                    if node_id not in utxo_nodes:
                        utxo_nodes[node_id] = utxo
                        self._create_utxo_node(graph, utxo)
                    ET.SubElement(
                        graph,
                        "edge",
                        id=f"e{edge_counter}",
                        source=node_id,
                        target=detail.txid,
                    )
                    edge_counter += 1
                    continue

                # External/spent-but-unknown input
                external_id = f"external-{detail.txid}-{index}"
                node = ET.SubElement(graph, "node", id=external_id)
                self._set_data(node, "d0", "external_utxo")
                self._set_data(node, "d2", external_id)
                self._set_data(node, "d4", "spent")
                self._set_data(node, "d7", "false")
                self._set_data(node, "d6", ColorScheme.Purple.as_color().name())
                self._apply_wallet_label_metadata(node, None, wallet_label="", categories=[])
                ET.SubElement(
                    graph,
                    "edge",
                    id=f"e{edge_counter}",
                    source=external_id,
                    target=detail.txid,
                )
                edge_counter += 1

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _create_utxo_node(self, graph: ET.Element, utxo: PythonUtxo) -> None:
        """Create utxo node."""
        if not self.server or not self.server.wallet_signals:
            return
        node_id = str(utxo.outpoint)
        node = ET.SubElement(graph, "node", id=node_id)
        status = "spent" if utxo.is_spent_by_txid else "unspent"
        wallet = self.graph_view.current_wallet
        color = UtxoEllipseItem._color_for_utxo(
            utxo, wallet=wallet, wallet_signals=self.server.wallet_signals
        )
        is_mine = wallet.is_my_address(utxo.address) if wallet else False
        self._set_data(node, "d0", "utxo")
        self._set_data(node, "d2", node_id)
        self._set_data(node, "d3", utxo.address)
        self._set_data(node, "d4", status)
        self._set_data(node, "d5", str(utxo.value))
        self._set_data(node, "d6", color.name())
        self._set_data(node, "d7", "true" if is_mine else "false")

        utxo_label = ""
        metadata_ref: str | None = None
        if wallet:
            metadata_ref = utxo.address
            utxo_label = wallet.get_label_for_address(utxo.address) or ""

        self._apply_wallet_label_metadata(node, metadata_ref, wallet_label=utxo_label)

    @staticmethod
    def _set_data(node: ET.Element, key: str, value: str | bool | int | float | None) -> None:
        """Set data."""
        data_element = ET.SubElement(node, "data", key=key)
        if isinstance(value, bool):
            data_element.text = "true" if value else "false"
        elif value is None:
            data_element.text = ""
        else:
            data_element.text = str(value)

    @staticmethod
    def _format_timestamp(timestamp: float | None) -> str | None:
        """Format timestamp."""
        if timestamp is None:
            return None
        dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        iso = dt.isoformat()
        if iso.endswith("+00:00"):
            iso = iso[:-6] + "Z"
        return iso

    def _apply_wallet_label_metadata(
        self,
        node: ET.Element,
        ref: str | None,
        *,
        wallet_label: str = "",
        categories: Iterable[str] | None = None,
    ) -> None:
        """Apply wallet label metadata."""
        wallet_label_value = wallet_label or ""
        categories_value = ""
        if categories:
            categories_value = ", ".join(str(cat) for cat in categories if cat is not None)

        wallet = self.graph_view.current_wallet
        wallet_name_value = self._get_wallet_name(wallet)

        category_value = ""
        timestamp_iso = ""
        origin_value = ""
        spendable_value: bool | None | str = ""

        labels = wallet.labels if wallet else None
        if ref and labels:
            category_value = labels.get_category_raw(ref) or ""

            if not category_value and hasattr(labels, "get_category"):
                category_value = labels.get_category(ref) or ""

            timestamp_iso = self._format_timestamp(labels.get_timestamp(ref)) or ""

            label_entry = None
            if hasattr(labels, "data"):
                label_entry = labels.data.get(ref)

            if label_entry:
                origin_value = getattr(label_entry, "origin", "") or ""
                spendable = getattr(label_entry, "spendable", None)
                if spendable is not None:
                    spendable_value = bool(spendable)
                else:
                    spendable_value = ""

        self._set_data(node, "d8", wallet_label_value)
        self._set_data(node, "d9", category_value)
        self._set_data(node, "d10", timestamp_iso)
        self._set_data(node, "d11", origin_value)
        self._set_data(node, "d12", spendable_value)
        self._set_data(node, "d13", categories_value)
        self._set_data(node, "d14", wallet_name_value)

    @staticmethod
    def _get_wallet_name(wallet: object | None) -> str:
        """Get wallet name."""
        if not wallet:
            return ""

        for attr in ("id", "name", "wallet_name"):
            value = getattr(wallet, attr, None)
            if value:
                return str(value)
        return ""

    def updateUi(self) -> None:
        """UpdateUi."""
        self.export_button.setText(self.tr("Export graph…"))
        self.refresh_button.setText(self.tr("Refresh"))
        if ENABLE_WALLET_GRAPH_TOOLTIPS:
            self.refresh_button.setToolTip(self.tr("Redraw the wallet graph."))
        self.instructions_label.setText(
            self.tr(
                "Drag to explore the timeline. Click or right-click a transaction, txid, or UTXO for options."
            )
        )
        super().updateUi()

    def close(self) -> bool:
        return super().close()
