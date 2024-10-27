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


import enum
import logging
from math import ceil
from typing import Any, Dict, List, Optional, Tuple

from bitcoin_safe.gui.qt.util import custom_exception_handler
from bitcoin_safe.network_config import NetworkConfig
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.threading_manager import TaskThread, ThreadingManager

from .config import MIN_RELAY_FEE

logger = logging.getLogger(__name__)

import datetime

import numpy as np
import requests
from PyQt6.QtCore import QObject, pyqtSignal

feeLevels = [
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
chartColors = [
    "#D81B60",
    "#8E24AA",
    "#5E35B1",
    "#3949AB",
    "#1E88E5",
    "#039BE5",
    "#00ACC1",
    "#00897B",
    "#43A047",
    "#7CB342",
    "#C0CA33",
    "#FDD835",
    "#FFB300",
    "#FB8C00",
    "#F4511E",
    "#6D4C41",
    "#757575",
    "#546E7A",
    "#b71c1c",
    "#880E4F",
    "#4A148C",
    "#311B92",
    "#1A237E",
    "#0D47A1",
    "#01579B",
    "#006064",
    "#004D40",
    "#1B5E20",
    "#33691E",
    "#827717",
    "#F57F17",
    "#FF6F00",
    "#E65100",
    "#BF360C",
    "#3E2723",
    "#212121",
    "#263238",
    "#801313",
]


mempoolFeeColors = [
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


def fee_to_color(fee, colors=chartColors) -> str:
    if fee == 0:
        # for 0 just use the same color as 1
        fee = 1
    indizes = np.where(np.array(feeLevels) <= fee)[0]
    if len(indizes) == 0:
        return "#000000"
    return colors[indizes[-1]]


def fetch_from_url(url: str, is_json=True) -> Optional[Any]:
    logger.debug(f"fetch_json_from_url requests.get({url}, timeout=10)")

    try:
        response = requests.get(url, timeout=10)
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Parse the JSON response
            data = response.json() if is_json else response.content
            return data
        else:
            # If the request was unsuccessful, print the status code
            logger.error(f"Request failed with status code: {response.status_code}")
            return None
    except:
        logger.error(f"fetch_json_from_url {url} failed")
        return None


def threaded_fetch(url: str, on_success, is_json=True) -> TaskThread:
    def do() -> Any:
        return fetch_from_url(url, is_json=is_json)

    def on_error(packed_error_info) -> None:
        custom_exception_handler(*packed_error_info)

    def on_done(data) -> None:
        pass

    return TaskThread().add_and_start(do, on_success, on_done, on_error)


class TxPrio(enum.Enum):
    low = enum.auto()
    medium = enum.auto()
    high = enum.auto()


class MempoolData(ThreadingManager, QObject):
    signal_data_updated = pyqtSignal()

    def __init__(
        self,
        network_config: NetworkConfig,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager,
    ) -> None:
        super().__init__(threading_parent=threading_parent)
        self.signals_min = signals_min

        self.network_config = network_config
        self.mempool_blocks = self._empty_mempool_blocks()
        self.recommended: Dict[str, int] = {
            "fastestFee": MIN_RELAY_FEE,
            "halfHourFee": MIN_RELAY_FEE,
            "hourFee": MIN_RELAY_FEE,
            "economyFee": MIN_RELAY_FEE,
            "minimumFee": MIN_RELAY_FEE,
        }
        self.time_of_data = datetime.datetime.fromtimestamp(0)
        self.mempool_dict: Dict[str, Any] = {
            "count": 0,
            "vsize": 0,
            "total_fee": 0,
            "fee_histogram": [],
        }
        logger.debug(f"initialized {self}")

    def _empty_mempool_blocks(self) -> List[Dict[str, Any]]:
        return [
            {
                "blockSize": 1,
                "blockVSize": 1,
                "nTx": 0,
                "totalFees": MIN_RELAY_FEE,
                "medianFee": MIN_RELAY_FEE,
                "feeRange": [MIN_RELAY_FEE, MIN_RELAY_FEE],
            }
        ]

    def fee_rates_min_max(self, block_index: int) -> Tuple[int, float]:
        block_index = min(block_index, len(self.mempool_blocks) - 1)
        fee_rates = self.mempool_blocks[block_index]["feeRange"]
        return min(fee_rates), max(fee_rates)

    def median_block_fee_rate(self, block_index: int) -> float:
        block_index = min(block_index, len(self.mempool_blocks) - 1)
        return self.mempool_blocks[block_index]["medianFee"]

    def num_mempool_blocks(self) -> int:
        vBytes_per_block = 1e6
        return ceil(self.mempool_dict["vsize"] / vBytes_per_block)

    def get_prio_fee_rates(self) -> Dict[TxPrio, float]:
        return {
            prio: self.recommended[key]
            for prio, key in zip(
                [TxPrio.high, TxPrio.medium, TxPrio.low],
                ["fastestFee", "halfHourFee", "hourFee"],
            )
        }

    def get_min_relay_fee_rate(self) -> float:
        return self.recommended["minimumFee"]

    def max_reasonable_fee_rate(self) -> float:
        "Average fee of the 0 projected block"
        average_fee_rate = sum(self.fee_rates_min_max(0)) / 2

        # allow for up to 20% more then the average_fee_rate
        slack = 0.2

        return average_fee_rate * (1 + slack)

    def set_data_from_mempoolspace(self, force=False) -> None:
        if not force and datetime.datetime.now() - self.time_of_data < datetime.timedelta(minutes=9):
            logger.debug(
                f"Do not fetch data from {self.network_config.mempool_url} because data is only {datetime.datetime.now()- self.time_of_data  } old."
            )
            return None

        self.time_of_data = datetime.datetime.now()

        def on_mempool_blocks(mempool_blocks) -> None:
            if mempool_blocks:
                self.mempool_blocks = mempool_blocks
                logger.info(f"Updated mempool_blocks {mempool_blocks}")

        self.append_thread(
            threaded_fetch(
                f"{self.network_config.mempool_url}api/v1/fees/mempool-blocks",
                on_mempool_blocks,
            )
        )
        logger.debug(f"started on_mempool_blocks")

        def on_recommended(recommended) -> None:
            if recommended:
                self.recommended = recommended
                logger.info(f"Updated recommended {recommended}")

        self.append_thread(
            threaded_fetch(
                f"{self.network_config.mempool_url}api/v1/fees/recommended",
                on_recommended,
            )
        )
        logger.debug(f"started on_recommended")

        def on_mempool_dict(mempool_dict) -> None:
            if mempool_dict:
                self.mempool_dict = mempool_dict
                logger.info(f"Updated mempool_dict {mempool_dict}")
            self.signal_data_updated.emit()

        self.append_thread(
            threaded_fetch(
                f"{self.network_config.mempool_url}api/mempool",
                on_mempool_dict,
            )
        )
        logger.debug(f"started on_mempool_dict")

    def fetch_block_tip_height(self) -> int:
        response = fetch_from_url(f"{self.network_config.mempool_url}api/blocks/tip/height")
        return response if response else 0

    def fee_rate_to_projected_block_index(self, fee_rate: float) -> int:
        available_blocks = len(self.mempool_blocks)
        for i in range(available_blocks):
            v_min, v_max = self.fee_rates_min_max(i)
            if fee_rate >= v_min:
                return i
        return available_blocks
