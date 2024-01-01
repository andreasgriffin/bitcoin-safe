import enum
import logging

from bitcoin_safe.gui.qt.util import custom_exception_handler

from .config import MIN_RELAY_FEE, NetworkConfig, UserConfig

logger = logging.getLogger(__name__)

import requests
import numpy as np
from PySide2.QtCore import QObject, Signal
import datetime
import bdkpython as bdk
from .util import NoThread, TaskThread

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


def fee_to_color(fee, colors=chartColors):
    indizes = np.where(np.array(feeLevels) <= fee)[0]
    if len(indizes) == 0:
        return "#000000"
    return colors[indizes[-1]]


def fetch_json_from_url(url):
    logger.info(f"Fetching {url}")

    try:
        response = requests.get(url)
        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Parse the JSON response
            data = response.json()
            return data
        else:
            # If the request was unsuccessful, print the status code
            logger.error(f"Request failed with status code: {response.status_code}")
            return None
    except:
        logger.error(f"Fetching {url} failed")
        return None


def fetch_mempool_blocks(mempool_url: str):
    return fetch_json_from_url(f"{mempool_url}v1/fees/mempool-blocks")


def fetch_mempool_recommended(mempool_url: str):
    return fetch_json_from_url(f"{mempool_url}v1/fees/recommended")


class TxPrio(enum.Enum):
    low = enum.auto()
    medium = enum.auto()
    high = enum.auto()


class MempoolData(QObject):
    signal_data_updated = Signal()

    def __init__(self, config: UserConfig) -> None:
        super().__init__()

        self.config = config
        self.mempool_blocks = [
            {
                "blockSize": 1,
                "blockVSize": 1,
                "nTx": 1,
                "totalFees": MIN_RELAY_FEE,
                "medianFee": MIN_RELAY_FEE,
                "feeRange": [MIN_RELAY_FEE, MIN_RELAY_FEE],
            }
        ]
        self.recommended = {
            "fastestFee": MIN_RELAY_FEE,
            "halfHourFee": MIN_RELAY_FEE,
            "hourFee": MIN_RELAY_FEE,
            "economyFee": MIN_RELAY_FEE,
            "minimumFee": MIN_RELAY_FEE,
        }
        self.time_of_data = datetime.datetime.fromtimestamp(0)

    def fee_min_max(self, block_index):
        block_index = min(block_index, len(self.mempool_blocks) - 1)
        fees = self.mempool_blocks[block_index]["feeRange"]
        return min(fees), max(fees)

    def median_block_fee(self, block_index):
        block_index = min(block_index, len(self.mempool_blocks) - 1)
        return self.mempool_blocks[block_index]["medianFee"]

    def get_prio_fees(self):
        return {
            prio: self.recommended[key]
            for prio, key in zip(
                [TxPrio.high, TxPrio.medium, TxPrio.low],
                ["fastestFee", "halfHourFee", "hourFee"],
            )
        }

    def max_reasonable_fee_rate(self, max_reasonable_fee_rate_fallback=100):
        "Average fee of the 0 projected block"
        if self.mempool_blocks is None:
            return max_reasonable_fee_rate_fallback
        return sum(self.fee_min_max(0)) / 2

    def set_data_from_file(self, datafile=None):
        self.set_data(np.loadtxt(datafile, delimiter=","))

    def set_data(self, mempool_blocks, recommended):
        self.mempool_blocks = mempool_blocks
        self.recommended = recommended
        self.time_of_data = datetime.datetime.now()
        self.signal_data_updated.emit()

    def set_data_from_mempoolspace(self, force=False):
        def do():
            if (
                not force
                and datetime.datetime.now() - self.time_of_data
                < datetime.timedelta(minutes=9)
            ):
                logger.debug(
                    f"Do not fetch data from mempoolspace because data is only {datetime.datetime.now()- self.time_of_data  } old."
                )
                return None
            mempool_blocks = fetch_mempool_blocks(
                self.config.network_config.mempool_url
            )
            recommended = fetch_mempool_recommended(
                self.config.network_config.mempool_url
            )
            return mempool_blocks, recommended

        def on_success(data):
            if data is not None:
                if not all(data):
                    # some is None
                    return
                mempool_blocks, recommended = data
                self.set_data(mempool_blocks, recommended)

        def on_error(packed_error_info):
            custom_exception_handler(*packed_error_info)

        def on_done(data):
            pass

        TaskThread(self).add_and_start(do, on_success, on_done, on_error)

    def fee_rate_to_projected_block_index(self, fee):
        available_blocks = len(self.mempool_blocks)
        for i in range(available_blocks):
            v_min, v_max = self.fee_min_max(i)
            if fee > v_min:
                return i
        return available_blocks
