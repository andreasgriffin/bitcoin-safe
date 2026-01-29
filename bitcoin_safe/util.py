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
import math
import os
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from functools import cache, lru_cache, wraps
from pathlib import Path
from types import TracebackType
from typing import (
    Any,
    Concatenate,
    Literal,
    ParamSpec,
    Protocol,
    TypeVar,
)

import numpy as np
from packaging.version import Version

OptExcInfo = tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
SATOSHIS_PER_BTC = 100_000_000

logger = logging.getLogger(__name__)


@cache
def fast_version(s: str) -> Version:
    """Fast version."""
    return Version(s)


def current_project_dir() -> Path:
    # __file__ == /tmp/.mount_Bitcoix7tQIZ/usr/app/bitcoin_safe/util.py
    """Current project dir."""
    return Path(__file__).parent


def resource_path(*parts: str):
    # absolute path to python package folder  ("lib")
    """Resource path."""
    pkg_dir = os.path.split(os.path.realpath(__file__))[0]
    return os.path.join(pkg_dir, *parts)


def calculate_ema(
    values: Iterable[float | int], n: int = 10, weights: list[float | int] | None = None
) -> float:
    """Calculate the Exponential Moving Average (EMA) of a list of values, with an
    option to apply custom weights to each data point.

    :param values: List of data points (prices, measurements, etc.)
    :param n: The period of the EMA
    :param weights: Optional list of weights to apply to each data point. If not provided, all points are
        weighted equally.
    :return: The calculated EMA as a float
    """
    values = list(values)

    alpha = 2 / (n + 1)
    adjusted_weights = weights if weights else [1] * len(values)
    adjusted_weights = np.array(adjusted_weights)
    # Normalize weights while guarding against division by zero
    max_weight = np.max(adjusted_weights)
    if max_weight == 0:
        adjusted_weights = np.ones_like(adjusted_weights)
    else:
        adjusted_weights = adjusted_weights / max_weight

    ema = values[0]  # Initialize EMA with the first data point
    for weight, value in zip(adjusted_weights, values, strict=False):
        weighted_alpha = min(1, alpha * weight)
        ema = value * weighted_alpha + (ema * (1 - weighted_alpha))
    return ema


def monotone_increasing_timestamps(
    heights_timestamps: list[tuple[int, datetime]], default_block_time: timedelta = timedelta(minutes=1)
) -> list[datetime]:
    """Given a monotone‐increasing list of (height, timestamp) pairs where timestamp is
    a datetime, returns a list of datetimes whose values.

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

    result: list[datetime] = []

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


def list_of_dict_to_jsonline_list(list_of_dict: list[dict]):
    """List of dict to jsonline list."""
    return [json.dumps(d) for d in list_of_dict]


def list_of_dict_to_jsonlines(list_of_dict: list[dict]):
    """List of dict to jsonlines."""
    return "\n".join(list_of_dict_to_jsonline_list(list_of_dict))


def clean_lines(lines: list[str]) -> list[str]:
    """Clean lines."""
    return [line.strip() for line in lines if line.strip()]


def jsonlines_to_list_of_dict(jsonlines: str) -> list[dict]:
    """Jsonlines to list of dict."""
    return [json.loads(line) for line in clean_lines(jsonlines.splitlines())]


P = ParamSpec("P")
R = TypeVar("R")


class _CacheHost(Protocol):
    _instance_cache: dict[Callable[..., Any], Callable[..., Any]]
    _cached_instance_methods_always_keep: list[Callable[..., Any]]
    _cached_instance_methods: list[Callable[..., Any]]


T = TypeVar("T", bound=_CacheHost)


def instance_lru_cache(
    always_keep: bool = False,
) -> Callable[[Callable[Concatenate[T, P], R]], Callable[Concatenate[T, P], R]]:
    """Instance lru cache."""

    def decorator(func: Callable[Concatenate[T, P], R]) -> Callable[Concatenate[T, P], R]:
        @wraps(func)
        def wrapper(self: T, *args: P.args, **kwargs: P.kwargs) -> R:
            """Wrapper."""
            cache = self._instance_cache
            is_method_in_cache = func in cache
            if not is_method_in_cache:
                # __get__ typing is tricky; result is a bound function (*P)->R.
                cached = lru_cache(maxsize=None)(func.__get__(self))  # type: ignore[misc]
                cache[func] = cached
                (
                    self._cached_instance_methods_always_keep
                    if always_keep
                    else self._cached_instance_methods
                ).append(cached)
            result: R = cache[func](*args, **kwargs)
            return result

        return wrapper

    return decorator


class CacheManager:
    def __init__(self) -> None:
        """Initialize instance."""
        super().__init__()
        self._instance_cache: dict[Callable, Any] = {}
        self._cached_instance_methods: list[Any] = []
        self._cached_instance_methods_always_keep: list[Any] = []

    def clear_instance_cache(self, clear_always_keep=False):
        """Clear instance cache."""
        logger.debug(f"clear_instance_cache {self.__class__.__name__}")
        for cached_method in self._cached_instance_methods:
            cached_method.cache_clear()
        if clear_always_keep:
            for cached_method in self._cached_instance_methods_always_keep:
                cached_method.cache_clear()

    def clear_method(self, method):
        """Clear method."""
        for f, wrapped in self._instance_cache.items():
            if f.__name__ == method.__name__:
                wrapped.cache_clear()


def required_precision(min_value: float, max_value: float, min_prec: int = 0, max_prec: int = 10) -> int:
    """Required precision."""
    diff = abs(max_value - min_value)
    if diff == 0:
        return min_prec
    # how many places until the difference shows up as ≥ 1 in the last digit
    d = math.ceil(-math.log10(diff))
    # clamp to sensible bounds
    return max(min_prec, min(d, max_prec))


def filename_clean(id: str, file_extension: str = ".wallet", replace_spaces_by=None) -> str:
    """Filename clean."""
    import os
    import string

    def create_valid_filename(filename) -> str:
        """Create valid filename."""
        basename = os.path.basename(filename)
        if replace_spaces_by is not None:
            basename = basename.replace(" ", replace_spaces_by)
        valid_chars = f"-_.() {string.ascii_letters}{string.digits}"
        return "".join(c for c in basename if c in valid_chars) + file_extension

    return create_valid_filename(id)


def short_address(address: str, prefix: int = 6, suffix: int = 4) -> str:
    """Return an abbreviated representation of an address for logging."""

    if len(address) <= prefix + suffix:
        return address
    return f"{address[:prefix]}...{address[-suffix:]}"


def default_timeout(proxies: Any, timeout: float | Literal["default"] = "default") -> float:
    if timeout == "default":
        return 10 if proxies else 2
    return timeout
