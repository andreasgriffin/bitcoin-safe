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
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from typing import Any, cast
from urllib.parse import urlsplit

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.storage import BaseSaveableClass, SaveAllClass, filtered_for_init
from btcpay_tools.btcpay_subscription_api.models import SubscriptionStatusCode, SubscriptionStatusResponse
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import SUPPORT_EMAIL
from bitcoin_safe.descriptors import hash_from_descriptor
from bitcoin_safe.gui.qt.util import Message, MessageType, open_website
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.plugin_framework.subscription_api_client import (
    LIVE_SUBSCRIPTION_CODES,
    SubscriptionApiClient,
    SubscriptionApiError,
    derive_subscriber_email,
)

logger = logging.getLogger(__name__)


@dataclass
class StoredSubscriptionStatus(SaveAllClass):
    VERSION = "0.2.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
    }

    status: SubscriptionStatusResponse | None
    checked_at_ts: float | None
    last_status_error: str | None

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data["status"] = self.status.model_dump(mode="json") if self.status else None
        return data

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None) -> StoredSubscriptionStatus:
        super()._from_dump(dct, class_kwargs=class_kwargs)
        raw_status = dct.get("status")
        dct["status"] = SubscriptionStatusResponse.model_validate(raw_status) if raw_status else None
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        # Pre-0.2.0 statuses came from the nostr/management page format and cannot be
        # converted. Drop them; the next refresh recreates the status.
        if not isinstance(dct.get("status"), dict) or "plan_id" not in dct["status"]:
            dct["status"] = None
            dct["checked_at_ts"] = None
        return super().from_dump_migration(dct)


class SubscriptionManager(QObject, BaseSaveableClass):
    """
    Tracks one subscription plan for one buyer email.

    The subscription service has no authentication, so a successful status response is only
    used together with the email that created the subscription, never as proof of ownership.
    """

    VERSION = "0.3.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        StoredSubscriptionStatus.__name__: StoredSubscriptionStatus,
        SubscriptionStatusResponse.__name__: SubscriptionStatusResponse,
        UserConfig.__name__: UserConfig,
    }

    signal_state_changed = cast(SignalProtocol[[]], pyqtSignal())
    signal_access_activated = cast(SignalProtocol[[]], pyqtSignal())
    signal_access_revoked = cast(SignalProtocol[[]], pyqtSignal())

    @classmethod
    def cls_kwargs(
        cls,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
    ) -> dict[str, object | None]:
        return {
            "config": config,
            "loop_in_thread": loop_in_thread,
        }

    def __init__(
        self,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
        plan_id: str | None = None,
        subscriber_email: str | None = None,
        management_url: str | None = None,
        stored_subscription_status: StoredSubscriptionStatus | None = None,
        parent: QWidget | None = None,
        additional_access_provider: Callable[[], bool] | None = None,
        ask_for_email: bool = False,
    ) -> None:
        super().__init__(parent=parent)
        self._parent = parent
        self.config = config
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None
        self.plan_id = plan_id
        self.subscriber_email = subscriber_email
        self.management_url = management_url
        self.stored_subscription_status = stored_subscription_status or StoredSubscriptionStatus(
            status=None, checked_at_ts=None, last_status_error=None
        )
        self.additional_access_provider = additional_access_provider
        self.ask_for_email = ask_for_email
        self.signal_tracker = SignalTracker()
        self._activation_in_progress = False

    def set_additional_access_provider(self, additional_access_provider: Callable[[], bool] | None) -> None:
        self.additional_access_provider = additional_access_provider

    def set_plan_id(self, plan_id: str) -> None:
        """
        Switch to the plan that now carries this product. An existing subscription follows the
        switch: its email and status are kept until the new plan answers. Without a subscription
        there is nothing to move.
        """
        old_plan_id = self.plan_id
        if plan_id == old_plan_id:
            return
        if not old_plan_id or not self.subscriber_email or not self.management_url:
            self.plan_id = plan_id
            return
        self._move_subscription_to_plan(plan_id=plan_id, buyer_email=self.subscriber_email)

    def _move_subscription_to_plan(self, plan_id: str, buyer_email: str) -> None:
        """
        Ask the new plan for the buyer's status and management URL. The plan_id is only committed
        on success, so a failed move is retried on the next start.
        """
        client = SubscriptionApiClient(self.proxy_dict())

        async def do() -> tuple[SubscriptionStatusResponse, str | None]:
            status = await asyncio.to_thread(client.fetch_status, plan_id, buyer_email)
            if status.status not in LIVE_SUBSCRIPTION_CODES:
                return status, None
            management_url = await asyncio.to_thread(client.fetch_management_url, plan_id, buyer_email)
            return status, management_url

        def on_success(result: tuple[SubscriptionStatusResponse, str | None] | None) -> None:
            if result is None:
                return
            status, management_url = result
            if status.status == SubscriptionStatusCode.UNKNOWN:
                self._handle_subscription_refresh_error(
                    translate("subscription", "Could not determine the current subscription status."),
                    notify_on_error=False,
                )
                return
            # The management URL belongs to the old store, so it is replaced or cleared, never kept.
            self.plan_id = plan_id
            self.management_url = management_url
            self._apply_management_status(status, disable_if_inactive=True)

        def on_error(error_info: ExcInfo | None) -> None:
            error = self._error_from_exc_info(error_info)
            self._handle_subscription_refresh_error(
                str(error) if error is not None else translate("subscription", "Subscription move failed."),
                notify_on_error=False,
            )

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}_plan_move",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    @property
    def activation_in_progress(self) -> bool:
        return self._activation_in_progress

    def allow_subscription_enable_request(self, multipath_descriptor: bdk.Descriptor) -> bool:
        if self.subscription_allows_access():
            return True
        if self._activation_in_progress:
            return False
        if self.management_url:
            return self._prompt_extend_subscription()
        self._start_free_trial_purchase(multipath_descriptor=multipath_descriptor)
        return False

    def supports_manage_subscription(self) -> bool:
        return bool(self.management_url)

    def trigger_manage_subscription(self) -> None:
        if self.management_url:
            open_website(self.management_url)

    def supports_refresh_subscription_status(self) -> bool:
        return bool(self.management_url)

    def refresh_subscription_status_button_text(self) -> str:
        return translate("subscription", "Refresh Subscription status")

    def trigger_refresh_subscription_status(self, disable_if_inactive: bool = True) -> None:
        self.refresh_subscription_status(
            disable_if_inactive=disable_if_inactive,
            notify_on_error=True,
        )

    def refresh_subscription_status(self, disable_if_inactive: bool, notify_on_error: bool) -> None:
        self._refresh_subscription_status(
            disable_if_inactive=disable_if_inactive,
            notify_on_error=notify_on_error,
        )

    def check_existing_subscription(self, multipath_descriptor: bdk.Descriptor) -> None:
        """
        Look up the wallet's live subscription on any plan of the product in one request. The
        response lists only live plans, so after an upgrade the new plan is adopted and the replaced
        plan is dropped. Its management URL, status and plan_id are taken from that live entry.
        """
        to_be_signed = self.get_to_be_signed(multipath_descriptor=multipath_descriptor)
        if not to_be_signed:
            return

        buyer_email = derive_subscriber_email(to_be_signed)
        client = SubscriptionApiClient(self.proxy_dict())

        async def do() -> tuple[SubscriptionStatusResponse | None, str | None]:
            active = await asyncio.to_thread(client.fetch_active_subscriptions, buyer_email)
            if not active:
                return None, None
            live = active[0]
            try:
                management_url = await asyncio.to_thread(
                    client.fetch_management_url, live.plan_id, buyer_email
                )
            except SubscriptionApiError:
                logger.warning("Management URL could not be fetched for an existing subscription")
                return live, None
            return live, management_url

        def on_success(result: tuple[SubscriptionStatusResponse | None, str | None] | None) -> None:
            if result is None:
                return
            status, management_url = result
            if status is None:
                had_direct_access = self.has_direct_subscription_access()
                self.subscriber_email = None
                self.management_url = None
                self._activation_in_progress = False
                self.stored_subscription_status = StoredSubscriptionStatus(
                    status=None,
                    checked_at_ts=datetime.now().timestamp(),
                    last_status_error=translate("subscription", "No subscription was found for this wallet."),
                )
                self.signal_state_changed.emit()
                if had_direct_access and not self.subscription_allows_access():
                    self.signal_access_revoked.emit()
                return
            # The management URL of another plan is never kept.
            if management_url or status.plan_id != self.plan_id:
                self.management_url = management_url
            self.plan_id = status.plan_id
            self.subscriber_email = buyer_email
            self._apply_management_status(status, disable_if_inactive=False)

        def on_error(error_info: ExcInfo | None) -> None:
            error = self._error_from_exc_info(error_info)
            self._handle_subscription_refresh_error(
                str(error) if error is not None else translate("subscription", "Subscription check failed."),
                notify_on_error=True,
            )

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}_check_subscription",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def subscription_status_text(self) -> str:
        if self._has_additional_access():
            return translate("subscription", "Business plan access is active.")
        if self._activation_in_progress:
            return translate("subscription", "Waiting for the free trial to be activated...")

        parts = []
        if not self.management_url:
            parts.append(translate("subscription", "No subscription has been activated yet."))
        elif self.stored_subscription_status.status:
            status_label = self.stored_subscription_status.status.status.value.replace("_", " ")
            parts.append(
                translate("subscription", "Current status: {status}.").format(status=status_label.title())
            )
            if self.stored_subscription_status and self.stored_subscription_status.checked_at_ts is not None:
                checked_at = datetime.fromtimestamp(self.stored_subscription_status.checked_at_ts).strftime(
                    "%Y-%m-%d %H:%M"
                )
                parts.append(
                    translate("subscription", "Last checked: {checked_at}.").format(checked_at=checked_at)
                )
        if self.stored_subscription_status.last_status_error:
            parts.append(
                translate("subscription", "Last refresh error: {error}.").format(
                    error=self.stored_subscription_status.last_status_error
                )
            )
        return " ".join(parts)

    def subscription_allows_access(self) -> bool:
        if self._has_additional_access():
            return True
        return self.has_direct_subscription_access()

    def has_direct_subscription_access(self) -> bool:
        status = self.stored_subscription_status.status
        if not self.management_url or status is None:
            return False
        if self.subscriber_email is None:
            return False
        return status.status in {
            SubscriptionStatusCode.ACTIVE,
            SubscriptionStatusCode.TRIAL,
            SubscriptionStatusCode.GRACE,
        }

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data.update(
            {
                "plan_id": self.plan_id,
                "management_url": self.management_url,
                "subscriber_email": self.subscriber_email,
                "stored_subscription_status": self.stored_subscription_status,
                "ask_for_email": self.ask_for_email,
            }
        )
        return data

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None) -> SubscriptionManager:
        super()._from_dump(dct, class_kwargs=class_kwargs)
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
        # Pre-0.3.0 managers were keyed by plan key and carried no plan_id. The stored
        # status belongs to the old format and is dropped by StoredSubscriptionStatus.
        dct.pop("subscription_product_key", None)
        dct.pop("subscription_duration", None)
        return super().from_dump_migration(dct)

    def clear_subscription_state(self) -> None:
        had_access = self.subscription_allows_access()
        self.subscriber_email = None
        self.management_url = None
        self.stored_subscription_status = StoredSubscriptionStatus(
            status=None, checked_at_ts=None, last_status_error=None
        )
        self._activation_in_progress = False

        if had_access:
            self.signal_access_revoked.emit()
            return

        self.signal_state_changed.emit()

    def hash_from_descriptor(self, multipath_descriptor: bdk.Descriptor) -> str | None:
        return hash_from_descriptor(
            multipath_descriptor=multipath_descriptor,
            network=self.config.network,
            additional_string="SubscriptionPurchaseClient",
        )

    def get_to_be_signed(self, multipath_descriptor: bdk.Descriptor) -> str | None:
        return self.hash_from_descriptor(multipath_descriptor=multipath_descriptor)

    def proxy_dict(self) -> dict[str, str] | None:
        proxy_info = self._proxy_info()
        return proxy_info.get_requests_proxy_dict() if proxy_info else None

    def prompt_subscriber_email_dialog(self) -> str | None:
        parent = self._parent
        dialog = QDialog(parent)
        dialog.setWindowTitle(translate("subscription", "Subscription reminders"))
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        label = QLabel(
            translate("subscription", "Email address for subscription reminders and renewal notices:"),
            dialog,
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        email_input = QLineEdit(dialog)
        email_input.setText(self.subscriber_email or "")
        email_input.setPlaceholderText(translate("subscription", "name@example.com"))
        layout.addWidget(email_input)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        ok_button.setText(translate("subscription", "Continue"))
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel_button is not None
        cancel_button.setText(translate("subscription", "Cancel"))
        layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        while dialog.exec():
            email = email_input.text().strip()
            if self._is_valid_subscriber_email(email):
                return email
            Message(
                translate("subscription", "Please enter a valid email address."),
                parent=dialog,
                type=MessageType.Warning,
            )
            email_input.setFocus()
            email_input.selectAll()
        return None

    def prompt_management_url_dialog(self) -> str | None:
        if not self.subscriber_email:
            return None

        dialog = QDialog(self._parent)
        dialog.setWindowTitle(translate("subscription", "Complete subscription setup"))
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setMaximumWidth(700)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        title_label = QLabel(
            translate(
                "subscription",
                "The subscription management URL could not be fetched automatically.",
            ),
            dialog,
        )
        title_font = title_label.font()
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        help_label = QLabel(
            translate(
                "subscription",
                'Please contact <a href="mailto:{email}">{email}</a> to get the management URL, '
                "then paste it in the field below.",
            ).format(email=SUPPORT_EMAIL),
            dialog,
        )
        help_label.setTextFormat(Qt.TextFormat.RichText)
        help_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        help_label.setOpenExternalLinks(True)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        layout.addSpacing(4)

        subscription_id_title = QLabel(translate("subscription", "Subscription ID"), dialog)
        subscription_id_font = subscription_id_title.font()
        subscription_id_font.setBold(True)
        subscription_id_title.setFont(subscription_id_font)
        layout.addWidget(subscription_id_title)

        subscription_id_label = QLabel(self.subscriber_email, dialog)
        subscription_id_label.setTextInteractionFlags(
            subscription_id_label.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        subscription_id_label.setWordWrap(True)
        layout.addWidget(subscription_id_label)

        layout.addSpacing(4)

        management_url_label = QLabel(translate("subscription", "Management URL"), dialog)
        management_url_font = management_url_label.font()
        management_url_font.setBold(True)
        management_url_label.setFont(management_url_font)
        layout.addWidget(management_url_label)

        management_url_input = QLineEdit(dialog)
        management_url_input.setPlaceholderText(translate("subscription", "Paste management URL"))
        management_url_input.setClearButtonEnabled(True)
        layout.addWidget(management_url_input)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        ok_button.setText(translate("subscription", "Use management URL"))
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        assert cancel_button is not None
        cancel_button.setText(translate("subscription", "Close"))
        layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        while dialog.exec():
            management_url = management_url_input.text().strip()
            if self._is_valid_management_url(management_url):
                return management_url
            Message(
                translate("subscription", "Please enter a valid HTTP(S) management URL."),
                parent=dialog,
                type=MessageType.Warning,
            )
            management_url_input.setFocus()
            management_url_input.selectAll()
        return None

    def close(self) -> None:
        self.signal_tracker.disconnect_all()
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()

    def _prompt_extend_subscription(self) -> bool:
        if not self.management_url:
            return False

        response = question_dialog(
            text=translate(
                "subscription",
                "This plugin is currently inactive. Extend the subscription before enabling it again.",
            ),
            title=translate("subscription", "Subscription required"),
            true_button=translate("subscription", "Open subscription"),
            false_button=translate("subscription", "Cancel"),
        )
        if response:
            open_website(self.management_url)
        return False

    def _start_free_trial_purchase(self, multipath_descriptor: bdk.Descriptor) -> None:
        if not self.plan_id:
            return

        to_be_signed = self.get_to_be_signed(multipath_descriptor=multipath_descriptor)
        if not to_be_signed:
            self._handle_trial_purchase_error(
                translate("subscription", "Free-trial purchase requires a wallet descriptor.")
            )
            return

        subscriber_email = (
            self._prompt_subscriber_email() if self.ask_for_email else derive_subscriber_email(to_be_signed)
        )
        if not subscriber_email:
            return

        self.subscriber_email = subscriber_email
        self._activation_in_progress = True
        self.signal_state_changed.emit()

        plan_id = self.plan_id
        client = SubscriptionApiClient(self.proxy_dict())

        async def do() -> str:
            return await asyncio.to_thread(client.fetch_management_url, plan_id, subscriber_email)

        def on_success(management_url: str | None) -> None:
            if not management_url:
                self._handle_trial_purchase_error(
                    translate("subscription", "Free-trial purchase did not return a management URL.")
                )
                return
            self._refresh_subscription_status(
                disable_if_inactive=True,
                notify_on_error=True,
                candidate_management_url=management_url,
            )

        def on_error(error_info: ExcInfo | None) -> None:
            if error_info:
                logger.warning("Free trial activation failed", exc_info=error_info)
            self._handle_trial_purchase_error(self._trial_purchase_error_text(error_info))

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}_trial_purchase",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def _handle_trial_purchase_error(self, error_text: str) -> None:
        self.stored_subscription_status.last_status_error = error_text
        self._activation_in_progress = False
        self.signal_state_changed.emit()
        if not self.subscriber_email:
            Message(error_text, parent=self._parent, type=MessageType.Warning)
            return

        management_url = self.prompt_management_url_dialog()
        if not management_url:
            return

        self.stored_subscription_status.last_status_error = None
        self.signal_state_changed.emit()
        self._refresh_subscription_status(
            disable_if_inactive=True,
            notify_on_error=True,
            candidate_management_url=management_url,
        )

    @classmethod
    def _trial_purchase_error_text(cls, error_info: ExcInfo | BaseException | None) -> str:
        error = cls._error_from_exc_info(error_info)
        if error and cls._is_timeout_error(error):
            return cls._trial_purchase_retry_error_text(
                translate("subscription", "The free trial activation timed out.")
            )

        return cls._trial_purchase_retry_error_text(
            translate("subscription", "The free trial activation failed.")
        )

    @staticmethod
    def _trial_purchase_retry_error_text(reason: str) -> str:
        return translate(
            "subscription",
            "{reason} Please retry later. If it still does not work, contact {email}.",
        ).format(reason=reason, email=SUPPORT_EMAIL)

    @staticmethod
    def _error_from_exc_info(error_info: ExcInfo | BaseException | None) -> BaseException | None:
        if error_info is None:
            return None
        if isinstance(error_info, BaseException):
            return error_info
        return error_info[1]

    @staticmethod
    def _is_timeout_error(error: BaseException) -> bool:
        return isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()

    def _refresh_subscription_status(
        self,
        disable_if_inactive: bool,
        notify_on_error: bool,
        candidate_management_url: str | None = None,
    ) -> None:
        if self._has_additional_access():
            return
        if not self.plan_id or not self.subscriber_email:
            return

        management_url = candidate_management_url or self.management_url
        if not management_url:
            return

        plan_id = self.plan_id
        buyer_email = self.subscriber_email
        client = SubscriptionApiClient(self.proxy_dict())

        async def do() -> SubscriptionStatusResponse:
            return await asyncio.to_thread(client.fetch_status, plan_id, buyer_email)

        def on_success(status: SubscriptionStatusResponse | None) -> None:
            if status is None:
                self._handle_subscription_refresh_error(
                    translate("subscription", "Subscription status refresh returned no result."),
                    notify_on_error=notify_on_error,
                )
                return
            if candidate_management_url:
                self.management_url = candidate_management_url
                self.signal_state_changed.emit()
            self._apply_management_status(status, disable_if_inactive=disable_if_inactive)

        def on_error(error_info: ExcInfo | None) -> None:
            error = self._error_from_exc_info(error_info)
            error_text = (
                str(error)
                if error is not None
                else translate("subscription", "Subscription status refresh failed.")
            )
            self._handle_subscription_refresh_error(error_text, notify_on_error=notify_on_error)

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}_subscription_status",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def _apply_management_status(
        self,
        status: SubscriptionStatusResponse,
        disable_if_inactive: bool,
    ) -> SubscriptionStatusResponse | None:
        if status.status == SubscriptionStatusCode.UNKNOWN:
            self.stored_subscription_status.last_status_error = translate(
                "subscription", "Could not determine the current subscription status."
            )
            self._activation_in_progress = False
            self.signal_state_changed.emit()
            return self.stored_subscription_status.status
        self.stored_subscription_status = StoredSubscriptionStatus(
            status=status,
            checked_at_ts=datetime.now().timestamp(),
            last_status_error=None,
        )
        self._activation_in_progress = False
        self.signal_state_changed.emit()

        if self.subscription_allows_access():
            self.signal_access_activated.emit()
            return self.stored_subscription_status.status

        if disable_if_inactive and not self.subscription_allows_access():
            self.signal_access_revoked.emit()

        return self.stored_subscription_status.status

    def _handle_subscription_refresh_error(
        self,
        error_text: str,
        notify_on_error: bool,
    ) -> SubscriptionStatusResponse | None:
        self.stored_subscription_status.last_status_error = error_text
        self._activation_in_progress = False
        self.signal_state_changed.emit()
        if notify_on_error:
            Message(error_text, parent=self._parent, type=MessageType.Warning)
        return self.stored_subscription_status.status

    @staticmethod
    def _is_valid_subscriber_email(email: str) -> bool:
        _, parsed_email = parseaddr(email)
        if parsed_email != email:
            return False
        local_part, _, domain = email.rpartition("@")
        return bool(local_part and domain and "." in domain and " " not in email)

    @staticmethod
    def _is_valid_management_url(management_url: str) -> bool:
        if any(character.isspace() for character in management_url):
            return False
        try:
            parsed_url = urlsplit(management_url)
            port = parsed_url.port
            return (
                parsed_url.scheme == "https"
                and parsed_url.hostname is not None
                and parsed_url.username is None
                and parsed_url.password is None
                and (port is None or 1 <= port <= 65535)
            )
        except ValueError:
            return False

    def _proxy_info(self) -> ProxyInfo | None:
        proxy_url = self.config.network_config.proxy_url
        return ProxyInfo.parse(proxy_url) if proxy_url else None

    def _has_additional_access(self) -> bool:
        if self.additional_access_provider is None:
            return False
        return self.additional_access_provider()

    def _prompt_subscriber_email(self) -> str | None:
        return self.prompt_subscriber_email_dialog()
