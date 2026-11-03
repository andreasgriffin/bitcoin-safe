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

import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from btcpay_tools.btcpay_subscription_api.models import PlanCatalogResponse
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.plugin_framework.subscription_api_client import (
    SubscriptionApiClient,
    flatten_plans,
    plan_id_for_product,
)
from bitcoin_safe.plugin_framework.subscription_manager import SubscriptionManager
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup
from tests.btcpay_support import TEST_BUSINESS_PLAN_ID, TEST_MONTHLY_PLAN_ID, TEST_YEARLY_PLAN_ID

CATALOG_RESPONSE = {
    "schema_version": 1,
    "plans": {
        "business-plan": [
            {
                "plan_id": TEST_BUSINESS_PLAN_ID,
                "duration": "year",
                "name": "Business Plan",
                "description": None,
                "price": "1599",
                "currency": "USD",
                "recurringType": "Yearly",
                "trialDays": 7,
                "gracePeriodDays": 7,
                "status": "Active",
                "features": [],
            }
        ],
        "schedule": [
            {
                "plan_id": "plan_E8A8xrESQqhG4UGXga",
                "duration": "year",
                "name": "Schedule",
                "description": None,
                "price": "1299",
                "currency": "USD",
                "recurringType": "Yearly",
                "trialDays": 30,
                "gracePeriodDays": 30,
                "status": "Active",
                "features": [],
            }
        ],
        "notifications": [
            {
                "plan_id": TEST_MONTHLY_PLAN_ID,
                "duration": "month",
                "name": "Monthly",
                "description": None,
                "price": "6.99",
                "currency": "USD",
                "recurringType": "Monthly",
                "trialDays": 7,
                "gracePeriodDays": 7,
                "status": "Active",
                "features": [],
            },
            {
                "plan_id": TEST_YEARLY_PLAN_ID,
                "duration": "year",
                "name": "Yearly",
                "description": None,
                "price": "59.99",
                "currency": "USD",
                "recurringType": "Yearly",
                "trialDays": 7,
                "gracePeriodDays": 7,
                "status": "Active",
                "features": [],
            },
        ],
    },
}


@pytest.fixture
def catalog() -> dict[str, list]:
    return PlanCatalogResponse.model_validate(CATALOG_RESPONSE).plans


def test_catalog_is_grouped_by_product(catalog: dict[str, list]) -> None:
    assert sorted(catalog) == ["business-plan", "notifications", "schedule"]
    assert len(flatten_plans(catalog)) == 4


def test_business_plan_id_is_resolved_by_product_key(catalog: dict[str, list]) -> None:
    assert plan_id_for_product(catalog, "business-plan") == TEST_BUSINESS_PLAN_ID


def test_plan_id_for_unknown_product_is_rejected(catalog: dict[str, list]) -> None:
    with pytest.raises(Exception, match="no plan"):
        plan_id_for_product(catalog, "missing-product")


def test_plan_id_for_product_with_several_plans_is_rejected(catalog: dict[str, list]) -> None:
    with pytest.raises(Exception, match="refusing to choose"):
        plan_id_for_product(catalog, "notifications")


def test_price_lookup_serves_prices_from_the_plan_catalog(
    qtbot: QtBot,
    qapp: QApplication,
    loop_in_thread: LoopInThread,
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_plans",
        lambda self: PlanCatalogResponse.model_validate(CATALOG_RESPONSE).plans,
    )
    lookup = SubscriptionPriceLookup()
    manager = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=loop_in_thread,
        plan_id=TEST_MONTHLY_PLAN_ID,
    )

    with qtbot.waitSignal(lookup.signal_prices_changed, timeout=5_000):
        lookup.ensure_prices(manager)

    monthly = lookup.catalog_item_for_plan_id(TEST_MONTHLY_PLAN_ID)
    assert monthly is not None
    assert (monthly.name, monthly.price, monthly.currency, monthly.recurringType) == (
        "Monthly",
        "6.99",
        "USD",
        "Monthly",
    )
    assert lookup.catalog_item_for_plan_id(TEST_BUSINESS_PLAN_ID) is not None
    assert lookup.catalog_item_for_plan_id("plan_unknown") is None

    lookup.close()
    manager.close()


def test_price_lookup_is_empty_until_fetched(
    qapp: QApplication,
    test_config_main_chain: UserConfig,
) -> None:
    lookup = SubscriptionPriceLookup()

    assert lookup.catalog_item_for_plan_id(TEST_MONTHLY_PLAN_ID) is None

    lookup.close()
