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
from typing import Any, cast

from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import pyqtSignal

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import APP_NAME
from bitcoin_safe.fx import FX
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
from bitcoin_safe.plugin_framework.subscription_api_client import (
    SubscriptionApiClient,
    plan_id_for_product,
)
from bitcoin_safe.plugin_framework.subscription_manager import SubscriptionManager
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup

logger = logging.getLogger(__name__)


class BusinessPlanItem(PaidPluginClient):
    # derived from PaidPluginClient because the business plan needs access to the descriptor, just like a plugin
    VERSION = "0.1.2"
    IS_AVAILABLE = False
    known_classes = {**PaidPluginClient.known_classes}
    title = translate("BusinessPlanItem", "Business Plan")
    description = translate(
        "BusinessPlanItem",
        "Unlock all paid plugins with one subscription and remove the scheduled-payments service fee. "
        "Start the free trial first, then manage or refresh the subscription here.",
    )
    provider = APP_NAME
    subscription_product_id = "business-plan"

    signal_request_enabled = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_enabled_changed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_needs_persist = cast(SignalProtocol[[]], pyqtSignal())

    @classmethod
    def set_base_infos(cls):
        cls.title = translate("BusinessPlanItem", "Business Plan")
        cls.description = translate(
            "BusinessPlanItem",
            "Unlock all paid plugins with one subscription and remove the scheduled-payments service fee. "
            "Start the free trial first, then manage or refresh the subscription here.",
        )
        cls.provider = APP_NAME

    @staticmethod
    def cls_kwargs(  # type: ignore
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
    ) -> dict[str, object]:
        data: dict[str, object] = {
            "config": config,
            "fx": fx,
            "loop_in_thread": loop_in_thread,
        }
        if subscription_price_lookup is not None:
            data["subscription_price_lookup"] = subscription_price_lookup
        return data

    def __init__(
        self,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
    ) -> None:
        super().__init__(
            config=config,
            fx=fx,
            icon="stars4.svg",
            loop_in_thread=loop_in_thread,
            enabled=False,
            additional_access_providers=[],
            subscription_managers=subscription_managers,
            selected_subscription_key=selected_subscription_key,
            subscription_price_lookup=subscription_price_lookup,
        )

        self._sync_enabled_state()
        self._resolve_business_plan_id()

    def _resolve_business_plan_id(self) -> None:
        """
        The Business Plan is looked up by its product id in the service catalog. Until that succeeds,
        no plan is configured and no access is granted.
        """
        if self.loop_in_thread is None:
            logger.warning("Business Plan lookup skipped: no loop available")
            return
        proxy_url = self.config.network_config.proxy_url
        proxy_dict = ProxyInfo.parse(proxy_url).get_requests_proxy_dict() if proxy_url else None

        product_id = self.subscription_product_id
        assert product_id is not None

        async def do() -> str | None:
            plans = await asyncio.to_thread(SubscriptionApiClient(proxy_dict).fetch_plans)
            if not plans.get(product_id):
                return None
            return plan_id_for_product(plans, product_id)

        def on_success(plan_id: str | None) -> None:
            # A catalog without the product clears obsolete plan ids, so their access cannot survive.
            self.set_subscription_plan_ids((plan_id,) if plan_id else ())

        def on_error(error_info: ExcInfo | None) -> None:
            logger.warning("Business Plan lookup failed: %s", error_info)

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key="business_plan_lookup",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def _sync_access_state(self) -> None:
        self._sync_enabled_state()

    def set_business_plan(self, business_plan: BusinessPlanItem | None) -> None:
        pass

    def supports_enable_toggle(self) -> bool:
        return False

    def supports_refresh_subscription_status_action(self) -> bool:
        return self.subscription_manager.supports_refresh_subscription_status()

    def refresh_subscription_status_button_text(self) -> str:
        return self.subscription_manager.refresh_subscription_status_button_text()

    def trigger_refresh_subscription_status_action(self) -> None:
        self.subscription_manager.trigger_refresh_subscription_status(disable_if_inactive=False)

    def status_text(self) -> str:
        if self.subscription_allows_access() and not self.subscription_manager.activation_in_progress:
            return self.tr("Business plan access is active.")
        return super().status_text()

    def updateUi(self) -> None:
        super().updateUi()
        self.signal_enabled_changed.emit(self.enabled)

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct

    def _on_subscription_state_changed(self, storage_key: str) -> None:
        self._sync_enabled_state()
        super()._on_subscription_state_changed(storage_key)

    def _on_subscription_access_activated(self, storage_key: str) -> None:
        self._sync_enabled_state()
        super()._on_subscription_access_activated(storage_key)

    def _on_subscription_access_revoked(self, storage_key: str) -> None:
        self._sync_enabled_state()
        super()._on_subscription_access_revoked(storage_key)

    def _sync_enabled_state(self) -> None:
        self.enabled = self.subscription_allows_access()

    def load_paid_plugin(self) -> None:
        pass

    def unload_paid_plugin(self) -> None:
        pass
