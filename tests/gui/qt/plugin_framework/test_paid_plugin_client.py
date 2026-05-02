#
# Bitcoin Safe
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
# SOFTWARE.

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from btcpay_tools.btcpay_subscription_nostr.pos_item_lookup import BtcpayPosItemData
from btcpay_tools.btcpay_subscription_nostr.service import (
    SubscriptionManagementPhase,
    SubscriptionManagementStatus,
    SubscriptionManagementStatusCode,
)
from btcpay_tools.config import BTCPayConfig, PlanDuration
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

from bitcoin_safe.btcpay_config import BTCPAY_SUBSCRIPTION_CONFIG as PROD_BTCPAY_SUBSCRIPTION_CONFIG
from bitcoin_safe.config import UserConfig
from bitcoin_safe.execute_config import IS_PRODUCTION
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
from bitcoin_safe.plugin_framework.plugin_identity import PluginSource as PluginClientSource
from bitcoin_safe.plugin_framework.plugin_list_widget import (
    PaidPluginWidget,
)
from bitcoin_safe.plugin_framework.plugin_manager import PluginManagerWidget
from bitcoin_safe.plugin_framework.plugins.business_plan.client import BusinessPlanItem
from bitcoin_safe.plugin_framework.subscription_manager import (
    StoredSubscriptionStatus,
    SubscriptionManager,
)
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup
from tests.btcpay_support import (
    TEST_BTCPAY_SUBSCRIPTION_CONFIG as BTCPAY_SUBSCRIPTION_CONFIG,
)


def _make_subscription_managers(
    config: UserConfig,
    loop_in_thread: LoopInThread | None,
    product_id: str,
    duration: PlanDuration,
    management_url: str | None = None,
    status: SubscriptionManagementStatus | None = None,
    btcpay_config: BTCPayConfig = BTCPAY_SUBSCRIPTION_CONFIG,
) -> dict[str, SubscriptionManager] | None:
    if management_url is None and status is None:
        return None
    storage_key = btcpay_config.resolve_subscription(product_id, duration).plan_id
    return {
        storage_key: SubscriptionManager(
            config=config,
            loop_in_thread=loop_in_thread,
            subscription_product_key=product_id,
            btcpay_config=btcpay_config,
            subscription_duration=duration,
            management_url=management_url,
            stored_subscription_status=_stored_subscription_status(status),
        )
    }


def _make_pos_item(pos_url: str, item_id: str, price_text: str) -> BtcpayPosItemData:
    return BtcpayPosItemData(
        pos_url=pos_url,
        item_id=item_id,
        title=item_id,
        price_text=price_text,
        buy_button_text=f"Buy for {price_text}",
        form_action_url=pos_url,
        is_free=False,
    )


def _stored_subscription_status(
    status: SubscriptionManagementStatus | None,
    checked_at_ts: float = 123.0,
) -> StoredSubscriptionStatus:
    return StoredSubscriptionStatus(
        status=status,
        checked_at_ts=checked_at_ts if status else None,
        last_status_error=None,
    )


def _make_business_plan(
    config: UserConfig,
    fx: FX,
    loop_in_thread: LoopInThread | None,
    management_url: str | None = None,
    status: SubscriptionManagementStatus | None = None,
    subscription_price_lookup: SubscriptionPriceLookup | None = None,
) -> BusinessPlanItem:
    subscription_managers = _make_subscription_managers(
        config=config,
        loop_in_thread=loop_in_thread,
        product_id="business-plan",
        duration=PlanDuration.YEAR,
        management_url=management_url,
        status=status,
        btcpay_config=PROD_BTCPAY_SUBSCRIPTION_CONFIG,
    )
    return BusinessPlanItem(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        subscription_managers=subscription_managers,
        subscription_price_lookup=subscription_price_lookup,
    )


def _plan_texts(widget: PaidPluginWidget) -> list[str]:
    return [widget.plan_selector_combo.itemText(index) for index in range(widget.plan_selector_combo.count())]


# Test-local stand-in for the externalized demo paid plugin.
class DemoPaidPluginClient(PaidPluginClient):
    VERSION = "0.1.4"
    title = "Demo Subscription Plugin"
    description = (
        "Example plugin based on PaidPluginClient. "
        "Use this to verify subscription-gated activation and plugin-manager actions."
    )
    provider = "Bitcoin Safe"
    subscription_product_id = "demo-plugin"

    @classmethod
    def cls_kwargs(
        cls,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        additional_access_providers: list[Callable[[], bool]] | None = None,
        parent: QWidget | None = None,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
        btcpay_config: BTCPayConfig | None = BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
    ) -> dict[str, object]:
        data = super().cls_kwargs(
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            additional_access_providers=additional_access_providers,
            subscription_price_lookup=subscription_price_lookup,
            parent=parent,
        )
        if subscription_managers is not None:
            data["subscription_managers"] = subscription_managers
        if selected_subscription_key is not None:
            data["selected_subscription_key"] = selected_subscription_key
        return data

    def __init__(
        self,
        config: UserConfig,
        fx: FX,
        loop_in_thread: LoopInThread | None,
        additional_access_providers: list[Callable[[], bool]] | None,
        enabled: bool = False,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
        btcpay_config: BTCPayConfig = BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_price_lookup: SubscriptionPriceLookup | None = None,
    ) -> None:
        super().__init__(
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            icon=svg_tools.get_QIcon("stars4.svg"),
            enabled=enabled,
            subscription_managers=subscription_managers,
            selected_subscription_key=selected_subscription_key,
            additional_access_providers=additional_access_providers,
            btcpay_config=btcpay_config,
            subscription_price_lookup=subscription_price_lookup,
        )

        self._load_count = 0
        self._loaded_label = QLabel("", self)
        self._loaded_label.setWordWrap(True)
        self._click_counter = 0
        self._counter_label = QLabel("", self)
        self._counter_button = QPushButton(self.tr("Increment counter"), self)
        self._counter_button.clicked.connect(self._increment_counter)

        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.addWidget(
            QLabel(
                self.tr("This content is only available while the subscription remains active."),
                self,
            )
        )
        body_layout.addWidget(self._loaded_label)
        body_layout.addWidget(self._counter_label)
        body_layout.addWidget(self._counter_button)
        body_layout.addStretch()

        self.set_paid_content_widget(body)
        self._update_counter_label()

        if not IS_PRODUCTION:
            assert self.subscription_manager.subscription_product_key == "demo-plugin"

    def _increment_counter(self) -> None:
        self._click_counter += 1
        self._update_counter_label()

    def _update_counter_label(self) -> None:
        self._counter_label.setText(
            self.tr("Interaction counter in demo subscription widget: {count}").format(
                count=self._click_counter
            )
        )

    def load_paid_plugin(self) -> None:
        self._load_count += 1
        self._loaded_label.setText(
            self.tr("Loaded {count} time(s). Last load at: {ts}").format(
                count=self._load_count,
                ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )

    def unload_paid_plugin(self) -> None:
        return None

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        if "VERSION" in dct:
            del dct["VERSION"]
        return dct


def _make_demo_plugin(
    config: UserConfig,
    fx: FX,
    loop_in_thread: LoopInThread | None,
    business_plan: BusinessPlanItem | None = None,
    management_url: str | None = None,
    status: SubscriptionManagementStatus | None = None,
    subscription_price_lookup: SubscriptionPriceLookup | None = None,
) -> DemoPaidPluginClient:
    if subscription_price_lookup is None and business_plan is not None:
        subscription_price_lookup = business_plan.subscription_price_lookup
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        additional_access_providers=None,
        subscription_price_lookup=subscription_price_lookup,
        subscription_managers=_make_subscription_managers(
            config=config,
            loop_in_thread=loop_in_thread,
            product_id="demo-plugin",
            duration=PlanDuration.MONTH,
            management_url=management_url,
            status=status,
        ),
    )
    plugin.set_business_plan(business_plan)
    return plugin


@pytest.mark.marker_qt_1
def test_demo_paid_plugin_requires_active_subscription_on_mainnet(
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    plugin.set_enabled(True)
    assert not plugin.enabled
    assert plugin._loaded_label.text() == ""

    async def get_management_status(
        self: object,
        management_url: str,
        proxy_dict: dict[str, str] | None = None,
    ) -> SubscriptionManagementStatus:
        return SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
            auto_renew=True,
        )

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionManagementClient.get_management_status",
        get_management_status,
    )
    _run_subscription_tasks_synchronously(monkeypatch, plugin.subscription_managers)
    plugin.subscription_manager.management_url = "https://example.com/manage"
    plugin.subscription_manager.stored_subscription_status = _stored_subscription_status(
        SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        )
    )
    plugin.load()
    qtbot.waitUntil(
        lambda: plugin.subscription_manager.stored_subscription_status.checked_at_ts != 123.0,
        timeout=5_000,
    )
    assert plugin._loaded_label.text()

    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_demo_paid_plugin_requires_subscription_on_regtest(
    qapp: QApplication,
    test_config: UserConfig,
) -> None:
    config = test_config
    config.network = bdk.Network.REGTEST
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    plugin.set_enabled(True)
    assert plugin._loaded_label.text() == ""

    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_plugin_widget_shows_subscription_buttons_when_management_url_known(
    qapp: QApplication,
    test_config: UserConfig,
) -> None:
    config = test_config
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/manage",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )

    widget = PaidPluginWidget(plugin)
    widget.updateUi()
    assert not widget.manage_subscription_button.isHidden()
    assert not widget.refresh_subscription_button.isHidden()
    assert widget.manage_subscription_button.text() == "Manage"
    assert widget.refresh_subscription_button.text() == "Refresh status"
    assert widget.subscription_section.isHidden()
    assert not widget.management_section.isHidden()
    assert not widget.enable_checkbox.isHidden()
    assert widget.manage_subscription_button.toolTip() == "Manage"
    assert widget.refresh_subscription_button.toolTip() == "Refresh status"

    widget.close()
    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_plugin_list_widget_shows_btcpay_price_texts(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
) -> None:
    business_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("business-plan", PlanDuration.YEAR)
    demo_monthly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    demo_yearly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.YEAR)
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    subscription_price_lookup = SubscriptionPriceLookup()
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=None,
        subscription_price_lookup=subscription_price_lookup,
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    price_items = {
        business_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=business_product.pos_id,
            price_text="10,00 EUR",
        ),
        demo_monthly_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=demo_monthly_product.pos_id,
            price_text="2,00 EUR",
        ),
        demo_yearly_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=demo_yearly_product.pos_id,
            price_text="20,00 EUR",
        ),
    }
    for subscription_manager in (*business_plan.subscription_managers, *plugin.subscription_managers):
        subscription_price_lookup._set_items(subscription_manager.subscription_pos_base_url, price_items)
    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        assert widget.business_plan_widget is not None
        qtbot.waitUntil(
            lambda: _plan_texts(widget.business_plan_widget) == ["10,00 EUR / year"],
            timeout=5_000,
        )

        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)

        qtbot.waitUntil(
            lambda: _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"],
            timeout=5_000,
        )
        assert widget.business_plan_widget.plan_selector_title_label.text() == "Subscription"

        assert first_widget.start_trial_button.isVisible()
        assert first_widget.start_trial_button.text() == "Start free trial"
        assert first_widget.enable_checkbox.isHidden()
        assert first_widget.plan_selector_title_label.text() == "Subscription"
        assert _plan_texts(widget.business_plan_widget) == ["10,00 EUR / year"]
        assert _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"]

        widget.close()
    finally:
        plugin.close()
        subscription_price_lookup.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_list_widget_shows_btcpay_price_texts_without_business_plan(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demo_monthly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    demo_yearly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.YEAR)
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_price_lookup.BtcpayPosItemLookup.fetch",
        lambda self, pos_url, proxy_dict=None: {
            demo_monthly_product.pos_id: _make_pos_item(
                pos_url=pos_url,
                item_id=demo_monthly_product.pos_id,
                price_text="2,00 EUR",
            ),
            demo_yearly_product.pos_id: _make_pos_item(
                pos_url=pos_url,
                item_id=demo_yearly_product.pos_id,
                price_text="20,00 EUR",
            ),
        },
    )
    config = test_config_main_chain
    # Keep widget price rendering synchronous so Windows teardown does not race
    # with background BTCPay lookup callbacks.
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=None,
    )
    _run_subscription_tasks_synchronously(monkeypatch, plugin.subscription_managers)
    try:
        widget = PluginManagerWidget(business_plan=None)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)
        qtbot.waitUntil(
            lambda: _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"],
            timeout=5_000,
        )
        assert widget.business_plan_widget is None
        assert _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"]

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_widget_hides_subscription_prices_when_lookup_returns_no_item(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls = 0

    def fake_fetch(self, pos_url: str, proxy_dict=None) -> dict[str, BtcpayPosItemData]:
        nonlocal fetch_calls
        fetch_calls += 1
        return {}

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_price_lookup.BtcpayPosItemLookup.fetch",
        fake_fetch,
    )
    config = test_config_main_chain
    # This test only verifies fallback UI text, so run the lookup synchronously
    # to avoid Windows-only stalls in the shared loop thread.
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    _run_subscription_tasks_synchronously(
        monkeypatch, (*business_plan.subscription_managers, *plugin.subscription_managers)
    )
    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        assert widget.business_plan_widget is not None
        qtbot.waitUntil(
            lambda: fetch_calls >= 1 and _plan_texts(widget.business_plan_widget) == ["Yearly"],
            timeout=5_000,
        )
        assert not widget.business_plan_widget.offer_label.isVisible()
        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)
        assert not first_widget.offer_label.isVisible()
        assert _plan_texts(widget.business_plan_widget) == ["Yearly"]
        assert _plan_texts(first_widget) == ["Monthly", "Yearly"]

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_widget_swallows_offer_lookup_failures(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls = 0

    def fake_fetch(self, pos_url: str, proxy_dict=None) -> dict[str, BtcpayPosItemData]:
        nonlocal fetch_calls
        fetch_calls += 1
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_price_lookup.BtcpayPosItemLookup.fetch",
        fake_fetch,
    )
    config = test_config_main_chain
    # The failure handling under test is synchronous UI fallback logic, so keep
    # the BTCPay lookup on the local thread for deterministic teardown.
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    _run_subscription_tasks_synchronously(
        monkeypatch, (*business_plan.subscription_managers, *plugin.subscription_managers)
    )
    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        assert widget.business_plan_widget is not None
        qtbot.waitUntil(
            lambda: (
                fetch_calls >= 1
                and _plan_texts(widget.business_plan_widget) == ["Yearly"]
                and "No subscription has been activated yet."
                in widget.business_plan_widget.status_label.text()
            ),
            timeout=5_000,
        )
        assert not widget.business_plan_widget.offer_label.isVisible()
        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)
        assert not first_widget.offer_label.isVisible()
        assert _plan_texts(first_widget) == ["Monthly", "Yearly"]
        assert "No subscription has been activated yet." in widget.business_plan_widget.status_label.text()

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_btcpay_offer_lookup_shares_single_fetch_for_same_pos_url(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls = 0
    business_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("business-plan", PlanDuration.YEAR)
    demo_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    subscription_pos_base_url = BTCPAY_SUBSCRIPTION_CONFIG.subscription_pos_base_url()

    def fake_fetch(self, pos_url: str, proxy_dict=None) -> dict[str, BtcpayPosItemData]:
        nonlocal fetch_calls
        fetch_calls += 1
        time.sleep(0.1)
        return {
            business_product.pos_id: _make_pos_item(
                pos_url=subscription_pos_base_url,
                item_id=business_product.pos_id,
                price_text="10,00 EUR",
            ),
            demo_product.pos_id: _make_pos_item(
                pos_url=subscription_pos_base_url,
                item_id=demo_product.pos_id,
                price_text="2,00 EUR",
            ),
        }

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_price_lookup.BtcpayPosItemLookup.fetch",
        fake_fetch,
    )
    config = test_config_main_chain
    # This assertion is about lookup caching, not cross-thread scheduling.
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    _run_subscription_tasks_synchronously(
        monkeypatch, (*business_plan.subscription_managers, *plugin.subscription_managers)
    )

    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        assert widget.business_plan_widget is not None
        qtbot.waitUntil(
            lambda: "10,00 EUR / year" in _plan_texts(widget.business_plan_widget),
            timeout=5_000,
        )
        assert fetch_calls == 2

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_list_widget_reuses_cached_price_texts_on_reload(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_calls = 0
    business_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("business-plan", PlanDuration.YEAR)
    demo_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    subscription_pos_base_url = BTCPAY_SUBSCRIPTION_CONFIG.subscription_pos_base_url()

    def fake_fetch(self, pos_url: str, proxy_dict=None) -> dict[str, BtcpayPosItemData]:
        nonlocal fetch_calls
        fetch_calls += 1
        return {
            business_product.pos_id: _make_pos_item(
                pos_url=subscription_pos_base_url,
                item_id=business_product.pos_id,
                price_text="10,00 EUR",
            ),
            demo_product.pos_id: _make_pos_item(
                pos_url=subscription_pos_base_url,
                item_id=demo_product.pos_id,
                price_text="2,00 EUR",
            ),
        }

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_price_lookup.BtcpayPosItemLookup.fetch",
        fake_fetch,
    )
    config = test_config_main_chain
    # Keep the reload/cache assertion on the synchronous code path so widget
    # replacement does not race with cross-thread price lookup callbacks.
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )

    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        assert widget.business_plan_widget is not None
        qtbot.waitUntil(
            lambda: "10,00 EUR / year" in _plan_texts(widget.business_plan_widget),
            timeout=5_000,
        )
        org_first_plugin_widget = widget.plugins_widgets[0]
        assert isinstance(org_first_plugin_widget, PaidPluginWidget)
        qtbot.waitUntil(
            lambda: "2,00 EUR / month" in _plan_texts(org_first_plugin_widget),
            timeout=5_000,
        )

        widget.set_plugins([plugin])

        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)

        assert first_widget is not org_first_plugin_widget
        qtbot.waitUntil(
            lambda: "2,00 EUR / month" in _plan_texts(first_widget),
            timeout=5_000,
        )
        assert first_widget.offer_label.isHidden()
        assert _plan_texts(first_widget) == ["2,00 EUR / month", "Yearly"]
        assert fetch_calls == 2

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_widget_plan_selector_updates_price_and_trial_cta(
    qapp: QApplication,
    qtbot: QtBot,
    loop_in_thread: LoopInThread,
    test_config_main_chain: UserConfig,
) -> None:
    business_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("business-plan", PlanDuration.YEAR)
    demo_monthly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    demo_yearly_product = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.YEAR)
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=loop_in_thread, update_rates=False)
    subscription_price_lookup = SubscriptionPriceLookup()
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        subscription_price_lookup=subscription_price_lookup,
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        business_plan=business_plan,
    )
    price_items = {
        business_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=business_product.pos_id,
            price_text="10,00 EUR",
        ),
        demo_monthly_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=demo_monthly_product.pos_id,
            price_text="2,00 EUR",
        ),
        demo_yearly_product.pos_id: _make_pos_item(
            pos_url="",
            item_id=demo_yearly_product.pos_id,
            price_text="20,00 EUR",
        ),
    }
    for subscription_manager in (*business_plan.subscription_managers, *plugin.subscription_managers):
        subscription_price_lookup._set_items(subscription_manager.subscription_pos_base_url, price_items)
    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        qtbot.addWidget(widget)
        widget.set_plugins([plugin])
        widget.show()

        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)
        qtbot.waitUntil(
            lambda: _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"],
            timeout=5_000,
        )
        assert first_widget.start_trial_button.text() == "Start free trial"
        assert first_widget.enable_checkbox.isHidden()
        assert _plan_texts(first_widget) == ["2,00 EUR / month", "20,00 EUR / year"]

        first_widget.plan_selector_combo.setCurrentIndex(1)

        qtbot.waitUntil(
            lambda: plugin.selected_subscription_plan.duration == PlanDuration.YEAR, timeout=5_000
        )
        assert plugin.selected_subscription_plan.duration == PlanDuration.YEAR

        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_close_disconnects_shared_price_lookup_signal(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    subscription_price_lookup = SubscriptionPriceLookup()
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        subscription_price_lookup=subscription_price_lookup,
    )

    try:
        updates: list[str] = []
        plugin.signal_price_texts_changed.connect(lambda: updates.append("updated"))

        subscription_price_lookup.signal_prices_changed.emit(
            plugin.subscription_manager.subscription_pos_base_url
        )
        assert updates == ["updated"]

        updates.clear()
        plugin.close()
        subscription_price_lookup.signal_prices_changed.emit(
            plugin.subscription_manager.subscription_pos_base_url
        )
        assert updates == []
    finally:
        subscription_price_lookup.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_close_closes_private_subscription_price_lookup(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    try:
        assert not plugin.subscription_price_lookup._closed
        plugin.close()
        assert plugin.subscription_price_lookup._closed
    finally:
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_close_does_not_close_shared_subscription_price_lookup(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    subscription_price_lookup = SubscriptionPriceLookup()
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        subscription_price_lookup=subscription_price_lookup,
    )

    try:
        plugin.close()
        assert not subscription_price_lookup._closed
    finally:
        subscription_price_lookup.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_subscription_price_lookup_close_is_idempotent(qapp: QApplication) -> None:
    subscription_price_lookup = SubscriptionPriceLookup()

    assert subscription_price_lookup.close()
    assert subscription_price_lookup._closed
    assert subscription_price_lookup.close()


def _attach_fake_descriptor_server(plugin: DemoPaidPluginClient) -> None:
    plugin.server = type("FakeServer", (), {"get_descriptor": lambda self: object()})()


def _run_subscription_tasks_synchronously(
    monkeypatch: pytest.MonkeyPatch,
    subscription_managers: tuple[SubscriptionManager, ...],
) -> None:
    def run_task_sync(
        coro,
        on_success=None,
        on_done=None,
        on_error=None,
        cancel=None,
        key=None,
        multiple_strategy=None,
    ):
        result = None
        try:
            result = asyncio.run(coro)
        except Exception as exc:
            if on_error:
                on_error((type(exc), exc, exc.__traceback__))
        else:
            if on_success:
                on_success(result)
        finally:
            if on_done:
                on_done(result)
            if cancel:
                cancel()
        return None

    for subscription_manager in subscription_managers:
        monkeypatch.setattr(subscription_manager.loop_in_thread, "run_task", run_task_sync)


@pytest.mark.marker_qt_1
def test_demo_paid_plugin_starts_trial_on_first_enable(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    async def fake_start_and_wait(self) -> object:
        return type(
            "Session",
            (),
            {
                "management_payload": type(
                    "ManagementPayload",
                    (),
                    {
                        "management_url": "https://example.com/manage",
                    },
                )(),
            },
        )()

    async def fake_get_management_status(
        self,
        management_url: str,
        proxy_dict: dict[str, str] | None = None,
    ) -> SubscriptionManagementStatus:
        return SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        )

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.question_dialog",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionPurchaseClient.start_and_wait",
        fake_start_and_wait,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionManagementClient.get_management_status",
        fake_get_management_status,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionManager.get_to_be_signed",
        lambda self, multipath_descriptor: "descriptor-hash",
    )
    _attach_fake_descriptor_server(plugin)
    _run_subscription_tasks_synchronously(monkeypatch, plugin.subscription_managers)

    requested_enable: list[bool] = []
    plugin.signal_request_enabled.connect(requested_enable.append)

    assert not plugin.allow_enable_request()
    assert plugin.subscription_manager.management_url == "https://example.com/manage"
    assert plugin.subscription_manager.stored_subscription_status.status is not None
    assert (
        plugin.subscription_manager.stored_subscription_status.status.status
        == SubscriptionManagementStatusCode.TRIAL
    )
    assert requested_enable == [True]

    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_demo_paid_plugin_disables_when_trial_purchase_refresh_is_inactive(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    async def fake_start_and_wait(self) -> object:
        return type(
            "Session",
            (),
            {
                "management_payload": type(
                    "ManagementPayload",
                    (),
                    {
                        "management_url": "https://example.com/manage",
                    },
                )(),
            },
        )()

    async def fake_get_management_status(
        self,
        management_url: str,
        proxy_dict: dict[str, str] | None = None,
    ) -> SubscriptionManagementStatus:
        return SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.EXPIRED,
            phase=SubscriptionManagementPhase.NORMAL,
            is_active=False,
            is_suspended=False,
        )

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.question_dialog",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionPurchaseClient.start_and_wait",
        fake_start_and_wait,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionManagementClient.get_management_status",
        fake_get_management_status,
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.subscription_manager.SubscriptionManager.get_to_be_signed",
        lambda self, multipath_descriptor: "descriptor-hash",
    )
    _attach_fake_descriptor_server(plugin)
    _run_subscription_tasks_synchronously(monkeypatch, plugin.subscription_managers)

    requested_enable: list[bool] = []
    plugin.signal_request_enabled.connect(requested_enable.append)

    assert not plugin.allow_enable_request()
    assert plugin.subscription_manager.management_url == "https://example.com/manage"
    assert plugin.subscription_manager.stored_subscription_status.status is not None
    assert (
        plugin.subscription_manager.stored_subscription_status.status.status
        == SubscriptionManagementStatusCode.EXPIRED
    )
    assert requested_enable == []

    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_demo_paid_plugin_start_trial_requests_enable(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)

    try:
        requested_enable: list[bool] = []
        plugin.signal_request_enabled.connect(requested_enable.append)

        plugin.trigger_start_trial()

        assert requested_enable == [True]
        assert plugin.subscription_manager.management_url is None
    finally:
        plugin.close()
        fx.close()


def test_demo_paid_plugin_roundtrip_persists_management_url_and_status(
    qapp: QApplication,
    loop_in_thread: LoopInThread,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=loop_in_thread, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/manage",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )

    restored = DemoPaidPluginClient._from_dumps(
        plugin.dumps(),
        class_kwargs={
            DemoPaidPluginClient.__name__: DemoPaidPluginClient.cls_kwargs(
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
            ),
            SubscriptionManager.__name__: SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
                btcpay_config=BTCPAY_SUBSCRIPTION_CONFIG,
            ),
        },
    )

    assert restored.subscription_manager.management_url == "https://example.com/manage"
    assert restored.subscription_manager.stored_subscription_status.status is not None
    assert (
        restored.subscription_manager.stored_subscription_status.status.status
        == SubscriptionManagementStatusCode.TRIAL
    )

    restored.close()
    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_business_plan_item_roundtrip_persists_management_url_and_status(
    qapp: QApplication,
    loop_in_thread: LoopInThread,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=loop_in_thread, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/manage",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )

    restored = BusinessPlanItem._from_dumps(
        business_plan.dumps(),
        class_kwargs={
            BusinessPlanItem.__name__: BusinessPlanItem.cls_kwargs(
                config=config,
                fx=fx,
                loop_in_thread=loop_in_thread,
            ),
            SubscriptionManager.__name__: SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=loop_in_thread,
            ),
        },
    )

    assert restored.subscription_manager.management_url == "https://example.com/manage"
    assert restored.subscription_manager.stored_subscription_status.status is not None
    assert (
        restored.subscription_manager.stored_subscription_status.status.status
        == SubscriptionManagementStatusCode.TRIAL
    )

    restored.close()
    business_plan.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_business_plan_item_shows_trial_action_without_toggle(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    fx = FX(config=test_config_main_chain, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=test_config_main_chain, fx=fx, loop_in_thread=None)

    widget = PaidPluginWidget(business_plan)

    assert widget.enable_checkbox.isHidden()
    assert widget.start_trial_button.text() == "Start free trial"
    assert "No subscription has been activated yet." in widget.status_label.text()

    widget.close()
    business_plan.close()
    fx.close()


@pytest.mark.marker_qt_1
def test_known_subscription_hides_plan_selector_and_ignores_selected_plan(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    monthly_key = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH).plan_id
    yearly_key = BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.YEAR).plan_id
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=None,
        additional_access_providers=None,
        subscription_managers=_make_subscription_managers(
            config=config,
            loop_in_thread=None,
            product_id="demo-plugin",
            duration=PlanDuration.MONTH,
            management_url="https://example.com/manage",
            status=SubscriptionManagementStatus(
                status=SubscriptionManagementStatusCode.TRIAL,
                phase=SubscriptionManagementPhase.TRIAL,
                is_active=True,
                is_suspended=False,
            ),
        ),
        selected_subscription_key=yearly_key,
    )

    try:
        widget = PaidPluginWidget(plugin)
        assert plugin.selected_subscription_plan.duration == PlanDuration.YEAR
        assert plugin.displayed_subscription_manager.subscription_duration == PlanDuration.MONTH
        assert widget.plan_selector_container.isHidden()
        assert widget.start_trial_button.isHidden()
        assert not widget.manage_subscription_button.isHidden()
        assert not widget.enable_checkbox.isHidden()

        initial_status = plugin.status_text()
        assert "Management URL saved." in initial_status

        plugin.select_plan_option(monthly_key)

        assert plugin.status_text() == initial_status
        assert widget.status_label.text() == initial_status
        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_scheduled_payments_uses_subscription_status_text_without_access(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None, business_plan=business_plan)

    try:
        assert "No subscription has been activated yet." in plugin.status_text()
        plugin.subscription_manager._activation_in_progress = True
        assert "Waiting for the free trial to be activated..." in plugin.status_text()
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_stays_hidden_while_trial_activation_is_in_progress(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
    )

    try:
        plugin.subscription_manager._activation_in_progress = True
        plugin.subscription_manager.signal_state_changed.emit()

        assert not plugin.enabled
        assert not plugin.node.isVisible()
        assert plugin._plugin_content.isHidden()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_subscription_action_buttons_use_management_section(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
) -> None:
    fx = FX(config=test_config_main_chain, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=test_config_main_chain,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/manage",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )

    try:
        widget = PaidPluginWidget(plugin)
        qtbot.addWidget(widget)
        widget.show()

        assert widget.manage_subscription_button.parentWidget() is widget.management_buttons_container
        assert widget.refresh_subscription_button.parentWidget() is widget.management_buttons_container
        assert widget.manage_subscription_button.text() == "Manage"
        assert widget.refresh_subscription_button.text() == "Refresh status"
        assert widget.subscription_section.isHidden()
        assert not widget.management_section.isHidden()
    finally:
        widget.close()
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_external_paid_plugin_places_update_button_with_action_controls(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    fx = FX(config=test_config_main_chain, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=test_config_main_chain,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/manage",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )
    plugin.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="demo-plugin",
    )
    plugin.set_external_state(
        update_available=True,
        installed_version="1.0.0",
        available_version="9.9.9",
        available_hash="new-hash",
    )

    widget = None
    try:
        widget = plugin.create_plugin_widget()

        assert widget.update_button.parentWidget() is widget.action_buttons_container
        assert widget.delete_button.parentWidget() is widget.action_buttons_container
        assert widget.action_buttons_layout.itemAt(0).widget() is widget.update_button
        assert widget.action_buttons_layout.itemAt(1).widget() is widget.delete_button
        assert widget.manage_subscription_button.parentWidget() is widget.management_buttons_container
        assert widget.refresh_subscription_button.parentWidget() is widget.management_buttons_container
    finally:
        if widget is not None:
            widget.close()
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_subscription_management_row_stays_hidden_without_visible_actions(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
) -> None:
    fx = FX(config=test_config_main_chain, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=test_config_main_chain,
        fx=fx,
        loop_in_thread=None,
    )

    try:
        widget = PaidPluginWidget(plugin)
        qtbot.addWidget(widget)
        widget.show()

        widget.management_buttons_container.setVisible(True)
        widget.manage_subscription_button.setVisible(False)
        widget.refresh_subscription_button.setVisible(False)
        widget._sync_section_visibility()

        assert widget.management_section.isHidden()
        assert widget.subscription_section.isVisible()
    finally:
        widget.close()
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_business_plan_unlocks_paid_plugin(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/business",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    try:
        _attach_fake_descriptor_server(plugin)
        assert plugin.allow_enable_request()

        widget = PaidPluginWidget(business_plan)
        assert "Business plan access is active." in widget.status_label.text()
        widget.close()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_shows_toggle_and_hides_trial_when_business_plan_is_active(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/business",
        status=SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode.TRIAL,
            phase=SubscriptionManagementPhase.TRIAL,
            is_active=True,
            is_suspended=False,
        ),
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    try:
        widget = PaidPluginWidget(plugin)
        assert widget.start_trial_button.isHidden()
        assert not widget.enable_checkbox.isHidden()
        assert widget.subscription_section.isHidden()
        assert widget.management_section.isHidden()
        assert not widget.activation_section.isHidden()
        assert "Business plan access is active." in widget.status_label.text()
        widget.close()
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_paid_plugin_widget_updates_when_business_plan_becomes_active(
    qapp: QApplication,
    qtbot: QtBot,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=None,
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    try:
        widget = PaidPluginWidget(plugin)
        qtbot.addWidget(widget)
        widget.show()

        assert not widget.start_trial_button.isHidden()
        assert widget.enable_checkbox.isHidden()
        assert not widget.subscription_section.isHidden()
        assert widget.activation_section.isHidden()

        business_plan.subscription_manager.management_url = "https://example.com/business"
        business_plan.subscription_manager.stored_subscription_status = _stored_subscription_status(
            SubscriptionManagementStatus(
                status=SubscriptionManagementStatusCode.ACTIVE,
                phase=SubscriptionManagementPhase.NORMAL,
                is_active=True,
                is_suspended=False,
            )
        )
        business_plan._on_subscription_state_changed(
            BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("business-plan", PlanDuration.YEAR).plan_id
        )

        qtbot.waitUntil(
            lambda: widget.start_trial_button.isHidden() and not widget.enable_checkbox.isHidden(),
            timeout=5_000,
        )
        assert widget.subscription_section.isHidden()
        assert not widget.activation_section.isHidden()

        widget.close()
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_scheduled_payments_shows_subscription_page_without_access(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    try:
        widget = plugin.create_plugin_widget()
        assert widget.status_label.text() == "No subscription has been activated yet."

        plugin.set_enabled(True)

        assert not plugin.subscription_allows_access()
        assert not plugin.enabled
        assert widget.start_trial_button.text() == "Start free trial"

        widget.close()
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plugin_list_widget_keeps_business_plan_above_plugins(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(config=config, fx=fx, loop_in_thread=None)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
    )
    try:
        widget = PluginManagerWidget(business_plan=business_plan)
        widget.resize(900, 500)
        widget.set_plugins([plugin])
        widget.show()
        QApplication.processEvents()

        assert widget.business_plan_widget is not None
        assert widget.business_plan_header.title_label.text() == "Business plan"
        assert widget.plugins_header.title_label.text() == "Plugins"
        assert len(widget.plugins_widgets) == 1

        first_widget = widget.plugins_widgets[0]
        assert isinstance(first_widget, PaidPluginWidget)

        assert first_widget.plugin is plugin
        assert first_widget.start_trial_button.isVisible()
        assert widget.business_plan_widget.enable_checkbox.isHidden()

        widget.close()
    finally:
        plugin.close()
        fx.close()
