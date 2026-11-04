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
import json

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from btcpay_tools.btcpay_subscription_api.models import SubscriptionStatusCode, SubscriptionStatusResponse

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import SUPPORT_EMAIL
from bitcoin_safe.plugin_framework.subscription_api_client import SubscriptionApiClient, SubscriptionApiError
from bitcoin_safe.plugin_framework.subscription_manager import (
    StoredSubscriptionStatus,
    SubscriptionManager,
)
from tests.btcpay_support import TEST_MONTHLY_PLAN_ID, TEST_YEARLY_PLAN_ID

MANAGEMENT_URL = "https://example.com/manage"


def _status(code: SubscriptionStatusCode) -> SubscriptionStatusResponse:
    return SubscriptionStatusResponse(plan_id=TEST_MONTHLY_PLAN_ID, status=code)


def test_subscription_support_roundtrip_persists_management_url_without_status(
    test_config_main_chain: UserConfig,
) -> None:
    config = test_config_main_chain
    config.network = bdk.Network.BITCOIN
    support = SubscriptionManager(
        config=config,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        management_url=MANAGEMENT_URL,
    )

    restored = SubscriptionManager._from_dumps(
        support.dumps(),
        class_kwargs={
            "SubscriptionManager": SubscriptionManager.cls_kwargs(config=config, loop_in_thread=None)
        },
    )

    assert restored.plan_id == TEST_MONTHLY_PLAN_ID
    assert restored.management_url == MANAGEMENT_URL
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
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="subscriber@example.com",
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.TRIAL),
            checked_at_ts=123.0,
            last_status_error=None,
        ),
    )

    restored = SubscriptionManager._from_dumps(
        support.dumps(),
        class_kwargs={
            "SubscriptionManager": SubscriptionManager.cls_kwargs(config=config, loop_in_thread=None)
        },
    )

    assert restored.management_url == MANAGEMENT_URL
    assert restored.stored_subscription_status.status is not None
    assert restored.stored_subscription_status.status.status == SubscriptionStatusCode.TRIAL
    assert restored.stored_subscription_status.checked_at_ts == 123.0

    restored.close()
    support.close()


def test_subscription_support_dump_contains_plan_id(test_config_main_chain: UserConfig) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
    )

    dumped = json.loads(support.dumps())

    assert dumped["plan_id"] == TEST_MONTHLY_PLAN_ID
    assert "subscription_product_key" not in dumped
    assert "subscription_duration" not in dumped

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
        ("https://example.com/subscriptions/manage/token", True),
        ("http://testnet.demo.btcpayserver.org/subscriber-portal/token", True),
        ("ftp://example.com/manage", False),
        ("https:///manage", False),
        ("https://[", False),
        ("https://example.com:99999/manage", False),
        ("https://user:password@example.com/manage", False),
        ("not a URL", False),
        ("", False),
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
        plan_id=TEST_MONTHLY_PLAN_ID,
    )

    assert support._is_valid_management_url(management_url) is is_valid

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
                plan_id=TEST_MONTHLY_PLAN_ID,
                subscriber_email="descriptor-hash@v0.bitcoin-safe.org",
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

    support._handle_trial_purchase_error("Subscription service unreachable")

    assert support.management_url is None
    assert support.stored_subscription_status.last_status_error is None
    assert support.refresh_requested
    assert support.candidate_management_url == management_url

    support.close()


@pytest.mark.parametrize(
    ("code", "expected_access"),
    [
        (SubscriptionStatusCode.ACTIVE, True),
        (SubscriptionStatusCode.TRIAL, True),
        (SubscriptionStatusCode.GRACE, True),
        (SubscriptionStatusCode.EXPIRED, False),
        (SubscriptionStatusCode.SUSPENDED, False),
        (SubscriptionStatusCode.NOT_FOUND, False),
        (SubscriptionStatusCode.UNKNOWN, False),
    ],
)
def test_access_follows_status_code(
    test_config_main_chain: UserConfig,
    code: SubscriptionStatusCode,
    expected_access: bool,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="descriptor-hash@v0.bitcoin-safe.org",
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(code), checked_at_ts=1.0, last_status_error=None
        ),
    )

    assert support.subscription_allows_access() is expected_access

    support.close()


def test_access_requires_subscriber_email(test_config_main_chain: UserConfig) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )

    assert not support.subscription_allows_access()

    support.close()


def test_error_from_exc_info_returns_original_exception() -> None:
    error = ValueError("boom")

    resolved_error = SubscriptionManager._error_from_exc_info((ValueError, error, None))

    assert resolved_error is error


def _active(plan_id: str, code: SubscriptionStatusCode) -> SubscriptionStatusResponse:
    return SubscriptionStatusResponse(plan_id=plan_id, status=code)


def test_check_existing_subscription_adopts_active_subscription(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bitcoin_safe.plugin_framework.subscription_api_client import derive_subscriber_email

    support = SubscriptionManager(
        config=test_config_main_chain, loop_in_thread=None, plan_id=TEST_MONTHLY_PLAN_ID
    )
    emails: list[str] = []

    def fake_fetch_active(self, buyer_email: str) -> list[SubscriptionStatusResponse]:
        emails.append(buyer_email)
        return [_active(TEST_MONTHLY_PLAN_ID, SubscriptionStatusCode.ACTIVE)]

    monkeypatch.setattr(SubscriptionApiClient, "fetch_active_subscriptions", fake_fetch_active)
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_management_url",
        lambda self, plan_id, buyer_email: "https://pay.bitcoin-safe.org/subscriber-portal/ps_fetched",
    )
    monkeypatch.setattr(
        SubscriptionManager, "get_to_be_signed", lambda self, multipath_descriptor: "wallet-hash"
    )
    _run_tasks_synchronously(monkeypatch)

    support.check_existing_subscription(multipath_descriptor=object())  # type: ignore[arg-type]

    expected_email = derive_subscriber_email("wallet-hash")
    assert emails == [expected_email]
    assert support.subscriber_email == expected_email
    assert support.stored_subscription_status.status is not None
    assert support.stored_subscription_status.status.status == SubscriptionStatusCode.ACTIVE
    assert support.management_url == "https://pay.bitcoin-safe.org/subscriber-portal/ps_fetched"

    support.close()


def test_check_existing_subscription_follows_upgrade_from_monthly_to_yearly(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The buyer had Monthly and upgraded to Yearly, so the service lists only Yearly as active. A
    single active lookup adopts Yearly and drops Monthly, with the management URL of Yearly.
    """
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="wallet-hash@v0.bitcoin-safe.org",
        management_url="https://pay.bitcoin-safe.org/subscriber-portal/ps_monthly",
        stored_subscription_status=StoredSubscriptionStatus(
            status=_active(TEST_MONTHLY_PLAN_ID, SubscriptionStatusCode.ACTIVE),
            checked_at_ts=1.0,
            last_status_error=None,
        ),
    )
    active_calls: list[str] = []
    management_calls: list[str] = []

    def fake_fetch_active(self, buyer_email: str) -> list[SubscriptionStatusResponse]:
        active_calls.append(buyer_email)
        return [_active(TEST_YEARLY_PLAN_ID, SubscriptionStatusCode.ACTIVE)]

    def fake_fetch_management_url(self, plan_id: str, buyer_email: str) -> str:
        management_calls.append(plan_id)
        return f"https://pay.bitcoin-safe.org/subscriber-portal/{plan_id}"

    monkeypatch.setattr(SubscriptionApiClient, "fetch_active_subscriptions", fake_fetch_active)
    monkeypatch.setattr(SubscriptionApiClient, "fetch_management_url", fake_fetch_management_url)
    monkeypatch.setattr(
        SubscriptionManager, "get_to_be_signed", lambda self, multipath_descriptor: "wallet-hash"
    )
    _run_tasks_synchronously(monkeypatch)

    support.check_existing_subscription(multipath_descriptor=object())  # type: ignore[arg-type]

    assert len(active_calls) == 1
    assert management_calls == [TEST_YEARLY_PLAN_ID]
    assert support.plan_id == TEST_YEARLY_PLAN_ID
    assert support.management_url == f"https://pay.bitcoin-safe.org/subscriber-portal/{TEST_YEARLY_PLAN_ID}"
    assert support.subscription_allows_access()

    support.close()


def test_check_existing_subscription_reports_missing_subscription(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain, loop_in_thread=None, plan_id=TEST_MONTHLY_PLAN_ID
    )
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_active_subscriptions",
        lambda self, buyer_email: [],
    )
    monkeypatch.setattr(
        SubscriptionManager, "get_to_be_signed", lambda self, multipath_descriptor: "wallet-hash"
    )
    _run_tasks_synchronously(monkeypatch)

    support.check_existing_subscription(multipath_descriptor=object())  # type: ignore[arg-type]

    assert support.subscriber_email is None
    assert not support.subscription_allows_access()
    assert "No subscription was found" in (support.stored_subscription_status.last_status_error or "")

    support.close()


def test_check_existing_subscription_revokes_stale_cached_access(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="old-wallet@v0.bitcoin-safe.org",
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )
    revoked: list[bool] = []
    support.signal_access_revoked.connect(lambda: revoked.append(True))
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_active_subscriptions",
        lambda self, buyer_email: [],
    )
    monkeypatch.setattr(
        SubscriptionManager, "get_to_be_signed", lambda self, multipath_descriptor: "new-wallet"
    )
    _run_tasks_synchronously(monkeypatch)

    support.check_existing_subscription(multipath_descriptor=object())  # type: ignore[arg-type]

    assert not support.subscription_allows_access()
    assert support.management_url is None
    assert support.subscriber_email is None
    assert revoked == [True]
    assert "No subscription was found" in support.subscription_status_text()

    support.close()


def _recorded_signals(support: SubscriptionManager) -> list[str]:
    events: list[str] = []
    support.signal_state_changed.connect(lambda: events.append("state_changed"))
    support.signal_access_activated.connect(lambda: events.append("access_activated"))
    support.signal_access_revoked.connect(lambda: events.append("access_revoked"))
    return events


def test_unknown_status_during_activation_resets_activation(
    test_config_main_chain: UserConfig,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="subscriber@example.com",
    )
    support._activation_in_progress = True

    support._apply_management_status(_status(SubscriptionStatusCode.UNKNOWN), disable_if_inactive=True)

    assert not support.activation_in_progress
    assert support.stored_subscription_status.last_status_error is not None
    assert "Could not determine" in support.stored_subscription_status.last_status_error

    support.close()


def test_unknown_status_preserves_previous_status_and_access(
    test_config_main_chain: UserConfig,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="subscriber@example.com",
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )
    previous_status = support.stored_subscription_status.status

    support._apply_management_status(_status(SubscriptionStatusCode.UNKNOWN), disable_if_inactive=True)

    assert support.stored_subscription_status.status is previous_status
    assert support.stored_subscription_status.checked_at_ts == 1.0
    assert support.subscription_allows_access()

    support.close()


def test_unknown_status_emits_only_state_changed(
    test_config_main_chain: UserConfig,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="subscriber@example.com",
        management_url=MANAGEMENT_URL,
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )
    events = _recorded_signals(support)

    support._apply_management_status(_status(SubscriptionStatusCode.UNKNOWN), disable_if_inactive=True)

    assert events == ["state_changed"]

    support.close()


def _run_tasks_synchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    def run_task_sync(
        coro, on_success=None, on_done=None, on_error=None, cancel=None, key=None, multiple_strategy=None
    ):
        try:
            result = asyncio.run(coro)
        except Exception as exc:
            if on_error:
                on_error((type(exc), exc, exc.__traceback__))
        else:
            if on_success:
                on_success(result)
        return None

    monkeypatch.setattr(LoopInThread, "run_task", lambda self, *a, **k: run_task_sync(*a, **k))


def test_set_plan_id_moves_existing_subscription_keeping_email_and_status(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="buyer@v0.bitcoin-safe.org",
        management_url="https://old.example.com/manage",
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )
    calls: list[tuple[str, str]] = []

    def fake_fetch_status(self, plan_id: str, buyer_email: str) -> SubscriptionStatusResponse:
        calls.append((plan_id, buyer_email))
        return SubscriptionStatusResponse(plan_id=plan_id, status=SubscriptionStatusCode.ACTIVE)

    monkeypatch.setattr(SubscriptionApiClient, "fetch_status", fake_fetch_status)
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_management_url",
        lambda self, plan_id, buyer_email: "https://new.example.com/manage",
    )
    _run_tasks_synchronously(monkeypatch)

    support.set_plan_id(TEST_YEARLY_PLAN_ID)

    assert calls == [(TEST_YEARLY_PLAN_ID, "buyer@v0.bitcoin-safe.org")]
    assert support.plan_id == TEST_YEARLY_PLAN_ID
    assert support.subscriber_email == "buyer@v0.bitcoin-safe.org"
    assert support.management_url == "https://new.example.com/manage"
    assert support.subscription_allows_access()

    support.close()


def test_set_plan_id_offline_keeps_previous_plan_and_access(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    support = SubscriptionManager(
        config=test_config_main_chain,
        loop_in_thread=None,
        plan_id=TEST_MONTHLY_PLAN_ID,
        subscriber_email="buyer@v0.bitcoin-safe.org",
        management_url="https://old.example.com/manage",
        stored_subscription_status=StoredSubscriptionStatus(
            status=_status(SubscriptionStatusCode.ACTIVE), checked_at_ts=1.0, last_status_error=None
        ),
    )

    def offline(self, plan_id: str, buyer_email: str) -> SubscriptionStatusResponse:
        raise SubscriptionApiError("Subscription service unreachable")

    monkeypatch.setattr(SubscriptionApiClient, "fetch_status", offline)
    _run_tasks_synchronously(monkeypatch)

    support.set_plan_id(TEST_YEARLY_PLAN_ID)

    assert support.plan_id == TEST_MONTHLY_PLAN_ID
    assert support.management_url == "https://old.example.com/manage"
    assert support.subscription_allows_access()
    assert support.stored_subscription_status.last_status_error == "Subscription service unreachable"

    support.close()


def test_set_plan_id_without_subscription_only_assigns_plan(
    test_config_main_chain: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        SubscriptionApiClient,
        "fetch_status",
        lambda self, plan_id, buyer_email: calls.append(plan_id),
    )
    support = SubscriptionManager(config=test_config_main_chain, loop_in_thread=None)

    support.set_plan_id(TEST_MONTHLY_PLAN_ID)

    assert support.plan_id == TEST_MONTHLY_PLAN_ID
    assert calls == []
    support.close()
