#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from btcpay_tools.btcpay_subscription_api.models import PlanCatalogItem
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.plugin_framework.plugin_list_widget import (
    ExternalPaidPluginWidget,
    PaidPluginWidget,
)
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission
from bitcoin_safe.plugin_framework.subscription_api_client import (
    SubscriptionApiClient,
    plan_id_for_product,
)

from .plugin_client import PluginClient
from .subscription_manager import StoredSubscriptionStatus, SubscriptionManager
from .subscription_price_lookup import SubscriptionPriceLookup

if TYPE_CHECKING:
    from bitcoin_safe.plugin_framework.plugins.business_plan.client import BusinessPlanItem

logger = logging.getLogger(__name__)


class PaidPluginClient(PluginClient):
    """
    A plugin that is unlocked by a subscription product of the subscription service.

    Managers are keyed by the product id, which is stable across store moves. The plan_id of the
    product is resolved from the service catalog and follows the store when it moves.
    """

    VERSION = "0.3.0"
    known_classes = {
        **PluginClient.known_classes,
        StoredSubscriptionStatus.__name__: StoredSubscriptionStatus,
        SubscriptionManager.__name__: SubscriptionManager,
    }

    required_permissions: set[PluginPermission] = PluginClient.required_permissions.union(
        {PluginPermission.DESCRIPTOR}
    )

    signal_price_texts_changed = cast(SignalProtocol[[]], pyqtSignal())

    @staticmethod
    def cls_kwargs(  # type: ignore
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        additional_access_providers: list[Callable[[], bool]] | None = None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
        parent: QWidget | None = None,
    ) -> dict[str, object]:
        data: dict[str, object] = {
            "config": config,
            "fx": fx,
            "loop_in_thread": loop_in_thread,
            "parent": parent,
            "additional_access_providers": additional_access_providers,
        }
        if subscription_price_lookup is not None:
            data["subscription_price_lookup"] = subscription_price_lookup
        return data

    def __init__(
        self,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        icon: QIcon | Path | str,
        enabled: bool,
        additional_access_providers: list[Callable[[], bool]] | None,
        subscription_product_id: str,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(enabled=enabled, icon=icon, parent=parent)
        self.fx = fx
        self.config = config
        self.loop_in_thread = loop_in_thread
        self.subscription_product_id = subscription_product_id
        self.additional_access_providers = additional_access_providers or []
        self._business_plan_access_provider: Callable[[], bool] | None = None
        self._business_plan_signal_tracker = SignalTracker()
        self._price_signal_tracker = SignalTracker()
        self._manager_signal_tracker = SignalTracker()
        self._owns_subscription_price_lookup = subscription_price_lookup is None
        self.subscription_price_lookup = (
            subscription_price_lookup
            if subscription_price_lookup is not None
            else SubscriptionPriceLookup(parent=self)
        )
        self._price_signal_tracker.connect(
            self.subscription_price_lookup.signal_prices_changed,
            self._on_subscription_prices_changed,
        )
        self._subscription_managers_by_key: dict[str, SubscriptionManager] = {}
        self._selected_subscription_key = ""
        self._inert_manager = SubscriptionManager(
            config=config,
            loop_in_thread=loop_in_thread,
            parent=self,
            additional_access_provider=self._has_additional_access,
        )
        self._subscription_managers_by_key = self._restored_subscription_managers(subscription_managers)
        self._connect_subscription_manager_signals()
        self._selected_subscription_key = self._resolve_selected_subscription_key(selected_subscription_key)

        self._plugin_loaded = False
        self._defer_subscription_refresh = False

        self._plugin_content = QWidget(self)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._plugin_content)

        self._refresh_plugin_ui()
        self._resolve_subscription_plans()

    @property
    def subscription_manager(self) -> SubscriptionManager:
        """The product's manager, or an inert one while the product has no plan yet."""
        return self._subscription_managers_by_key.get(self._selected_subscription_key, self._inert_manager)

    @property
    def subscription_managers(self) -> tuple[SubscriptionManager, ...]:
        return tuple(self._subscription_managers_by_key.values())

    @property
    def displayed_subscription_manager(self) -> SubscriptionManager:
        return (
            self._manager_with_access()
            or self._manager_with_management_url()
            or self._manager_with_activation_in_progress()
            or self.subscription_manager
        )

    def supports_plan_selection(self) -> bool:
        return not self.displayed_subscription_manager.supports_manage_subscription()

    def plan_selection_title(self) -> str:
        return self.tr("Subscription")

    def supports_enable_toggle(self) -> bool:
        return True

    def available_plan_options(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (catalog_item.plan_id, self._format_plan_option(catalog_item))
            for catalog_item in self.subscription_price_lookup.catalog_items_for_product(
                self.subscription_product_id
            )
        )

    def selected_plan_option_key(self) -> str:
        return self.subscription_manager.plan_id or ""

    def select_plan_option(self, storage_key: str) -> None:
        self.subscription_manager.set_plan_id(storage_key)

    def set_paid_content_widget(self, widget: QWidget) -> None:
        self._layout.removeWidget(self._plugin_content)
        self._plugin_content.setParent(None)
        self._plugin_content = widget
        self._layout.addWidget(self._plugin_content)
        self._refresh_plugin_ui()

    def allow_enable_request(self) -> bool:
        if self.subscription_allows_access():
            return True
        descriptor = self.server.get_descriptor() if self.server else None
        if descriptor:
            return self.subscription_manager.allow_subscription_enable_request(
                multipath_descriptor=descriptor
            )
        else:
            logger.warning("No descriptor available")
        return False

    def supports_start_trial_action(self) -> bool:
        return not (
            self._has_business_plan_access_only()
            or self.displayed_subscription_manager.supports_manage_subscription()
        )

    def start_trial_button_text(self) -> str:
        return self.tr("Start free trial")

    def trigger_start_trial(self) -> None:
        self.signal_request_enabled.emit(True)

    def check_subscription_button_text(self) -> str:
        return self.tr("Check subscription")

    def trigger_check_subscription(self) -> None:
        """Look up an existing subscription for this wallet via subscriptions/status."""
        descriptor = self.server.get_descriptor() if self.server else None
        if not descriptor:
            logger.warning("No descriptor available; cannot check the subscription")
            return
        for subscription_manager in self.subscription_managers:
            subscription_manager.check_existing_subscription(multipath_descriptor=descriptor)

    def supports_refresh_subscription_status_action(self) -> bool:
        return self.displayed_subscription_manager.supports_refresh_subscription_status()

    def refresh_subscription_status_button_text(self) -> str:
        return self.displayed_subscription_manager.refresh_subscription_status_button_text()

    def trigger_refresh_subscription_status_action(self) -> None:
        self.displayed_subscription_manager.trigger_refresh_subscription_status(disable_if_inactive=True)

    def status_text(self) -> str:
        return self.displayed_subscription_manager.subscription_status_text()

    def ensure_price_texts(self) -> None:
        if not self._needs_subscription_price_texts():
            return
        for subscription_manager in self.subscription_managers:
            self.subscription_price_lookup.ensure_prices(subscription_manager)

    def load(self, refresh_subscription_status: bool = True) -> None:
        if refresh_subscription_status and not self._defer_subscription_refresh:
            for subscription_manager in self.subscription_managers:
                subscription_manager.refresh_subscription_status(
                    disable_if_inactive=True,
                    notify_on_error=False,
                )

        if not self.subscription_allows_access():
            self.set_enabled(False)
            return

        if self._plugin_loaded:
            self._refresh_plugin_ui()
            return
        self.load_paid_plugin()
        self._plugin_loaded = True
        self._refresh_plugin_ui()

    def defer_subscription_refresh(self, defer: bool) -> None:
        self._defer_subscription_refresh = defer

    def refresh_subscription_status(self) -> None:
        for subscription_manager in self.subscription_managers:
            subscription_manager.refresh_subscription_status(
                disable_if_inactive=True,
                notify_on_error=False,
            )

    def unload(self) -> None:
        if not self._plugin_loaded:
            return
        self.unload_paid_plugin()
        self._plugin_loaded = False
        self._refresh_plugin_ui()

    def load_paid_plugin(self) -> None:
        pass

    def unload_paid_plugin(self) -> None:
        pass

    def on_business_plan_changed(self) -> None:
        self._refresh_plugin_ui()
        self.signal_enabled_changed.emit(self.enabled)
        self.signal_needs_persist.emit()
        if not self.enabled:
            return
        if self.subscription_allows_access():
            self.load()
            return
        if self._plugin_loaded:
            self.set_enabled(False)

    def _refresh_plugin_ui(self) -> None:
        self._plugin_content.setVisible(self.enabled and self.subscription_allows_access())

    def updateUi(self) -> None:
        super().updateUi()
        self._refresh_plugin_ui()

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data["subscription_managers"] = self._subscription_managers_by_key
        data["selected_subscription_key"] = self._selected_subscription_key
        data["enabled"] = self.enabled

        return data

    def _on_subscription_state_changed(self, _storage_key: str) -> None:
        if self.enabled and not self.subscription_allows_access():
            self.set_enabled(False)
            return
        self._refresh_plugin_ui()
        self.signal_enabled_changed.emit(self.enabled)
        self.signal_needs_persist.emit()

    def _on_subscription_access_activated(self, storage_key: str) -> None:
        self._set_selected_subscription_key(storage_key, emit_signal=False)
        self._on_subscription_state_changed(storage_key)
        self.signal_request_enabled.emit(True)

    def _on_subscription_access_revoked(self, storage_key: str) -> None:
        if not self.subscription_allows_access() and self.enabled:
            self.set_enabled(False)
            return
        active_manager = self._manager_with_access()
        if active_manager is not None:
            self._set_selected_subscription_key(
                self._storage_key_for_manager(active_manager),
                emit_signal=False,
            )
        self._on_subscription_state_changed(storage_key)

    def set_business_plan(self, business_plan: BusinessPlanItem | None) -> None:
        self._set_business_plan_access_provider(business_plan=business_plan)

        if business_plan is self.business_plan:
            self.on_business_plan_changed()
            return

        self._business_plan_signal_tracker.disconnect_all()
        self.business_plan = business_plan

        if self.business_plan is not None:
            self._business_plan_signal_tracker.connect(
                self.business_plan.signal_enabled_changed,
                self._on_business_plan_enabled_changed,
            )

        self.on_business_plan_changed()

    def _set_business_plan_access_provider(self, business_plan: BusinessPlanItem | None) -> None:
        if (
            self._business_plan_access_provider is not None
            and self._business_plan_access_provider in self.additional_access_providers
        ):
            self.additional_access_providers.remove(self._business_plan_access_provider)

        self._business_plan_access_provider = (
            business_plan.subscription_allows_access if business_plan else None
        )
        if self._business_plan_access_provider is not None:
            self.additional_access_providers.append(self._business_plan_access_provider)
        for subscription_manager in self.subscription_managers:
            subscription_manager.set_additional_access_provider(self._has_additional_access)

    def _has_additional_access(self) -> bool:
        for additional_access_provider in self.additional_access_providers:
            if additional_access_provider():
                return True
        return False

    def _on_business_plan_enabled_changed(self, _enabled: bool) -> None:
        self.on_business_plan_changed()

    def _on_subscription_prices_changed(self, _cache_key: str) -> None:
        self.signal_price_texts_changed.emit()

    def _resolve_subscription_plans(self) -> None:
        """
        Look up the plan of this client's product in the service catalog. A catalog without the
        product clears its manager, so access cannot survive a removed product. A failed lookup
        keeps the persisted state, so access continues from the cache while offline.
        """
        if self.loop_in_thread is None:
            logger.warning("Subscription plan lookup skipped: no loop available")
            return
        proxy_url = self.config.network_config.proxy_url
        proxy_dict = ProxyInfo.parse(proxy_url).get_requests_proxy_dict() if proxy_url else None
        product_id = self.subscription_product_id
        preferred_plan_id = self.subscription_manager.plan_id

        async def do() -> str | None:
            plans = await asyncio.to_thread(SubscriptionApiClient(proxy_dict).fetch_plans)
            if not plans.get(product_id):
                return None
            return plan_id_for_product(plans, product_id, preferred_plan_id)

        def on_success(plan_id: str | None) -> None:
            self._set_subscription_plan_id(plan_id)

        def on_error(error_info: ExcInfo | None) -> None:
            logger.warning("Subscription plan lookup failed for %s: %s", product_id, error_info)

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"subscription_plans:{product_id}",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def _set_subscription_plan_id(self, plan_id: str | None) -> None:
        """
        Apply the catalog's plan_id of the product. None removes the product's manager and its access.
        A changed plan_id moves the existing subscription to the new plan.
        """
        had_access = self.subscription_allows_access()
        product_id = self.subscription_product_id
        self._manager_signal_tracker.disconnect_all()
        if plan_id is None:
            for subscription_manager in self._subscription_managers_by_key.values():
                subscription_manager.close()
            self._subscription_managers_by_key = {}
        else:
            manager = self._subscription_managers_by_key.get(product_id)
            if manager is None:
                manager = self._new_subscription_manager()
                self._subscription_managers_by_key = {product_id: manager}
            manager.set_plan_id(plan_id)
        self._connect_subscription_manager_signals()
        self._selected_subscription_key = self._resolve_selected_subscription_key(
            self._selected_subscription_key
        )
        self._sync_access_state()
        self._refresh_plugin_ui()
        self.signal_needs_persist.emit()
        if had_access and not self.subscription_allows_access():
            self._on_subscription_state_changed(product_id)
        else:
            self.signal_enabled_changed.emit(self.enabled)

    def _sync_access_state(self) -> None:
        """Hook for subclasses whose enabled state mirrors subscription access."""

    def _restored_subscription_managers(
        self,
        persisted_managers: dict[str, SubscriptionManager] | None,
    ) -> dict[str, SubscriptionManager]:
        """
        Pick the product's manager from a persisted dump. A dump keyed by an older plan_id has its
        single manager adopted, keeping email, management URL and status; its plan_id is moved to the
        catalog's plan later. Any other persisted manager is closed.
        """
        managers = dict(persisted_managers or {})
        manager = managers.pop(self.subscription_product_id, None)
        if manager is None and len(managers) == 1:
            legacy_key, manager = managers.popitem()
            logger.info(
                "Adopting the subscription of legacy key %s for product %s",
                legacy_key,
                self.subscription_product_id,
            )
        for orphaned_manager in managers.values():
            orphaned_manager.close()
        if manager is None:
            manager = self._new_subscription_manager()
        manager.set_additional_access_provider(self._has_additional_access)
        return {self.subscription_product_id: manager}

    def _new_subscription_manager(self) -> SubscriptionManager:
        return SubscriptionManager(
            config=self.config,
            loop_in_thread=self.loop_in_thread,
            parent=self,
            additional_access_provider=self._has_additional_access,
        )

    def _connect_subscription_manager_signals(self) -> None:
        for storage_key, manager in self._subscription_managers_by_key.items():
            self._manager_signal_tracker.connect(
                manager.signal_state_changed,
                partial(self._on_subscription_state_changed, storage_key),
            )
            self._manager_signal_tracker.connect(
                manager.signal_access_activated,
                partial(self._on_subscription_access_activated, storage_key),
            )
            self._manager_signal_tracker.connect(
                manager.signal_access_revoked,
                partial(self._on_subscription_access_revoked, storage_key),
            )

    def _manager_with_access(self) -> SubscriptionManager | None:
        for subscription_manager in self.subscription_managers:
            if subscription_manager.subscription_allows_access():
                return subscription_manager
        return None

    def _manager_with_management_url(self) -> SubscriptionManager | None:
        for subscription_manager in self.subscription_managers:
            if subscription_manager.management_url:
                return subscription_manager
        return None

    def _manager_with_activation_in_progress(self) -> SubscriptionManager | None:
        for subscription_manager in self.subscription_managers:
            if subscription_manager.activation_in_progress:
                return subscription_manager
        return None

    def _needs_subscription_price_texts(self) -> bool:
        return self.supports_plan_selection() and not self.subscription_allows_access()

    def subscription_allows_access(self) -> bool:
        if self._has_additional_access():
            return True
        return any(manager.subscription_allows_access() for manager in self.subscription_managers)

    def _has_direct_subscription_access(self) -> bool:
        return any(manager.has_direct_subscription_access() for manager in self.subscription_managers)

    def _has_business_plan_access_only(self) -> bool:
        return self._has_additional_access() and not self._has_direct_subscription_access()

    def _set_selected_subscription_key(self, storage_key: str, emit_signal: bool = True) -> None:
        if storage_key not in self._subscription_managers_by_key:
            return
        if self._selected_subscription_key == storage_key:
            return
        self._selected_subscription_key = storage_key
        self._refresh_plugin_ui()
        if emit_signal:
            self.signal_needs_persist.emit()

    def _resolve_selected_subscription_key(self, selected_subscription_key: str | None) -> str:
        if selected_subscription_key in self._subscription_managers_by_key:
            return selected_subscription_key
        return next(iter(self._subscription_managers_by_key), "")

    def _storage_key_for_manager(self, target_manager: SubscriptionManager) -> str:
        for storage_key, subscription_manager in self._subscription_managers_by_key.items():
            if subscription_manager is target_manager:
                return storage_key
        raise KeyError("subscription manager not registered")

    def _format_plan_option(self, catalog_item: PlanCatalogItem) -> str:
        return self.tr("{name}: {price} {currency} / {recurring}").format(
            name=catalog_item.name,
            price=catalog_item.price,
            currency=catalog_item.currency,
            recurring=catalog_item.recurringType,
        )

    def create_plugin_widget(
        self,
        icon_size: tuple[int, int] = (40, 40),
        parent: QWidget | None = None,
    ) -> PaidPluginWidget:
        widget_cls = ExternalPaidPluginWidget if self.is_external_plugin() else PaidPluginWidget
        return widget_cls(plugin=self, icon_size=icon_size, parent=parent)

    def close(self) -> bool:
        self._price_signal_tracker.disconnect_all()
        self._business_plan_signal_tracker.disconnect_all()
        self._manager_signal_tracker.disconnect_all()
        if self._owns_subscription_price_lookup:
            self.subscription_price_lookup.close()
        for subscription_manager in (*self.subscription_managers, self._inert_manager):
            subscription_manager.close()
        return super().close()
