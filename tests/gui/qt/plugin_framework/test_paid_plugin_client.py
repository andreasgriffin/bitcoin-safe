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
# SOFTWARE.

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from btcpay_tools.btcpay_subscription_api.models import (
    PlanCatalogItem,
    SubscriptionStatusCode,
    SubscriptionStatusResponse,
)
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import SUPPORT_EMAIL
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
from bitcoin_safe.plugin_framework.subscription_api_client import SubscriptionApiClient
from bitcoin_safe.plugin_framework.subscription_manager import (
    StoredSubscriptionStatus,
    SubscriptionManager,
)
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup
from tests.btcpay_support import (
    TEST_BUSINESS_PLAN_ID,
    TEST_MONTHLY_PLAN_ID,
    TEST_YEARLY_PLAN_ID,
)

BUSINESS_PRODUCT_ID = "business-plan"
TEST_DEMO_PRODUCT_ID = "demo-plan"


def _make_subscription_managers(
    config: UserConfig,
    loop_in_thread: LoopInThread | None,
    product_id: str,
    plan_id: str,
    management_url: str | None = None,
    status: SubscriptionStatusResponse | None = None,
) -> dict[str, SubscriptionManager] | None:
    if management_url is None and status is None:
        return None
    return {
        product_id: SubscriptionManager(
            config=config,
            loop_in_thread=loop_in_thread,
            plan_id=plan_id,
            subscriber_email=SUBSCRIBER_EMAIL,
            management_url=management_url,
            stored_subscription_status=_stored_subscription_status(status),
        )
    }


SUBSCRIBER_EMAIL = "descriptor-hash@v0.bitcoin-safe.org"


def _subscribed_manager(config: UserConfig, plan_id: str) -> SubscriptionManager:
    """A manager of an active trial: the subscription is bound to the subscriber email."""
    return SubscriptionManager(
        config=config,
        loop_in_thread=None,
        plan_id=plan_id,
        subscriber_email=SUBSCRIBER_EMAIL,
        management_url="https://example.com/manage",
        stored_subscription_status=_stored_subscription_status(
            SubscriptionStatusResponse(plan_id=plan_id, status=SubscriptionStatusCode.TRIAL)
        ),
    )


def _stored_subscription_status(
    status: SubscriptionStatusResponse | None,
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
    status: SubscriptionStatusCode | None = None,
    subscription_price_lookup: SubscriptionPriceLookup | None = None,
) -> BusinessPlanItem:
    subscription_managers = _make_subscription_managers(
        config=config,
        loop_in_thread=loop_in_thread,
        product_id=BUSINESS_PRODUCT_ID,
        plan_id=TEST_BUSINESS_PLAN_ID,
        management_url=management_url,
        status=status,
    ) or {
        BUSINESS_PRODUCT_ID: SubscriptionManager(
            config=config, loop_in_thread=loop_in_thread, plan_id=TEST_BUSINESS_PLAN_ID
        )
    }
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
    provider = "Bitcoin-Safe"
    subscription_product_id = TEST_DEMO_PRODUCT_ID

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
            subscription_product_id=self.subscription_product_id,
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
            assert self.subscription_manager.plan_id == TEST_MONTHLY_PLAN_ID

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
    status: SubscriptionStatusCode | None = None,
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
            product_id=TEST_DEMO_PRODUCT_ID,
            plan_id=TEST_MONTHLY_PLAN_ID,
            management_url=management_url,
            status=status,
        ),
    )
    plugin.set_business_plan(business_plan)
    return plugin


@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
def test_paid_plugin_load_can_defer_subscription_refresh(
    qapp: QApplication,
    test_config: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del qapp
    plugin = _make_demo_plugin(
        config=test_config,
        fx=FX(config=test_config, loop_in_thread=None, update_rates=False),
        loop_in_thread=None,
    )
    refresh_calls: list[None] = []
    monkeypatch.setattr(
        plugin.subscription_manager,
        "refresh_subscription_status",
        lambda **kwargs: refresh_calls.append(None),
    )

    try:
        plugin.load(refresh_subscription_status=False)
        assert refresh_calls == []
        plugin.load()
        assert refresh_calls == [None]
    finally:
        plugin.close()


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
        status=SubscriptionStatusResponse(
            plan_id=TEST_MONTHLY_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
        ),
    )

    widget = PaidPluginWidget(plugin)
    widget.updateUi()
    assert not widget.manage_subscription_button.isHidden()
    assert not widget.refresh_subscription_button.isHidden()
    assert widget.manage_subscription_button.text() == "Manage"
    assert widget.refresh_subscription_button.text() == "Refresh status"
    assert widget.management_title_label.textLabel.text() == "Subscription:"
    assert (
        widget.management_title_label.toolTip()
        == "This subscription is valid on any computer with this wallet"
    )
    assert widget.subscription_section.isHidden()
    assert not widget.management_section.isHidden()
    assert not widget.enable_checkbox.isHidden()
    assert widget.manage_subscription_button.toolTip() == "Manage"
    assert widget.refresh_subscription_button.toolTip() == "Refresh status"

    widget.close()
    plugin.close()
    fx.close()


@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
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


@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
def _attach_fake_descriptor_server(plugin: DemoPaidPluginClient) -> None:
    plugin.wallet_context = type("FakeWalletContext", (), {"descriptor": lambda self: object()})()


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
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
@pytest.mark.marker_qt_1
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
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
        restored.subscription_manager.stored_subscription_status.status.status == SubscriptionStatusCode.TRIAL
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
    assert widget.check_subscription_button.text() == "Check subscription"
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
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=None,
        additional_access_providers=None,
        subscription_managers={
            TEST_DEMO_PRODUCT_ID: _subscribed_manager(config, TEST_MONTHLY_PLAN_ID),
        },
        selected_subscription_key=TEST_DEMO_PRODUCT_ID,
    )

    try:
        widget = PaidPluginWidget(plugin)
        assert plugin.displayed_subscription_manager.plan_id == TEST_MONTHLY_PLAN_ID
        assert widget.plan_selector_container.isHidden()
        assert widget.start_trial_button.isHidden()
        assert not widget.manage_subscription_button.isHidden()
        assert not widget.enable_checkbox.isHidden()

        initial_status = plugin.status_text()

        plugin.select_plan_option(TEST_YEARLY_PLAN_ID)

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
        status=SubscriptionStatusResponse(
            plan_id=TEST_MONTHLY_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_MONTHLY_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
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
        assert widget.action_buttons_layout.itemAt(0).widget() is widget.open_button
        assert widget.action_buttons_layout.itemAt(1).widget() is widget.update_button
        assert widget.action_buttons_layout.itemAt(2).widget() is widget.delete_button
        assert widget.manage_subscription_button.parentWidget() is widget.management_buttons_container
        assert widget.refresh_subscription_button.parentWidget() is widget.management_buttons_container
    finally:
        if widget is not None:
            widget.close()
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_subscription_status_is_shown_next_to_refresh_button(
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
        status=SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE),
    )

    try:
        widget = PaidPluginWidget(plugin)
        qtbot.addWidget(widget)
        widget.show()
        widget.refresh_subscription_button.setVisible(True)
        widget.manage_subscription_button.setVisible(True)
        widget.set_status_text("Current status: Active.")
        widget._sync_section_visibility()

        # The status sits in the management row, after the buttons it describes, not above the row.
        assert widget.status_label.parentWidget() is widget.management_buttons_container
        row_index = widget.management_buttons_layout.indexOf(widget.status_label)
        refresh_index = widget.management_buttons_layout.indexOf(widget.refresh_subscription_button)
        assert row_index > refresh_index >= 0
        assert widget.status_label.isVisibleTo(widget)
    finally:
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID,
            status=SubscriptionStatusCode.TRIAL,
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
        business_plan.subscription_manager.subscriber_email = SUBSCRIBER_EMAIL
        business_plan.subscription_manager.stored_subscription_status = _stored_subscription_status(
            SubscriptionStatusResponse(plan_id=TEST_BUSINESS_PLAN_ID, status=SubscriptionStatusCode.ACTIVE)
        )
        business_plan.signal_enabled_changed.emit(True)

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
        assert widget.check_subscription_button.text() == "Check subscription"

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
    plugin.subscription_manager.set_plan_id(TEST_MONTHLY_PLAN_ID)

    plugin.set_enabled(True)
    assert not plugin.enabled
    assert plugin._loaded_label.text() == ""

    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: SubscriptionStatusResponse(
            plan_id=plan_id, status=SubscriptionStatusCode.TRIAL
        ),
    )
    _run_subscription_tasks_synchronously(monkeypatch, plugin.subscription_managers)
    plugin.subscription_manager.management_url = "https://example.com/manage"
    plugin.subscription_manager.subscriber_email = "descriptor-hash@v0.bitcoin-safe.org"
    plugin.load()
    qtbot.waitUntil(
        lambda: plugin.subscription_manager.stored_subscription_status.checked_at_ts is not None,
        timeout=5_000,
    )
    assert plugin.subscription_manager.subscription_allows_access()

    plugin.close()
    fx.close()


def test_management_url_fallback_dialog_shows_subscription_id(
    qapp: QApplication,
) -> None:
    # Pure dialog test: it needs no blockchain backend, so it must not depend on the
    # backend fixtures (which download Fulcrum from github.com when missing).
    management_url = "https://pay.bitcoin-safe.org/subscriber-portal/token"
    subscription_id = "descriptor-hash@v0.bitcoin-safe.org"
    subscription_manager = SubscriptionManager(
        config=UserConfig(),
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email=subscription_id,
    )

    def enter_management_url() -> None:
        dialog = qapp.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog_text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        assert "could not be fetched automatically" in dialog_text
        assert SUPPORT_EMAIL in dialog_text
        assert subscription_id in dialog_text

        management_url_input = dialog.findChild(QLineEdit)
        assert management_url_input is not None
        management_url_input.setText(management_url)

        button_box = dialog.findChild(QDialogButtonBox)
        assert button_box is not None
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        ok_button.click()

    QTimer.singleShot(0, enter_management_url)

    assert subscription_manager.prompt_management_url_dialog() == management_url

    subscription_manager.close()


def test_candidate_management_url_is_rejected_for_different_subscriber(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mocked status check only: needs no blockchain backend, so do not depend on the
    # backend fixtures (which download Fulcrum from github.com when missing).
    subscription_manager = SubscriptionManager(
        config=UserConfig(),
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="expected@v0.bitcoin-safe.org",
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: SubscriptionStatusResponse(
            plan_id=plan_id, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    _run_subscription_tasks_synchronously(monkeypatch, (subscription_manager,))

    subscription_manager._refresh_subscription_status(
        disable_if_inactive=True,
        notify_on_error=False,
        candidate_management_url="https://pay.bitcoin-safe.org/subscriber-portal/token",
    )

    assert subscription_manager.stored_subscription_status.status is not None
    assert subscription_manager.stored_subscription_status.last_status_error is None

    subscription_manager.close()


@pytest.mark.marker_qt_1
def test_obsolete_plan_removal_revokes_access(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None)
    plugin._set_subscription_plan_id(TEST_MONTHLY_PLAN_ID)
    active_manager = plugin.subscription_managers[0]
    active_manager.management_url = "https://example.com/manage"
    active_manager.subscriber_email = SUBSCRIBER_EMAIL
    active_manager.stored_subscription_status = _stored_subscription_status(
        SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE)
    )
    plugin.enabled = True
    plugin._plugin_loaded = True
    enabled_values: list[bool] = []
    plugin.signal_enabled_changed.connect(enabled_values.append)
    try:
        assert plugin.subscription_allows_access()

        plugin._set_subscription_plan_id(None)

        assert not plugin.subscription_allows_access()
        assert not plugin.enabled
        assert enabled_values == [False]
        assert active_manager not in plugin.subscription_managers
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_removing_only_access_source_disables_enabled_plugin(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/manage",
        status=SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE),
    )
    plugin.enabled = True
    plugin._plugin_loaded = True
    enabled_values: list[bool] = []
    plugin.signal_enabled_changed.connect(enabled_values.append)
    try:
        plugin._set_subscription_plan_id(None)

        assert not plugin.enabled
        assert enabled_values == [False]
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_business_plan_removal_disables_dependent_plugin(
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None, business_plan=business_plan)
    plugin.enabled = True
    plugin._plugin_loaded = True
    try:
        assert plugin.subscription_allows_access()

        business_plan._set_subscription_plan_id(None)

        assert not business_plan.enabled
        assert not plugin.subscription_allows_access()
        assert not plugin.enabled
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_business_plan_missing_product_clears_plan_ids_and_managers(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
    loop_in_thread: LoopInThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/business",
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    previous_manager = business_plan.subscription_manager
    closed: list[bool] = []
    monkeypatch.setattr(previous_manager, "close", lambda: closed.append(True))
    monkeypatch.setattr(SubscriptionApiClient, "fetch_plans", lambda self: {"other-product": []})
    _run_subscription_tasks_synchronously(monkeypatch, (previous_manager,))
    try:
        business_plan._resolve_subscription_plans()

        assert business_plan.subscription_managers == ()
        assert closed == [True]
        assert not business_plan.enabled
        assert not business_plan.subscription_allows_access()
    finally:
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_removing_individual_subscription_keeps_business_plan_access(
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
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=None,
        business_plan=business_plan,
        management_url="https://example.com/manage",
        status=SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE),
    )
    plugin.enabled = True
    plugin._plugin_loaded = True
    try:
        assert plugin._has_direct_subscription_access()

        plugin._set_subscription_plan_id(None)

        assert not plugin._has_direct_subscription_access()
        assert plugin._has_additional_access()
        assert plugin.subscription_allows_access()
        assert plugin.enabled
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_replacing_plan_ids_while_access_remains_emits_no_revocation(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
    loop_in_thread: LoopInThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    business_plan = _make_business_plan(
        config=config,
        fx=fx,
        loop_in_thread=None,
        management_url="https://example.com/business",
        status=SubscriptionStatusResponse(
            plan_id=TEST_BUSINESS_PLAN_ID, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    plugin = _make_demo_plugin(config=config, fx=fx, loop_in_thread=None, business_plan=business_plan)
    plugin.enabled = True
    plugin._plugin_loaded = True
    revocations: list[str] = []
    enabled_values: list[bool] = []
    plugin.signal_enabled_changed.connect(enabled_values.append)
    business_plan.subscription_manager.signal_access_revoked.connect(lambda: revocations.append("revoked"))
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: SubscriptionStatusResponse(
            plan_id=plan_id, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_management_url",
        lambda self, plan_id, buyer_email: "https://example.com/moved",
    )
    _run_subscription_tasks_synchronously(monkeypatch, (business_plan.subscription_manager,))
    try:
        business_plan.subscription_manager.set_plan_id("plan_moved")

        assert business_plan.subscription_manager.plan_id == "plan_moved"
        assert business_plan.subscription_manager.subscriber_email == SUBSCRIBER_EMAIL
        assert business_plan.subscription_manager.management_url == "https://example.com/moved"
        assert business_plan.subscription_allows_access()
        assert plugin.subscription_allows_access()
        assert plugin.enabled
        assert revocations == []
    finally:
        plugin.close()
        business_plan.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_legacy_plan_id_keyed_dump_adopts_single_manager_for_product(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    legacy_manager = _subscribed_manager(config, TEST_MONTHLY_PLAN_ID)
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=None,
        additional_access_providers=None,
        subscription_managers={TEST_MONTHLY_PLAN_ID: legacy_manager},
    )
    try:
        assert plugin.subscription_managers == (legacy_manager,)
        assert plugin.subscription_manager.subscriber_email == SUBSCRIBER_EMAIL
        assert plugin.subscription_manager.management_url == "https://example.com/manage"
        assert plugin._subscription_managers_by_key == {TEST_DEMO_PRODUCT_ID: legacy_manager}
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_offline_catalog_lookup_keeps_managers_and_access(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
    loop_in_thread: LoopInThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/manage",
        status=SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE),
    )
    previous_manager = plugin.subscription_manager
    closed: list[bool] = []
    monkeypatch.setattr(previous_manager, "close", lambda: closed.append(True))

    def offline(self) -> dict:
        raise ConnectionError("offline")

    monkeypatch.setattr(SubscriptionApiClient, "fetch_plans", offline)
    _run_subscription_tasks_synchronously(monkeypatch, (previous_manager,))
    try:
        plugin._resolve_subscription_plans()

        assert plugin.subscription_manager is previous_manager
        assert closed == []
        assert plugin.subscription_allows_access()
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_store_move_keeps_enabled_plugin_enabled_with_new_plan_ids(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
    loop_in_thread: LoopInThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    old_plan_id = TEST_MONTHLY_PLAN_ID
    new_plan_id = "plan_moved_to_new_store"
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/manage",
        status=SubscriptionStatusResponse(plan_id=old_plan_id, status=SubscriptionStatusCode.ACTIVE),
    )
    plugin.set_enabled(True)
    assert plugin.enabled

    enabled_values: list[bool] = []
    plugin.signal_enabled_changed.connect(enabled_values.append)
    revocations: list[str] = []
    plugin.subscription_manager.signal_access_revoked.connect(lambda: revocations.append("revoked"))

    # The new store: the catalog maps the same product to a new plan id,
    # and the new plan answers ACTIVE for the buyer.
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_plans",
        lambda self: {
            TEST_DEMO_PRODUCT_ID: [
                PlanCatalogItem(
                    plan_id=new_plan_id,
                    duration="month",
                    name="Monthly",
                    price="10",
                    currency="USD",
                    recurringType="monthly",
                    status="active",
                )
            ]
        },
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: SubscriptionStatusResponse(
            plan_id=plan_id, status=SubscriptionStatusCode.ACTIVE
        ),
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_active_subscriptions",
        lambda self, buyer_email, product_plan_ids: [
            SubscriptionStatusResponse(plan_id=new_plan_id, status=SubscriptionStatusCode.ACTIVE)
        ],
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_management_url",
        lambda self, plan_id, buyer_email: "https://example.com/moved",
    )
    _run_subscription_tasks_synchronously(monkeypatch, (plugin.subscription_manager,))
    try:
        plugin._resolve_subscription_plans()

        manager = plugin.subscription_manager
        assert manager.plan_id == new_plan_id
        assert manager.subscriber_email == SUBSCRIBER_EMAIL
        assert manager.management_url == "https://example.com/moved"
        assert plugin.subscription_allows_access()
        assert plugin.enabled
        assert revocations == []
        assert False not in enabled_values
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_store_move_reenables_plugin_once_new_plan_is_active(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
    loop_in_thread: LoopInThread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    new_plan_id = "plan_moved_to_new_store"
    plugin = _make_demo_plugin(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        management_url="https://example.com/manage",
        status=SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=SubscriptionStatusCode.ACTIVE),
    )
    plugin.set_enabled(True)
    assert plugin.enabled

    # Before the move the new store has no subscription for the buyer yet: access is revoked.
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: SubscriptionStatusResponse(
            plan_id=plan_id, status=SubscriptionStatusCode.NOT_FOUND
        ),
    )
    _run_subscription_tasks_synchronously(monkeypatch, (plugin.subscription_manager,))
    plugin.subscription_manager.set_plan_id(new_plan_id)
    assert not plugin.subscription_allows_access()
    assert not plugin.enabled

    # The operator re-creates the subscription under the new plan: the new plan is listed as active.
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_active_subscriptions",
        lambda self, buyer_email, product_plan_ids: [
            SubscriptionStatusResponse(plan_id=new_plan_id, status=SubscriptionStatusCode.ACTIVE)
        ],
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_management_url",
        lambda self, plan_id, buyer_email: "https://example.com/moved",
    )
    requested_enable: list[bool] = []
    plugin.signal_request_enabled.connect(requested_enable.append)
    monkeypatch.setattr(
        SubscriptionManager,
        "get_to_be_signed",
        lambda self, multipath_descriptor: "wallet-hash",
    )
    _run_subscription_tasks_synchronously(monkeypatch, (plugin.subscription_manager,))
    try:
        plugin.subscription_manager.check_existing_subscription(
            multipath_descriptor=object(),  # type: ignore[arg-type]
            product_plan_ids=[new_plan_id],
        )

        assert plugin.subscription_manager.plan_id == new_plan_id
        assert plugin.subscription_allows_access()
        assert plugin.subscription_manager.management_url == "https://example.com/moved"
        assert requested_enable == [True]
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_plan_option_labels_show_price_and_period(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=None,
        additional_access_providers=None,
        subscription_managers={
            TEST_DEMO_PRODUCT_ID: SubscriptionManager(config=config, loop_in_thread=None),
        },
    )
    monthly = PlanCatalogItem.model_validate(
        {
            "plan_id": TEST_MONTHLY_PLAN_ID,
            "duration": "month",
            "name": "Monthly",
            "price": "6.99",
            "currency": "USD",
            "recurringType": "Monthly",
            "status": "Active",
        }
    )
    yearly = PlanCatalogItem.model_validate(
        {
            "plan_id": TEST_YEARLY_PLAN_ID,
            "duration": "year",
            "name": "Yearly",
            "price": "59.99",
            "currency": "USD",
            "recurringType": "Yearly",
            "status": "Active",
        }
    )

    try:
        assert plugin._format_plan_option(monthly) == "6.99 USD / month"
        assert plugin._format_plan_option(yearly) == "59.99 USD / year"
    finally:
        plugin.close()
        fx.close()


@pytest.mark.marker_qt_1
def test_single_plan_product_selector_shows_only_price_and_period(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    lookup = SubscriptionPriceLookup()
    yearly = PlanCatalogItem.model_validate(
        {
            "plan_id": TEST_YEARLY_PLAN_ID,
            "duration": "year",
            "name": "Schedule",
            "price": "1299",
            "currency": "USD",
            "recurringType": "Yearly",
            "status": "Active",
        }
    )
    lookup._set_catalog({TEST_DEMO_PRODUCT_ID: [yearly]})
    plugin = DemoPaidPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=None,
        additional_access_providers=None,
        subscription_price_lookup=lookup,
    )

    try:
        widget = PaidPluginWidget(plugin)
        assert _plan_texts(widget) == ["1299 USD / year"]
        widget.close()
    finally:
        plugin.close()
        lookup.close()
        fx.close()
