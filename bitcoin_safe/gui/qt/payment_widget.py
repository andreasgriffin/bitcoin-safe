#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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

from __future__ import annotations

import logging
import socket
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import TracebackType
from typing import Any, cast
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import requests
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import (
    Qt,
    QTimer,
    QUrl,
    pyqtBoundSignal,
    pyqtSignal,
)
from PyQt6.QtGui import QCloseEvent, QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.config import UserConfig
from bitcoin_safe.execute_config import DONATION_ADDRESS
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.logging_handlers import mail_contact
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.util import OptExcInfo

from ...fx import FX
from .ui_tx.spinbox import FiatSpinBox

logger = logging.getLogger(__name__)

DONATION_STORE_ID = "7agECo6zfJRp4Thi8vnBCjCoopb2yrnstaA5FophRfJe"
DONATION_INVOICE_ENDPOINT = "https://pay.bitcoin-safe.org/api/v1/invoices"
INVOICE_TIMEOUT = timedelta(minutes=15)


@dataclass
class CallbackServerState:
    invoice_id: str
    server: HTTPServer
    thread: threading.Thread
    port: int
    started_at: datetime
    invoice_url: str | None = None


class PaymentButton(QPushButton):
    signal_payment_completed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_update_status = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        config: UserConfig,
        loop_in_thread: LoopInThread,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.amount: float | None = None
        self.currency_iso: str | None = None
        self.loop_in_thread = loop_in_thread
        self.use_external_browser = True
        self._use_external_browser_current = True
        self._callback_server_state: CallbackServerState | None = None
        self._callback_timeout_timer: QTimer | None = None
        self._external_callback_seen = False
        self.future_invoice: Future[Any] | None = None

        self.clicked.connect(self.create_invoice)

        self.signal_update_status.emit(self.tr("Choose an amount and create a donation invoice."))
        self.updateUi()

    # ---------- public action ----------

    def set_amount(self, amount: float, currency_iso: str) -> None:
        self.amount = amount
        self.currency_iso = currency_iso

    def create_invoice(self) -> None:
        # cancel old creation
        self.cancel_invoice_task()
        self._stop_callback_server()
        self._external_callback_seen = False
        self._use_external_browser_current = True

        if not self.amount or not self.currency_iso:
            self.signal_update_status.emit(self.tr("Please choose a donation amount and a currency."))
            return

        redirect_url_override: str | None = None
        if self._use_external_browser_current:
            redirect_url_override = self._start_callback_server()
            if not redirect_url_override:
                self._use_external_browser_current = False
                self.signal_update_status.emit(
                    self.tr(
                        "Could not start the local callback server. Opening the invoice in your browser without automatic confirmation."
                    )
                )
                self.signal_update_status.emit(self.tr("Requesting invoice..."))
        else:
            self.signal_update_status.emit(self.tr("Requesting invoice..."))

        self.setEnabled(False)
        if self._use_external_browser_current:
            self.signal_update_status.emit(
                self.tr(
                    "Requesting invoice... A browser will open and Bitcoin Safe will listen for the callback locally."
                )
            )

        self.future_invoice = self.loop_in_thread.run_task(
            self._create_invoice_request(self.amount, self.currency_iso, redirect_url_override),
            on_success=self._on_invoice_created,
            on_error=self._on_invoice_error,
            key="donation_invoice",
        )

    # ---------- async / network ----------

    async def _create_invoice_request(
        self, amount: float, currency: str, redirect_url_override: str | None = None
    ) -> tuple[int, str | None, str | None, str]:
        proxies = (
            ProxyInfo.parse(self.config.network_config.proxy_url).get_requests_proxy_dict()
            if self.config.network_config.proxy_url
            else None
        )

        redirect_url = redirect_url_override or f"https://bitcoin-safe.org/redirecturl{uuid4()}"
        response = requests.post(
            DONATION_INVOICE_ENDPOINT,
            data={
                "storeId": DONATION_STORE_ID,
                "currency": currency,
                "price": f"{amount:.2f}",
                "browserRedirect": redirect_url,
            },
            allow_redirects=False,
            timeout=20 if proxies else 10,
            proxies=proxies,
        )
        return response.status_code, response.headers.get("Location"), response.text, redirect_url

    # ---------- callbacks ----------

    def _on_invoice_created(self, result: tuple[int, str | None, str | None, str]) -> None:
        status_code, invoice_url, _, redirect_url = result
        self.setEnabled(True)

        if not invoice_url:
            self.signal_update_status.emit(self.tr("Could not create invoice. Please try again."))
            self.signal_payment_completed.emit(False)
            self._stop_callback_server()
            return

        if status_code >= 400:
            self._stop_callback_server()
            self.signal_update_status.emit(
                self.tr("Invoice service returned an error ({code}).").format(code=status_code)
            )
            return

        if self._callback_server_state:
            self._callback_server_state.invoice_url = invoice_url

        if self._use_external_browser_current:
            if self._open_invoice_in_browser(invoice_url):
                self.signal_update_status.emit(
                    self.tr(
                        "Complete the payment in your browser.\n"
                        "If there is an issue, please dont hesitate to contact us at: andreasgriffin@proton.me"
                    )
                )
                return
            self.signal_update_status.emit(
                self.tr("Could not open your browser automatically. Please open the invoice link manually:")
            )
            self._stop_callback_server()
            self.signal_update_status.emit(invoice_url)
        else:
            self.signal_update_status.emit(
                self.tr(
                    "Invoice ready. Complete the payment in your browser. Automatic confirmation may not be available."
                )
            )
            self._open_invoice_in_browser(invoice_url)

    def _on_invoice_error(self, exc_info: OptExcInfo) -> None:
        exc_info_for_logger: tuple[type[BaseException], BaseException, TracebackType | None] | None = None
        if exc_info and exc_info[0] and exc_info[1]:
            exc_info_for_logger = cast(
                tuple[type[BaseException], BaseException, "TracebackType | None"], exc_info
            )

        logger.error("Failed to create donation invoice", exc_info=exc_info_for_logger)
        self.setEnabled(True)
        self.signal_update_status.emit(
            self.tr("Unable to reach the donation server. You can donate to: {address}").format(
                address=DONATION_ADDRESS
            )
        )
        self.signal_payment_completed.emit(False)
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

    def _build_callback_handler(self, invoice_id: str):
        parent = self

        class DonationCallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/donation/callback":
                    self.send_error(404)
                    return

                query = parse_qs(parsed.query)
                invoice_query = query.get("invoice", [""])[0]
                if invoice_query != invoice_id:
                    self.send_error(400, "Unknown invoice")
                    return

                parent._handle_callback_request(invoice_id)
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

    def _start_callback_server(self) -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
        except OSError:
            logger.exception("Failed to bind a local port for the callback listener")
            return None

        invoice_id = str(uuid4())
        handler = self._build_callback_handler(invoice_id)
        try:
            server = HTTPServer(("127.0.0.1", port), handler)
        except OSError:
            logger.exception("Failed to start the callback HTTP server on port %s", port)
            return None

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        self._callback_server_state = CallbackServerState(
            invoice_id=invoice_id, server=server, thread=thread, port=port, started_at=datetime.now()
        )
        logger.info(f"started  callback_server  {invoice_id=}, {port=}")
        self._start_callback_timeout_timer()
        return f"http://127.0.0.1:{port}/donation/callback?invoice={invoice_id}"

    def _request_stop_callback_server(self) -> None:
        threading.Thread(target=self._stop_callback_server, daemon=True).start()

    def _stop_callback_server(self) -> None:
        if self._callback_timeout_timer is not None:
            self._callback_timeout_timer.stop()
        state = self._callback_server_state
        self._callback_server_state = None
        if not state:
            return

        try:
            state.server.shutdown()
        except Exception:
            logger.exception("Failed to shutdown callback server cleanly")
        try:
            state.server.server_close()
        except Exception:
            logger.exception("Failed to close callback server socket cleanly")
        if state.thread.is_alive() and threading.current_thread() is not state.thread:
            state.thread.join(timeout=2)

    def _handle_callback_request(self, invoice_id: str) -> None:
        state = self._callback_server_state
        if not state or state.invoice_id != invoice_id:
            return
        if datetime.now() - state.started_at > INVOICE_TIMEOUT:
            self.signal_update_status.emit(
                self.tr("A browser callback arrived after the invoice expired. Please try again.")
            )
            return
        if self._external_callback_seen:
            return
        self._external_callback_seen = True
        self.signal_update_status.emit(self.tr("Payment confirmed via browser callback. Thank you!"))
        self.signal_payment_completed.emit(True)

    def _open_invoice_in_browser(self, invoice_url: str) -> bool:
        opened = QDesktopServices.openUrl(QUrl(invoice_url))
        return bool(opened)


class DonationInvoiceWidget(QWidget):
    payment_completed = cast(SignalProtocol[[bool]], pyqtSignal(bool))

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

        self.status_label = QLabel(self)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.payment_button = PaymentButton(
            config=fx.config,
            loop_in_thread=loop_in_thread,
            parent=self,
        )
        self.payment_button.signal_payment_completed.connect(self.payment_completed.emit)
        self.payment_button.signal_update_status.connect(self._update_status)

        self.donate_row.addStretch()
        self.donate_row.addWidget(self.fiat_label)
        self.donate_row.addWidget(self.fiat_spin_box)
        self.donate_row.addWidget(self.fiat_unit)
        self.donate_row.addWidget(self.payment_button)
        self.donate_row.addStretch()

        self.fiat_spin_box.setValue(amount)
        self.fiat_spin_box.setCurrencyCode(currency_iso)
        self._sync_amount_to_button()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(self.donate_row)
        layout.addWidget(self.status_label)

        self._update_status("")
        self.updateUi()

        self.fiat_spin_box.valueChanged.connect(self._sync_amount_to_button)
        signal_currency_changed.connect(self._sync_amount_to_button)

    def _update_status(self, message: str) -> None:
        logger.info(f"{message}")
        self.status_label.setText(str(message))

    def _sync_amount_to_button(self, *args) -> None:
        self.payment_button.set_amount(self.fiat_spin_box.value(), self.fx.get_currency_iso())

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        self.payment_button.close()
        super().closeEvent(a0)

    def updateUi(self):
        currency_symbol = self.fx.get_currency_symbol()
        self.fiat_unit.setText(currency_symbol)
        self.fiat_label.setText(self.tr("Value"))
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

        layout = QVBoxLayout(self)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setPixmap(svg_tools.get_QIcon("logo.svg").pixmap(96, 96))
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

    def _on_payment_complete(self, success: bool) -> None:
        if not success:
            return
        message = self.tr("Donation successful. Thank you so much for supporting Bitcoin Safe!")
        QMessageBox.information(self, self.tr("Donation"), message)

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.donation_widget.close()
        self.aboutToClose.emit(self)  # Emit the signal when the window is about to close
        super().closeEvent(a0)
