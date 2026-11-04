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

import string
from typing import Any

import requests
from btcpay_tools.btcpay_subscription_api.models import (
    PlanCatalogItem,
    PlanCatalogResponse,
    StoreInfoResponse,
    SubscriptionStatusResponse,
)

SUBSCRIPTION_API_BASE_URL = "https://subscription.bitcoin-safe.org"
REQUEST_TIMEOUT_SECONDS = 20


class SubscriptionApiError(Exception):
    pass


def derive_subscriber_email(message_to_be_signed: str) -> str:
    """Deterministic buyer email for a wallet. Must stay identical to the one used for existing subscribers."""
    allowed = set(string.ascii_lowercase + string.digits + "-")
    local = "".join(ch for ch in message_to_be_signed.lower() if ch in allowed)
    return f"{local}@v0.bitcoin-safe.org"


class SubscriptionApiClient:
    """Thin wrapper around the subscription service endpoints used by the app."""

    def __init__(self, proxy_dict: dict[str, str] | None, base_url: str = SUBSCRIPTION_API_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._proxy_dict = proxy_dict

    def fetch_plans(self) -> dict[str, list[PlanCatalogItem]]:
        """Plans grouped by subscription product id, e.g. {"business-plan": [...]}."""
        data = self._request("GET", "/api/subscription-plans")
        return PlanCatalogResponse.model_validate(data).plans

    def fetch_store(self) -> StoreInfoResponse:
        """The BTCPay store that the service and the pay endpoints use: its base_url and store_id."""
        data = self._request("GET", "/api/store")
        return StoreInfoResponse.model_validate(data)

    def fetch_status(self, plan_id: str, buyer_email: str) -> SubscriptionStatusResponse:
        data = self._request(
            "POST",
            "/api/subscriptions/status",
            {"plan_id": plan_id, "buyerEmail": buyer_email},
        )
        return SubscriptionStatusResponse.model_validate(data)

    def fetch_management_url(self, plan_id: str, buyer_email: str) -> str:
        data = self._request(
            "POST",
            "/api/subscriptions/management-url",
            {"plan_id": plan_id, "buyerEmail": buyer_email},
        )
        management_url = data.get("management_url")
        if not isinstance(management_url, str) or not management_url:
            raise SubscriptionApiError("The subscription service returned no management URL.")
        return management_url

    def _request(self, method: str, path: str, payload: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{self._base_url}{path}",
                json=payload,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
                proxies=self._proxy_dict,
            )
        except requests.RequestException as exc:
            raise SubscriptionApiError(f"Subscription service unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise SubscriptionApiError(f"Subscription service returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise SubscriptionApiError("Subscription service returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise SubscriptionApiError("Subscription service returned an unexpected payload.")
        return data


def flatten_plans(plans: dict[str, list[PlanCatalogItem]]) -> list[PlanCatalogItem]:
    return [plan for product_plans in plans.values() for plan in product_plans]


def plan_id_for_product(
    plans: dict[str, list[PlanCatalogItem]],
    product_id: str,
    preferred_plan_id: str | None,
) -> str:
    """The plan_id of a product: the preferred plan while it is offered, otherwise the first plan."""
    offered_plan_ids = [plan.plan_id for plan in plans.get(product_id, [])]
    if not offered_plan_ids:
        raise SubscriptionApiError(f"The subscription service offers no plan for '{product_id}'.")
    if preferred_plan_id is not None and preferred_plan_id in offered_plan_ids:
        return preferred_plan_id
    return offered_plan_ids[0]
