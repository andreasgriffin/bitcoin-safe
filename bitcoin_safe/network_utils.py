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

import json
import logging
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import bdkpython as bdk
import socks

from bitcoin_safe.pythonbdk_types import (
    IpAddress,  # Requires PySocks or similar package.
)
from bitcoin_safe.util import default_timeout

logger = logging.getLogger(__name__)


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
    ssock = None
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
        if ssock is not None:
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
