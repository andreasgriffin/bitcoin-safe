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

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Protocol, cast, runtime_checkable

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTracker
from bitcoin_safe_lib.gui.qt.util import question_dialog
from bitcoin_safe_lib.storage import BaseSaveableClass, SaveAllClass, filtered_for_init
from btcpay_tools.btcpay_subscription_nostr.core import PosInvoiceMetadata, derive_subscriber_email
from btcpay_tools.btcpay_subscription_nostr.service import (
    PurchaseSession,
    SubscriptionManagementClient,
    SubscriptionManagementPhase,
    SubscriptionManagementStatus,
    SubscriptionManagementStatusCode,
    SubscriptionPurchaseClient,
)
from btcpay_tools.config import BTCPayConfig, PlanDuration, SubscriptionProduct
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from bitcoin_safe.btcpay_config import BTCPAY_SUBSCRIPTION_CONFIG
from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import CONTACT_EMAIL
from bitcoin_safe.descriptors import hash_from_descriptor
from bitcoin_safe.gui.qt.util import Message, MessageType, open_website
from bitcoin_safe.i18n import translate
from bitcoin_safe.network_utils import ProxyInfo

logger = logging.getLogger(__name__)


@runtime_checkable
class HasSubscriptionSupport(Protocol):
    subscription_manager: SubscriptionManager


class NoSubscriptionKeyRequired:
    pass


@dataclass
class StoredSubscriptionStatus(SaveAllClass):
    VERSION = "0.1.0"
    known_classes = {
        **BaseSaveableClass.known_classes,
        SubscriptionManagementStatus.__name__: SubscriptionManagementStatus,
    }

    status: SubscriptionManagementStatus | None
    checked_at_ts: float | None
    last_status_error: str | None

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data["status"] = self._dump_status()
        return data

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None) -> StoredSubscriptionStatus:
        super()._from_dump(dct, class_kwargs=class_kwargs)
        dct["status"] = cls._load_status(dct.get("status"))
        return cls(**filtered_for_init(dct, cls))

    def _dump_status(self) -> dict[str, Any] | None:
        if self.status is None:
            return None
        return {
            "status": self.status.status.value,
            "phase": self.status.phase.value,
            "is_active": self.status.is_active,
            "is_suspended": self.status.is_suspended,
            "pending_invoice": self.status.pending_invoice,
            "payment_due": self.status.payment_due,
            "upgrade_required": self.status.upgrade_required,
            "auto_renew": self.status.auto_renew,
        }

    @staticmethod
    def _load_status(status_data: dict[str, Any] | None) -> SubscriptionManagementStatus | None:
        if status_data is None:
            return None
        return SubscriptionManagementStatus(
            status=SubscriptionManagementStatusCode(status_data["status"]),
            phase=SubscriptionManagementPhase(status_data["phase"]),
            is_active=status_data["is_active"],
            is_suspended=status_data["is_suspended"],
            pending_invoice=status_data["pending_invoice"],
            payment_due=status_data["payment_due"],
            upgrade_required=status_data["upgrade_required"],
            auto_renew=status_data["auto_renew"],
        )


class SubscriptionManager(QObject, BaseSaveableClass):
    """
    multipath_descriptor is not persisted and set_subscription_multipath_descriptor
    needs to be called after init.
    """

    VERSION = "0.2.2"
    known_classes = {
        **BaseSaveableClass.known_classes,
        StoredSubscriptionStatus.__name__: StoredSubscriptionStatus,
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
        btcpay_config: BTCPayConfig = BTCPAY_SUBSCRIPTION_CONFIG,
    ) -> dict[str, object | None]:
        return {
            "config": config,
            "loop_in_thread": loop_in_thread,
            "btcpay_config": btcpay_config,
        }

    def __init__(
        self,
        config: UserConfig,
        loop_in_thread: LoopInThread | None,
        subscription_product_key: str | None | NoSubscriptionKeyRequired,
        btcpay_config: BTCPayConfig = BTCPAY_SUBSCRIPTION_CONFIG,
        subscription_duration: PlanDuration | str | None = None,
        stored_subscription_status: StoredSubscriptionStatus | None = None,
        subscriber_email: str | None = None,
        management_url: str | None = None,
        parent: QWidget | None = None,
        additional_access_provider: Callable[[], bool] | None = None,
        ask_for_email: bool = False,
    ) -> None:
        super().__init__(parent=parent)
        self._parent = parent
        self.config = config
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None
        self.subscription_product_key = subscription_product_key
        self.btcpay_config = btcpay_config
        self._subscription_duration = (
            subscription_duration
            if isinstance(subscription_duration, PlanDuration) or subscription_duration is None
            else PlanDuration(subscription_duration)
        )
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

    def set_btcpay_config(self, btcpay_config: BTCPayConfig) -> None:
        self.btcpay_config = btcpay_config

    def set_subscription_target(
        self,
        subscription_product_key: str | None | NoSubscriptionKeyRequired,
        subscription_duration: PlanDuration | None,
    ) -> None:
        self.subscription_product_key = subscription_product_key
        self._subscription_duration = subscription_duration

    @property
    def activation_in_progress(self) -> bool:
        return self._activation_in_progress

    @property
    def subscription_product(self) -> SubscriptionProduct | None:
        if not self.subscription_product_key or isinstance(
            self.subscription_product_key, NoSubscriptionKeyRequired
        ):
            return None
        return self.btcpay_config.resolve_subscription(
            self.subscription_product_key,
            duration=self._subscription_duration,
        )

    @property
    def subscription_duration(self) -> PlanDuration | None:
        if self._subscription_duration is not None:
            return self._subscription_duration
        subscription_product = self.subscription_product
        if subscription_product is None:
            return None
        return subscription_product.duration

    @property
    def subscription_pos_base_url(self) -> str:
        if not self.subscription_product_key:
            return ""
        return self.btcpay_config.subscription_pos_base_url()

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

    def manage_subscription_text(self) -> str:
        return translate("subscription", "Manage Subscription")

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

    def subscription_status_text(self) -> str:
        if self._has_additional_access():
            return translate("subscription", "Business plan access is active.")
        if self._activation_in_progress:
            return translate("subscription", "Waiting for the free trial to be activated...")
        if not self.management_url:
            return translate("subscription", "No subscription has been activated yet.")

        parts = [translate("subscription", "Management URL saved.")]
        if self.stored_subscription_status.status:
            status = self.stored_subscription_status.status.status
            if status == SubscriptionManagementStatusCode.UPGRADE_REQUIRED:
                # TODO: handle this better
                status = SubscriptionManagementStatusCode.ACTIVE

            status_label = status.value.replace("_", " ")
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
        if not self.management_url or not self.stored_subscription_status.status:
            return False
        if self.stored_subscription_status.status.is_suspended:
            return False
        if self.stored_subscription_status.status.status in {
            SubscriptionManagementStatusCode.EXPIRED,
            SubscriptionManagementStatusCode.SESSION_EXPIRED,
        }:
            return False
        if self.stored_subscription_status.status.is_active is not None:
            return self.stored_subscription_status.status.is_active
        return self.stored_subscription_status.status.status != SubscriptionManagementStatusCode.UNKNOWN

    def is_trial_subscription_active(self) -> bool:
        return bool(
            self.management_url
            and self.stored_subscription_status.status
            and self.stored_subscription_status.status.status == SubscriptionManagementStatusCode.TRIAL
            and self.subscription_allows_access()
        )

    def dump(self) -> dict[str, Any]:
        data = super().dump()
        data.update(
            {
                "management_url": self.management_url,
                "subscriber_email": self.subscriber_email,
                "stored_subscription_status": self.stored_subscription_status,
                "subscription_product_key": NoSubscriptionKeyRequired.__name__
                if isinstance(self.subscription_product_key, NoSubscriptionKeyRequired)
                else self.subscription_product_key,
                "subscription_duration": (
                    self._subscription_duration.value if self._subscription_duration else None
                ),
                "ask_for_email": self.ask_for_email,
            }
        )
        return data

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None) -> SubscriptionManager:
        super()._from_dump(dct, class_kwargs=class_kwargs)
        if (
            subscription_product_key := dct.get("subscription_product_key")
        ) and subscription_product_key == NoSubscriptionKeyRequired.__name__:
            dct["subscription_product_key"] = NoSubscriptionKeyRequired()
        if subscription_duration := dct.get("subscription_duration"):
            dct["subscription_duration"] = PlanDuration(subscription_duration)
        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_dump_migration(cls, dct: dict[str, Any]) -> dict[str, Any]:
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
        if self.subscription_product is None:
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

        purchase_client = SubscriptionPurchaseClient(
            pos_base_url=self.subscription_pos_base_url,
            pos_item_id=self.subscription_product.trial_pos_id,
            metadata=PosInvoiceMetadata(
                buyer_email=subscriber_email,
                message_to_be_signed=to_be_signed,
            ),
            proxy_dict=self.proxy_dict(),
            loop_in_thread=self.loop_in_thread,
            npub_bitcoin_safe_pos=self.btcpay_config.npub_bitcoin_safe_pos,
        )

        async def do() -> PurchaseSession:
            return await purchase_client.start_and_wait()

        def on_success(session: PurchaseSession | None) -> None:
            if session is None:
                self._handle_trial_purchase_error(
                    translate("subscription", "Free-trial purchase did not return a session.")
                )
                return
            self._handle_trial_purchase_success(session)

        def on_error(error_info: ExcInfo | None) -> None:
            self._handle_trial_purchase_error(self._trial_purchase_error_text(error_info))

        self.loop_in_thread.run_task(
            do(),
            on_done=lambda result: None,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}_trial_purchase",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def _handle_trial_purchase_success(self, session: PurchaseSession) -> None:
        if not session.management_payload:
            self._handle_trial_purchase_error(
                translate("subscription", "Free-trial purchase did not return a management payload.")
            )
            return

        self.management_payload = session.management_payload
        self.management_url = session.management_payload.management_url
        self.signal_state_changed.emit()
        self._refresh_subscription_status(disable_if_inactive=True, notify_on_error=True)

    def _handle_trial_purchase_error(self, error_text: str) -> None:
        self.stored_subscription_status.last_status_error = error_text
        self._activation_in_progress = False
        self.signal_state_changed.emit()
        Message(error_text, parent=self._parent, type=MessageType.Warning)

    @classmethod
    def _trial_purchase_error_text(cls, error_info: ExcInfo | BaseException | None) -> str:
        error = cls._error_from_exc_info(error_info)
        if error and cls._is_timeout_error(error):
            return cls._trial_purchase_retry_error_text(
                translate("subscription", "The free trial activation timed out.")
            )

        if error:
            return str(error)

        return cls._trial_purchase_retry_error_text(
            translate("subscription", "The free trial activation failed.")
        )

    @staticmethod
    def _trial_purchase_retry_error_text(reason: str) -> str:
        return translate(
            "subscription",
            "{reason} Please retry later. If it still does not work, contact {email}.",
        ).format(reason=reason, email=CONTACT_EMAIL)

    @staticmethod
    def _error_from_exc_info(error_info: ExcInfo | BaseException | None) -> BaseException | None:
        if error_info is None:
            return None
        if isinstance(error_info, BaseException):
            return error_info
        return error_info[1]

    @staticmethod
    def _is_timeout_error(error: BaseException) -> bool:
        return (
            isinstance(error, (TimeoutError, asyncio.TimeoutError))
            or "timeout" in type(error).__name__.lower()
        )

    def _refresh_subscription_status(self, disable_if_inactive: bool, notify_on_error: bool) -> None:
        if self._has_additional_access() or not self.management_url:
            return

        management_url = self.management_url
        proxy_dict = self.proxy_dict()
        management_client = SubscriptionManagementClient(
            proxy_dict=proxy_dict,
            loop_in_thread=self.loop_in_thread,
        )

        async def do() -> SubscriptionManagementStatus:
            return await management_client.get_management_status(
                management_url,
                proxy_dict=proxy_dict,
            )

        def on_success(subscription_management_status: SubscriptionManagementStatus | None) -> None:
            if subscription_management_status is None:
                self._handle_subscription_refresh_error(
                    translate("subscription", "Subscription status refresh returned no result."),
                    notify_on_error=notify_on_error,
                )
                return
            self._apply_management_status(
                subscription_management_status, disable_if_inactive=disable_if_inactive
            )

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
        status: SubscriptionManagementStatus,
        disable_if_inactive: bool,
    ) -> SubscriptionManagementStatus | None:
        if status.status == SubscriptionManagementStatusCode.UNKNOWN and self.stored_subscription_status:
            self.stored_subscription_status.last_status_error = translate(
                "subscription", "Could not determine the current subscription status."
            )
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
    ) -> SubscriptionManagementStatus | None:
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

    def _proxy_info(self) -> ProxyInfo | None:
        proxy_url = self.config.network_config.proxy_url
        return ProxyInfo.parse(proxy_url) if proxy_url else None

    def _has_additional_access(self) -> bool:
        if self.additional_access_provider is None:
            return False
        return self.additional_access_provider()

    def _prompt_subscriber_email(self) -> str | None:
        return self.prompt_subscriber_email_dialog()
