#
# Bitcoin Safe
# Copyright (C) 2025-2026 Andreas Griffin
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
import ipaddress
import json
import logging
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import aiohttp
import bdkpython as bdk
import requests
import socks
from aiohttp_socks import ProxyConnector

from bitcoin_safe.util import default_timeout

logger = logging.getLogger(__name__)


class ExternalPluginError(Exception):
    """Error raised when an external plugin operation (e.g. downloading a
    plugin source) fails. Defined here so ``fetch_bytes`` can raise it and
    plugin-framework callers catch it via ``except ExternalPluginError``.
    """


class RequestsGetException(ExternalPluginError):
    pass


class IpAddress(bdk.IpAddress):
    _RESOLVE_TIMEOUT_SECONDS = 5.0

    @staticmethod
    def _resolve_domain(host: str, timeout: float, proxy_info: ProxyInfo | None = None) -> str:
        """Resolve domain."""
        addresses = resolve_host_addresses(host, proxy_info=proxy_info, timeout=timeout)
        if not addresses:
            raise ValueError(f"Could not resolve domain {host!r} to an IP address")
        return addresses[0]

    @classmethod
    def from_host(cls, host: str, proxy_info: ProxyInfo | None = None):
        """From host."""
        try:
            host_ip = ipaddress.ip_address(host)
        except ValueError:
            resolved_host = cls._resolve_domain(host, cls._RESOLVE_TIMEOUT_SECONDS, proxy_info=proxy_info)
            host_ip = ipaddress.ip_address(resolved_host)
        host = str(host_ip.exploded)

        try:
            a1, a2, a3, a4 = host.split(".")
            return cls.from_ipv4(int(a1), int(a2), int(a3), int(a4))
        except Exception:
            pass

        try:
            a1, a2, a3, a4, a5, a6, a7, a8 = host.split(":")
            return cls.from_ipv6(
                int(a1, 16),
                int(a2, 16),
                int(a3, 16),
                int(a4, 16),
                int(a5, 16),
                int(a6, 16),
                int(a7, 16),
                int(a8, 16),
            )
        except Exception:
            pass
        raise Exception(f"{host=} could not be converted to {cls}")


@dataclass(frozen=True)
class ResolvedEndpoint:
    host: str
    port: int | None
    family: int


@dataclass
class ProxyInfo:
    host: str | None
    port: int | None
    scheme: str = "socks5h"

    def get_socks_scheme(self) -> int:
        """Get socks scheme."""
        if self.scheme == "socks4":
            return socks.SOCKS4
        return socks.SOCKS5

    def get_url(self):
        """Get url."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def get_url_no_h(self):
        """Get url no h."""
        return f"{self.scheme[:-1] if self.scheme.endswith('h') else self.scheme}://{self.host}:{self.port}"

    def get_requests_proxy_dict(self):
        """Get requests proxy dict."""
        return {"http": self.get_url(), "https": self.get_url()}

    @classmethod
    def parse(cls, proxy_url: str):
        # Prepend "socks5h://" if the proxy string does not contain a scheme
        """Parse."""
        if "://" not in proxy_url:
            proxy_url = f"{cls.scheme}://{proxy_url}"  # Default to SOCKS5 with remote DNS
        parsed_proxy = urlparse(proxy_url)
        return cls(host=parsed_proxy.hostname, port=parsed_proxy.port, scheme=parsed_proxy.scheme)

    def to_bdk(self) -> bdk.Socks5Proxy:
        """To bdk."""

        assert self.host, "No host set"
        assert self.port, "No port set"
        return bdk.Socks5Proxy(address=IpAddress.from_host(self.host), port=self.port)


@dataclass(frozen=True)
class AsyncHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


def _aiohttp_session_kwargs(
    proxy_info: ProxyInfo | None, timeout: float
) -> tuple[dict[str, Any], dict[str, Any]]:
    session_kwargs: dict[str, Any] = {"timeout": aiohttp.ClientTimeout(total=timeout)}
    request_kwargs: dict[str, Any] = {}

    if not proxy_info:
        return session_kwargs, request_kwargs

    scheme = proxy_info.scheme.lower()
    if scheme.startswith("socks"):
        session_kwargs["connector"] = ProxyConnector.from_url(proxy_info.get_url())
        return session_kwargs, request_kwargs

    if scheme.startswith("http"):
        request_kwargs["proxy"] = proxy_info.get_url()
        return session_kwargs, request_kwargs

    raise ValueError(f"Unsupported proxy scheme for aiohttp: {proxy_info.scheme}")


async def post_form_async(
    url: str,
    data: dict[str, str],
    proxy_info: ProxyInfo | None,
    timeout: float,
    allow_redirects: bool = False,
) -> AsyncHttpResponse:
    session_kwargs, request_kwargs = _aiohttp_session_kwargs(proxy_info=proxy_info, timeout=timeout)
    async with aiohttp.ClientSession(**session_kwargs) as session:
        async with session.post(
            url, data=data, allow_redirects=allow_redirects, **request_kwargs
        ) as response:
            return AsyncHttpResponse(
                status_code=response.status,
                headers=dict(response.headers),
                body=await response.read(),
            )


def is_ip_address(host: str) -> bool:
    """Return True when the given host string is an IPv4 or IPv6 literal."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def uses_remote_dns(proxy_info: ProxyInfo | None) -> bool:
    """Return True when the proxy resolves hostnames on the proxy side."""
    return bool(proxy_info and proxy_info.scheme.endswith("h"))


def _family_for_ip_literal(host: str) -> int:
    address = ipaddress.ip_address(host)
    return socket.AF_INET if address.version == 4 else socket.AF_INET6


def resolve_host_endpoints(
    host: str,
    proxy_info: ProxyInfo | None,
    port: int | None = None,
    timeout: float | Literal["default"] = "default",
    family: int = socket.AF_UNSPEC,
    socktype: int = socket.SOCK_STREAM,
) -> list[ResolvedEndpoint]:
    """Resolve a host into socket endpoints according to the app's proxy policy."""
    if is_ip_address(host):
        return [ResolvedEndpoint(host=host, port=port, family=_family_for_ip_literal(host))]

    if uses_remote_dns(proxy_info):
        logger.debug("Skipping local DNS resolution for %s because remote-DNS proxy is enabled", host)
        return []

    timeout_seconds = default_timeout(proxy_info, timeout)

    def _resolve() -> list[ResolvedEndpoint]:
        infos = socket.getaddrinfo(host, port, family=family, type=socktype)
        endpoints: list[ResolvedEndpoint] = []
        for resolved_family, _, _, _, sockaddr in infos:
            if resolved_family not in (socket.AF_INET, socket.AF_INET6):
                continue
            candidate = sockaddr[0]
            if not isinstance(candidate, str):
                continue
            candidate_port = None
            if len(sockaddr) > 1 and isinstance(sockaddr[1], int):
                candidate_port = sockaddr[1]
            endpoint = ResolvedEndpoint(host=candidate, port=candidate_port, family=resolved_family)
            if endpoint not in endpoints:
                endpoints.append(endpoint)
        return endpoints

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_resolve)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            logger.warning("Timed out after %s seconds resolving host %r", timeout_seconds, host)
            return []
        except OSError as exc:
            logger.debug("Could not resolve host %r: %s", host, exc)
            return []


async def resolve_host_endpoints_async(
    host: str,
    proxy_info: ProxyInfo | None,
    port: int | None = None,
    timeout: float | Literal["default"] = "default",
    family: int = socket.AF_UNSPEC,
    socktype: int = socket.SOCK_STREAM,
) -> list[ResolvedEndpoint]:
    """Async wrapper around the centralized hostname endpoint resolver."""
    return await asyncio.to_thread(
        resolve_host_endpoints,
        host,
        proxy_info,
        port,
        timeout,
        family,
        socktype,
    )


def resolve_host_addresses(
    host: str,
    proxy_info: ProxyInfo | None,
    timeout: float | Literal["default"] = "default",
    family: int = socket.AF_UNSPEC,
    socktype: int = socket.SOCK_STREAM,
) -> list[str]:
    """Resolve a host into unique IP addresses according to the app's proxy policy."""
    addresses: list[str] = []
    for endpoint in resolve_host_endpoints(
        host=host,
        proxy_info=proxy_info,
        timeout=timeout,
        family=family,
        socktype=socktype,
    ):
        if endpoint.host not in addresses:
            addresses.append(endpoint.host)
    return addresses


async def resolve_host_addresses_async(
    host: str,
    proxy_info: ProxyInfo | None,
    timeout: float | Literal["default"] = "default",
    family: int = socket.AF_UNSPEC,
    socktype: int = socket.SOCK_STREAM,
) -> list[str]:
    """Async wrapper around the centralized hostname resolver."""
    endpoints = await resolve_host_endpoints_async(
        host=host,
        proxy_info=proxy_info,
        timeout=timeout,
        family=family,
        socktype=socktype,
    )
    addresses: list[str] = []
    for endpoint in endpoints:
        if endpoint.host not in addresses:
            addresses.append(endpoint.host)
    return addresses


def clean_electrum_url(url: str, electrum_use_ssl: bool) -> str:
    """Clean electrum url."""
    if electrum_use_ssl and not url.startswith("ssl://"):
        url = "ssl://" + url
    return url


def ensure_scheme(url, default_scheme="https://"):
    """Check if "://" is in the URL and split it."""
    if "://" in url:
        return url  # Return the original URL if   scheme is found
    else:
        return f"{default_scheme}{url}"


def get_host_and_port(url) -> tuple[str | None, int | None]:
    """Get host and port."""
    parsed_url = urlparse(ensure_scheme(url))

    # Extract the hostname and port
    return parsed_url.hostname, parsed_url.port


def fetch_bytes(
    url: str,
    headers: dict[str, str],
    proxy_info: ProxyInfo | None,
) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=default_timeout(proxy_info),
                proxies=proxy_info.get_requests_proxy_dict() if proxy_info else None,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RequestsGetException(f"Could not download plugin source URL {url}: {exc}") from exc
        return response.content
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).read_bytes()

    path = Path(url)
    if path.exists():
        return path.read_bytes()

    raise ValueError(f"Could not read plugin source URL {url}.")


def send_request_to_electrum_server(
    host: str,
    port: int,
    request: dict[str, Any],
    use_ssl: bool,
    proxy_info: ProxyInfo | None,
    timeout: float | Literal["default"] = "default",
) -> dict[str, Any] | None:
    """Sends an arbitrary JSON-RPC request to the Electrum server and returns the
    decoded JSON response.

    Args:
        host (str): The server hostname.
        port (int): The server port.
        request (Dict[str, Any]): The JSON-RPC request as a dictionary.
        use_ssl (bool): Whether to wrap the connection in SSL.
        timeout (int): Connection timeout in seconds.
        proxy_info (Optional[ProxyInfo]): Optional proxy configuration.

    Returns:
        Optional[Dict[str, Any]]: The server's response as a dictionary, or None on failure.
    """
    sock = None
    ssock: socket.socket | None | ssl.SSLContext = None
    timeout = default_timeout(proxy_info, timeout)
    try:
        # Set up the proxy if provided.
        if proxy_info:
            socks.set_default_proxy(
                proxy_info.get_socks_scheme(),
                proxy_info.host,
                proxy_info.port,
                rdns=(proxy_info.scheme == "socks5h"),
            )
            # Create a socks socket instance directly.
            sock = socks.socksocket()
            sock.settimeout(timeout)
            sock.connect((host, port))
        else:
            sock = socket.create_connection((host, port), timeout=timeout)

        # Wrap the socket with SSL if requested.
        if use_ssl:
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            ssock = context.wrap_socket(sock, server_hostname=host)
        else:
            ssock = sock

        if not ssock:
            return None

        # Send the JSON-RPC request.
        request_str: str = json.dumps(request) + "\n"
        ssock.sendall(request_str.encode())

        # Read the response (assumes response fits in 4096 bytes and is newline terminated).
        response_data = ssock.recv(4096).decode()
        response_json: dict[str, Any] = json.loads(response_data.split("\n")[0])
        return response_json

    except Exception as e:
        logger.debug(f"Connection or communication error: {e}")
        return None

    finally:
        # Attempt to close the SSL-wrapped socket if it was created.
        if isinstance(ssock, socket.socket):
            try:
                ssock.close()
            except Exception as close_err:
                logger.debug(f"Error closing SSL socket: {close_err}")
        # If no SSL socket exists, close the plain socket if available.
        elif sock is not None:
            try:
                sock.close()
            except Exception as close_err:
                logger.debug(f"Error closing socket: {close_err}")


def get_electrum_blockheight(
    host: str,
    port: int,
    use_ssl: bool,
    proxy_info: ProxyInfo | None,
    timeout: int = 2,
) -> int | None:
    """Retrieves the current blockchain height from an Electrum server.

    Args:
        host (str): The server hostname.
        port (int): The server port.
        use_ssl (bool): Whether to use SSL for the connection.
        proxy_info (Optional[ProxyInfo]): Optional proxy configuration.
        timeout (int): Connection timeout in seconds. Defaults to 2.

    Returns:
        Optional[int]: The blockchain height if available, else None.
    """
    request: dict[str, Any] = {"id": 0, "method": "blockchain.headers.subscribe", "params": []}
    response = send_request_to_electrum_server(
        host=host, port=port, request=request, use_ssl=use_ssl, timeout=timeout, proxy_info=proxy_info
    )
    if response is None:
        return None
    result = response.get("result")
    if isinstance(result, dict) and "height" in result:
        return int(result["height"])
    return None


def get_electrum_server_version(
    host: str,
    port: int,
    use_ssl: bool,
    proxy_info: ProxyInfo | None,
    timeout: float | Literal["default"] = "default",
) -> str | None:
    """Retrieves the server version from an Electrum server.

    Args:
        host (str): The server hostname.
        port (int): The server port.
        use_ssl (bool): Whether to use SSL for the connection. Defaults to True.
        timeout (int): Connection timeout in seconds. Defaults to 2.
        proxy_info (Optional[ProxyInfo]): Optional proxy configuration.

    Returns:
        Optional[str]: The server version string if available, else None.
    """
    request: dict[str, Any] = {"id": 1, "method": "server.version", "params": ["1.4", "1.4"]}
    response = send_request_to_electrum_server(
        host=host, port=port, request=request, use_ssl=use_ssl, timeout=timeout, proxy_info=proxy_info
    )
    if response is None:
        return None
    if "result" in response:
        logger.debug(f"Server version: {response['result']}")
        return response["result"]
    else:
        logger.debug(f"Failed to retrieve server version for {(host, port, use_ssl)}.")
        return None


if __name__ == "__main__":
    hostname, port = get_host_and_port("electrum.blockstream.info:50002")
    height = get_electrum_blockheight(host=hostname, port=port, use_ssl=True, proxy_info=None)  # type: ignore

    print(height)
