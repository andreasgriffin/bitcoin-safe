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
import platform
import shutil
import socket
import webbrowser
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from typing import Any, cast
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

import requests
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import (
    QSize,
    Qt,
    QTimer,
    QUrl,
    pyqtBoundSignal,
    pyqtSignal,
)
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.config import BtcPayInvoiceDetails, UserConfig
from bitcoin_safe.constants import CONTACT_EMAIL
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.logging_handlers import mail_contact
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.util import SATOSHIS_PER_BTC, OptExcInfo
from bitcoin_safe.util_os import webopen

from ...fx import FX
from .ui_tx.spinbox import FiatSpinBox

logger = logging.getLogger(__name__)

DONATION_STORE_ID = "7agECo6zfJRp4Thi8vnBCjCoopb2yrnstaA5FophRfJe"
DONATION_INVOICE_ENDPOINT = "https://pay.bitcoin-safe.org/api/v1/invoices"
INVOICE_TIMEOUT = timedelta(minutes=15)


@dataclass
class CallbackServerState:
    invoice_details: BtcPayInvoiceDetails
    server: HTTPServer
    serve_future: Future[Any]
    port: int
    started_at: datetime
    invoice_url: str | None = None


class BTCPayWebButton(QPushButton):
    signal_payment_completed = cast(SignalProtocol[[BtcPayInvoiceDetails]], pyqtSignal(BtcPayInvoiceDetails))
    signal_update_status = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        config: UserConfig,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.amount: int | None = None
        self.loop_in_thread = loop_in_thread
        self._callback_server_state: CallbackServerState | None = None
        self._callback_timeout_timer: QTimer | None = None
        self.future_invoice: Future[Any] | None = None
        self.invoice_id: str = str(uuid4())
        self._checkout_desc: str | None = None

        self.signal_update_status.emit(self.tr("Choose an amount and create a donation invoice."))
        self.updateUi()

    # ---------- public action ----------

    def set_amount(self, amount: int) -> None:
        self.amount = amount

    def set_invoice_id(self, order_id: str) -> None:
        self.invoice_id = order_id.strip() if order_id else str(uuid4())

    def set_checkout_desc(self, checkout_desc: str | None) -> None:
        self._checkout_desc = checkout_desc.strip() if checkout_desc else None

    def create_invoice(self) -> None:
        # cancel old creation
        self.cancel_invoice_task()
        self._stop_callback_server()

        if not self.amount:
            self.signal_update_status.emit(self.tr("Please choose an amount."))
            return

        invoice_details = BtcPayInvoiceDetails(
            id=self.invoice_id, amount=self.amount, url=None, bitcoin_address=None
        )

        redirect_url_override = self._start_callback_server(invoice_details=invoice_details)
        if redirect_url_override:
            self.signal_update_status.emit(
                self.tr(
                    "Requesting invoice... A browser will open and Bitcoin Safe will listen for the callback locally."
                )
            )
        else:
            self.signal_update_status.emit(
                self.tr(
                    "Could not start the local callback server. Opening the invoice in your browser without automatic confirmation."
                )
            )
            self.signal_update_status.emit(self.tr("Requesting invoice..."))

        self.setEnabled(False)

        self.future_invoice = self.loop_in_thread.run_task(
            self._create_invoice_request(
                redirect_url_override=redirect_url_override,
                invoice_details=invoice_details,
                checkout_desc=self._checkout_desc,
            ),
            on_success=self._on_invoice_created,
            on_error=partial(self._on_invoice_error, invoice_details),
            key="donation_invoice",
        )

    # ---------- async / network ----------

    async def _create_invoice_request(
        self,
        invoice_details: BtcPayInvoiceDetails,
        redirect_url_override: str | None = None,
        checkout_desc: str | None = None,
    ) -> tuple[int, BtcPayInvoiceDetails]:
        proxies = (
            ProxyInfo.parse(self.config.network_config.proxy_url).get_requests_proxy_dict()
            if self.config.network_config.proxy_url
            else None
        )
        if not invoice_details.amount:
            raise ValueError("Invoice must have an amount")

        redirect_url = redirect_url_override or f"https://bitcoin-safe.org/redirecturl{uuid4()}"
        request_data: dict[str, str] = {
            "storeId": DONATION_STORE_ID,
            "currency": "BTC",
            "price": f"{invoice_details.amount / SATOSHIS_PER_BTC:.8f}",
            "browserRedirect": redirect_url,
        }
        if invoice_details.id:
            request_data["orderId"] = invoice_details.id
        if checkout_desc:
            request_data["checkoutDesc"] = checkout_desc

        response = requests.post(
            DONATION_INVOICE_ENDPOINT,
            data=request_data,
            allow_redirects=False,
            timeout=20 if proxies else 10,
            proxies=proxies,
        )
        status_code, invoice_url = response.status_code, response.headers.get("Location")

        invoice_details.url = urljoin(DONATION_INVOICE_ENDPOINT, invoice_url) if invoice_url else None

        return status_code, invoice_details

    # ---------- callbacks ----------

    def _on_invoice_created(self, result: tuple[int, BtcPayInvoiceDetails]) -> None:
        status_code, invoice_details = result
        self.setEnabled(True)

        if not invoice_details.url:
            self.signal_update_status.emit(self.tr("Could not create invoice. Please try again."))
            self.signal_payment_completed.emit(invoice_details)
            self._stop_callback_server()
            return

        if status_code >= 400:
            self._stop_callback_server()
            self.signal_update_status.emit(
                self.tr("Invoice service returned an error ({code}).").format(code=status_code)
            )
            return

        if self._callback_server_state:
            self._callback_server_state.invoice_url = invoice_details.url

        callback_available = self._callback_server_state is not None
        if not self._open_invoice_in_browser(invoice_details.url):
            self._show_browser_open_failure()
            return

        if callback_available:
            self.signal_update_status.emit(
                self.tr(
                    "Complete the payment in your browser.\n"
                    "If there is an issue, please dont hesitate to contact us at: {email}"
                ).format(email=CONTACT_EMAIL)
            )
        else:
            self.signal_update_status.emit(
                self.tr(
                    "Invoice ready. Complete the payment in your browser. Automatic confirmation may not be available."
                )
            )

    def _on_invoice_error(self, invoice_details: BtcPayInvoiceDetails, exc_info: OptExcInfo) -> None:
        exc_info_for_logger: tuple[type[BaseException], BaseException, TracebackType | None] | None = None
        if exc_info and exc_info[0] and exc_info[1]:
            exc_info_for_logger = cast(
                tuple[type[BaseException], BaseException, "TracebackType | None"], exc_info
            )

        logger.error("Failed to create donation invoice", exc_info=exc_info_for_logger)
        self.setEnabled(True)
        self.signal_update_status.emit(
            self.tr("Unable to reach the donation server. Please try again later.")
        )
        invoice_details.paid = False
        self.signal_payment_completed.emit(invoice_details)
        self._stop_callback_server()

    def cancel_invoice_task(self):
        # cancel pending async task if supported
        if self.future_invoice is not None and self.future_invoice.running():
            try:
                self.future_invoice.cancel()
            except Exception:
                pass
            self.future_invoice = None
        self._stop_callback_server()

    def _start_callback_timeout_timer(self) -> None:
        if self._callback_timeout_timer is None:
            self._callback_timeout_timer = QTimer(self)
            self._callback_timeout_timer.setSingleShot(True)
            self._callback_timeout_timer.timeout.connect(self._on_callback_timeout)
        self._callback_timeout_timer.start(int(INVOICE_TIMEOUT.total_seconds() * 1000))

    def _on_callback_timeout(self) -> None:
        if not self._callback_server_state:
            return
        invoice_url = self._callback_server_state.invoice_url
        self._stop_callback_server()
        if invoice_url:
            self.signal_update_status.emit(
                self.tr(
                    "No browser callback was received before the invoice timed out. Please retry the donation."
                )
            )
        else:
            self.signal_update_status.emit(
                self.tr("No browser callback was received before the invoice timed out. Please try again.")
            )

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.cancel_invoice_task()
        self._stop_callback_server()

        super().closeEvent(a0)

    def updateUi(self):
        self.setText(self.tr("Create invoice"))

    # ---------- external browser callback helpers ----------

    def _build_callback_handler(self, invoice_details: BtcPayInvoiceDetails):
        parent = self

        class DonationCallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/donation/callback":
                    self.send_error(404)
                    return

                query = parse_qs(parsed.query)
                invoice_query = query.get("invoice", [""])[0]
                if invoice_query != invoice_details.id:
                    self.send_error(400, "Unknown invoice")
                    return

                parent._handle_callback_request(invoice_details)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<!doctype html><html><body><h3>Thanks!</h3><p>You can return to Bitcoin Safe.</p></body></html>"
                )
                parent._request_stop_callback_server()

            def log_message(self, format: str, *args: Any) -> None:
                logger.debug("Donation callback server: " + format % args)

        return DonationCallbackHandler

    def _start_callback_server(self, invoice_details: BtcPayInvoiceDetails) -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
        except OSError:
            logger.exception("Failed to bind a local port for the callback listener")
            return None

        handler = self._build_callback_handler(invoice_details)
        try:
            server = HTTPServer(("127.0.0.1", port), handler)
        except OSError:
            logger.exception("Failed to start the callback HTTP server on port %s", port)
            return None

        serve_future = self.loop_in_thread.run_background(asyncio.to_thread(server.serve_forever))

        self._callback_server_state = CallbackServerState(
            invoice_details=invoice_details,
            server=server,
            serve_future=serve_future,
            port=port,
            started_at=datetime.now(),
        )
        logger.info(f"started  callback_server  {invoice_details.id=}, {port=}")
        self._start_callback_timeout_timer()
        return f"http://127.0.0.1:{port}/donation/callback?invoice={invoice_details.id}"

    def _request_stop_callback_server(self, state: CallbackServerState | None = None) -> None:
        self._stop_callback_server(state)

    def _stop_callback_server(self, state: CallbackServerState | None = None) -> None:
        state = self._consume_callback_server_state(state)
        if not state:
            return

        self.loop_in_thread.run_background(self._shutdown_callback_server(state))

    def _consume_callback_server_state(
        self, state: CallbackServerState | None = None
    ) -> CallbackServerState | None:
        if self._callback_timeout_timer is not None:
            self._callback_timeout_timer.stop()

        if state is None:
            state = self._callback_server_state
            self._callback_server_state = None
        elif self._callback_server_state is state:
            self._callback_server_state = None

        return state

    async def _shutdown_callback_server(self, state: CallbackServerState) -> None:
        await asyncio.to_thread(self._shutdown_callback_server_blocking, state)

    def _shutdown_callback_server_blocking(self, state: CallbackServerState) -> None:
        try:
            state.server.shutdown()
        except Exception:
            logger.exception("Failed to shutdown callback server cleanly")
        try:
            state.server.server_close()
        except Exception:
            logger.exception("Failed to close callback server socket cleanly")
        if not state.serve_future.done():
            try:
                state.serve_future.result(timeout=2)
            except Exception:
                logger.exception("Failed while waiting for callback server thread to stop")

    def _handle_callback_request(self, invoice_details: BtcPayInvoiceDetails) -> None:
        state = self._callback_server_state
        if not state or state.invoice_details.id != invoice_details.id:
            return
        if datetime.now() - state.started_at > INVOICE_TIMEOUT:
            self.signal_update_status.emit(
                self.tr("A browser callback arrived after the invoice expired. Please try again.")
            )
            return
        self._callback_server_state = None
        self._request_stop_callback_server(state)
        self.signal_update_status.emit(self.tr("Payment confirmed via browser callback. Thank you!"))

        invoice_details.paid = True
        self.signal_payment_completed.emit(invoice_details)

    def _show_browser_open_failure(self) -> None:
        self._stop_callback_server()
        self.signal_update_status.emit(
            self.tr("Could not open your browser automatically. Please try again.")
        )

    def _has_url_handler(self, url: QUrl) -> bool:
        if not url.isValid():
            return False

        scheme = url.scheme().lower()
        if scheme not in {"http", "https"}:
            return False

        system = platform.system()
        if system == "Windows":
            return self._has_windows_url_handler(scheme) or self._has_stdlib_browser_handler()
        if system == "Darwin":
            return bool(shutil.which("open")) or self._has_stdlib_browser_handler()
        if system == "Linux":
            return any(shutil.which(helper) for helper in ("xdg-open", "gio", "gvfs-open")) or (
                self._has_stdlib_browser_handler()
            )

        return self._has_stdlib_browser_handler()

    def _has_stdlib_browser_handler(self) -> bool:
        try:
            webbrowser.get()
        except webbrowser.Error:
            return False
        return True

    def _has_windows_url_handler(self, scheme: str) -> bool:
        try:
            import winreg
        except ImportError:
            return False

        winreg_module = cast(Any, winreg)
        key_candidates: list[tuple[Any, str]] = []
        try:
            with winreg_module.OpenKey(
                winreg_module.HKEY_CURRENT_USER,
                rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice",
            ) as key:
                prog_id, _ = winreg_module.QueryValueEx(key, "ProgId")
                if prog_id:
                    key_candidates.append((winreg_module.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command"))
        except OSError:
            pass

        key_candidates.append((winreg_module.HKEY_CLASSES_ROOT, rf"{scheme}\shell\open\command"))

        for root_key, key_path in key_candidates:
            try:
                with winreg_module.OpenKey(root_key, key_path) as key:
                    command, _ = winreg_module.QueryValueEx(key, "")
                    if isinstance(command, str) and command.strip():
                        return True
            except OSError:
                continue

        return False

    def _open_invoice_in_browser(self, invoice_url: str) -> bool:
        url = QUrl(invoice_url)
        if not url.isValid():
            logger.warning("Donation invoice URL is invalid: %s", invoice_url)
            return False

        if not self._has_url_handler(url):
            logger.warning("No browser handler detected for donation invoice URL: %s", invoice_url)

        opened = webopen(invoice_url)
        if not opened:
            logger.warning("Failed to open donation invoice URL in browser: %s", invoice_url)
        return bool(opened)


class DonationInvoiceWidget(QWidget):
    payment_completed = cast(SignalProtocol[[BtcPayInvoiceDetails]], pyqtSignal(BtcPayInvoiceDetails))

    def __init__(
        self,
        amount: float,
        currency_iso: str,
        fx: FX,
        loop_in_thread: LoopInThread,
        signal_currency_changed: SignalProtocol[[]] | pyqtBoundSignal,
        signal_language_switch: SignalProtocol[[]] | pyqtBoundSignal,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.fx = fx

        self.donate_row = QHBoxLayout()
        self.fiat_label = QLabel(self)
        self.fiat_unit = QLabel(self)
        self.fiat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.fiat_spin_box = FiatSpinBox(
            fx=fx,
            signal_currency_changed=signal_currency_changed,
            signal_language_switch=signal_language_switch,
        )
        self.message_label = QLabel(self)
        self.message_input = QLineEdit(self)
        self.message_input.textChanged.connect(self._sync_message_to_button)

        self.status_label = QLabel(self)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.payment_button = BTCPayWebButton(
            config=fx.config,
            loop_in_thread=loop_in_thread,
            parent=self,
        )
        self.payment_button.clicked.connect(self.payment_button.create_invoice)
        self.payment_button.signal_payment_completed.connect(self.payment_completed.emit)
        self.payment_button.signal_update_status.connect(self._update_status)

        self.donate_row.addStretch()
        self.donate_row.addWidget(self.fiat_label)
        self.donate_row.addWidget(self.fiat_spin_box)
        self.donate_row.addWidget(self.fiat_unit)
        self.donate_row.addWidget(self.payment_button)
        self.donate_row.addStretch()

        self.message_row = QHBoxLayout()
        self.message_row.addStretch()
        self.message_row.addWidget(self.message_label)
        self.message_row.addWidget(self.message_input)
        self.message_row.addStretch()

        self.fiat_spin_box.setValue(amount)
        self.fiat_spin_box.setCurrencyCode(currency_iso)
        self._sync_amount_to_button()
        self._sync_message_to_button()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(self.donate_row)
        layout.addLayout(self.message_row)
        layout.addWidget(self.status_label)

        self._update_status("")
        self.updateUi()

        self.fiat_spin_box.valueChanged.connect(self._sync_amount_to_button)
        signal_currency_changed.connect(self._sync_amount_to_button)

    def _update_status(self, message: str) -> None:
        logger.info(f"{message}")
        self.status_label.setText(str(message))

    def _sync_amount_to_button(self, *args) -> None:
        amount = self.fx.fiat_to_btc(self.fiat_spin_box.value(), self.fx.get_currency_iso())
        self.payment_button.set_amount(amount if amount is not None else 0)

    def _sync_message_to_button(self, *args) -> None:
        self.payment_button.set_checkout_desc(self.message_input.text())

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.payment_button.close()
        super().closeEvent(a0)

    def updateUi(self):
        currency_symbol = self.fx.get_currency_symbol()
        self.fiat_unit.setText(currency_symbol)
        self.fiat_label.setText(self.tr("Value"))
        self.message_label.setText(self.tr("Message (optional)"))
        self.message_input.setPlaceholderText(self.tr("Thanks for Bitcoin Safe!"))
        self.payment_button.updateUi()


class DonateDialog(QWidget):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(
        self,
        fx: FX,
        loop_in_thread: LoopInThread,
        signal_currency_changed: SignalProtocol[[]] | pyqtBoundSignal,
        signal_language_switch: SignalProtocol[[]] | pyqtBoundSignal,
        parent: QWidget | None = None,
        on_about_to_close: SignalProtocol[[QWidget]] | None = None,
    ):
        super().__init__(parent)

        self._on_about_to_close = on_about_to_close

        self.setWindowTitle(self.tr("Support Bitcoin Safe"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self.setMinimumWidth(420)
        self.setMinimumHeight(620)

        layout = QVBoxLayout(self)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setPixmap(svg_tools.get_QIcon("logo.svg").pixmap(QSize(96, 96), self.devicePixelRatioF()))
        layout.addWidget(logo_label)

        title_label = QLabel(self.tr("Help Bitcoin Safe grow as Free and Open Source Software."))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-weight: 600; font-size: 14pt;")
        layout.addWidget(title_label)

        description = QLabel(
            self.tr(
                "Bitcoin Safe is community funded. Your support keeps development independent, "
                "lets us ship new features, and improves security reviews. Larger supporters "
                "can be featured on our <a href='https://bitcoin-safe.org/en/donate/'>supporters page</a>."
            )
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setOpenExternalLinks(True)
        layout.addWidget(description)

        contact_label = QLabel(
            self.tr(
                "Want to discuss a larger contribution or partnership? Use the contact button "
                "below to reach us."
            )
        )
        contact_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        contact_label.setWordWrap(True)
        layout.addWidget(contact_label)

        currency_iso = fx.get_currency_iso()

        self.donation_widget = DonationInvoiceWidget(
            amount=fx.btc_to_fiat(fx.fiat_to_btc(10, "USD") or 10_000, currency=currency_iso) or 10,
            currency_iso=currency_iso,
            fx=fx,
            loop_in_thread=loop_in_thread,
            signal_currency_changed=signal_currency_changed,
            signal_language_switch=signal_language_switch,
            parent=self,
        )
        self.donation_widget.payment_completed.connect(self._on_payment_complete)
        layout.addWidget(self.donation_widget)

        self.contact_button = QPushButton(self.tr("Email us"))
        self.contact_button.clicked.connect(mail_contact)
        layout.addWidget(self.contact_button, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_payment_complete(self, invoice_details: BtcPayInvoiceDetails) -> None:
        if not invoice_details.paid:
            return
        message = self.tr("Donation successful. Thank you so much for supporting Bitcoin Safe!")
        QMessageBox.information(self, self.tr("Donation"), message)

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.donation_widget.close()
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)
