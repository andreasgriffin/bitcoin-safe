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
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, cast
from uuid import uuid4

import requests
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol, SignalTools
from bitcoin_safe_lib.gui.qt.util import question_dialog
from PyQt6.QtCore import (
    Qt,
    QUrl,
    pyqtBoundSignal,
    pyqtSignal,
)
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWebEngineWidgets import QWebEngineView
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
from .util import (
    center_on_screen,
)

logger = logging.getLogger(__name__)

DONATION_STORE_ID = "7agECo6zfJRp4Thi8vnBCjCoopb2yrnstaA5FophRfJe"
DONATION_INVOICE_ENDPOINT = "https://pay.bitcoin-safe.org/api/v1/invoices"
INVOICE_TIMEOUT = timedelta(minutes=15)


class DonationWebDialog(QWidget):
    signal_cancelled = cast(SignalProtocol[[object]], pyqtSignal(object))  # DonationWebDialog
    signal_url_changed = cast(
        SignalProtocol[[object, str]], pyqtSignal(object, str)
    )  # DonationWebDialog, new_url

    def __init__(
        self, callback_ok_to_close: Callable[[object, str], bool], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.callback_ok_to_close = callback_ok_to_close
        self.creation_time = datetime.now()
        self.invoice_url = ""

        self.setWindowTitle(self.tr("Complete Donation"))
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))

        self.setMinimumSize(500, 800)

        self.web_view = QWebEngineView(self)
        self.web_view.urlChanged.connect(self._on_url_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.web_view)

    def _on_url_changed(self, url: QUrl | None):
        if not url:
            return
        self.signal_url_changed.emit(self, url.toString())

    def show_url(self, url: str) -> None:
        self.invoice_url = url
        self.web_view.setUrl(QUrl(url))
        center_on_screen(self)
        self.show()
        self.raise_()

    def _shutdown_webengine(self) -> None:
        # helps avoid QWebEngine hanging around during shutdown
        self.web_view.stop()
        self.web_view.setUrl(QUrl("about:blank"))

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        if not a0:
            return
        if self.callback_ok_to_close(self, self.web_view.url().toString()):
            a0.accept()
            SignalTools.disconnect_all_signals_from(self)
            return

        if question_dialog(self.tr("Do you want to cancel the payment?")):
            self.signal_cancelled.emit(self)
            self._shutdown_webengine()
            a0.accept()
            SignalTools.disconnect_all_signals_from(self)
            return

        a0.ignore()


class UrlInfos:
    visited_urls: list[str] = []
    success_urls: list[str] = []
    auto_close_urls: list[str] = []


class PaymentButton(QPushButton):
    signal_payment_completed = cast(SignalProtocol[[bool]], pyqtSignal(bool))
    signal_update_status = cast(SignalProtocol[[str]], pyqtSignal(str))

    def __init__(
        self,
        config: UserConfig,
        loop_in_thread: LoopInThread,
        close_webview_on_successful_payment: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.amount: float | None = None
        self.currency_iso: str | None = None
        self.loop_in_thread = loop_in_thread
        self.close_webview_on_successful_payment = close_webview_on_successful_payment
        self.url_infos: defaultdict[str, UrlInfos] = defaultdict(UrlInfos)  # invoice_url,  UrlInfos

        self.future_invoice: Future[Any] | None = None

        self._web_dialogs: list[DonationWebDialog] = []

        self.clicked.connect(self.create_invoice)

        self._set_status(self.tr("Choose an amount and create a donation invoice."))
        self.updateUi()

    # ---------- public action ----------

    def set_amount(self, amount: float, currency_iso: str) -> None:
        self.amount = amount
        self.currency_iso = currency_iso

    def create_invoice(self) -> None:
        # cancel old creation
        self.cancel_invoice_task()

        if not self.amount or not self.currency_iso:
            self._set_status(self.tr("Please choose a donation amount and a currency."))
            return

        self.setEnabled(False)
        self._set_status(self.tr("Requesting invoice..."))

        self.future_invoice = self.loop_in_thread.run_task(
            self._create_invoice_request(self.amount, self.currency_iso),
            on_success=self._on_invoice_created,
            on_error=self._on_invoice_error,
            key="donation_invoice",
        )

    # ---------- async / network ----------

    async def _create_invoice_request(
        self, amount: float, currency: str
    ) -> tuple[int, str | None, str | None, str]:
        proxies = (
            ProxyInfo.parse(self.config.network_config.proxy_url).get_requests_proxy_dict()
            if self.config.network_config.proxy_url
            else None
        )

        redirect_url = f"https://bitcoin-safe.org/redirecturl{uuid4()}"
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
            self._set_status(self.tr("Could not create invoice. Please try again."))
            self.signal_payment_completed.emit(False)
            return

        self.url_infos[invoice_url].success_urls.append(invoice_url + "/receipt")
        self.url_infos[invoice_url].success_urls.append(redirect_url)
        self.url_infos[invoice_url].auto_close_urls.append(redirect_url)

        # show dialog even if status_code is an error (some services still provide a human-readable page)
        self._show_web_dialog(invoice_url)

        if status_code >= 400:
            self._set_status(self.tr("Invoice service returned an error ({code}).").format(code=status_code))
            return

        self._set_status(self.tr("Invoice ready. Complete the payment in the opened window."))

    def _on_invoice_error(self, exc_info: OptExcInfo) -> None:
        exc_info_for_logger: tuple[type[BaseException], BaseException, TracebackType | None] | None = None
        if exc_info and exc_info[0] and exc_info[1]:
            exc_info_for_logger = cast(
                tuple[type[BaseException], BaseException, "TracebackType | None"], exc_info
            )

        logger.error("Failed to create donation invoice", exc_info=exc_info_for_logger)
        self.setEnabled(True)
        self._set_status(
            self.tr("Unable to reach the donation server. You can donate to: {address}").format(
                address=DONATION_ADDRESS
            )
        )
        self.signal_payment_completed.emit(False)

    def url_is_successful_payment(self, web_dialog: object, url: str) -> bool:
        if not isinstance(web_dialog, DonationWebDialog):
            return False
        if datetime.now() - web_dialog.creation_time > INVOICE_TIMEOUT:
            return False
        return url in self.url_infos[web_dialog.invoice_url].success_urls

    def _show_web_dialog(self, url: str) -> None:
        dlg = DonationWebDialog(callback_ok_to_close=self.url_is_successful_payment)
        dlg.signal_url_changed.connect(self._on_url_changed)
        dlg.signal_cancelled.connect(self._on_user_cancelled_payment)

        self._web_dialogs.append(dlg)

        dlg.show_url(url)

    def _close_web_dialog(self, web_dialog: DonationWebDialog) -> None:
        web_dialog.close()
        if web_dialog in self._web_dialogs:
            self._web_dialogs.remove(web_dialog)

    def _on_user_cancelled_payment(self, web_dialog: object) -> None:
        if not isinstance(web_dialog, DonationWebDialog):
            return
        # If you want, you can emit a "failed/cancelled" signal here.
        self._set_status(self.tr("Payment cancelled."))
        self._close_web_dialog(web_dialog)
        self.signal_payment_completed.emit(False)

    def _on_url_changed(self, web_dialog: object, url: str) -> None:
        if not isinstance(web_dialog, DonationWebDialog):
            return
        self.url_infos[web_dialog.invoice_url].visited_urls.append(url)

        if self.url_is_successful_payment(web_dialog=web_dialog, url=url):
            self._set_status(self.tr("Payment confirmed. Thank you!"))
            if self.close_webview_on_successful_payment and (
                url in self.url_infos[web_dialog.invoice_url].auto_close_urls
            ):
                self._close_web_dialog(web_dialog)
            self.signal_payment_completed.emit(True)

    # ---------- ui helpers ----------

    def _set_status(self, message: str) -> None:
        self.signal_update_status.emit(message)

    def cancel_invoice_task(self):
        # cancel pending async task if supported
        if self.future_invoice is not None:
            try:
                self.future_invoice.cancel()
            except Exception:
                pass
            self.future_invoice = None

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        # stop web dialog first
        while self._web_dialogs:
            self._close_web_dialog(web_dialog=self._web_dialogs.pop())

        self.cancel_invoice_task()

        super().closeEvent(a0)

    def updateUi(self):
        self.setText(self.tr("Create invoice"))


class DonationInvoiceWidget(QWidget):
    payment_completed = cast(SignalProtocol[[bool]], pyqtSignal(bool))

    def __init__(
        self,
        amount: float,
        fx: FX,
        loop_in_thread: LoopInThread,
        signal_currency_changed: SignalProtocol[[]] | pyqtBoundSignal,
        signal_language_switch: SignalProtocol[[]] | pyqtBoundSignal,
        close_webview_on_successful_payment: bool = True,
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
            close_webview_on_successful_payment=close_webview_on_successful_payment,
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
        self.fiat_spin_box.setCurrencyCode(self.fx.get_currency_iso())
        self._sync_amount_to_button()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(self.donate_row)
        layout.addWidget(self.status_label)

        self._update_status(self.tr("Choose an amount and create a donation invoice."))
        self.updateUi()

        self.fiat_spin_box.valueChanged.connect(self._sync_amount_to_button)
        signal_currency_changed.connect(self._sync_amount_to_button)

    def _update_status(self, message: str) -> None:
        self.status_label.setText(message)

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
        fx,
        loop_in_thread,
        signal_currency_changed,
        signal_language_switch,
        close_webview_on_successful_payment: bool = True,
        on_about_to_close=None,
        parent=None,
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

        self.donation_widget = DonationInvoiceWidget(
            amount=10.00,
            fx=fx,
            loop_in_thread=loop_in_thread,
            signal_currency_changed=signal_currency_changed,
            signal_language_switch=signal_language_switch,
            close_webview_on_successful_payment=close_webview_on_successful_payment,
            parent=self,
        )
        self.donation_widget.payment_completed.connect(self._on_payment_complete)
        layout.addWidget(self.donation_widget)

        contact_button = QPushButton(self.tr("Email us"))
        contact_button.clicked.connect(mail_contact)
        layout.addWidget(contact_button, alignment=Qt.AlignmentFlag.AlignCenter)

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
