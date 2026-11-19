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
import requests

from bitcoin_safe.network_utils import cached_get, fetch_bytes


def test_cached_get_reuses_only_successful_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_get(url: str, **kwargs: object) -> requests.Response:
        nonlocal calls
        calls += 1
        response = requests.Response()
        response.status_code = 500 if calls == 1 else 200
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    args = ("https://cache-test.example/plans", {"Accept": "application/json"}, None, 20)
    with pytest.raises(requests.HTTPError):
        cached_get(*args)
    assert cached_get(*args).status_code == 200
    assert cached_get(*args).status_code == 200
    assert calls == 2
    cached_get(*args, caching=False)
    assert calls == 3


def test_fetch_bytes_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_get(url: str, **kwargs: object) -> requests.Response:
        nonlocal calls
        calls += 1
        response = requests.Response()
        response.status_code = 200
        response._content = b"content"
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    assert fetch_bytes("https://cache-test.example/bytes", {}, None) == b"content"
    assert fetch_bytes("https://cache-test.example/bytes", {}, None) == b"content"
    assert calls == 1
