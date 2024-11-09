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

# Original Version from:
# Electrum - lightweight Bitcoin client
# Copyright (C) 2011 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
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
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from bitcoin_safe.gui.qt.data_tab_widget import T2, T

logger = logging.getLogger(__name__)
import builtins
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Set,
    SupportsBytes,
    SupportsIndex,
    Tuple,
    Union,
)

from PyQt6.QtCore import QByteArray, QLocale

from .i18n import translate

TX_HEIGHT_FUTURE = -3
TX_HEIGHT_LOCAL = -2
TX_HEIGHT_UNCONF_PARENT = -1
TX_HEIGHT_UNCONFIRMED = 0

TX_TIMESTAMP_INF = 999_999_999_999
TX_HEIGHT_INF = 10**9

TX_STATUS = [
    translate("util", "Unconfirmed"),
    translate("util", "Unconfirmed parent"),
    translate("util", "Not Verified"),
    translate("util", "Local"),
]


import bdkpython as bdk


def is_int(a: Any) -> bool:
    try:
        int(a)
    except:
        return False
    return True


def path_to_rel_home_path(path: Union[Path, str]) -> Path:
    try:

        return Path(path).relative_to(Path.home())
    except:
        return Path(path)


def rel_home_path_to_abs_path(rel_home_path: Union[Path, str]) -> Path:
    return Path.home() / rel_home_path


def serialized_to_hex(serialized: Union[Iterable[SupportsIndex], SupportsIndex, SupportsBytes]):
    return bytes(serialized).hex()


def hex_to_serialized(hex_string: str):
    return bytes.fromhex(hex_string)


def tx_of_psbt_to_hex(psbt: bdk.PartiallySignedTransaction):
    return serialized_to_hex(psbt.extract_tx().serialize())


def tx_to_hex(tx: bdk.Transaction):
    return serialized_to_hex(tx.serialize())


def call_call_functions(functions: List[Callable]):
    for f in functions:
        f()


def compare_dictionaries(dict1: Dict, dict2: Dict):
    # Get unique keys from both dictionaries
    unique_keys = set(dict1.keys()) ^ set(dict2.keys())

    # Get keys with different values
    differing_values = {k for k in dict1 if k in dict2 and dict1[k] != dict2[k]}

    # Combine unique keys and differing values
    keys_to_include = unique_keys | differing_values

    # Create a new dictionary with only the differing entries
    result = {k: dict1.get(k, dict2.get(k)) for k in keys_to_include}

    return result


def inv_dict(d: Dict):
    return {v: k for k, v in d.items()}


def all_subclasses(cls) -> Set:
    """Return all (transitive) subclasses of cls."""
    res = set(cls.__subclasses__())
    for sub in res.copy():
        res |= all_subclasses(sub)
    return res


import hashlib

import bdkpython as bdk


def replace_non_alphanumeric(string: str):
    return re.sub(r"\W+", "_", string)


def hash_string(text: str):
    return hashlib.sha256(text.encode()).hexdigest()


def is_iterable(obj):
    return hasattr(obj, "__iter__") or hasattr(obj, "__getitem__")


from functools import lru_cache, wraps

cached_always_keep_functions = []
cached_functions = []


def register_cache(always_keep=False):
    def wrapper(func):
        # Decorate the function with lru_cache
        cached_func = lru_cache(maxsize=None)(func)

        # Logging
        logger.debug(f"register_cache always_keep {always_keep}")

        # Store the decorated function
        if always_keep:
            cached_always_keep_functions.append(cached_func)
        else:
            cached_functions.append(cached_func)

        return cached_func

    return wrapper


# Function to clear all caches
def clear_cache(clear_always_keep=False):
    logger.debug(
        f"clear_cache clear_always_keep {clear_always_keep}  of {len(cached_functions), len(cached_always_keep_functions)} functions"
    )
    for func in cached_functions:
        func.cache_clear()
    if clear_always_keep:
        for func in cached_always_keep_functions:
            func.cache_clear()


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


def time_logger(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        duration = end_time - start_time

        message = f"Function {func.__qualname__} needed {duration:.3f}s"
        if duration < 5e-2:
            logger.debug(message)
        else:
            logger.info(message)

        return result

    return wrapper


def threadtable(f, arglist, max_workers=20):
    with ThreadPoolExecutor(max_workers=int(max_workers)) as executor:
        logger.debug("Starting {} threads {}({})".format(max_workers, str(f), str(arglist)))
        res = []
        for arg in arglist:
            res.append(executor.submit(f, arg))
    return [r.result() for r in res]


@time_logger
def threadtable_batched(f: Callable[[T], T2], txs: List[T], number_chunks=8) -> List[T2]:
    chunks = np.array_split(np.array(txs), number_chunks)

    def batched_f(txs):
        return [f(tx) for tx in txs]

    result = threadtable(batched_f, chunks, max_workers=number_chunks)
    return sum(result, [])


def clean_dict(d: Dict):
    return {k: v for k, v in d.items() if v}


def clean_list(l: Iterable[T | None]) -> List[T]:
    return [v for v in l if v]


def list_of_dict_to_jsonline_list(list_of_dict: list[Dict]):
    return [json.dumps(d) for d in list_of_dict]


def list_of_dict_to_jsonlines(list_of_dict: list[Dict]):
    return "\n".join(list_of_dict_to_jsonline_list(list_of_dict))


def clean_lines(lines: List[str]) -> List[str]:
    return [line.strip() for line in lines if line.strip()]


def jsonlines_to_list_of_dict(jsonlines: str) -> list[Dict]:
    return [json.loads(line) for line in clean_lines(jsonlines.splitlines())]


class NotEnoughFunds(Exception):
    def __str__(self):
        return translate("util", "Insufficient funds")


class NoDynamicFeeEstimates(Exception):
    def __str__(self):
        return translate("util", "Dynamic fee estimates not available")


class BelowDustLimit(Exception):
    pass


class InvalidPassword(Exception):
    def __init__(self, message: Optional[str] = None):
        self.message = message

    def __str__(self):
        if self.message is None:
            return translate("util", "Incorrect password")
        else:
            return str(self.message)


class AddTransactionException(Exception):
    pass


class UnrelatedTransactionException(AddTransactionException):
    def __str__(self):
        return translate("util", "Transaction is unrelated to this wallet.")


class FileImportFailed(Exception):
    def __init__(self, message=""):
        self.message = str(message)

    def __str__(self):
        return translate("util", "Failed to import from file.") + "\n" + self.message


class FileExportFailed(Exception):
    def __init__(self, message=""):
        self.message = str(message)

    def __str__(self):
        return translate("util", "Failed to export to file.") + "\n" + self.message


class WalletFileException(Exception):
    pass


class BitcoinException(Exception):
    pass


class UserFacingException(Exception):
    """Exception that contains information intended to be shown to the user."""


class InvoiceError(UserFacingException):
    pass


# Throw this exception to unwind the stack like when an error occurs.
# However unlike other exceptions the user won't be informed.
class UserCancelled(Exception):
    """An exception that is suppressed from the user."""


# Helper function to lighten a color
def lighten_color(hex_color: str, factor: float):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_ansi(hex_color: str):
    """Convert hex color to closest ANSI color."""
    # Mapping of ANSI color codes to RGB values
    ansi_colors = {
        30: (0, 0, 0),  # Black
        31: (128, 0, 0),  # Red
        32: (0, 128, 0),  # Green
        33: (128, 128, 0),  # Yellow
        34: (0, 0, 128),  # Blue
        35: (128, 0, 128),  # Magenta
        36: (0, 128, 128),  # Cyan
        37: (192, 192, 192),  # Light gray
        90: (128, 128, 128),  # Dark gray
        91: (255, 0, 0),  # Light red
        92: (0, 255, 0),  # Light green
        93: (255, 255, 0),  # Light yellow
        94: (0, 0, 255),  # Light blue
        95: (255, 0, 255),  # Light magenta
        96: (0, 255, 255),  # Light cyan
        97: (255, 255, 255),  # White
    }

    # Convert hex to RGB
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)

    # Find the closest ANSI color
    closest_ansi = min(
        ansi_colors,
        key=lambda k: (r - ansi_colors[k][0]) ** 2
        + (g - ansi_colors[k][1]) ** 2
        + (b - ansi_colors[k][2]) ** 2,
    )
    return closest_ansi


# New function to apply color formatting to a string
def color_format_str(
    s, hex_color="#000000", color_formatting: Optional[Literal["html", "rich", "bash"]] = "rich"
):
    if hex_color == "#000000":
        return s
    if color_formatting == "html":
        return f'<span style="color:{hex_color}">{s}</span>'
    if color_formatting == "rich":
        return f'<font color="{hex_color}">{s}</font>'
    if color_formatting == "bash":
        ansi_code = hex_to_ansi(hex_color)
        return f"\033[{ansi_code}m{s}\033[0m"

    return s


# Main formatting function
@register_cache(always_keep=True)
def format_number(
    number,
    color_formatting: Optional[Literal["html", "rich", "bash"]] = None,
    include_decimal_spaces=True,
    base_color="#000000",
    indicate_balance_change=False,
    unicode_space_character=None,
):
    number = int(number)
    # Split into integer and decimal parts
    integer_part, decimal_part = f"{number/1e8:.8f}".split(".")

    # Format the integer part with commas or OS native separators
    abs_integer_part_formatted = QLocale().toString(abs(int(integer_part)))

    # Split the decimal part into groups
    decimal_groups = [decimal_part[:2], decimal_part[2:5], decimal_part[5:]]

    # Determine color for negative numbers if indicated
    overall_color = (
        "#ff0000" if indicate_balance_change and number < 0 and base_color == "#000000" else base_color
    )

    # Apply color formatting to decimal groups
    if color_formatting:
        lighter_color = lighten_color(overall_color, 0.3)
        lightest_color = lighten_color(overall_color, 0.5)

        for i in range(len(decimal_groups)):
            if i == len(decimal_groups) - 1:
                color = lightest_color
            elif i == len(decimal_groups) - 2:
                color = lighter_color
            else:
                color = overall_color

            decimal_groups[i] = color_format_str(decimal_groups[i], color, color_formatting)

    # No color formatting applied if color_formatting is None
    space_character = "\u00A0" if unicode_space_character else " "
    decimal_part_formatted = (
        space_character.join(decimal_groups) if include_decimal_spaces else "".join(decimal_groups)
    )

    integer_part_formatted = abs_integer_part_formatted
    if number < 0:
        integer_part_formatted = f"-{abs_integer_part_formatted}"
    if indicate_balance_change and number >= 0:
        integer_part_formatted = f"+{abs_integer_part_formatted}"

    # Combine integer and decimal parts with separator
    int_part = color_format_str(integer_part_formatted, overall_color, color_formatting)

    formatted_number = f"{int_part}{color_format_str(QLocale().decimalPoint(), overall_color, color_formatting)}{decimal_part_formatted}"

    return formatted_number


class Satoshis:
    def __init__(self, value: Union[str, int], network: bdk.Network):
        self.network = network
        self.value = value if isinstance(value, int) else self._to_int(value)

    def _to_int(self, s: Union[float, str]):
        if isinstance(s, float):
            return int(s)

        f = QLocale().toDouble(str(s).replace(unit_str(self.network), "").strip().replace(" ", ""))[0] * 1e8
        return int(round(f))

    def __repr__(self):
        return f"Satoshis({self.value})"

    def __str__(self):
        return format_number(self.value, color_formatting=None, include_decimal_spaces=True)

    def __eq__(self, other):
        return (self.value == other.value) and (self.network == other.network)

    def __ne__(self, other):
        return not (self == other)

    def __add__(self, other: "Satoshis"):
        assert self.network == other.network
        return Satoshis(self.value + other.value, self.network)

    def str_with_unit(self, color_formatting: Literal["html", "rich", "bash"] = "rich"):
        return f"{format_number(self.value, color_formatting=color_formatting, include_decimal_spaces=True, unicode_space_character=True )} {color_format_str( unit_str(self.network), color_formatting=color_formatting)}"

    def str_as_change(self, color_formatting: Optional[Literal["html", "rich", "bash"]] = None, unit=False):

        return (
            f"{format_number(self.value, color_formatting=color_formatting, include_decimal_spaces=True,   indicate_balance_change=True)}"
            + (
                f" {color_format_str( unit_str(self.network), color_formatting=color_formatting)}"
                if unit
                else ""
            )
        )

    def format_as_balance(self):
        return translate("util", "Balance: {amount}").format(amount=self.str_with_unit())

    def __bool__(self):
        return bool(self.value)

    @classmethod
    def sum(cls, l: Union[List, Tuple, "Satoshis"]) -> "Satoshis":
        def calc_satoshi(v: Union[List, Tuple, "Satoshis"]) -> Satoshis:
            # allow recursive summing
            return Satoshis.sum(v) if isinstance(v, (list, tuple)) else v

        if not l:
            raise ValueError("Cannot sum an empty list")
        if isinstance(l, Satoshis):
            return l

        summed = calc_satoshi(l[0])
        for v in l[1:]:
            summed += calc_satoshi(v)

        return summed


def resource_path(*parts: str):
    return os.path.join(pkg_dir, *parts)


# absolute path to python package folder of electrum ("lib")
pkg_dir = os.path.split(os.path.realpath(__file__))[0]


def unit_str(network: bdk.Network) -> str:
    return "BTC" if network is None or network == bdk.Network.BITCOIN else "tBTC"


def unit_sat_str(network: bdk.Network) -> str:
    return "Sat" if network is None or network == bdk.Network.BITCOIN else "tSat"


def unit_fee_str(network: bdk.Network) -> str:
    "Sat/vB"
    return "Sat/vB" if network is None or network == bdk.Network.BITCOIN else "tSat/vB"


def format_fee_rate(fee_rate: float, network: bdk.Network) -> str:
    return f"{round(fee_rate,1 )} {unit_fee_str(network)}"


def age(
    from_date: Union[int, float, None, timedelta],  # POSIX timestamp
    *,
    since_date: datetime | None = None,
    target_tz=None,
    include_seconds: bool = False,
) -> str:
    """Takes a timestamp and returns a string with the approximation of the
    age."""
    if from_date is None:
        return translate("util", "Unknown")

    if since_date is None:
        since_date = datetime.now(target_tz)

    from_date_clean = (
        since_date + from_date if isinstance(from_date, timedelta) else datetime.fromtimestamp(from_date)
    )

    distance_in_time = from_date_clean - since_date
    is_in_past = from_date_clean < since_date
    distance_in_seconds = int(round(abs(distance_in_time.days * 86400 + distance_in_time.seconds)))
    distance_in_minutes = int(round(distance_in_seconds / 60))

    if distance_in_minutes == 0:
        if include_seconds:
            if is_in_past:
                return translate("util", "{} seconds ago").format(distance_in_seconds)
            else:
                return translate("util", "in {} seconds").format(distance_in_seconds)
        else:
            if is_in_past:
                return translate("util", "less than a minute ago")
            else:
                return translate("util", "in less than a minute")
    elif distance_in_minutes < 45:
        if is_in_past:
            return translate("util", "about {} minutes ago").format(distance_in_minutes)
        else:
            return translate("util", "in about {} minutes").format(distance_in_minutes)
    elif distance_in_minutes < 90:
        if is_in_past:
            return translate("util", "about 1 hour ago")
        else:
            return translate("util", "in about 1 hour")
    elif distance_in_minutes < 1440:
        if is_in_past:
            return translate("util", "about {} hours ago").format(round(distance_in_minutes / 60.0))
        else:
            return translate("util", "in about {} hours").format(round(distance_in_minutes / 60.0))
    elif distance_in_minutes < 2880:
        if is_in_past:
            return translate("util", "about 1 day ago")
        else:
            return translate("util", "in about 1 day")
    elif distance_in_minutes < 43220:
        if is_in_past:
            return translate("util", "about {} days ago").format(round(distance_in_minutes / 1440))
        else:
            return translate("util", "in about {} days").format(round(distance_in_minutes / 1440))
    elif distance_in_minutes < 86400:
        if is_in_past:
            return translate("util", "about 1 month ago")
        else:
            return translate("util", "in about 1 month")
    elif distance_in_minutes < 525600:
        if is_in_past:
            return translate("util", "about {} months ago").format(round(distance_in_minutes / 43200))
        else:
            return translate("util", "in about {} months").format(round(distance_in_minutes / 43200))
    elif distance_in_minutes < 1051200:
        if is_in_past:
            return translate("util", "about 1 year ago")
        else:
            return translate("util", "in about 1 year")
    else:
        if is_in_past:
            return translate("util", "over {} years ago").format(round(distance_in_minutes / 525600))
        else:
            return translate("util", "in over {} years").format(round(distance_in_minutes / 525600))


def confirmation_wait_formatted(projected_mempool_block_index: int):
    estimated_duration = timedelta(minutes=projected_mempool_block_index * 10)
    estimated_duration = max(estimated_duration, timedelta(minutes=10))

    return age(estimated_duration)


def block_explorer_URL(mempool_url: str, kind: Literal["tx", "addr"], item: str) -> Optional[str]:
    explorer_url, explorer_dict = mempool_url, {
        "tx": "tx/",
        "addr": "address/",
    }
    kind_str = explorer_dict.get(kind)
    if kind_str is None:
        return None
    if explorer_url[-1] != "/":
        explorer_url += "/"
    url_parts = [explorer_url, kind_str, item]
    return "".join(url_parts)


def block_explorer_URL_of_projected_block(mempool_url: str, block_index: int) -> Optional[str]:
    explorer_url = mempool_url
    if explorer_url[-1] != "/":
        explorer_url += "/"
    explorer_url = explorer_url.replace("/api", "")
    return f"{explorer_url}mempool-block/{block_index}"


# URL decode
# _ud = re.compile('%([0-9a-hA-H]{2})', re.MULTILINE)
# urldecode = lambda x: _ud.sub(lambda m: chr(int(m.group(1), 16)), x)


# note: when checking against these, use .lower() to support case-insensitivity
BITCOIN_BIP21_URI_SCHEME = "bitcoin"
LIGHTNING_URI_SCHEME = "lightning"


class InvalidBitcoinURI(Exception):
    pass


class FailedToParsePaymentIdentifier(Exception):
    pass


# Python bug (http://bugs.python.org/issue1927) causes raw_input
# to be redirected improperly between stdin/stderr on Unix systems
# TODO: py3
def raw_input(prompt=None):
    if prompt:
        sys.stdout.write(prompt)
    return builtin_raw_input()


builtin_raw_input = builtins.input
builtins.input = raw_input


def versiontuple(v) -> Tuple:
    return tuple(map(int, (v.split("."))))


class CannotBumpFee(Exception):
    def __str__(self) -> str:
        return translate("util", "Cannot bump fee") + ":\n\n" + Exception.__str__(self)


class CannotDoubleSpendTx(Exception):
    def __str__(self) -> str:
        return translate("util", "Cannot cancel transaction") + ":\n\n" + Exception.__str__(self)


class CannotCPFP(Exception):
    def __str__(self) -> str:
        return translate("util", "Cannot create child transaction") + ":\n\n" + Exception.__str__(self)


class InternalAddressCorruption(Exception):
    def __str__(self) -> str:
        return translate(
            "util",
            "Wallet file corruption detected. "
            "Please restore your wallet from seed, and compare the addresses in both files",
        )


def remove_duplicates_keep_order(seq):
    seen = set()
    result = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def calculate_ema(data, alpha=0.1):
    """
    Calculate Exponential Moving Average (EMA) for a list of numbers.

    :param data: List of numbers.
    :param alpha: Smoothing factor within (0, 1), where higher value gives more weight to recent data.
    :return: EMA value.
    """
    ema = data[0]
    for i in range(1, len(data)):
        ema = alpha * data[i] + (1 - alpha) * ema
    return ema


def briefcase_project_dir() -> Path:
    # __file__ == /tmp/.mount_Bitcoix7tQIZ/usr/app/bitcoin_safe/util.py
    return Path(__file__).parent


def qbytearray_to_str(a: QByteArray) -> str:
    return a.data().decode()


def str_to_qbytearray(s: str) -> QByteArray:
    return QByteArray(s.encode())  # type: ignore[call-overload]
