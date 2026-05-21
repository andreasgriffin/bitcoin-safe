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
import socket

from bitcoin_safe.network_utils import (
    ProxyInfo,
    ResolvedEndpoint,
    resolve_host_addresses,
    resolve_host_addresses_async,
    resolve_host_endpoints,
    resolve_host_endpoints_async,
)


def test_resolve_host_addresses_bypasses_dns_for_ip_literals(monkeypatch) -> None:
    def fail_getaddrinfo(*args, **kwargs):
        raise AssertionError("getaddrinfo should not be called for IP literals")

    monkeypatch.setattr("bitcoin_safe.network_utils.socket.getaddrinfo", fail_getaddrinfo)

    assert resolve_host_addresses("8.8.8.8", proxy_info=None) == ["8.8.8.8"]
    assert resolve_host_addresses("2606:4700:4700::1111", proxy_info=None) == ["2606:4700:4700::1111"]


def test_resolve_host_endpoints_preserves_port_and_family(monkeypatch) -> None:
    monkeypatch.setattr(
        "bitcoin_safe.network_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, None, None, None, ("8.8.8.8", 8333)),
            (socket.AF_INET6, None, None, None, ("2606:4700:4700::1111", 18333, 0, 0)),
        ],
    )

    assert resolve_host_endpoints("example.com", proxy_info=None, port=50001) == [
        ResolvedEndpoint(host="8.8.8.8", port=8333, family=socket.AF_INET),
        ResolvedEndpoint(host="2606:4700:4700::1111", port=18333, family=socket.AF_INET6),
    ]


def test_resolve_host_addresses_returns_unique_results(monkeypatch) -> None:
    monkeypatch.setattr(
        "bitcoin_safe.network_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, None, None, None, ("8.8.8.8", 0)),
            (socket.AF_INET6, None, None, None, ("2606:4700:4700::1111", 0)),
            (socket.AF_INET, None, None, None, ("8.8.8.8", 0)),
        ],
    )

    assert resolve_host_addresses("example.com", proxy_info=None) == [
        "8.8.8.8",
        "2606:4700:4700::1111",
    ]


def test_resolve_host_addresses_skips_local_dns_for_remote_dns_proxy(monkeypatch) -> None:
    calls: list[str] = []

    def fake_getaddrinfo(host, *args, **kwargs):
        del args, kwargs
        calls.append(host)
        return []

    monkeypatch.setattr("bitcoin_safe.network_utils.socket.getaddrinfo", fake_getaddrinfo)

    proxy_info = ProxyInfo.parse("socks5h://127.0.0.1:9050")

    assert resolve_host_addresses("example.com", proxy_info=proxy_info) == []
    assert calls == []


def test_resolve_host_endpoints_ip_literal_keeps_requested_port(monkeypatch) -> None:
    def fail_getaddrinfo(*args, **kwargs):
        raise AssertionError("getaddrinfo should not be called for IP literals")

    monkeypatch.setattr("bitcoin_safe.network_utils.socket.getaddrinfo", fail_getaddrinfo)

    assert resolve_host_endpoints("8.8.8.8", proxy_info=None, port=8333) == [
        ResolvedEndpoint(host="8.8.8.8", port=8333, family=socket.AF_INET)
    ]


def test_resolve_host_addresses_async_uses_same_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        "bitcoin_safe.network_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, None, None, None, ("1.1.1.1", 0))],
    )

    assert asyncio.run(resolve_host_addresses_async("example.com", proxy_info=None)) == ["1.1.1.1"]


def test_resolve_host_endpoints_async_uses_same_policy(monkeypatch) -> None:
    monkeypatch.setattr(
        "bitcoin_safe.network_utils.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, None, None, None, ("1.1.1.1", 50001))],
    )

    assert asyncio.run(resolve_host_endpoints_async("example.com", proxy_info=None, port=50001)) == [
        ResolvedEndpoint(host="1.1.1.1", port=50001, family=socket.AF_INET)
    ]
