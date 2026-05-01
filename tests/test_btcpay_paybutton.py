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
Tests for the BTCPay pay button helper.
"""

from typing import Any

import bdkpython as bdk
import pytest
import requests

from bitcoin_safe.btcpay_address_fetcher import BtcPayAddressFetcher
from bitcoin_safe.btcpay_config import BTCPAY_SUBSCRIPTION_CONFIG
from bitcoin_safe.config import BtcPayInvoiceDetails
from bitcoin_safe.network_utils import ProxyInfo


class StubResponse:
    def __init__(self, status_code: int = 200, text: str = "", headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status code {self.status_code}")


class StubSession:
    def __init__(self, responses: list[StubResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(
        self, url: str, data: dict[str, str] | None = None, allow_redirects: bool = True, **kwargs: Any
    ) -> StubResponse:
        self.calls.append(("post", url, {"data": data, "allow_redirects": allow_redirects, **kwargs}))
        return self.responses.pop(0)

    def get(self, url: str, **kwargs: Any) -> StubResponse:
        self.calls.append(("get", url, kwargs))
        return self.responses.pop(0)


SAMPLE_HTML = """
<html>
  <body>
    <div data-destination="bc1p0nchainexampleaddressxxxxxx">
      <a href="bitcoin:bc1p0nchainexampleaddressxxxxxx">Bitcoin</a>
    </div>
  </body>
</html>
"""


class TestBtcPayAddressFetcher:
    @staticmethod
    def _build_client(session: StubSession) -> BtcPayAddressFetcher:
        return BtcPayAddressFetcher(
            store_id=BTCPAY_SUBSCRIPTION_CONFIG.btcpay_base.store_id,
            session=session,
            network=bdk.Network.BITCOIN,
            invoice_details=[],
        )

    def test_parse_payment_details(self):
        client = BtcPayAddressFetcher(
            store_id="dummy",
            session=StubSession([]),
            network=bdk.Network.BITCOIN,
            invoice_details=[],
        )
        bitcoin_address, lightning_invoice = client.parse_payment_details(SAMPLE_HTML)

        assert bitcoin_address == "bc1p0nchainexampleaddressxxxxxx"
        assert lightning_invoice is None

    def test_full_invoice_request_flow(self):
        session = StubSession(
            [
                StubResponse(status_code=302, headers={"Location": "/invoice?id=test"}),
                StubResponse(text=SAMPLE_HTML),
            ]
        )
        client = self._build_client(session)

        details: BtcPayInvoiceDetails = client.request_invoice_details(proxy_info=None)

        assert details.url == f"{client.base_url}/invoice?id=test"
        assert details.bitcoin_address == "bc1p0nchainexampleaddressxxxxxx"
        assert session.calls[0][0] == "post"
        assert session.calls[1][0] == "get"
        assert session.calls[0][2]["timeout"] == 2
        assert session.calls[0][2]["proxies"] is None
        assert session.calls[1][2]["timeout"] == 2
        assert session.calls[1][2]["proxies"] is None

    def test_full_invoice_request_flow_uses_proxy_for_html_fetch(self):
        session = StubSession(
            [
                StubResponse(status_code=302, headers={"Location": "/invoice?id=test"}),
                StubResponse(text=SAMPLE_HTML),
            ]
        )
        client = self._build_client(session)
        proxy_info = ProxyInfo(host="127.0.0.1", port=9050)

        details = client.request_invoice_details(proxy_info=proxy_info)

        expected_proxies = proxy_info.get_requests_proxy_dict()
        assert details.url
        assert session.calls[0][2]["timeout"] == 10
        assert session.calls[0][2]["proxies"] == expected_proxies
        assert session.calls[1][2]["timeout"] == 10
        assert session.calls[1][2]["proxies"] == expected_proxies

    def test_invoice_request_flow_falls_back_to_donation_address(self):
        session = StubSession([StubResponse(status_code=500)])
        client = self._build_client(session)

        details: BtcPayInvoiceDetails = client.request_invoice_details(proxy_info=None)

        assert details.url is None
        assert details.bitcoin_address == "bc1qs8vxaclc0ncf92nrhc4rcdgppwganny6mpn9d4"

    @pytest.mark.integration
    def test_live_invoice_request_flow(self):
        """Optional integration test hitting the public endpoint when enabled."""

        client = BtcPayAddressFetcher(
            store_id=BTCPAY_SUBSCRIPTION_CONFIG.btcpay_base.store_id,
            network=bdk.Network.BITCOIN,
            invoice_details=[],
        )

        details = client.request_invoice_details(proxy_info=None)

        assert details.url
        assert details.url.startswith(f"{client.base_url}")
        assert details.bitcoin_address
