import logging

logger = logging.getLogger(__name__)

import requests
import numpy as np
from PySide2.QtCore import QObject, Signal
from .thread_manager import ThreadManager
import datetime


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


def fetch_mempool_histogram():
    logger.info("Fetching mempool data from mempool.space")

    # Send GET request to an API endpoint
    response = requests.get("https://mempool.space/api/mempool")

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Parse the JSON response
        data = response.json()

        # Display the JSON response
        return np.array(data["fee_histogram"])
    else:
        # If the request was unsuccessful, print the status code
        logger.error("Request failed with status code:", response.status_code)


def index_of_sum_until_including(array, limit):
    s = 0
    for i, entry in enumerate(array):
        s += entry
        if s >= limit:
            return i
    return len(array) - 1


def get_min_feerates_of_blocktemplates(data, i):
    block_sive_invbytes = 4e6 / 4  #  4e6 is the max WU of a block
    idx = index_of_sum_until_including(data[:, 1], block_sive_invbytes * (i + 1))
    return data[idx, 0]


def get_cutoff_fee_rate(data, last_block_template=10):
    return get_min_feerates_of_blocktemplates(data, last_block_template)


def fee_to_depth(data, fee):
    indizes = np.where(data[:, 0] >= fee)
    if len(indizes) == 0:
        return 0
    return data[indizes, 1].sum()


def fee_to_blocknumber(data, fee):
    depth = fee_to_depth(data, fee)
    return max(int(np.ceil(depth / 1e6)), 1)


def blocks_to_min_fees(data, blocks):
    block_sive_invbytes = 4e6 / 4  #  4e6 is the max WU of a block
    fees = []
    for i in blocks:
        idx = index_of_sum_until_including(data[:, 1], block_sive_invbytes * (i + 1))
        fees.append(data[idx, 0])
    return fees


def get_block_min_fees(data):
    blocks = [0, 1, 2]
    return np.array(list(zip(blocks, blocks_to_min_fees(data, blocks))))


def get_prio_fees(data):
    blocks = [-0.5, 1, 2]
    return np.array(blocks_to_min_fees(data, blocks))


def fees_of_depths(data, depths):
    fee_borders_indizes = [
        index_of_sum_until_including(data[:, 1], depth) for depth in depths
    ]
    return [data[i, 0] for i in fee_borders_indizes]


def bin_data(bin_edges, data):
    "assumes the data has the structure [[x, y], ...]"
    # Extract x-values from data
    x_values = data[:, 0]

    # Aggregate the y-values based on the binned x-values
    aggregated_data = []
    for i in range(len(bin_edges) - 1):
        x_bin_indices = np.where(
            (x_values >= bin_edges[i]) & (x_values < bin_edges[i + 1])
        )[0]
        y_bin_values = data[x_bin_indices, 1]
        aggregated_data.append([bin_edges[i], y_bin_values.sum()])

    # Convert aggregated_data to NumPy array
    return np.array(aggregated_data)


class MempoolData(QObject):
    signal_data_updated = Signal()

    def __init__(self) -> None:
        super().__init__()

        self.thread_manager = ThreadManager()
        self.current_timestamp = 0
        self.data = np.zeros((1, 2))
        self.time_of_data = datetime.datetime.fromtimestamp(0)

    def set_data_from_file(self, datafile=None):
        self.set_data(np.loadtxt(datafile, delimiter=","))

    def set_data(self, data):
        self.data = data
        self.time_of_data = datetime.datetime.now()
        self.signal_data_updated.emit()

    def set_data_from_mempoolspace(self, force=False):
        def do():
            if datetime.datetime.now() - self.time_of_data < datetime.timedelta(
                minutes=9
            ):
                logger.debug(
                    f"Do not fetch data from mempoolspace because data is only {datetime.datetime.now()- self.time_of_data  } old."
                )
                return None
            return fetch_mempool_histogram()

        def on_finished(data):
            if data is not None:
                self.set_data(data)

        return self.thread_manager.start_in_background_thread(
            do, on_finished=on_finished, name=self.__class__.__name__
        )
