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

import logging
from concurrent.futures import Future
from typing import cast

from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from btcpay_tools.btcpay_subscription_api.models import PlanCatalogItem
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.plugin_framework.subscription_api_client import (
    SUBSCRIPTION_API_BASE_URL,
    SubscriptionApiClient,
    flatten_plans,
)
from bitcoin_safe.plugin_framework.subscription_manager import SubscriptionManager

logger = logging.getLogger(__name__)


class _SubscriptionPriceLookupState:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class SubscriptionPriceLookup(QObject):
    """Caches the public plan catalog. The signal carries the catalog cache key."""

    signal_prices_changed = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.signal_tracker = SignalTracker()
        self._state = _SubscriptionPriceLookupState()
        self._catalog_by_plan_id: dict[str, PlanCatalogItem] = {}
        self._loading = False
        self._fetch_task: Future[list[PlanCatalogItem]] | None = None
        self.signal_tracker.connect(cast(SignalProtocol[[]], self.destroyed), self._state.close)

    @property
    def _closed(self) -> bool:
        return self._state.closed

    def ensure_prices(self, subscription_manager: SubscriptionManager) -> None:
        if self._closed or self._loading or self._catalog_by_plan_id:
            return

        proxy_dict = subscription_manager.proxy_dict()
        self._loading = True
        if subscription_manager.loop_in_thread is None:
            try:
                self._set_catalog(flatten_plans(SubscriptionApiClient(proxy_dict).fetch_plans()))
            except Exception as exc:
                self._handle_fetch_error(exc)
            return

        future: Future[list[PlanCatalogItem]] | None = None

        def on_success(plans: list[PlanCatalogItem] | None) -> None:
            self._on_fetch_success(plans, future)

        def on_error(error_info: ExcInfo | Exception | None) -> None:
            self._handle_fetch_error(error_info, future)

        future = subscription_manager.loop_in_thread.run_task(
            self._fetch_catalog_async(proxy_dict),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"subscription_prices:{SUBSCRIPTION_API_BASE_URL}",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )
        if future is not None:
            self._fetch_task = future

    def catalog_item_for_plan_id(self, plan_id: str) -> PlanCatalogItem | None:
        if self._closed:
            return None
        return self._catalog_by_plan_id.get(plan_id)

    def close(self) -> bool:
        if self._closed:
            return True

        self._state.close()
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._fetch_task = None
        self.signal_tracker.disconnect_all()
        self._loading = False
        return True

    async def _fetch_catalog_async(self, proxy_dict: dict[str, str] | None) -> list[PlanCatalogItem]:
        return flatten_plans(SubscriptionApiClient(proxy_dict).fetch_plans())

    def _on_fetch_success(
        self,
        plans: list[PlanCatalogItem] | None,
        future: Future[list[PlanCatalogItem]] | None = None,
    ) -> None:
        if self._closed:
            return

        self._clear_fetch_task(future)
        self._set_catalog(plans or [])

    def _set_catalog(self, plans: list[PlanCatalogItem]) -> None:
        if self._closed:
            return

        self._loading = False
        self._catalog_by_plan_id = {plan.plan_id: plan for plan in plans}
        self.signal_prices_changed.emit(SUBSCRIPTION_API_BASE_URL)

    def _handle_fetch_error(
        self,
        error_info: ExcInfo | Exception | None,
        future: Future[list[PlanCatalogItem]] | None = None,
    ) -> None:
        if self._closed:
            return

        self._clear_fetch_task(future)
        logger.debug("Subscription plan catalog lookup failed: %s", error_info)
        self._loading = False
        self.signal_prices_changed.emit(SUBSCRIPTION_API_BASE_URL)

    def _clear_fetch_task(self, future: Future[list[PlanCatalogItem]] | None) -> None:
        if future is None or self._fetch_task is future:
            self._fetch_task = None
