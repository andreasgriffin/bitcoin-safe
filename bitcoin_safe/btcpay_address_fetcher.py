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
# SOFTWARE.

"""
Utilities for interacting with the BTCPay Server pay button endpoint.

The helper exposes a small client that can request a new invoice from the
public BTCPay endpoint, download the rendered HTML page referenced by the
`Location` header, and parse out the on-chain Bitcoin address embedded in
the page. Lightning invoices are not always present on the public page and
are therefore treated as optional.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from uuid import uuid4

import bdkpython as bdk
import requests
from bitcoin_safe_lib.storage import BaseSaveableClass, filtered_for_init

from bitcoin_safe.btcpay_config import BTCPAY_SUBSCRIPTION_CONFIG
from bitcoin_safe.config import BtcPayInvoiceDetails
from bitcoin_safe.execute_config import (
    DONATION_ADDRESS,
    DONATION_ADDRESS_regtest,
    DONATION_ADDRESS_signet,
    DONATION_ADDRESS_testnet,
    DONATION_ADDRESS_testnet4,
)
from bitcoin_safe.network_utils import ProxyInfo
from bitcoin_safe.util import SATOSHIS_PER_BTC, default_timeout

logger = logging.getLogger(__name__)


class BtcPayState(BaseSaveableClass):
    known_classes = {
        **BaseSaveableClass.known_classes,
        BtcPayInvoiceDetails.__name__: BtcPayInvoiceDetails,
    }
    VERSION = "0.1.0"

    def __init__(
        self,
        invoice_details: dict[str, BtcPayInvoiceDetails] | None = None,
        store_id: str = BTCPAY_SUBSCRIPTION_CONFIG.btcpay_base.store_id,
    ):
        super().__init__()
        self.store_id = store_id
        self.invoice_details = invoice_details if invoice_details else {}

    def add_address_only_invoice(self, invoice: BtcPayInvoiceDetails):
        self.invoice_details[str(uuid4())] = invoice

    def add_invoice(self, key: str, invoice: BtcPayInvoiceDetails):
        self.invoice_details[key] = invoice

    def dump(self) -> dict[str, Any]:
        """Dump."""
        d = super().dump()
        d["invoice_details"] = self.invoice_details
        return d

    @classmethod
    def from_dump(cls, dct: dict, class_kwargs: dict | None = None):
        """From dump."""
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    def merge(self, other: BtcPayState) -> int:
        new_invoices = 0
        for other_key, other_detail in other.invoice_details.items():
            if other_key not in self.invoice_details:
                new_invoices += 1
                self.invoice_details[other_key] = other_detail
        return new_invoices


class BtcPayAddressFetcher:
    """Simple client for the public BTCPay pay button endpoint."""

    def __init__(
        self,
        network: bdk.Network,
        invoice_details: list[BtcPayInvoiceDetails],
        store_id: str = BTCPAY_SUBSCRIPTION_CONFIG.btcpay_base.store_id,
        session: requests.sessions.Session | None = None,
    ):
        super().__init__()
        btcpay_base = BTCPAY_SUBSCRIPTION_CONFIG.btcpay_base
        self.store_id = store_id or btcpay_base.store_id
        self.network = network
        self.session: requests.sessions.Session = session or requests.Session()
        self.base_url = btcpay_base.base_url.rstrip("/")
        self.invoice_details = invoice_details  # no copy, we write directly to this instance

    def request_invoice(self, proxy_info: ProxyInfo | None, amount: int | None) -> str:
        """Request a new invoice and return the absolute invoice URL."""
        payload = {"storeId": self.store_id, "currency": "BTC"}
        if amount is not None:
            payload["price"] = f"{amount / SATOSHIS_PER_BTC:.8f}"

        response = self.session.post(
            f"{self.base_url}/api/v1/invoices",
            data=payload,
            allow_redirects=False,
            timeout=self._request_timeout(proxy_info),
            proxies=self._request_proxies(proxy_info),
        )
        response.raise_for_status()

        location = response.headers.get("Location")
        if not location:
            raise ValueError("BTCPay response did not include invoice Location header")

        return urljoin(self.base_url + "/", location)

    def fetch_invoice_html(self, invoice_url: str, proxy_info: ProxyInfo | None) -> str:
        """Return the HTML content for a given invoice URL."""
        response = self.session.get(
            invoice_url,
            timeout=self._request_timeout(proxy_info),
            proxies=self._request_proxies(proxy_info),
        )
        response.raise_for_status()
        return response.text

    def parse_payment_details(self, html: str) -> tuple[str, int | None]:
        """Parse the invoice HTML to extract the bitcoin address and optional amount in satoshis."""

        bitcoin_uri = self._extract_first_match(
            html,
            patterns=[
                r'bitcoin:([a-zA-Z0-9]{26,90}(?:\?[^"\s<]+)?)',
                r'data-qr-value="bitcoin:([a-zA-Z0-9]{26,90}(?:\?[^"]+)?)"',
                r'data-clipboard="bitcoin:([a-zA-Z0-9]{26,90}(?:\?[^"]+)?)"',
            ],
        )

        if bitcoin_uri:
            parsed = urlparse(f"bitcoin:{bitcoin_uri}")
            bitcoin_address = parsed.path

            amount_str = parse_qs(parsed.query).get("amount", [None])[0]

            amount_sats: int | None = None
            if amount_str is not None:
                # Convert BTC string → satoshis (int)
                amount_sats = int(Decimal(amount_str) * SATOSHIS_PER_BTC)

            return bitcoin_address, amount_sats

        # Fallback: address only
        fallback_bitcoin_address = self._extract_first_match(
            html,
            patterns=[
                r"\baddress\"?\s*[:=]\s*\"?([a-zA-Z0-9]{26,90})\"?",
                r'data-destination="([a-zA-Z0-9]{26,90})"',
            ],
        )
        if fallback_bitcoin_address:
            return fallback_bitcoin_address, None

        raise ValueError("Unable to locate bitcoin address in invoice HTML")

    def request_invoice_details(
        self,
        proxy_info: ProxyInfo | None,
        amount: int | None = None,
        enable_fallback_address: bool = True,
    ) -> BtcPayInvoiceDetails:
        """Perform the full flow: create an invoice, fetch HTML, and parse payment details.

        When the BTCPay endpoint cannot be reached and ``enable_fallback_address`` is
        true, this method will return invoice details using the static donation
        address instead of raising.
        """
        if self.network == bdk.Network.REGTEST:
            details = BtcPayInvoiceDetails(
                url=None,
                bitcoin_address=DONATION_ADDRESS_regtest,
                amount=amount,
            )
            return details
        if self.network == bdk.Network.SIGNET:
            details = BtcPayInvoiceDetails(
                url=None,
                bitcoin_address=DONATION_ADDRESS_signet,
                amount=amount,
            )
            return details
        if self.network == bdk.Network.TESTNET:
            details = BtcPayInvoiceDetails(
                url=None,
                bitcoin_address=DONATION_ADDRESS_testnet,
                amount=amount,
            )
            return details
        if self.network == bdk.Network.TESTNET4:
            details = BtcPayInvoiceDetails(
                url=None,
                bitcoin_address=DONATION_ADDRESS_testnet4,
                amount=amount,
            )
            return details

        try:
            invoice_url = self.request_invoice(amount=amount, proxy_info=proxy_info)
            invoice_html = self.fetch_invoice_html(invoice_url, proxy_info=proxy_info)
            bitcoin_address, amount = self.parse_payment_details(invoice_html)
            details = BtcPayInvoiceDetails(
                url=invoice_url,
                bitcoin_address=bitcoin_address,
                amount=amount,
            )
            return details
        except Exception:
            if not enable_fallback_address:
                raise

            details = BtcPayInvoiceDetails(
                url=None,
                bitcoin_address=DONATION_ADDRESS,
                amount=amount,
            )
            return details

    @staticmethod
    def _request_proxies(proxy_info: ProxyInfo | None) -> dict[str, str] | None:
        return proxy_info.get_requests_proxy_dict() if proxy_info else None

    @classmethod
    def _request_timeout(cls, proxy_info: ProxyInfo | None) -> float:
        return default_timeout(cls._request_proxies(proxy_info))

    @staticmethod
    def _extract_first_match(html: str, patterns: Iterable[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
