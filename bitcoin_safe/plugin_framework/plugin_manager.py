#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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
#

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.storage import BaseSaveableClass, filtered_for_init
from bitcoin_safe_lib.util import fast_version
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.category_manager.category_core import CategoryCore
from bitcoin_safe.gui.qt.invisible_scroll_area import InvisibleScrollArea
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode
from bitcoin_safe.gui.qt.util import Message, MessageType, set_no_margins, svg_tools
from bitcoin_safe.plugin_framework.builtin_plugins import (
    BUILTIN_PLUGIN_BUNDLES,
    BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS,
    BUILTIN_PLUGIN_CLIENT_CLASSES,
)
from bitcoin_safe.plugin_framework.external_plugin_registry import (
    ExternalPluginCatalogEntry,
    ExternalPluginError,
    ExternalPluginRegistry,
    InstalledSourcePluginMetadata,
    VerifiedExternalPluginBundle,
    VerifiedPluginSourceManifest,
)
from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
from bitcoin_safe.plugin_framework.plugin_bundle import (
    PluginRuntimeContext,
    RuntimePluginBundle,
    create_runtime_plugin_clients,
    normalize_static_plugin_bundle,
)
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_identity import PluginSource as PluginClientSource
from bitcoin_safe.plugin_framework.plugin_list_widget import (
    BasePluginWidget,
    PaidPluginWidget,
    PluginListWidget,
    SectionHeader,
)
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission, PluginServer
from bitcoin_safe.plugin_framework.plugin_source_widget import SourceCatalogItem
from bitcoin_safe.plugin_framework.plugins.business_plan.client import BusinessPlanItem
from bitcoin_safe.plugin_framework.subscription_manager import SubscriptionManager
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup
from bitcoin_safe.signals import T, WalletFunctions

from .plugin_source_widget import AddPluginSourceDialog, SourceManagementDialog

logger = logging.getLogger(__name__)


class PluginManagerWidget(QWidget):
    signal_sources_requested = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        icon_size: tuple[int, int] = (40, 40),
        business_plan: BusinessPlanItem | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.business_plan: None | BusinessPlanItem = business_plan
        self.business_plan_widget: PaidPluginWidget | None = None
        self.signal_tracker_business_plugin = SignalTracker()
        self.icon_size = icon_size

        scroll = InvisibleScrollArea(self)
        scroll.setWidgetResizable(True)

        self.container_layout = QVBoxLayout(scroll.content_widget)
        self.container_layout.setSpacing(18)

        self.business_plan_section = QWidget(scroll.content_widget)
        self.business_plan_section_layout = QVBoxLayout(self.business_plan_section)
        self.business_plan_section_layout.setContentsMargins(0, 0, 0, 0)
        self.business_plan_section_layout.setSpacing(10)
        self.container_layout.addWidget(self.business_plan_section)

        self.business_plan_header = SectionHeader(
            self.tr("Business plan"),
            self.tr("Applies to all paid plugins and subscription-gated service fees."),
            self.business_plan_section,
        )
        self.business_plan_section_layout.addWidget(self.business_plan_header)

        self.business_plan_container = QFrame(self.business_plan_section)
        self.business_plan_container.setObjectName("businessPlanContainer")
        self.business_plan_container.setStyleSheet(
            """
            QFrame#businessPlanContainer {
                border: 1px solid palette(midlight);
                border-radius: 8px;
                background: palette(alternate-base);
            }
            """
        )
        self.business_plan_container_layout = QVBoxLayout(self.business_plan_container)
        self.business_plan_container_layout.setContentsMargins(8, 8, 8, 8)
        self.business_plan_container_layout.setSpacing(0)
        self.business_plan_section_layout.addWidget(self.business_plan_container)

        self.plugin_list_widget = PluginListWidget(icon_size=icon_size, parent=scroll.content_widget)
        self.header_button_row = QWidget(self.plugin_list_widget)
        self.header_button_layout = QHBoxLayout(self.header_button_row)
        self.header_button_layout.setContentsMargins(0, 0, 0, 0)
        self.header_button_layout.setSpacing(6)
        self.sources_button = QPushButton(self.header_button_row)
        self.header_button_layout.addWidget(self.sources_button)
        self.sources_button.clicked.connect(self.signal_sources_requested.emit)
        self.plugin_list_widget.plugins_header.add_title_widget(self.header_button_row)
        self.container_layout.addWidget(self.plugin_list_widget)

        layout = QVBoxLayout(self)
        set_no_margins(layout)
        layout.addWidget(scroll)

        self.node = SidebarNode[object](
            data=self,
            widget=self,
            icon=svg_tools.get_QIcon("bi--gear.svg"),
            title="",
        )
        self.updateUi()

    @property
    def plugins_header(self) -> SectionHeader:
        return self.plugin_list_widget.plugins_header

    @property
    def plugins_widgets(self) -> list[BasePluginWidget]:
        return self.plugin_list_widget.plugins_widgets

    def set_plugins(
        self, plugins: list[PluginClient | SourceCatalogItem], rebuild_sidebar: bool = True
    ) -> None:
        selected_plugin_widget = self.node.currentWidget()
        self.business_plan_widget = None
        while self.business_plan_container_layout.count():
            item = self.business_plan_container_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.close()
                widget.hide()

        self.plugin_list_widget.set_plugins(
            [plugin for plugin in plugins if not isinstance(plugin, BusinessPlanItem)]
        )
        self.signal_tracker_business_plugin.disconnect_all()
        if rebuild_sidebar:
            self.node.clearChildren()

        tracked_price_plugins: list[PaidPluginClient] = []
        for plugin in plugins:
            if isinstance(plugin, PaidPluginClient) and plugin not in tracked_price_plugins:
                tracked_price_plugins.append(plugin)
                self.signal_tracker_business_plugin.connect(
                    plugin.signal_price_texts_changed,
                    self._update_price_texts,
                )
            if isinstance(plugin, BusinessPlanItem):
                self.business_plan = plugin
                self.business_plan_widget = self.business_plan.create_plugin_widget(
                    icon_size=self.icon_size,
                    parent=self.business_plan_container,
                )
                self.business_plan_container_layout.addWidget(self.business_plan_widget)
            elif rebuild_sidebar:
                if plugin.node:
                    self.node.addChildNode(plugin.node, focus=False)

        if self.business_plan and self.business_plan_widget is None:
            self.business_plan_widget = self.business_plan.create_plugin_widget(
                icon_size=self.icon_size,
                parent=self.business_plan_container,
            )
            self.business_plan_container_layout.addWidget(self.business_plan_widget)
            if self.business_plan not in tracked_price_plugins:
                tracked_price_plugins.append(self.business_plan)
                self.signal_tracker_business_plugin.connect(
                    self.business_plan.signal_price_texts_changed,
                    self._update_price_texts,
                )
        self.business_plan_section.setVisible(self.business_plan_widget is not None)

        self._update_price_texts()
        for plugin in tracked_price_plugins:
            plugin.ensure_price_texts()
        if rebuild_sidebar and selected_plugin_widget is not None:
            selected_node = self.node.findNodeByWidget(selected_plugin_widget)
            if selected_node is not None:
                selected_node.select()

    def updateUi(self) -> None:
        if self.business_plan_widget:
            self.business_plan_widget.updateUi()
        self.node.setTitle(self.tr("Plugins"))
        self.business_plan_header.title_label.setText(self.tr("Business plan"))
        self.business_plan_header.description_label.setText(
            self.tr("Applies to all paid plugins and subscription-gated service fees.")
        )
        self.business_plan_header.description_label.setVisible(True)
        self.sources_button.setText(self.tr("Sources"))
        self.plugin_list_widget.updateUi()

    def close(self) -> bool:
        self.signal_tracker_business_plugin.disconnect_all()
        self.plugin_list_widget.close()
        if self.business_plan_widget:
            self.business_plan_widget.close()
        return super().close()

    def _update_price_texts(self) -> None:
        if self.business_plan_widget:
            self.business_plan_widget.updateUi()
        self.plugin_list_widget.updateUi()


class PluginManager(BaseSaveableClass):
    _base_known_classes = {
        **BaseSaveableClass.known_classes,
        PluginClient.__name__: PluginClient,
        PluginPermission.__name__: PluginPermission,
        **{client_cls.__name__: client_cls for client_cls in BUILTIN_PLUGIN_CLIENT_CLASSES},
    }
    known_classes = _base_known_classes.copy()
    VERSION = "0.0.17"

    signal_client_action = cast(SignalProtocol[[PluginClient]], pyqtSignal(PluginClient))
    client_classes: list[type[PluginClient]] = [*BUILTIN_PLUGIN_CLIENT_CLASSES]
    _base_client_classes = list(client_classes)

    @staticmethod
    def _external_bundle_state_signature(
        bundles: dict[str, VerifiedExternalPluginBundle],
    ) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        return tuple(
            sorted(
                (
                    bundle_id,
                    bundle.folder_hash,
                    tuple(sorted(client_cls.__name__ for client_cls in bundle.runtime_bundle.client_classes)),
                )
                for bundle_id, bundle in bundles.items()
            )
        )

    @staticmethod
    def cls_kwargs(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        external_registry: ExternalPluginRegistry,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
        external_bundles: dict[str, VerifiedExternalPluginBundle] | None = None,
    ) -> dict[str, object]:
        return {
            "wallet_functions": wallet_functions,
            "config": config,
            "fx": fx,
            "loop_in_thread": loop_in_thread,
            "subscription_price_lookup": subscription_price_lookup,
            "external_registry": external_registry,
            "external_bundles": external_bundles,
        }

    @staticmethod
    def _plugin_runtime_context(
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        parent: QWidget | None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
    ) -> PluginRuntimeContext:
        return PluginRuntimeContext(
            wallet_functions=wallet_functions,
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            subscription_price_lookup=subscription_price_lookup,
            parent=parent,
        )

    @classmethod
    def class_kwargs(
        cls,
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        parent: QWidget | None,
        external_registry: ExternalPluginRegistry,
    ) -> dict[str, dict[str, object]]:
        subscription_price_lookup = SubscriptionPriceLookup()
        runtime_context = cls._plugin_runtime_context(
            wallet_functions=wallet_functions,
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            parent=parent,
            subscription_price_lookup=subscription_price_lookup,
        )
        class_kwargs = {
            cls.__name__: cls.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
                external_registry=external_registry,
                subscription_price_lookup=subscription_price_lookup,
            ),
            BusinessPlanItem.__name__: BusinessPlanItem.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
                fx=fx,
                subscription_price_lookup=subscription_price_lookup,
            ),
            SubscriptionManager.__name__: SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
            ),
        }
        for runtime_bundle in cls._static_runtime_bundles(runtime_context):
            class_kwargs.update(runtime_bundle.class_kwargs)
        external_bundles = cls._refresh_external_state(runtime_context, external_registry)
        for bundle in external_bundles.values():
            class_kwargs.update(bundle.runtime_bundle.class_kwargs)
        class_kwargs[cls.__name__].update(
            {
                "external_bundles": external_bundles,
            }
        )
        return class_kwargs

    def __init__(
        self,
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        external_registry: ExternalPluginRegistry,
        clients: list[PluginClient] | None = None,
        serialized_client_dumps: list[str] | None = None,
        plugin_permissions: dict[str, set[PluginPermission]] | None = None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
        external_bundles: dict[str, VerifiedExternalPluginBundle] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__()
        self.network = config.network
        self.parent = parent
        self.wallet_functions = wallet_functions
        self.config = config
        self.loop_in_thread = loop_in_thread
        self.fx = fx
        self.subscription_price_lookup = (
            subscription_price_lookup
            if subscription_price_lookup is not None
            else SubscriptionPriceLookup(parent=None)
        )
        self._current_descriptor: bdk.Descriptor | None = None
        self._current_wallet_id: str | None = None
        self._current_category_core: CategoryCore | None = None
        self.external_registry = external_registry
        # `external_bundles` is the current runtime view of installed external plugin bundles.
        # It contains the loaded bundle metadata plus the client classes exported by each bundle.
        # During wallet deserialization `class_kwargs()` can inject the already-discovered
        # bundles directly so we do not have to rediscover them again in this constructor.
        self.external_bundles: dict[str, VerifiedExternalPluginBundle]
        self._external_state_loaded: bool
        if external_bundles is None:
            self.external_bundles = {}
            self._external_state_loaded = False
        else:
            self.external_bundles = external_bundles
            self._external_state_loaded = True
        self.external_client_classes: list[type[PluginClient]] = [
            client_cls
            for bundle in self.external_bundles.values()
            for client_cls in bundle.runtime_bundle.client_classes
        ]
        self.source_catalog_items: list[SourceCatalogItem] = []
        self.available_source_plugins_by_bundle_id: dict[str, ExternalPluginCatalogEntry] = {}
        self.clients: list[PluginClient] = clients if clients else []
        self.serialized_client_dumps: list[str] = self._merge_serialized_client_payloads(
            [payload for payload in serialized_client_dumps or [] if isinstance(payload, str)]
        )
        self.plugin_server: PluginServer | None = None
        self.plugin_permissions: dict[str, set[PluginPermission]] = (
            plugin_permissions if plugin_permissions else {}
        )
        self._client_registered_callbacks: list[Callable[[PluginClient], None]] = []
        self._source_management_dialog: SourceManagementDialog | None = None
        self.signal_tracker = SignalTracker()
        self.signal_tracker.connect(self.wallet_functions.signals.language_switch, self._on_language_switch)
        self.client_signal_tracker = SignalTracker()
        self._startup_source_refresh_timer: QTimer | None = None

        for client in list(self.clients):
            self._register_client(client=client)

        self.widget = PluginManagerWidget(parent=parent)
        self.widget.signal_sources_requested.connect(self.show_plugin_sources_dialog)
        self._rebuild_source_catalog_items()
        for client in self.clients:
            self._sync_external_client_state(client)
        self._schedule_startup_source_refresh()

    @staticmethod
    def _serialize_client_dump_dict(dct: dict[str, Any]) -> str:
        """Serialize one plugin client dump dict into a raw JSON payload string."""
        return BaseSaveableClass.dumps_object(dct)

    @classmethod
    def _serialize_client_payload(cls, client: PluginClient) -> str:
        """Serialize a live plugin client into the raw payload format used for persistence."""
        return cls._serialize_client_dump_dict(client.dump())

    @staticmethod
    def _parse_client_payload(payload: str) -> dict[str, Any] | None:
        """Parse a persisted raw plugin payload without triggering object-hook deserialization."""
        try:
            parsed = json.loads(payload)
        except Exception as exc:
            logger.warning("Could not parse serialized plugin client payload: %s", exc)
            return None
        if not isinstance(parsed, dict):
            logger.warning("Serialized plugin client payload is not a dict.")
            return None
        return parsed

    @staticmethod
    def _payload_identity_from_dict(payload_dict: dict[str, Any]) -> str | None:
        """Extract the stable plugin identity used to dedupe persisted client payloads."""
        if isinstance((plugin_id := payload_dict.get("plugin_id")), str) and plugin_id.strip():
            return plugin_id.strip()
        if not isinstance((class_name := payload_dict.get("__class__")), str) or not class_name.strip():
            return None
        if (
            payload_dict.get("plugin_source") == PluginClientSource.EXTERNAL.value
            and isinstance((plugin_bundle_id := payload_dict.get("plugin_bundle_id")), str)
            and plugin_bundle_id.strip()
        ):
            return PluginClient.build_plugin_id(
                plugin_source=PluginClientSource.EXTERNAL,
                plugin_bundle_id=plugin_bundle_id.strip(),
                class_name=class_name.strip(),
            )
        return class_name.strip()

    @classmethod
    def _payload_identity(cls, payload: str) -> str | None:
        """Resolve the stable identity for one serialized plugin payload."""
        payload_dict = cls._parse_client_payload(payload)
        if payload_dict is None:
            return None
        return cls._payload_identity_from_dict(payload_dict)

    @classmethod
    def _merge_serialized_client_payloads(cls, payloads_ascending_relevance: list[str]) -> list[str]:
        """Deduplicate payloads, keeping the last payload seen for each identity."""
        ordered_payloads: list[str] = []
        payload_by_key: dict[str, str] = {}
        anonymous_payloads: list[str] = []
        seen_anonymous_payloads: set[str] = set()

        for payload in payloads_ascending_relevance:
            identity = cls._payload_identity(payload)
            if identity is None:
                if payload not in seen_anonymous_payloads:
                    anonymous_payloads.append(payload)
                    seen_anonymous_payloads.add(payload)
                continue
            if identity not in payload_by_key:
                ordered_payloads.append(identity)
            payload_by_key[identity] = payload

        return [payload_by_key[identity] for identity in ordered_payloads] + anonymous_payloads

    @classmethod
    def _restore_client_from_payload(
        cls,
        payload: str,
        class_kwargs: dict[str, dict[str, object]] | None = None,
    ) -> PluginClient | None:
        """Best-effort restore of one serialized client payload into a live PluginClient."""
        payload_dict = cls._parse_client_payload(payload)
        if payload_dict is None:
            return None

        class_name = payload_dict.get("__class__")
        if not isinstance(class_name, str) or not class_name.strip():
            logger.warning("Serialized plugin client payload is missing __class__.")
            return None

        candidate_cls = cls.known_classes.get(class_name)
        if not isinstance(candidate_cls, type) or not issubclass(candidate_cls, PluginClient):
            logger.warning("Could not restore plugin client payload for unknown class %s.", class_name)
            return None

        try:
            restored = candidate_cls._from_dumps(payload, class_kwargs=class_kwargs)
        except Exception as exc:
            logger.warning("Could not restore plugin client payload for %s: %s", class_name, exc)
            logger.debug("Failed plugin client payload", exc_info=True)
            return None

        if not isinstance(restored, PluginClient):
            logger.warning(
                "Deserializing plugin client payload for %s did not produce a PluginClient.", class_name
            )
            return None
        return restored

    @classmethod
    def _restore_clients_from_payloads(
        cls,
        payloads: list[str],
        class_kwargs: dict[str, dict[str, object]] | None = None,
    ) -> tuple[list[PluginClient], list[str]]:
        """Restore as many persisted payloads as possible and keep the rest pending."""
        restored_clients: list[PluginClient] = []
        pending_payloads: list[str] = []

        for payload in payloads:
            restored_client = cls._restore_client_from_payload(payload, class_kwargs=class_kwargs)
            if restored_client is None:
                pending_payloads.append(payload)
                continue
            restored_clients.append(restored_client)

        return restored_clients, cls._merge_serialized_client_payloads(pending_payloads)

    @classmethod
    def _runtime_manager_class_kwargs(
        cls,
        wallet_functions: WalletFunctions,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        subscription_price_lookup: SubscriptionPriceLookup,
        parent: QWidget | None,
        external_bundles: dict[str, VerifiedExternalPluginBundle],
        external_registry: ExternalPluginRegistry,
    ) -> dict[str, dict[str, object]]:
        """Build the runtime class kwargs map used when restoring serialized plugin clients."""
        runtime_context = cls._plugin_runtime_context(
            wallet_functions=wallet_functions,
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            subscription_price_lookup=subscription_price_lookup,
            parent=parent,
        )
        class_kwargs: dict[str, dict[str, object]] = {
            cls.__name__: cls.cls_kwargs(
                wallet_functions=wallet_functions,
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
                subscription_price_lookup=subscription_price_lookup,
                external_registry=external_registry,
            ),
            BusinessPlanItem.__name__: BusinessPlanItem.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
                fx=fx,
                subscription_price_lookup=subscription_price_lookup,
            ),
            SubscriptionManager.__name__: SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
            ),
        }
        for runtime_bundle in cls._static_runtime_bundles(runtime_context):
            class_kwargs.update(runtime_bundle.class_kwargs)
        for bundle in external_bundles.values():
            class_kwargs.update(bundle.runtime_bundle.class_kwargs)
        return class_kwargs

    def _class_kwargs_for_runtime(self) -> dict[str, dict[str, object]]:
        """Get class kwargs for the manager's current runtime plugin configuration."""
        return self._runtime_manager_class_kwargs(
            wallet_functions=self.wallet_functions,
            config=self.config,
            fx=self.fx,
            loop_in_thread=self.loop_in_thread,
            subscription_price_lookup=self.subscription_price_lookup,
            parent=self.parent,
            external_bundles=self.external_bundles,
            external_registry=self.external_registry,
        )

    def _restore_pending_clients_by_class(
        self,
        candidate_classes: set[type[PluginClient]],
    ) -> dict[type[PluginClient], PluginClient]:
        """Retry pending payloads for currently available client classes and keep failures pending."""
        if not self.serialized_client_dumps:
            return {}

        restored_by_class: dict[type[PluginClient], PluginClient] = {}
        remaining_payloads: list[str] = []
        class_kwargs = self._class_kwargs_for_runtime()

        for payload in self.serialized_client_dumps:
            payload_dict = self._parse_client_payload(payload)
            if payload_dict is None:
                remaining_payloads.append(payload)
                continue

            class_name = payload_dict.get("__class__")
            if not isinstance(class_name, str):
                remaining_payloads.append(payload)
                continue

            candidate_cls = next((cls for cls in candidate_classes if cls.__name__ == class_name), None)
            if candidate_cls is None or candidate_cls in restored_by_class:
                remaining_payloads.append(payload)
                continue

            restored_client = self._restore_client_from_payload(payload, class_kwargs=class_kwargs)
            if restored_client is None:
                remaining_payloads.append(payload)
                continue
            restored_by_class[candidate_cls] = restored_client

        self.serialized_client_dumps = self._merge_serialized_client_payloads(remaining_payloads)
        return restored_by_class

    def _serialized_client_payloads(self) -> list[str]:
        """Return the deduplicated persisted payload list for live and still-pending clients."""
        pending_payloads = list(self.serialized_client_dumps)
        live_payloads = [self._serialize_client_payload(client) for client in self.clients]
        return self._merge_serialized_client_payloads([*pending_payloads, *live_payloads])

    @property
    def business_plan(self) -> BusinessPlanItem | None:
        for client in self.clients:
            if isinstance(client, BusinessPlanItem):
                return client
        return None

    @property
    def node(self) -> SidebarNode[object]:
        return self.widget.node

    @property
    def listable_clients(self) -> list[PluginClient]:
        return [client for client in self.clients if client.show_in_list]

    @property
    def listable_items(self) -> list[PluginClient | SourceCatalogItem]:
        active_external_bundle_ids = {
            client.plugin_bundle_id
            for client in self.listable_clients
            if isinstance(client, PluginClient)
            and client.plugin_source == PluginClientSource.EXTERNAL
            and client.plugin_bundle_id is not None
        }
        visible_source_catalog_items = [
            item
            for item in self.source_catalog_items
            if item.entry.bundle_id not in active_external_bundle_ids
        ]
        return [*self.listable_clients, *visible_source_catalog_items]

    @classmethod
    def _filter_valid_external_bundles(
        cls,
        bundles: list[VerifiedExternalPluginBundle],
    ) -> dict[str, VerifiedExternalPluginBundle]:
        valid_bundles: dict[str, VerifiedExternalPluginBundle] = {}
        seen_class_names = set(cls._base_known_classes)
        seen_plugin_ids = {client_cls.__name__ for client_cls in cls._available_base_client_classes()}

        for bundle in bundles:
            if bundle.bundle_id in valid_bundles:
                # Example:
                # - source A ships bundle_id = "notes"
                # - source B ships bundle_id = "notes"
                # The first one wins, and the later one is skipped.
                logger.warning("Skipping duplicate external bundle id %s.", bundle.bundle_id)
                continue

            duplicate_class_names = bundle.class_names.intersection(seen_class_names)
            if duplicate_class_names:
                logger.warning(
                    "Skipping external bundle %s because class names collide: %s",
                    bundle.bundle_id,
                    ", ".join(sorted(duplicate_class_names)),
                )
                continue

            duplicate_plugin_ids = bundle.plugin_ids.intersection(seen_plugin_ids)
            if duplicate_plugin_ids:
                logger.warning(
                    "Skipping external bundle %s because plugin ids collide: %s",
                    bundle.bundle_id,
                    ", ".join(sorted(duplicate_plugin_ids)),
                )
                continue

            valid_bundles[bundle.bundle_id] = bundle
            seen_class_names.update(bundle.class_names)
            seen_plugin_ids.update(bundle.plugin_ids)

        return valid_bundles

    @classmethod
    def _refresh_external_state(
        cls,
        context: PluginRuntimeContext,
        external_registry: ExternalPluginRegistry,
    ) -> dict[str, VerifiedExternalPluginBundle]:
        """Rediscover installed external bundles and refresh the class-wide runtime view.

        This does three things in one place:
        1. ask the external registry which installed bundles are currently valid,
        2. filter out bundles that would collide with builtin or already-seen plugin classes,
        3. rebuild ``known_classes`` so plugin client deserialization can restore external
           clients by class name.

        That refresh is necessary because external plugins are not static imports. Their
        client classes only become known after the installed bundles are verified and loaded
        from disk, so the manager has to rebuild this runtime state whenever the external
        plugin set may have changed.
        """
        valid_bundles = cls._filter_valid_external_bundles(
            external_registry.discover_verified_bundles(context)
        )

        cls.known_classes = cls._base_known_classes.copy()
        for bundle in valid_bundles.values():
            for client_cls in bundle.runtime_bundle.client_classes:
                cls.known_classes[client_cls.__name__] = client_cls

        return valid_bundles

    def _rebuild_source_catalog_items(self) -> None:
        entries = self.external_registry.list_available_plugins()
        self.available_source_plugins_by_bundle_id = {entry.bundle_id: entry for entry in entries}
        self.source_catalog_items = []
        for entry in entries:
            item = SourceCatalogItem(entry=entry, parent=self.parent)
            item.signal_install_requested.connect(self.install_source_plugin)
            self.source_catalog_items.append(item)

    def get_instance(self, cls: type[T], clients: list[PluginClient] | None = None) -> T | None:
        active_clients = clients if clients is not None else self.clients
        for client in active_clients:
            if isinstance(client, cls):
                return client
        return None

    def add_client_registered_callback(self, callback: Callable[[PluginClient], None]) -> None:
        self._client_registered_callbacks.append(callback)

    @staticmethod
    def _static_runtime_bundles(
        context: PluginRuntimeContext,
    ) -> tuple[RuntimePluginBundle, ...]:
        return tuple(
            normalize_static_plugin_bundle(bundle=bundle, context=context)
            for bundle in BUILTIN_PLUGIN_BUNDLES
        )

    @classmethod
    def _available_base_client_classes(cls) -> list[type[PluginClient]]:
        return list(cls._base_client_classes)

    def _register_client(self, client: PluginClient) -> None:
        self._assign_client_identity(client)
        self._sync_external_client_state(client)
        self._connect_client_signals(client)
        for callback in self._client_registered_callbacks:
            callback(client)

        if client not in self.clients:
            self.clients.append(client)

    def _ensure_external_state_loaded(self) -> None:
        if self._external_state_loaded:
            return
        self.external_bundles = self._refresh_external_state(
            self._plugin_runtime_context(
                wallet_functions=self.wallet_functions,
                config=self.config,
                fx=self.fx,
                loop_in_thread=self.loop_in_thread,
                subscription_price_lookup=self.subscription_price_lookup,
                parent=self.parent,
            ),
            self.external_registry,
        )
        self._external_state_loaded = True
        self.external_client_classes = [
            client_cls
            for bundle in self.external_bundles.values()
            for client_cls in bundle.runtime_bundle.client_classes
        ]

    def _connect_client_signals(self, client: PluginClient) -> None:
        self.client_signal_tracker.connect(
            client.signal_update_requested,
            partial(self._on_client_update_requested, client),
        )
        self.client_signal_tracker.connect(
            client.signal_request_enabled,
            partial(self._on_client_enabled_changed, client),
        )
        self.client_signal_tracker.connect(
            client.signal_delete_requested,
            partial(self._on_client_delete_requested, client),
        )

    def _all_client_classes(self) -> list[type[PluginClient]]:
        return [*self._available_base_client_classes(), *self.external_client_classes]

    def _external_bundle_for_client_class(
        self, cls: type[PluginClient]
    ) -> VerifiedExternalPluginBundle | None:
        for bundle in self.external_bundles.values():
            if cls in bundle.runtime_bundle.client_classes:
                return bundle
        return None

    @staticmethod
    def _external_initial_dumps_by_client_class(
        bundle: VerifiedExternalPluginBundle,
    ) -> dict[type[PluginClient], dict[str, object]]:
        return {
            client_cls: {
                "plugin_source": PluginClientSource.EXTERNAL.value,
                "plugin_bundle_id": bundle.bundle_id,
                "plugin_id": PluginClient.build_plugin_id(
                    plugin_source=PluginClientSource.EXTERNAL,
                    plugin_bundle_id=bundle.bundle_id,
                    class_name=client_cls.__name__,
                ),
            }
            for client_cls in bundle.runtime_bundle.client_classes
        }

    def _create_discovered_clients_by_class(
        self,
        descriptor: bdk.Descriptor,
        candidate_classes: set[type[PluginClient]],
    ) -> dict[type[PluginClient], PluginClient]:
        runtime_context = self._plugin_runtime_context(
            wallet_functions=self.wallet_functions,
            config=self.config,
            fx=self.fx,
            loop_in_thread=self.loop_in_thread,
            subscription_price_lookup=self.subscription_price_lookup,
            parent=self.parent,
        )
        clients_by_class: dict[type[PluginClient], PluginClient] = {}
        for runtime_bundle in self._static_runtime_bundles(runtime_context):
            if not set(runtime_bundle.client_classes).intersection(candidate_classes):
                continue
            for client in create_runtime_plugin_clients(
                bundle=runtime_bundle,
                context=runtime_context,
                descriptor=descriptor,
            ):
                if client.__class__ not in candidate_classes:
                    client.close()
                    continue
                clients_by_class[client.__class__] = client
        for bundle in self.external_bundles.values():
            if not set(bundle.runtime_bundle.client_classes).intersection(candidate_classes):
                continue
            try:
                created_clients = create_runtime_plugin_clients(
                    bundle=bundle.runtime_bundle,
                    context=runtime_context,
                    descriptor=descriptor,
                    initial_dumps_by_client_class=self._external_initial_dumps_by_client_class(bundle),
                    bundle_name=bundle.bundle_id,
                    error_type=ExternalPluginError,
                )
            except Exception as e:
                logger.error(f"Could not load external bundle {bundle.bundle_id} due to {e}")
                continue
            for client in created_clients:
                if client.__class__ not in candidate_classes:
                    client.close()
                    continue
                clients_by_class[client.__class__] = client
        return clients_by_class

    def _runtime_bundle_for_client_class(self, cls: type[PluginClient]) -> RuntimePluginBundle | None:
        if external_bundle := self._external_bundle_for_client_class(cls):
            return external_bundle.runtime_bundle
        static_bundle = BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS.get(cls)
        if static_bundle is None:
            return None
        runtime_context = self._plugin_runtime_context(
            wallet_functions=self.wallet_functions,
            config=self.config,
            fx=self.fx,
            loop_in_thread=self.loop_in_thread,
            subscription_price_lookup=self.subscription_price_lookup,
            parent=self.parent,
        )
        return normalize_static_plugin_bundle(bundle=static_bundle, context=runtime_context)

    def _assign_client_identity(self, client: PluginClient) -> None:
        bundle = self._external_bundle_for_client_class(client.__class__)
        if bundle is None:
            if client.plugin_source == PluginClientSource.EXTERNAL and client.plugin_bundle_id is not None:
                return
            client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
            return
        client.set_plugin_identity(
            plugin_source=PluginClientSource.EXTERNAL,
            plugin_bundle_id=bundle.bundle_id,
        )

    def _sync_external_client_state(self, client: PluginClient) -> None:
        bundle = (
            self.external_bundles.get(client.plugin_bundle_id)
            if client.plugin_bundle_id is not None
            else None
        )
        entry = (
            self.available_source_plugins_by_bundle_id.get(client.plugin_bundle_id)
            if client.plugin_bundle_id is not None
            else None
        )
        client.set_external_state(
            update_available=bool(entry and entry.update_available),
            installed_version=bundle.version if bundle is not None else None,
            available_version=entry.version if entry and entry.update_available else None,
            available_hash=entry.folder_hash if entry and entry.update_available else None,
        )

    def _reconnect_client_signals(self) -> None:
        self.client_signal_tracker.disconnect_all()
        for client in self.clients:
            self._connect_client_signals(client)

    def _on_language_switch(self) -> None:
        for client in list(self.clients):
            client.reload_translator()
            client.updateUi()
        self.widget.updateUi()

    def _restore_or_create_clients(self, descriptor: bdk.Descriptor) -> None:
        existing_clients = self.clients.copy()
        self.clients.clear()
        candidate_classes = {
            cls
            for cls in self._all_client_classes()
            if self.get_instance(cls, clients=existing_clients) is None
            and cls.plugin_conditions.descriptor_allowed(str(descriptor))
        }
        restored_pending_clients = self._restore_pending_clients_by_class(candidate_classes)
        candidate_classes -= set(restored_pending_clients)
        discovered_clients_by_class = self._create_discovered_clients_by_class(
            descriptor=descriptor,
            candidate_classes=candidate_classes,
        )
        for cls in self._all_client_classes():
            if client := self.get_instance(cls, clients=existing_clients):
                self._register_client(client=client)
                continue

            if not cls.plugin_conditions.descriptor_allowed(str(descriptor)):
                continue

            if restored_pending_client := restored_pending_clients.get(cls):
                self._register_client(restored_pending_client)
            elif discovered_client := discovered_clients_by_class.get(cls):
                self._register_client(discovered_client)

    def create_and_connect_clients(
        self,
        descriptor: bdk.Descriptor,
        wallet_id: str,
        category_core: CategoryCore,
    ) -> None:
        self._current_descriptor = descriptor
        self._current_wallet_id = wallet_id
        self._current_category_core = category_core
        self._ensure_external_state_loaded()
        self.client_signal_tracker.disconnect_all()
        self.signal_tracker = SignalTracker()
        self.plugin_server = PluginServer(
            wallet_id=wallet_id,
            network=self.network,
            wallet_functions=self.wallet_functions,
            plugin_permissions=self.plugin_permissions,
        )
        self._restore_or_create_clients(descriptor=descriptor)

        for client in self.clients:
            plugin_id = self._plugin_id(client)
            if plugin_id not in self.plugin_permissions:
                self.plugin_permissions[plugin_id] = set()
            if self._is_permission_auto_allowed(client):
                self.plugin_permissions[plugin_id].update(client.required_permissions)

            scoped_server = self.plugin_server.view_for(plugin_id)
            if not scoped_server.request_access(client.required_permissions):
                client.set_enabled(False)
            client.set_server_view(server=scoped_server)

            if isinstance(client, PaidPluginClient):
                client.set_business_plan(business_plan=self.business_plan)

        self.widget.set_plugins(self.listable_items)

    @staticmethod
    def _plugin_id(client: PluginClient) -> str:
        return client.plugin_id

    def _client_for_plugin_id(self, plugin_id: str) -> PluginClient | None:
        for client in self.clients:
            if client.plugin_id == plugin_id:
                return client
        return None

    def _is_permission_auto_allowed(self, client: PluginClient) -> bool:
        runtime_bundle = self._runtime_bundle_for_client_class(client.__class__)
        return bool(runtime_bundle and client.__class__ in runtime_bundle.auto_allow_plugin_clients)

    def _on_client_enabled_changed(self, client: PluginClient, enabled: bool) -> None:
        plugin_id = self._plugin_id(client)
        if enabled:
            granted_permissions = self._request_permission(plugin_id, client)
            if not client.allow_enable_request():
                return
            client.set_enabled(enabled and bool(granted_permissions))
            return

        client.set_enabled(False)
        self.plugin_permissions[plugin_id] = set()

    def _on_client_delete_requested(self, client: PluginClient) -> None:
        if client.plugin_source != PluginClientSource.EXTERNAL or client.plugin_bundle_id is None:
            return
        self.delete_installed_source_plugin(client)

    def _on_client_update_requested(self, client: PluginClient) -> None:
        if client.plugin_source != PluginClientSource.EXTERNAL or client.plugin_bundle_id is None:
            return
        entry = self.available_source_plugins_by_bundle_id.get(client.plugin_bundle_id)
        if entry is None or not entry.update_available:
            return
        self.update_installed_source_plugin(client, entry)

    def _request_permission(self, plugin_id: str, client: PluginClient) -> bool:
        not_yet_granted_permissions = set(client.required_permissions) - self.plugin_permissions.get(
            plugin_id,
            set(),
        )
        if not not_yet_granted_permissions:
            return True

        permission_lines = "\n".join(
            f"- {permission.name}: {permission.description}"
            for permission in sorted(not_yet_granted_permissions, key=lambda permission: permission.name)
        )
        response = self._is_permission_auto_allowed(client) or question_dialog(
            text=(
                f"{client.title} requests access to:\n{permission_lines}\n\n"
                "Allow this plugin to access these features?"
            ),
            title="Plugin permission request",
            true_button="Allow",
            false_button="Deny",
        )

        if not response:
            return False

        self.plugin_permissions[plugin_id].update(not_yet_granted_permissions)
        return True

    def load_all_enabled(self) -> None:
        for client in self.clients:
            if client.enabled:
                client.load()

    def disconnect_all(self) -> None:
        for client in self.clients:
            client.unload()

    def drop_wallet_specific_things(self) -> bool:
        for client in list(self.clients):
            if not client.drop_wallet_specific_things():
                self.clients.remove(client)

        self._rebuild_source_catalog_items()
        self.widget.set_plugins(self.listable_items)
        return True

    def _refresh_current_wallet_plugins(self) -> None:
        if (
            self._current_descriptor is None
            or self._current_wallet_id is None
            or self._current_category_core is None
        ):
            self.widget.set_plugins(self.listable_items)
            return

        self.create_and_connect_clients(
            descriptor=self._current_descriptor,
            wallet_id=self._current_wallet_id,
            category_core=self._current_category_core,
        )

    def _refresh_external_registry_state(self) -> bool:
        previous_signature = self._external_bundle_state_signature(self.external_bundles)
        self.external_bundles = self._refresh_external_state(
            self._plugin_runtime_context(
                wallet_functions=self.wallet_functions,
                config=self.config,
                fx=self.fx,
                loop_in_thread=self.loop_in_thread,
                subscription_price_lookup=self.subscription_price_lookup,
                parent=self.parent,
            ),
            self.external_registry,
        )
        self.external_client_classes = [
            client_cls
            for bundle in self.external_bundles.values()
            for client_cls in bundle.runtime_bundle.client_classes
        ]
        self._rebuild_source_catalog_items()
        for client in self.clients:
            self._sync_external_client_state(client)
        if self._source_management_dialog is not None:
            self._source_management_dialog.reload_sources()
        return previous_signature != self._external_bundle_state_signature(self.external_bundles)

    def _refresh_plugin_list_only(self) -> None:
        self.widget.set_plugins(self.listable_items, rebuild_sidebar=False)

    def _refresh_after_registry_change(self, runtime_changed: bool) -> None:
        if runtime_changed:
            self._refresh_current_wallet_plugins()
            return
        self._refresh_plugin_list_only()

    def _schedule_startup_source_refresh(self) -> None:
        """Refresh external plugin sources once shortly after startup when sources exist."""
        if self.loop_in_thread is None or not self.external_registry.load_sources():
            return
        if self.external_registry.should_skip_startup_source_refresh():
            return

        self._startup_source_refresh_timer = QTimer(self.widget)
        self._startup_source_refresh_timer.setSingleShot(True)
        self._startup_source_refresh_timer.timeout.connect(self._refresh_plugin_sources_after_startup)
        self._startup_source_refresh_timer.start(60_000)

    def _refresh_plugin_sources_after_startup(self) -> None:
        self.refresh_plugin_sources(show_errors=False)

    def _render_async_registry_error(self, error_info: ExcInfo | Exception | None) -> str:
        """Convert loop-thread and synchronous exceptions into a user-facing error string."""
        if error_info is None:
            return self.widget.tr("Plugin operation failed.")
        if isinstance(error_info, tuple):
            return str(error_info[1])
        return str(error_info)

    def _show_async_registry_error(self, error_info: ExcInfo | Exception | None) -> None:
        """Show plugin source/install failures without letting them escape into the UI thread."""
        Message(
            self._render_async_registry_error(error_info),
            type=MessageType.Error,
            parent=self.parent or self.widget,
        )

    def show_plugin_sources_dialog(self) -> None:
        dialog = SourceManagementDialog(
            registry=self.external_registry,
            parent=self.parent or self.widget,
        )
        self._source_management_dialog = dialog
        dialog.signal_add_source_requested.connect(self._handle_source_dialog_add_source)
        dialog.signal_refresh_source_requested.connect(self._handle_source_dialog_refresh_source)
        dialog.signal_recheck_plugins_requested.connect(self._handle_source_dialog_recheck_plugins)
        dialog.signal_delete_source_requested.connect(self._handle_source_dialog_delete_source)
        dialog.exec()
        self._source_management_dialog = None

    def _handle_source_dialog_add_source(self) -> None:
        self.add_plugin_source()

    def _handle_source_dialog_refresh_source(self, source_id: str) -> None:
        self.refresh_plugin_sources(source_id=source_id)

    def _handle_source_dialog_recheck_plugins(self) -> None:
        self.recheck_installed_plugins()

    def _handle_source_dialog_delete_source(self, source_id: str) -> None:
        self.remove_plugin_source(source_id)

    def add_plugin_source(self) -> None:
        dialog = AddPluginSourceDialog(parent=self.parent or self.widget)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        manifest_url, display_name, auth_config, pinned_key = dialog.source_values()
        if not manifest_url or not pinned_key:
            Message(
                self.widget.tr("Manifest URL and pinned public key are required."),
                type=MessageType.Error,
                parent=self.parent or self.widget,
            )
            return

        try:
            manifest = self.external_registry.add_source(
                manifest_url=manifest_url,
                pinned_source_public_key=pinned_key,
                auth_config=auth_config,
                display_name=display_name,
            )
            runtime_changed = self._refresh_external_registry_state()
            self._refresh_after_registry_change(runtime_changed)
            logger.info("Added plugin source %s.", manifest.display_name)
        except ExternalPluginError as exc:
            Message(str(exc), type=MessageType.Error, parent=self.parent or self.widget)

    def _log_async_registry_error(self, error_info: ExcInfo | Exception | None) -> None:
        logger.warning("Plugin source refresh failed: %s", self._render_async_registry_error(error_info))

    def refresh_plugin_sources(self, source_id: str | None = None, show_errors: bool = True) -> None:
        if not self.loop_in_thread:
            return

        def on_success(refreshed: Sequence[VerifiedPluginSourceManifest]) -> None:
            runtime_changed = self._refresh_external_registry_state()
            self._refresh_after_registry_change(runtime_changed)
            if source_id is None:
                logger.info("Refreshed %s plugin source(s).", len(refreshed))
                return
            if not refreshed:
                return
            logger.info("Refreshed plugin source %s.", refreshed[0].display_name)

        async def do() -> Sequence[VerifiedPluginSourceManifest]:
            return await self.external_registry.refresh_sources(
                source_id=source_id, raise_on_error=show_errors
            )

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=self._show_async_registry_error if show_errors else self._log_async_registry_error,
            key="plugin_source_refresh_all" if source_id is None else f"plugin_source_refresh:{source_id}",
            multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
        )

    def recheck_installed_plugins(self) -> None:
        results = self.external_registry.recheck_installed_plugins()
        runtime_changed = self._refresh_external_registry_state()
        self._refresh_after_registry_change(runtime_changed)
        invalid_count = len([result for result in results if not result.last_verification_ok])
        message = (
            self.widget.tr("Rechecked installed plugins. {count} plugin(s) are invalid.")
            if invalid_count
            else self.widget.tr("Rechecked installed plugins.")
        )
        rendered_message = message.format(count=invalid_count) if "{count}" in message else message
        if invalid_count:
            Message(
                rendered_message,
                type=MessageType.Warning,
                parent=self.parent or self.widget,
            )
            return
        logger.info(rendered_message)

    def install_source_plugin(self, entry: ExternalPluginCatalogEntry) -> None:
        if not self.loop_in_thread:
            return

        def on_success(_result: InstalledSourcePluginMetadata) -> None:
            runtime_changed = self._refresh_external_registry_state()
            self._refresh_after_registry_change(runtime_changed)
            logger.info("Installed plugin %s.", entry.display_name)

        async def do() -> InstalledSourcePluginMetadata:
            return await self.external_registry.install_plugin(entry.source_id, entry.bundle_id)

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=self._show_async_registry_error,
            key=f"plugin_source_install:{entry.bundle_id}",
            multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
        )

    def update_installed_source_plugin(
        self,
        client: PluginClient,
        entry: ExternalPluginCatalogEntry,
    ) -> None:
        if self.loop_in_thread is None:
            return

        was_enabled = client.enabled
        if was_enabled:
            client.set_enabled(False)

        def on_success(_result: InstalledSourcePluginMetadata) -> None:
            replacement_payload_dict = client.dump()
            replacement_payload = self._serialize_client_dump_dict(replacement_payload_dict)
            runtime_changed = self._refresh_external_registry_state()
            if runtime_changed:
                self.serialized_client_dumps = self._merge_serialized_client_payloads(
                    [*self.serialized_client_dumps, replacement_payload]
                )
            self._refresh_after_registry_change(runtime_changed)
            if runtime_changed:
                replacement_client = self._client_for_plugin_id(client.plugin_id)
                if replacement_client is None:
                    logger.warning("Could not restore updated plugin %s after refresh.", client.plugin_id)
                else:
                    replacement_client.set_enabled(was_enabled)
            else:
                client.set_enabled(was_enabled)
            self._refresh_plugin_list_only()
            logger.info("Updated plugin %s to version %s.", entry.display_name, entry.version)

        def on_error(error_info: ExcInfo | Exception | None) -> None:
            if was_enabled:
                client.set_enabled(was_enabled)
            self._show_async_registry_error(error_info)

        async def do() -> InstalledSourcePluginMetadata:
            return await self.external_registry.install_plugin(entry.source_id, entry.bundle_id)

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"plugin_source_install:{entry.bundle_id}",
            multiple_strategy=MultipleStrategy.REJECT_NEW_TASK,
        )

    def remove_plugin_source(self, source_id: str) -> None:
        source = self.external_registry.load_source(source_id)
        if source is None:
            Message(
                self.widget.tr("Plugin source {source_id} does not exist.").format(source_id=source_id),
                type=MessageType.Error,
                parent=self.parent or self.widget,
            )
            return

        if not question_dialog(
            text=self.widget.tr("Remove plugin source {source}?").format(source=source.display_name),
            title=self.widget.tr("Remove Plugin Source"),
            true_button=self.widget.tr("Delete"),
            false_button=self.widget.tr("Cancel"),
        ):
            return

        try:
            self.external_registry.remove_source(source_id)
            runtime_changed = self._refresh_external_registry_state()
            self._refresh_after_registry_change(runtime_changed)
            logger.info("Removed plugin source %s.", source.display_name)
        except ExternalPluginError as exc:
            Message(str(exc), type=MessageType.Error, parent=self.parent or self.widget)

    def delete_installed_source_plugin(self, client: PluginClient) -> None:
        if client.enabled:
            Message(
                self.widget.tr("Disable the plugin before deleting it."),
                type=MessageType.Error,
                parent=self.parent or self.widget,
            )
            return
        if client.plugin_bundle_id is None:
            Message(
                self.widget.tr("This plugin cannot be deleted."),
                type=MessageType.Error,
                parent=self.parent or self.widget,
            )
            return
        if not question_dialog(
            text=self.widget.tr("Delete installed plugin {plugin}?").format(plugin=client.title),
            title=self.widget.tr("Delete Installed Plugin"),
            true_button=self.widget.tr("Delete"),
            false_button=self.widget.tr("Cancel"),
        ):
            return

        try:
            bundle_id = client.plugin_bundle_id
            self.external_registry.remove_installed_plugin(bundle_id)
            removed_clients = [
                existing_client
                for existing_client in self.clients
                if existing_client.plugin_source == PluginClientSource.EXTERNAL
                and existing_client.plugin_bundle_id == bundle_id
            ]
            self.serialized_client_dumps = self._merge_serialized_client_payloads(
                [
                    *self.serialized_client_dumps,
                    *(self._serialize_client_payload(removed_client) for removed_client in removed_clients),
                ]
            )
            self.clients = [
                existing_client for existing_client in self.clients if existing_client not in removed_clients
            ]
            for removed_client in removed_clients:
                self.plugin_permissions.pop(removed_client.plugin_id, None)
                removed_client.close()
            self._reconnect_client_signals()
            runtime_changed = self._refresh_external_registry_state()
            self._refresh_after_registry_change(runtime_changed)
            logger.info("Deleted plugin %s.", client.title)
        except ExternalPluginError as exc:
            Message(str(exc), type=MessageType.Error, parent=self.parent or self.widget)

    def clone(self, class_kwargs: dict | None = None):
        class_kwargs = class_kwargs if class_kwargs else {}
        class_kwargs.update(
            self.class_kwargs(
                wallet_functions=self.wallet_functions,
                config=self.config,
                fx=self.fx,
                loop_in_thread=self.loop_in_thread,
                parent=self.parent,
                external_registry=self.external_registry,
            )
        )
        return super().clone(class_kwargs=class_kwargs)

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data["serialized_client_dumps"] = self._serialized_client_payloads()
        data["plugin_permissions"] = {
            plugin_id: list(permissions) for plugin_id, permissions in self.plugin_permissions.items()
        }
        return data

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if class_kwargs:
            dct.update(class_kwargs[cls.__name__])

        plugin_permissions: dict[str, set[PluginPermission]] = dct.get("plugin_permissions", {})
        for plugin_id in plugin_permissions:
            plugin_permissions[plugin_id] = {
                entry for entry in plugin_permissions[plugin_id] if isinstance(entry, PluginPermission)
            }

        dct["clients"] = [client for client in dct.get("clients", []) if isinstance(client, PluginClient)]
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.0"):
            pass
        if fast_version(str(dct["VERSION"])) <= fast_version("0.0.1"):
            dct.setdefault("plugin_permissions", {})
            for client in dct.get("clients", []):
                if not isinstance(client, PluginClient):
                    continue

                plugin_id = client.plugin_id
                if plugin_id in dct["plugin_permissions"]:
                    continue

                required_permissions = set(client.required_permissions)
                enabled = bool(client.enabled)
                if enabled:
                    dct["plugin_permissions"][plugin_id] = set(required_permissions)
                else:
                    dct["plugin_permissions"].setdefault(plugin_id, set())

        if fast_version(str(dct["VERSION"])) < fast_version("0.0.4"):
            dct.setdefault("plugin_permissions", {})
            for client in dct.get("clients", []):
                if not isinstance(client, PluginClient):
                    continue

                plugin_id = client.plugin_id
                if not client.enabled:
                    continue

                dct["plugin_permissions"][plugin_id] = set(client.required_permissions)

        if fast_version(str(dct["VERSION"])) < fast_version("0.0.5"):
            dct.setdefault("plugin_permissions", {})

        if fast_version(str(dct["VERSION"])) < fast_version("0.0.6"):
            dct.setdefault("business_plan", None)
        if fast_version(str(dct["VERSION"])) < fast_version("0.0.12"):
            if isinstance((client := dct.get("business_plan", None)), BusinessPlanItem):
                plugin_id = client.plugin_id
                dct["plugin_permissions"][plugin_id] = set(client.required_permissions)
        if fast_version(str(dct["VERSION"])) < fast_version("0.0.14"):
            dct.setdefault("plugin_permissions", {})
            migrated_permissions: dict[str, set[PluginPermission]] = {}
            for client in dct.get("clients", []):
                if not isinstance(client, PluginClient):
                    continue
                old_key = client.__class__.__name__
                if old_key in dct["plugin_permissions"]:
                    migrated_permissions[client.plugin_id] = set(dct["plugin_permissions"][old_key])
            if isinstance((client := dct.get("business_plan", None)), PluginClient):
                old_key = client.__class__.__name__
                if old_key in dct["plugin_permissions"]:
                    migrated_permissions[client.plugin_id] = set(dct["plugin_permissions"][old_key])
            dct["plugin_permissions"].update(migrated_permissions)

        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def close(self) -> None:
        self.client_signal_tracker.disconnect_all()
        self.signal_tracker.disconnect_all()
        if self._startup_source_refresh_timer is not None:
            self._startup_source_refresh_timer.stop()
        for client in self.clients:
            client.close()
        if self.business_plan:
            self.business_plan.close()
        self.subscription_price_lookup.close()
        self.widget.close()

    def updateUi(self) -> None:
        if self.business_plan:
            self.business_plan.updateUi()
        for client in self.clients:
            client.updateUi()
        self.widget.updateUi()
