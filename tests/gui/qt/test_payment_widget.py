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
import threading
from datetime import datetime
from unittest.mock import Mock

from btcpay_tools.btcpay_subscription_api.models import StoreInfoResponse
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QCloseEvent

from bitcoin_safe.config import BtcPayInvoiceDetails, UserConfig
from bitcoin_safe.constants import SUPPORT_EMAIL
from bitcoin_safe.fx import FX
from bitcoin_safe.gui.qt.btcpay_web_button import (
    BTCPayWebButton,
    CallbackServerState,
    DonationInvoiceWidget,
)
from bitcoin_safe.network_utils import AsyncHttpResponse


class _SignalHost(QObject):
    signal = pyqtSignal()


def _payment_button(qtbot, loop_in_thread) -> BTCPayWebButton:
    button = BTCPayWebButton(config=UserConfig(), loop_in_thread=loop_in_thread)
    qtbot.addWidget(button)
    return button


def test_invoice_open_failure_without_callback_server_shows_fallback_link(
    qtbot, loop_in_thread, monkeypatch
) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    messages: list[str] = []
    button.signal_update_status.connect(messages.append)

    monkeypatch.setattr(button, "_open_invoice_in_browser", lambda invoice_url: False)

    button._on_invoice_created(
        (
            200,
            BtcPayInvoiceDetails(
                id="invoice-id", url="https://example.com/invoice", bitcoin_address=None, amount=None
            ),
        )
    )

    assert messages[-1] == (
        "Could not open your browser automatically.<br>"
        'If the browser did not open, click <a href="https://example.com/invoice">here</a>.'
    )


def test_invoice_open_success_with_callback_server_updates_status(qtbot, loop_in_thread, monkeypatch) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    messages: list[str] = []
    button.signal_update_status.connect(messages.append)
    button._callback_server_state = Mock(invoice_url=None)

    monkeypatch.setattr(button, "_open_invoice_in_browser", lambda invoice_url: True)

    button._on_invoice_created(
        (
            200,
            BtcPayInvoiceDetails(
                id="invoice-id", url="https://example.com/invoice", bitcoin_address=None, amount=None
            ),
        )
    )

    assert button._callback_server_state.invoice_url == "https://example.com/invoice"
    assert messages[-1].startswith("Complete the payment in your browser.")
    assert f'<a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>' in messages[-1]
    assert '<a href="https://example.com/invoice">here</a>' in messages[-1]


def test_invoice_open_failure_keeps_callback_server_running(qtbot, loop_in_thread, monkeypatch) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    state = Mock(invoice_url=None)
    button._callback_server_state = state

    monkeypatch.setattr(button, "_open_invoice_in_browser", lambda invoice_url: False)

    button._on_invoice_created(
        (
            200,
            BtcPayInvoiceDetails(
                id="invoice-id", url="https://example.com/invoice", bitcoin_address=None, amount=None
            ),
        )
    )

    assert button._callback_server_state is state
    assert button._callback_server_state.invoice_url == "https://example.com/invoice"


def test_open_invoice_in_browser_uses_webopen(monkeypatch, qtbot, loop_in_thread) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    opened_urls: list[str] = []

    monkeypatch.setattr(button, "_has_url_handler", lambda url: True)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.btcpay_web_button.webopen",
        lambda invoice_url: opened_urls.append(invoice_url) or True,
    )

    assert button._open_invoice_in_browser("https://example.com/invoice") is True
    assert opened_urls == ["https://example.com/invoice"]


def test_create_invoice_request_normalizes_relative_location_header(
    monkeypatch, qtbot, loop_in_thread
) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.btcpay_web_button.SubscriptionApiClient.fetch_store",
        lambda self: StoreInfoResponse(base_url="https://payments.example.com", store_id="test-store"),
    )
    request_urls: list[str] = []
    request_data: list[dict[str, str]] = []

    async def fake_post_form_async(**kwargs):
        request_urls.append(kwargs["url"])
        request_data.append(kwargs["data"])
        return AsyncHttpResponse(
            status_code=302,
            headers={"Location": "/invoice?id=test"},
            body=b"",
        )

    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.btcpay_web_button.post_form_async",
        fake_post_form_async,
    )

    result = asyncio.run(
        button._create_invoice_request(
            invoice_details=BtcPayInvoiceDetails(
                id="invoice-id",
                amount=1234,
                url=None,
                bitcoin_address=None,
            )
        )
    )

    assert request_urls == ["https://payments.example.com/api/v1/invoices"]
    assert result[1].url == "https://payments.example.com/invoice?id=test"
    assert request_data[0]["storeId"] == "test-store"


def _invoice_request_for_store(
    monkeypatch,
    qtbot,
    loop_in_thread,
    base_url: str,
    location: str = "/invoice?id=test",
    proxy_url: str | None = None,
) -> tuple[list[str], list[object], tuple[int, BtcPayInvoiceDetails]]:
    config = UserConfig()
    config.network_config.proxy_url = proxy_url
    button = BTCPayWebButton(config=config, loop_in_thread=loop_in_thread)
    qtbot.addWidget(button)
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.btcpay_web_button.SubscriptionApiClient.fetch_store",
        lambda self: StoreInfoResponse(base_url=base_url, store_id="test-store"),
    )
    request_urls: list[str] = []
    request_proxies: list[object] = []

    async def fake_post_form_async(**kwargs):
        request_urls.append(kwargs["url"])
        request_proxies.append(kwargs["proxy_info"])
        return AsyncHttpResponse(status_code=302, headers={"Location": location}, body=b"")

    monkeypatch.setattr("bitcoin_safe.gui.qt.btcpay_web_button.post_form_async", fake_post_form_async)

    result = asyncio.run(
        button._create_invoice_request(
            invoice_details=BtcPayInvoiceDetails(id="invoice-id", amount=1234, url=None, bitcoin_address=None)
        )
    )
    return request_urls, request_proxies, result


def test_invoice_uses_default_btcpay_base_url(monkeypatch, qtbot, loop_in_thread) -> None:
    request_urls, _, _ = _invoice_request_for_store(
        monkeypatch, qtbot, loop_in_thread, base_url="https://pay.bitcoin-safe.org"
    )

    assert request_urls == ["https://pay.bitcoin-safe.org/api/v1/invoices"]


def test_invoice_uses_custom_btcpay_base_url(monkeypatch, qtbot, loop_in_thread) -> None:
    request_urls, _, _ = _invoice_request_for_store(
        monkeypatch, qtbot, loop_in_thread, base_url="https://custom-btcpay.example.com"
    )

    assert request_urls == ["https://custom-btcpay.example.com/api/v1/invoices"]


def test_invoice_endpoint_has_no_duplicate_slash_for_trailing_slash(
    monkeypatch, qtbot, loop_in_thread
) -> None:
    request_urls, _, _ = _invoice_request_for_store(
        monkeypatch, qtbot, loop_in_thread, base_url="https://custom-btcpay.example.com/"
    )

    assert request_urls == ["https://custom-btcpay.example.com/api/v1/invoices"]


def test_invoice_relative_redirect_resolves_against_configured_endpoint(
    monkeypatch, qtbot, loop_in_thread
) -> None:
    _, _, result = _invoice_request_for_store(
        monkeypatch,
        qtbot,
        loop_in_thread,
        base_url="https://custom-btcpay.example.com",
        location="/i/abc123",
    )

    assert result[1].url == "https://custom-btcpay.example.com/i/abc123"


def test_invoice_request_keeps_configured_proxy(monkeypatch, qtbot, loop_in_thread) -> None:
    _, request_proxies, _ = _invoice_request_for_store(
        monkeypatch,
        qtbot,
        loop_in_thread,
        base_url="https://pay.bitcoin-safe.org",
        proxy_url="socks5h://127.0.0.1:9050",
    )

    assert request_proxies[0] is not None
    assert request_proxies[0].host == "127.0.0.1"
    assert request_proxies[0].port == 9050


def test_duplicate_callback_is_ignored_after_state_is_consumed(qtbot, loop_in_thread, monkeypatch) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    completed: list[bool] = []
    stop_requests: list[str] = []
    button.signal_payment_completed.connect(completed.append)

    state = CallbackServerState(
        invoice_details=BtcPayInvoiceDetails(id="invoice-id", url=None, bitcoin_address=None, amount=None),
        server=Mock(),
        serve_future=Mock(),
        port=1,
        started_at=datetime.now(),
    )
    button._callback_server_state = state
    monkeypatch.setattr(
        button,
        "_request_stop_callback_server",
        lambda captured_state=None: stop_requests.append(captured_state.invoice_details.id),
    )

    invoice = BtcPayInvoiceDetails(id="invoice-id", url=None, bitcoin_address=None, amount=None)
    button._handle_callback_request(invoice)
    button._handle_callback_request(invoice)

    assert completed == [invoice]
    assert stop_requests == ["invoice-id"]
    assert button._callback_server_state is None


def test_donation_widget_clears_stale_amount_when_conversion_returns_zero(qtbot, loop_in_thread) -> None:
    config = UserConfig()
    config.rates = {"USD": {"value": 100_000, "unit": "$", "name": "US Dollar"}}
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    signal_host = _SignalHost()
    widget = DonationInvoiceWidget(
        amount=10,
        currency_iso="USD",
        fx=fx,
        loop_in_thread=loop_in_thread,
        signal_currency_changed=signal_host.signal,
        signal_language_switch=signal_host.signal,
    )
    qtbot.addWidget(widget)

    try:
        assert widget.payment_button.amount == 10_000

        widget.fiat_spin_box.setValue(0)
        widget._sync_amount_to_button()

        assert widget.payment_button.amount == 0
    finally:
        widget.close()
        fx.close()


def test_donation_widget_status_label_supports_external_links(qtbot, loop_in_thread) -> None:
    config = UserConfig()
    config.rates = {"USD": {"value": 100_000, "unit": "$", "name": "US Dollar"}}
    fx = FX(config=config, loop_in_thread=None, update_rates=False)
    signal_host = _SignalHost()
    widget = DonationInvoiceWidget(
        amount=10,
        currency_iso="USD",
        fx=fx,
        loop_in_thread=loop_in_thread,
        signal_currency_changed=signal_host.signal,
        signal_language_switch=signal_host.signal,
    )
    qtbot.addWidget(widget)

    try:
        assert widget.status_label.openExternalLinks() is True
    finally:
        widget.close()
        fx.close()


def test_late_invoice_error_after_close_is_ignored(monkeypatch, qtbot, loop_in_thread) -> None:
    button = _payment_button(qtbot=qtbot, loop_in_thread=loop_in_thread)
    messages: list[str] = []
    completions: list[BtcPayInvoiceDetails] = []
    button.signal_update_status.connect(messages.append)
    button.signal_payment_completed.connect(completions.append)
    button.set_amount(1234)

    started = threading.Event()
    cancelled = threading.Event()

    async def fake_post_form_async(**kwargs) -> AsyncHttpResponse:
        _ = kwargs
        try:
            started.set()
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("The invoice request should have been cancelled before completing")

    monkeypatch.setattr("bitcoin_safe.gui.qt.btcpay_web_button.post_form_async", fake_post_form_async)
    monkeypatch.setattr(button, "_start_callback_server", lambda invoice_details: None)

    button.create_invoice()
    qtbot.waitUntil(started.is_set)
    button.closeEvent(QCloseEvent())
    qtbot.waitUntil(cancelled.is_set)

    assert not any("Unable to reach the donation server" in message for message in messages)
    assert completions == []
