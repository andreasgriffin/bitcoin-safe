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

import json

import bdkpython as bdk
import pytest
from btcpay_tools.btcpay_subscription_nostr.service import (
    SubscriptionManagementPhase,
    SubscriptionManagementStatus,
    SubscriptionManagementStatusCode,
)
from btcpay_tools.config import PlanDuration

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import SUPPORT_EMAIL
from bitcoin_safe.plugin_framework.subscription_manager import (
    StoredSubscriptionStatus,
    SubscriptionManager,
)
from tests.btcpay_support import TEST_BTCPAY_SUBSCRIPTION_CONFIG


def test_subscription_support_roundtrip_persists_management_url_without_status(
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    support = SubscriptionManager(
        config=config,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
        management_url="https://example.com/manage",
    )

    restored = SubscriptionManager._from_dumps(
        support.dumps(),
        class_kwargs={
            "SubscriptionManager": SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=None,
                btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
            )
        },
    )

    assert restored.management_url == "https://example.com/manage"
    assert restored.stored_subscription_status.status is None
    assert restored.stored_subscription_status.checked_at_ts is None

    restored.close()
    support.close()


def test_subscription_support_roundtrip_persists_status_payload(
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    support = SubscriptionManager(
        config=config,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
        management_url="https://example.com/manage",
        stored_subscription_status=StoredSubscriptionStatus(
            status=SubscriptionManagementStatus(
                status=SubscriptionManagementStatusCode.TRIAL,
                phase=SubscriptionManagementPhase.TRIAL,
                is_active=True,
                is_suspended=False,
                subscriber_email="subscriber@example.com",
            ),
            checked_at_ts=123.0,
            last_status_error=None,
        ),
    )

    restored = SubscriptionManager._from_dumps(
        support.dumps(),
        class_kwargs={
            "SubscriptionManager": SubscriptionManager.cls_kwargs(
                config=config,
                loop_in_thread=None,
                btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
            )
        },
    )

    assert restored.management_url == "https://example.com/manage"
    assert restored.stored_subscription_status.status is not None
    assert restored.stored_subscription_status.status.status == SubscriptionManagementStatusCode.TRIAL
    assert restored.stored_subscription_status.status.subscriber_email == "subscriber@example.com"
    assert restored.stored_subscription_status.checked_at_ts == 123.0

    restored.close()
    support.close()


def test_subscription_support_from_dump_restores_config_subscription_fields(
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    product = TEST_BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    support = SubscriptionManager(
        config=config,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
    )

    dumped = json.loads(support.dumps())

    assert dumped["subscription_product_key"] == "demo-plugin"
    assert dumped["subscription_duration"] == "month"

    restored = SubscriptionManager.from_dump(
        dumped,
        class_kwargs={
            "config": config,
            "loop_in_thread": None,
            "btcpay_config": TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        },
    )

    assert restored.subscription_duration is PlanDuration.MONTH
    assert restored.subscription_product is not None
    assert restored.subscription_product.offering_id == product.offering_id
    assert restored.subscription_pos_base_url == TEST_BTCPAY_SUBSCRIPTION_CONFIG.subscription_pos_base_url()

    restored.close()
    support.close()


def test_trial_purchase_timeout_error_text_asks_to_retry_and_contact_support() -> None:
    error_text = SubscriptionManager._trial_purchase_error_text(TimeoutError("timed out"))

    assert "free trial activation timed out" in error_text
    assert "retry later" in error_text
    assert SUPPORT_EMAIL in error_text


def test_trial_purchase_error_text_hides_network_details() -> None:
    network_error = RuntimeError("HTTPSConnectionPool(host=secret): Max retries exceeded")

    error_text = SubscriptionManager._trial_purchase_error_text(network_error)

    assert "HTTPSConnectionPool" not in error_text
    assert "free trial activation failed" in error_text
    assert SUPPORT_EMAIL in error_text


@pytest.mark.parametrize(
    ("management_url", "is_valid"),
    [
        ("https://testnet.demo.btcpayserver.org/subscriber-portal/token", True),
        ("https://example.com/subscriptions/manage/token", False),
        ("http://testnet.demo.btcpayserver.org/subscriber-portal/token", False),
        ("ftp://example.com/manage", False),
        ("https:///manage", False),
        ("not a URL", False),
        ("http://[", False),
    ],
)
def test_management_url_validation(
    test_config_main_chain: UserConfig,
    management_url: str,
    is_valid: bool,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
    )

    assert support._is_valid_management_url(management_url) is is_valid

    support.close()


def test_subscription_status_hides_subscription_email(
    test_config_main_chain: UserConfig,
) -> None:
    subscriber_email = "descriptor-hash@subscriptions.bitcoin-safe.org"
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
        subscriber_email=subscriber_email,
    )

    assert subscriber_email not in support.subscription_status_text()

    support.close()


def test_trial_purchase_error_accepts_manual_management_url(
    test_config_main_chain: UserConfig,
) -> None:
    management_url = "https://testnet.demo.btcpayserver.org/subscriber-portal/token"

    class ManualUrlSubscriptionManager(SubscriptionManager):
        def __init__(self) -> None:
            super().__init__(
                config=test_config_main_chain,
                loop_in_thread=None,
                subscription_product_key="demo-plugin",
                btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
                subscription_duration=PlanDuration.MONTH,
                subscriber_email="descriptor-hash@subscriptions.bitcoin-safe.org",
            )
            self.refresh_requested = False
            self.candidate_management_url: str | None = None

        def prompt_management_url_dialog(self) -> str | None:
            return management_url

        def _refresh_subscription_status(
            self,
            disable_if_inactive: bool,
            notify_on_error: bool,
            candidate_management_url: str | None = None,
        ) -> None:
            self.refresh_requested = disable_if_inactive and notify_on_error
            self.candidate_management_url = candidate_management_url

    support = ManualUrlSubscriptionManager()

    support._handle_trial_purchase_error("Nostr timed out")

    assert support.management_url is None
    assert support.stored_subscription_status.last_status_error is None
    assert support.refresh_requested
    assert support.candidate_management_url == management_url

    support.close()


@pytest.mark.parametrize(
    ("management_email", "expected_error"),
    [
        ("descriptor-hash@subscriptions.bitcoin-safe.org", None),
        (
            "other-hash@subscriptions.bitcoin-safe.org",
            "belongs to a different subscription ID",
        ),
        (None, "does not expose a subscription ID"),
    ],
)
def test_management_status_must_match_subscription_email(
    test_config_main_chain: UserConfig,
    management_email: str | None,
    expected_error: str | None,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        subscription_product_key="demo-plugin",
        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration=PlanDuration.MONTH,
        subscriber_email="descriptor-hash@subscriptions.bitcoin-safe.org",
    )
    status = SubscriptionManagementStatus(
        status=SubscriptionManagementStatusCode.ACTIVE,
        phase=SubscriptionManagementPhase.NORMAL,
        is_active=True,
        is_suspended=False,
        subscriber_email=management_email,
    )

    error = support._management_status_identity_error(status)
    support.management_url = "https://testnet.demo.btcpayserver.org/subscriber-portal/token"
    support.stored_subscription_status.status = status

    if expected_error is None:
        assert error is None
        assert support.has_direct_subscription_access()
    else:
        assert error is not None
        assert expected_error in error
        assert not support.has_direct_subscription_access()

    support.close()


def test_error_from_exc_info_returns_original_exception() -> None:
    error = ValueError("boom")

    resolved_error = SubscriptionManager._error_from_exc_info((ValueError, error, None))

    assert resolved_error is error
