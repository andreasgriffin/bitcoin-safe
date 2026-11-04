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

import pytest
from btcpay_tools.btcpay_subscription_api.models import StoreInfoResponse

from bitcoin_safe.plugin_framework.subscription_api_client import SubscriptionApiClient

LIVE_STORE_RESPONSE = {
    "schema_version": 1,
    "base_url": "https://pay.bitcoin-safe.org",
    "store_id": "GUwgxbBcM3CTo7rSCP2KEcATmzEXMHQXe4WbfBhEyWrS",
}


def test_fetch_store_parses_store_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        SubscriptionApiClient,
        "_request",
        lambda self, method, path, payload=None: LIVE_STORE_RESPONSE,
    )

    store = SubscriptionApiClient(None).fetch_store()

    assert store == StoreInfoResponse.model_validate(LIVE_STORE_RESPONSE)
    assert store.store_id == "GUwgxbBcM3CTo7rSCP2KEcATmzEXMHQXe4WbfBhEyWrS"
    assert store.base_url == "https://pay.bitcoin-safe.org"


def test_fetch_store_requests_the_store_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(self, method, path, payload=None):
        calls.append((method, path))
        return LIVE_STORE_RESPONSE

    monkeypatch.setattr(SubscriptionApiClient, "_request", fake_request)

    SubscriptionApiClient(None).fetch_store()

    assert calls == [("GET", "/api/store")]
