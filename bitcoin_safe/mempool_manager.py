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

import asyncio
import datetime
import enum
import logging
from dataclasses import dataclass
from math import ceil
from typing import Any, Literal, cast

import aiohttp
import numpy as np
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.network_config import NetworkConfig
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.util import default_timeout

from .network_utils import ProxyInfo

logger = logging.getLogger(__name__)

feeLevels = [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    8,
    10,
    12,
    15,
    20,
    30,
    40,
    50,
    60,
    70,
    80,
    90,
    100,
    125,
    150,
    175,
    200,
    250,
    300,
    350,
    400,
    500,
    600,
    700,
    800,
    900,
    1000,
    1200,
    1400,
    1600,
    1800,
    2000,
]

mempoolFeeColors = [
    "#007d3d",
    "#557d00",
    "#5d7d01",
    "#637d02",
    "#6d7d04",
    "#757d05",
    "#7d7d06",
    "#867d08",
    "#8c7d09",
    "#957d0b",
    "#9b7d0c",
    "#a67d0e",
    "#aa7d0f",
    "#b27d10",
    "#bb7d11",
    "#bf7d12",
    "#bf7815",
    "#bf7319",
    "#be6c1e",
    "#be6820",
    "#bd6125",
    "#bd5c28",
    "#bc552d",
    "#bc4f30",
    "#bc4a34",
    "#bb4339",
    "#bb3d3c",
    "#bb373f",
    "#ba3243",
    "#b92b48",
    "#b9254b",
    "#b8214d",
    "#b71d4f",
    "#b61951",
    "#b41453",
    "#b30e55",
    "#b10857",
    "#b00259",
    "#ae005b",
]


def fee_to_color(fee, colors=mempoolFeeColors) -> str:
    """Fee to color."""
    if fee == 0:
        # for 0 just use the same color as 1
        fee = 1
    indizes = np.where(np.array(feeLevels) <= fee)[0]
    if len(indizes) == 0:
        return "#000000"
    return colors[indizes[-1]]


async def fetch_from_url(
    url: str,
    proxies: dict[str, str] | None = None,
    is_json: bool = True,
    timeout: float | Literal["default"] = "default",
) -> Any | None:
    """Fetch from url."""
    logger.debug(f"fetch_from_url session.get({url}, timeout={timeout})")

    # If you have an HTTP/HTTPS proxy, aiohttp wants e.g. proxy="http://user:pass@host:port"
    conn_kwargs: dict[str, Any] = {"timeout": aiohttp.ClientTimeout(total=default_timeout(proxies, timeout))}
    if proxies:
        # prefer HTTP proxy but fall back to HTTPS
        proxy_url = proxies.get("http") or proxies.get("https")
        if proxy_url:
            conn_kwargs["proxy"] = proxy_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, **conn_kwargs) as resp:
                if resp.status == 200:
                    if is_json:
                        return await resp.json()
                    else:
                        return await resp.read()
                else:
                    logger.error(f"Request failed with status code: {resp.status}")
                    return None

    except asyncio.TimeoutError:
        logger.error(f"fetch_from_url {url} timed out")
        return None
    except Exception as e:
        logger.debug(str(e))
        logger.error(f"fetch_from_url {url} failed")
        return None


class TxPrio(enum.Enum):
    low = enum.auto()
    medium = enum.auto()
    high = enum.auto()


class BlockType(enum.Enum):
    mempool = enum.auto()
    confirmed = enum.auto()


@dataclass
class BlockInfo:
    block_type: BlockType
    min_fee: float = MIN_RELAY_FEE
    max_fee: float = MIN_RELAY_FEE
    median_fee: float = MIN_RELAY_FEE


class MempoolManager(QObject):
    signal_data_updated = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(
        self,
        network_config: NetworkConfig,
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread | None,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signals_min = signals_min
        self.loop_in_thread = loop_in_thread or LoopInThread()
        self._owns_loop_in_thread = loop_in_thread is None

        self.network_config = network_config
        self.data = network_config.mempool_data
        self.time_of_data = datetime.datetime.fromtimestamp(0)
        logger.debug(f"initialized {self.__class__.__name__}")

    def block_info(self, block_index: int, decimal_precision=1) -> BlockInfo:
        """Block info."""
        min_fee, max_fee = self.fee_rates_min_max(block_index)
        median_fee = self.median_block_fee_rate(block_index, decimal_precision=decimal_precision)
        return BlockInfo(
            max_fee=max_fee, min_fee=min_fee, median_fee=median_fee, block_type=BlockType.mempool
        )

    def fee_rates_min_max(self, block_index: int) -> tuple[int, float]:
        """Fee rates min max."""
        block_index = min(block_index, len(self.data.mempool_blocks) - 1)
        fee_rates = self.data.mempool_blocks[block_index]["feeRange"]
        return min(fee_rates), max(fee_rates)

    def median_block_fee_rate(self, block_index: int, decimal_precision=1) -> float:
        """Median block fee rate."""
        block_index = min(block_index, len(self.data.mempool_blocks) - 1)
        # mempool returns media fee of 0, even though the minimum feein feeRange is 1
        median = round(self.data.mempool_blocks[block_index]["medianFee"], decimal_precision)
        min_in_feerange = round(min(self.data.mempool_blocks[block_index]["feeRange"]), decimal_precision)
        max_in_feerange = round(max(self.data.mempool_blocks[block_index]["feeRange"]), decimal_precision)
        if median < min_in_feerange:
            median = min_in_feerange
        if median > max_in_feerange:
            median = max_in_feerange
        return median

    def num_mempool_blocks(self) -> int:
        """Num mempool blocks."""
        vBytes_per_block = 1e6
        return ceil(self.data.mempool_dict["vsize"] / vBytes_per_block)

    def get_prio_fee_rates(self) -> dict[TxPrio, float]:
        """Get prio fee rates."""
        return {
            prio: self.data.recommended[key]
            for prio, key in zip(
                [TxPrio.high, TxPrio.medium, TxPrio.low],
                ["fastestFee", "halfHourFee", "hourFee"],
                strict=False,
            )
        }

    def get_min_relay_fee_rate(self) -> float:
        """Get min relay fee rate."""
        return self.data.recommended["minimumFee"]

    def max_reasonable_fee_rate(self) -> float:
        "Average fee of the 0 projected block"
        average_fee_rate = sum(self.fee_rates_min_max(0)) / 2

        # allow for up to 20% more then the average_fee_rate
        slack = 0.2

        return average_fee_rate * (1 + slack)

    def close(self):
        """Close."""
        if self._owns_loop_in_thread:
            self.loop_in_thread.stop()
        logger.debug(f"{self.__class__.__name__} close")

    def set_data_from_mempoolspace(self, force=False) -> None:
        """Set data from mempoolspace."""
        if not force and datetime.datetime.now() - self.time_of_data < datetime.timedelta(minutes=9):
            logger.debug(
                f"Do not fetch data from {self.network_config.mempool_url} "
                f"because data is only {datetime.datetime.now() - self.time_of_data} old."
            )
            return None

        self._task_set_data = self.loop_in_thread.run_background(
            self._set_data_from_mempoolspace(), key=f"{id(self)}"
        )

    async def _set_data_from_mempoolspace(self) -> None:
        """Set data from mempoolspace."""
        self.time_of_data = datetime.datetime.now()

        urls = [
            f"{self.network_config.mempool_url}api/v1/fees/mempool-blocks",
            f"{self.network_config.mempool_url}api/v1/fees/recommended",
            f"{self.network_config.mempool_url}api/mempool",
        ]

        coroutines = [
            fetch_from_url(
                url,
                proxies=(
                    ProxyInfo.parse(self.network_config.proxy_url).get_requests_proxy_dict()
                    if self.network_config.proxy_url
                    else None
                ),
            )
            for url in urls
        ]
        results = await self.loop_in_thread.run_parallel(coroutines)
        if not results:
            return
        mempool_blocks, recommended, mempool_dict = results

        if mempool_blocks:
            self.data.mempool_blocks = mempool_blocks
        if recommended:
            self.data.recommended = recommended
        if mempool_dict:
            self.data.mempool_dict = mempool_dict
            logger.info(f"Updated mempool_dict {mempool_dict}")

            self.signal_data_updated.emit()

    def _loop_is_running(self) -> bool:
        """Check whether the background asyncio loop is running."""
        loop = self.loop_in_thread._loop
        return loop is not None and loop.is_running()

    def fetch_block_tip_height(self) -> int:
        """Fetch block tip height."""
        if not self._loop_is_running():
            logger.warning("Loop is not running; skipping mempool tip height fetch.")
            return 0
        response = self.loop_in_thread.run_foreground(
            fetch_from_url(
                f"{self.network_config.mempool_url}api/blocks/tip/height",
                proxies=(
                    ProxyInfo.parse(self.network_config.proxy_url).get_requests_proxy_dict()
                    if self.network_config.proxy_url
                    else None
                ),
            )
        )
        return response if response else 0

    def fee_rate_to_projected_block_index(self, fee_rate: float) -> int:
        """Fee rate to projected block index."""
        available_blocks = len(self.data.mempool_blocks)
        for i in range(available_blocks):
            v_min, v_max = self.fee_rates_min_max(i)
            if fee_rate >= v_min:
                return i
        return available_blocks
