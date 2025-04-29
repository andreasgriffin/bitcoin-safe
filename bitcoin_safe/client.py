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


import logging
from typing import Union

import bdkpython as bdk
import socks  # Requires PySocks or similar package.

from bitcoin_safe.network_config import ElectrumConfig
from bitcoin_safe.network_utils import (
    ProxyInfo,
    clean_electrum_url,
    get_electrum_blockheight,
    get_host_and_port,
)

logger = logging.getLogger(__name__)


class Client:
    def __init__(
        self,
        client: Union[bdk.ElectrumClient, bdk.EsploraClient],
        electrum_config: ElectrumConfig | None,
        proxy_info: ProxyInfo | None,
    ) -> None:
        self.client = client
        self.proxy_info = proxy_info
        self.electrum_config = electrum_config

    @classmethod
    def from_electrum(cls, url: str, use_ssl: bool, proxy_info: ProxyInfo | None) -> "Client":
        url = clean_electrum_url(url, use_ssl)
        client = bdk.ElectrumClient(
            url=url,
            socks5=(proxy_info.get_url_no_h() if proxy_info else None),
        )
        return cls(
            client=client, electrum_config=ElectrumConfig(url=url, use_ssl=use_ssl), proxy_info=proxy_info
        )

    @classmethod
    def from_esplora(cls, url: str, proxy_info: ProxyInfo | None) -> "Client":
        client = bdk.EsploraClient(url=url, proxy=(proxy_info.get_url_no_h() if proxy_info else None))
        return cls(client=client, electrum_config=None, proxy_info=proxy_info)

    def broadcast(self, tx: bdk.Transaction):
        if isinstance(self.client, bdk.ElectrumClient):
            return self.client.transaction_broadcast(tx)
        elif isinstance(self.client, bdk.EsploraClient):
            return self.client.broadcast(tx)
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")

    def get_height(self) -> int:
        if isinstance(self.client, bdk.ElectrumClient):
            #   ElectrumClient doesnt have  get_height
            # https://github.com/bitcoindevkit/bdk-ffi/issues/547#issuecomment-2471384856
            assert self.electrum_config, "self.electrum_config not set"
            hostname, port = get_host_and_port(self.electrum_config.url)
            assert hostname is not None, f"Could not extract the hostname from {self.electrum_config.url}"
            assert port is not None, f"Could not extract the port from {self.electrum_config.url}"
            height = get_electrum_blockheight(
                host=hostname, port=port, use_ssl=self.electrum_config.use_ssl, proxy_info=self.proxy_info
            )
            assert height is not None, "Server did not return block height"
            return height
        elif isinstance(self.client, bdk.EsploraClient):
            return self.client.get_height()
        else:
            raise NotImplementedError(f"Client is of type {type(self.client)}")

    def full_scan(self, full_request: bdk.FullScanRequest, stop_gap: int) -> bdk.Update:
        if isinstance(self.client, bdk.ElectrumClient):
            return self.client.full_scan(
                request=full_request, stop_gap=stop_gap, batch_size=100, fetch_prev_txouts=True
            )
        elif isinstance(self.client, bdk.EsploraClient):
            return self.client.full_scan(request=full_request, stop_gap=stop_gap, parallel_requests=2)
        else:
            raise ValueError("Unknown blockchain client type.")
