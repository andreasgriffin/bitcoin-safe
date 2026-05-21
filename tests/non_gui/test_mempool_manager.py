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
import json
from pathlib import Path
from urllib.parse import urljoin

import bdkpython as bdk

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.mempool_manager import MempoolManager, TxPrio
from bitcoin_safe.network_config import NetworkConfig, get_mempool_url
from bitcoin_safe.signals import SignalsMin


class FakeLoopInThread:
    def __init__(self) -> None:
        self._loop = None

    async def run_parallel(self, coros):
        return [await coro for coro in coros]


def test_urljoin_handles_slashless_network_paths() -> None:
    assert (
        urljoin("https://mempool.space/signet/", "api/v1/fees/recommended")
        == "https://mempool.space/signet/api/v1/fees/recommended"
    )
    assert (
        urljoin("https://mempool.space/testnet4/", "api/v1/fees/recommended")
        == "https://mempool.space/testnet4/api/v1/fees/recommended"
    )


def test_mempool_manager_ignores_html_fee_payload(monkeypatch) -> None:
    manager = MempoolManager(
        network_config=NetworkConfig(network=bdk.Network.SIGNET),
        signals_min=SignalsMin(),
        loop_in_thread=FakeLoopInThread(),
    )
    manager.network_config.mempool_url = "https://mempool.space/signet"
    original_recommended = dict(manager.data.recommended)

    fetched_urls: list[str] = []

    async def fake_fetch(url: str, proxies=None, timeout="default"):
        del proxies, timeout
        fetched_urls.append(url)
        payloads = {
            "https://mempool.space/signet/api/v1/fees/mempool-blocks": [
                {
                    "blockSize": 975_000,
                    "blockVSize": 975_000,
                    "nTx": 1_800,
                    "totalFees": 1_200_000,
                    "medianFee": 12.0,
                    "feeRange": [12.0, 20.0],
                }
            ],
            "https://mempool.space/signet/api/v1/fees/recommended": "<html>not json</html>",
            "https://mempool.space/signet/api/mempool": {
                "count": 4_500,
                "vsize": 2_825_000,
                "total_fee": 2_500_000,
                "fee_histogram": [],
            },
        }
        return payloads[url]

    monkeypatch.setattr("bitcoin_safe.mempool_manager.fetch_from_url", fake_fetch)

    asyncio.run(manager._set_data_from_mempoolspace())

    assert fetched_urls == [
        "https://mempool.space/signet/api/v1/fees/mempool-blocks",
        "https://mempool.space/signet/api/v1/fees/recommended",
        "https://mempool.space/signet/api/mempool",
    ]
    assert manager.data.recommended == original_recommended
    assert manager.get_prio_fee_rates()[TxPrio.low] == float(MIN_RELAY_FEE)
    assert manager.data.mempool_blocks[0]["medianFee"] == 12.0
    assert manager.data.mempool_dict["count"] == 4_500


def test_mempool_defaults_are_normalized_and_legacy_slashless_values_still_work() -> None:
    assert get_mempool_url(bdk.Network.SIGNET)["default"] == "https://mempool.space/signet/"
    assert get_mempool_url(bdk.Network.TESTNET4)["default"] == "https://mempool.space/testnet4/"

    data = json.loads(Path("tests/data/config_0.1.6_rpc.conf").read_text(encoding="utf-8"))
    legacy_signet_url = data["network_configs"]["configs"]["SIGNET"]["mempool_url"]
    assert legacy_signet_url == "https://mempool.space/signet"
    assert (
        urljoin(f"{legacy_signet_url.rstrip('/')}/", "api/v1/fees/recommended")
        == "https://mempool.space/signet/api/v1/fees/recommended"
    )
