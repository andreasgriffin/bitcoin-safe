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
#

from __future__ import annotations

import json

import bdkpython as bdk
from btcpay_tools.btcpay_subscription_nostr.service import (
    SubscriptionManagementPhase,
    SubscriptionManagementStatus,
    SubscriptionManagementStatusCode,
)
from btcpay_tools.config import PlanDuration

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import CONTACT_EMAIL
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
    assert CONTACT_EMAIL in error_text


def test_error_from_exc_info_returns_original_exception() -> None:
    error = ValueError("boom")

    resolved_error = SubscriptionManager._error_from_exc_info((ValueError, error, None))

    assert resolved_error is error
