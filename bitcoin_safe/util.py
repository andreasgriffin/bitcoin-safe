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

import json
import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)


def current_project_dir() -> Path:
    # __file__ == /tmp/.mount_Bitcoix7tQIZ/usr/app/bitcoin_safe/util.py
    return Path(__file__).parent


def resource_path(*parts: str):
    # absolute path to python package folder  ("lib")
    pkg_dir = os.path.split(os.path.realpath(__file__))[0]
    return os.path.join(pkg_dir, *parts)


def calculate_ema(
    values: Iterable[Union[float, int]], n: int = 10, weights: List[Union[float, int]] | None = None
) -> float:
    """
    Calculate the Exponential Moving Average (EMA) of a list of values, with an option to apply custom weights to each data point.

    :param values: List of data points (prices, measurements, etc.)
    :param n: The period of the EMA
    :param weights: Optional list of weights to apply to each data point. If not provided, all points are weighted equally.
    :return: The calculated EMA as a float
    """
    values = list(values)

    alpha = 2 / (n + 1)
    adjusted_weights = weights if weights else [1] * len(values)
    adjusted_weights = np.array(adjusted_weights) / np.max(
        adjusted_weights
    )  # Adjust weights to ensure alpha * w <= 1

    ema = values[0]  # Initialize EMA with the first data point
    for weight, value in zip(adjusted_weights, values):
        weighted_alpha = min(1, alpha * weight)
        ema = value * weighted_alpha + (ema * (1 - weighted_alpha))
    return ema


def monotone_increasing_timestamps(
    heights_timestamps: List[Tuple[int, datetime]], default_block_time: timedelta = timedelta(minutes=1)
) -> List[datetime]:
    """
    Given a monotone‐increasing list of (height, timestamp) pairs where
    timestamp is a datetime, returns a list of datetimes whose values
    never decrease. Whenever an input timestamp would go backwards,
    bumps it to last_timestamp + default_block_time * height_difference.

    Args:
        heights_timestamps: List of (block_height, timestamp) with strictly
            increasing block_height and timestamp as datetime.
        default_block_time: Fallback timedelta per block height difference.

    Returns:
        List[datetime]: corrected, non‐decreasing timestamps.
    """
    if not heights_timestamps:
        return []

    result: List[datetime] = []

    # Initialize with first entry
    last_height, last_ts = heights_timestamps[0]
    result.append(last_ts)

    # Process the rest
    for height, ts in heights_timestamps[1:]:
        # how many blocks since last
        height_diff = height - last_height

        if ts >= last_ts:
            fixed_ts = ts
        else:
            fixed_ts = last_ts + default_block_time * height_diff

        result.append(fixed_ts)
        last_height, last_ts = height, fixed_ts

    return result


def list_of_dict_to_jsonline_list(list_of_dict: list[Dict]):
    return [json.dumps(d) for d in list_of_dict]


def list_of_dict_to_jsonlines(list_of_dict: list[Dict]):
    return "\n".join(list_of_dict_to_jsonline_list(list_of_dict))


def clean_lines(lines: List[str]) -> List[str]:
    return [line.strip() for line in lines if line.strip()]


def jsonlines_to_list_of_dict(jsonlines: str) -> list[Dict]:
    return [json.loads(line) for line in clean_lines(jsonlines.splitlines())]


# Custom instance cache decorator
def instance_lru_cache(always_keep=False):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            is_method_in_cache = func in self._instance_cache
            if not is_method_in_cache:
                self._instance_cache[func] = lru_cache(maxsize=None)(func.__get__(self))

                if always_keep:
                    self._cached_instance_methods_always_keep.append(self._instance_cache[func])
                else:
                    self._cached_instance_methods.append(self._instance_cache[func])

            result = self._instance_cache[func](*args, **kwargs)
            if not is_method_in_cache:
                logger.debug(
                    f"filled cache {func} with {len(result) if isinstance(result, (list, dict, tuple, set)) else type(result)}"
                )
            return result

        return wrapper

    return decorator


class CacheManager:
    def __init__(self) -> None:
        self._instance_cache: Dict[Callable, Any] = {}
        self._cached_instance_methods: List[Any] = []
        self._cached_instance_methods_always_keep: List[Any] = []

    def clear_instance_cache(self, clear_always_keep=False):
        logger.debug(f"clear_instance_cache {self.__class__.__name__}")
        for cached_method in self._cached_instance_methods:
            cached_method.cache_clear()
        if clear_always_keep:
            for cached_method in self._cached_instance_methods_always_keep:
                cached_method.cache_clear()

    def clear_method(self, method):
        for f, wrapped in self._instance_cache.items():
            if f.__name__ == method.__name__:
                wrapped.cache_clear()
