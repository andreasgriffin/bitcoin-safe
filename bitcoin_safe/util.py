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

import logging

logger = logging.getLogger(__name__)

import os, sys, re, json
from collections import defaultdict, OrderedDict
from typing import (
    NamedTuple,
    Union,
    TYPE_CHECKING,
    Tuple,
    Optional,
    Callable,
    Any,
    Sequence,
    Dict,
    Generic,
    TypeVar,
    List,
    Iterable,
    Set,
)
from datetime import datetime
import decimal
from decimal import Decimal
import threading
import stat
import asyncio
import urllib.request, urllib.parse, urllib.error
import builtins
import json
import time
from typing import NamedTuple, Optional
import ipaddress
from ipaddress import IPv4Address, IPv6Address
from PySide2.QtCore import QLocale
from .i18n import _
from typing import (
    NamedTuple,
    Callable,
    Optional,
    TYPE_CHECKING,
    Union,
    List,
    Dict,
    Any,
    Sequence,
    Iterable,
    Tuple,
    Type,
)


from PySide2.QtCore import Signal, QRectF
from PySide2.QtCore import (
    Qt,
    QPersistentModelIndex,
    QModelIndex,
    QCoreApplication,
    QItemSelectionModel,
    QThread,
    QSortFilterProxyModel,
    QSize,
    QLocale,
    QAbstractItemModel,
    QEvent,
    QRect,
    QPoint,
    QObject,
    QTimer,
    QSize,
)
import queue

locale = QLocale()  # This initializes a QLocale object with the user's default locale


TX_HEIGHT_FUTURE = -3
TX_HEIGHT_LOCAL = -2
TX_HEIGHT_UNCONF_PARENT = -1
TX_HEIGHT_UNCONFIRMED = 0

TX_TIMESTAMP_INF = 999_999_999_999
TX_HEIGHT_INF = 10**9

TX_STATUS = [
    _("Unconfirmed"),
    _("Unconfirmed parent"),
    _("Not Verified"),
    _("Local"),
]


DEVELOPMENT_PREFILLS = True

import bdkpython as bdk


def serialized_to_hex(serialized):
    return bytes(serialized).hex()


def hex_to_serialized(hex_string):
    return bytes.fromhex(hex_string)


def psbt_to_hex(psbt: bdk.PartiallySignedTransaction):
    return serialized_to_hex(psbt.extract_tx().serialize())


def call_call_functions(functions):
    for f in functions:
        f()


def compare_dictionaries(dict1, dict2):
    # Get unique keys from both dictionaries
    unique_keys = set(dict1.keys()) ^ set(dict2.keys())

    # Get keys with different values
    differing_values = {k for k in dict1 if k in dict2 and dict1[k] != dict2[k]}

    # Combine unique keys and differing values
    keys_to_include = unique_keys | differing_values

    # Create a new dictionary with only the differing entries
    result = {k: dict1.get(k, dict2.get(k)) for k in keys_to_include}

    return result


def inv_dict(d):
    return {v: k for k, v in d.items()}


def all_subclasses(cls) -> Set:
    """Return all (transitive) subclasses of cls."""
    res = set(cls.__subclasses__())
    for sub in res.copy():
        res |= all_subclasses(sub)
    return res


import bdkpython as bdk
import hashlib


def replace_non_alphanumeric(string):
    return re.sub(r"\W+", "_", string)


def hash_string(text):
    return hashlib.sha256(text.encode()).hexdigest()


def is_iterable(obj):
    return hasattr(obj, "__iter__") or hasattr(obj, "__getitem__")


from functools import lru_cache


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
def clear_cache(include_always_keep=False):
    logger.debug(
        f"clear_cache include_always_keep {include_always_keep}  of {len(cached_functions), len(cached_always_keep_functions)} functions"
    )
    for func in cached_functions:
        func.cache_clear()
    if include_always_keep:
        for func in cached_always_keep_functions:
            func.cache_clear()


def clean_dict(d):
    return {k: v for k, v in d.items() if v}


def clean_list(l):
    return [v for v in l if v]


def is_address(address) -> bool:
    try:
        bdkaddress = bdk.Address(address)
        return bool(bdkaddress)
    except:
        return False


def parse_max_spend(amt: Any) -> Optional[int]:
    """Checks if given amount is "spend-max"-like.
    Returns None or the positive integer weight for "max". Never raises.

    When creating invoices and on-chain txs, the user can specify to send "max".
    This is done by setting the amount to '!'. Splitting max between multiple
    tx outputs is also possible, and custom weights (positive ints) can also be used.
    For example, to send 40% of all coins to address1, and 60% to address2:
    ```
    address1, 2!
    address2, 3!
    ```
    """
    if not (isinstance(amt, str) and amt and amt[-1] == "!"):
        return None
    if amt == "!":
        return 1
    x = amt[:-1]
    try:
        x = int(x)
    except ValueError:
        return None
    if x > 0:
        return x
    return None


class NotEnoughFunds(Exception):
    def __str__(self):
        return _("Insufficient funds")


class NoDynamicFeeEstimates(Exception):
    def __str__(self):
        return _("Dynamic fee estimates not available")


class BelowDustLimit(Exception):
    pass


class InvalidPassword(Exception):
    def __init__(self, message: Optional[str] = None):
        self.message = message

    def __str__(self):
        if self.message is None:
            return _("Incorrect password")
        else:
            return str(self.message)


class AddTransactionException(Exception):
    pass


class UnrelatedTransactionException(AddTransactionException):
    def __str__(self):
        return _("Transaction is unrelated to this wallet.")


class FileImportFailed(Exception):
    def __init__(self, message=""):
        self.message = str(message)

    def __str__(self):
        return _("Failed to import from file.") + "\n" + self.message


class FileExportFailed(Exception):
    def __init__(self, message=""):
        self.message = str(message)

    def __str__(self):
        return _("Failed to export to file.") + "\n" + self.message


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
    """An exception that is suppressed from the user"""

    pass


# Helper function to lighten a color
def lighten_color(hex_color, factor):
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_ansi(hex_color):
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
def color_format_str(s, hex_color="#000000", color_formatting="rich"):
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
    color_formatting=None,
    include_decimal_spaces=True,
    base_color="#000000",
    indicate_balance_change=False,
    unicode_space_character=None,
):
    number = int(number)
    # Split into integer and decimal parts
    integer_part, decimal_part = f"{number/1e8:.8f}".split(".")

    # Format the integer part with commas or OS native separators
    abs_integer_part_formatted = locale.toString(abs(int(integer_part)))

    # Split the decimal part into groups
    decimal_groups = [decimal_part[:2], decimal_part[2:5], decimal_part[5:]]

    # Determine color for negative numbers if indicated
    overall_color = (
        "#ff0000"
        if indicate_balance_change and number < 0 and base_color == "#000000"
        else base_color
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

            decimal_groups[i] = color_format_str(
                decimal_groups[i], color, color_formatting
            )

    # No color formatting applied if color_formatting is None
    space_character = "\u00A0" if unicode_space_character else " "
    decimal_part_formatted = (
        space_character.join(decimal_groups)
        if include_decimal_spaces
        else "".join(decimal_groups)
    )

    integer_part_formatted = abs_integer_part_formatted
    if number < 0:
        integer_part_formatted = f"-{abs_integer_part_formatted}"
    if indicate_balance_change and number >= 0:
        integer_part_formatted = f"+{abs_integer_part_formatted}"

    # Combine integer and decimal parts with separator
    int_part = color_format_str(integer_part_formatted, overall_color, color_formatting)

    formatted_number = f"{int_part}{color_format_str(locale.decimalPoint(), overall_color, color_formatting)}{decimal_part_formatted}"

    return formatted_number


class Satoshis:
    def __init__(self, value, network: bdk.Network):
        self.network = network
        self.value = value if isinstance(value, int) else self._to_int(value)

    def _to_int(self, s: str):
        if isinstance(s, float):
            return int(s)

        f = float(str(s).replace(str(self.network), "").strip().replace(" ", "")) * 1e8
        return int(f)

    def __repr__(self):
        return f"Satoshis({self.value})"

    def __str__(self):
        return format_number(
            self.value, color_formatting=None, include_decimal_spaces=True
        )

    def __eq__(self, other):
        return (self.value == other.value) and (self.network == other.network)

    def __ne__(self, other):
        return not (self == other)

    def __add__(self, other):
        assert self.network == other.network
        return Satoshis(self.value + other.value, self.network)

    def str_with_unit(self, color_formatting="rich"):
        return f"{format_number(self.value, color_formatting=color_formatting, include_decimal_spaces=True, unicode_space_character=True )} {color_format_str( unit_str(self.network), color_formatting=color_formatting)}"

    def diff(self, color_formatting=None, unit=False):

        return (
            f"{format_number(self.value, color_formatting=color_formatting, include_decimal_spaces=True,   indicate_balance_change=True)}"
            + (
                f" {color_format_str( unit_str(self.network), color_formatting=color_formatting)}"
                if unit
                else ""
            )
        )

    def __bool__(self):
        return bool(self.value)

    @classmethod
    def sum(cls, l: Iterable["Satoshis"]) -> "Satoshis":
        if not l:
            return 0
        if isinstance(l, Satoshis):
            return l

        summed = None
        for v in l:
            v = Satoshis.sum(v) if isinstance(v, (tuple, list)) else v
            if summed is None:
                summed = v
            else:
                summed += v

        return summed


# note: this is not a NamedTuple as then its json encoding cannot be customized
class Fiat(object):
    __slots__ = ("value", "ccy")

    def __new__(cls, value: Optional[Decimal], ccy: str):
        self = super(Fiat, cls).__new__(cls)
        self.ccy = ccy
        if not isinstance(value, (Decimal, type(None))):
            raise TypeError(f"value should be Decimal or None, not {type(value)}")
        self.value = value
        return self

    def __repr__(self):
        return "Fiat(%s)" % self.__str__()

    def __str__(self):
        if self.value is None or self.value.is_nan():
            return _("No Data")
        else:
            return "{:.2f}".format(self.value)

    def to_ui_string(self):
        if self.value is None or self.value.is_nan():
            return _("No Data")
        else:
            return "{:.2f}".format(self.value) + " " + self.ccy

    def __eq__(self, other):
        if not isinstance(other, Fiat):
            return False
        if self.ccy != other.ccy:
            return False
        if (
            isinstance(self.value, Decimal)
            and isinstance(other.value, Decimal)
            and self.value.is_nan()
            and other.value.is_nan()
        ):
            return True
        return self.value == other.value

    def __ne__(self, other):
        return not (self == other)

    def __add__(self, other):
        assert self.ccy == other.ccy
        return Fiat(self.value + other.value, self.ccy)


def print_stderr(*args):
    args = [str(item) for item in args]
    sys.stderr.write(" ".join(args) + "\n")
    sys.stderr.flush()


def print_msg(*args):
    # Stringify args
    args = [str(item) for item in args]
    sys.stdout.write(" ".join(args) + "\n")
    sys.stdout.flush()


def standardize_path(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def to_string(x, enc) -> str:
    if isinstance(x, (bytes, bytearray)):
        return x.decode(enc)
    if isinstance(x, str):
        return x
    else:
        raise TypeError("Not a string or bytes like object")


def to_bytes(something, encoding="utf8") -> bytes:
    """
    cast string to bytes() like object, but for python2 support it's bytearray copy
    """
    if isinstance(something, bytes):
        return something
    if isinstance(something, str):
        return something.encode(encoding)
    elif isinstance(something, bytearray):
        return bytes(something)
    else:
        raise TypeError("Not a string or bytes like object")


def resource_path(*parts):
    return os.path.join(pkg_dir, *parts)


# absolute path to python package folder of electrum ("lib")
pkg_dir = os.path.split(os.path.realpath(__file__))[0]


def unit_str(network: bdk.Network):
    return "BTC" if network is None or network == bdk.Network.BITCOIN else "tBTC"


FEERATE_PRECISION = 1  # num fractional decimal places for sat/byte fee rates
_feerate_quanta = Decimal(10) ** (-FEERATE_PRECISION)


def quantize_feerate(fee) -> Union[None, Decimal, int]:
    """Strip sat/byte fee rate of excess precision."""
    if fee is None:
        return None
    return Decimal(fee).quantize(_feerate_quanta, rounding=decimal.ROUND_HALF_DOWN)


def timestamp_to_datetime(timestamp: Union[int, float, None]) -> Optional[datetime]:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp)


def format_time(timestamp: Union[int, float, None]) -> str:
    date = timestamp_to_datetime(timestamp)
    return date.isoformat(" ", timespec="minutes") if date else _("Unknown")


def age(
    from_date: Union[int, float, None],  # POSIX timestamp
    *,
    since_date: datetime = None,
    target_tz=None,
    include_seconds: bool = False,
) -> str:
    """Takes a timestamp and returns a string with the approximation of the age"""
    if from_date is None:
        return _("Unknown")

    from_date = datetime.fromtimestamp(from_date)
    if since_date is None:
        since_date = datetime.now(target_tz)

    distance_in_time = from_date - since_date
    is_in_past = from_date < since_date
    distance_in_seconds = int(
        round(abs(distance_in_time.days * 86400 + distance_in_time.seconds))
    )
    distance_in_minutes = int(round(distance_in_seconds / 60))

    if distance_in_minutes == 0:
        if include_seconds:
            if is_in_past:
                return _("{} seconds ago").format(distance_in_seconds)
            else:
                return _("in {} seconds").format(distance_in_seconds)
        else:
            if is_in_past:
                return _("less than a minute ago")
            else:
                return _("in less than a minute")
    elif distance_in_minutes < 45:
        if is_in_past:
            return _("about {} minutes ago").format(distance_in_minutes)
        else:
            return _("in about {} minutes").format(distance_in_minutes)
    elif distance_in_minutes < 90:
        if is_in_past:
            return _("about 1 hour ago")
        else:
            return _("in about 1 hour")
    elif distance_in_minutes < 1440:
        if is_in_past:
            return _("about {} hours ago").format(round(distance_in_minutes / 60.0))
        else:
            return _("in about {} hours").format(round(distance_in_minutes / 60.0))
    elif distance_in_minutes < 2880:
        if is_in_past:
            return _("about 1 day ago")
        else:
            return _("in about 1 day")
    elif distance_in_minutes < 43220:
        if is_in_past:
            return _("about {} days ago").format(round(distance_in_minutes / 1440))
        else:
            return _("in about {} days").format(round(distance_in_minutes / 1440))
    elif distance_in_minutes < 86400:
        if is_in_past:
            return _("about 1 month ago")
        else:
            return _("in about 1 month")
    elif distance_in_minutes < 525600:
        if is_in_past:
            return _("about {} months ago").format(round(distance_in_minutes / 43200))
        else:
            return _("in about {} months").format(round(distance_in_minutes / 43200))
    elif distance_in_minutes < 1051200:
        if is_in_past:
            return _("about 1 year ago")
        else:
            return _("in about 1 year")
    else:
        if is_in_past:
            return _("over {} years ago").format(round(distance_in_minutes / 525600))
        else:
            return _("in over {} years").format(round(distance_in_minutes / 525600))


mainnet_block_explorers = {
    "Bitupper Explorer": (
        "https://bitupper.com/en/explorer/bitcoin/",
        {"tx": "transactions/", "addr": "addresses/"},
    ),
    "Bitflyer.jp": (
        "https://chainflyer.bitflyer.jp/",
        {"tx": "Transaction/", "addr": "Address/"},
    ),
    "Blockchain.info": (
        "https://blockchain.com/btc/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "blockchainbdgpzk.onion": (
        "https://blockchainbdgpzk.onion/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "Blockstream.info": (
        "https://blockstream.info/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "Bitaps.com": ("https://btc.bitaps.com/", {"tx": "", "addr": ""}),
    "BTC.com": ("https://btc.com/", {"tx": "", "addr": ""}),
    "Chain.so": ("https://www.chain.so/", {"tx": "tx/BTC/", "addr": "address/BTC/"}),
    "Insight.is": ("https://insight.bitpay.com/", {"tx": "tx/", "addr": "address/"}),
    "TradeBlock.com": (
        "https://tradeblock.com/blockchain/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "BlockCypher.com": (
        "https://live.blockcypher.com/btc/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "Blockchair.com": (
        "https://blockchair.com/bitcoin/",
        {"tx": "transaction/", "addr": "address/"},
    ),
    "blockonomics.co": (
        "https://www.blockonomics.co/",
        {"tx": "api/tx?txid=", "addr": "#/search?q="},
    ),
    "mempool.space": ("https://mempool.space/", {"tx": "tx/", "addr": "address/"}),
    "mempool.emzy.de": ("https://mempool.emzy.de/", {"tx": "tx/", "addr": "address/"}),
    "OXT.me": ("https://oxt.me/", {"tx": "transaction/", "addr": "address/"}),
    "smartbit.com.au": (
        "https://www.smartbit.com.au/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "mynode.local": ("http://mynode.local:3002/", {"tx": "tx/", "addr": "address/"}),
    "system default": ("blockchain:/", {"tx": "tx/", "addr": "address/"}),
}

testnet_block_explorers = {
    "Bitaps.com": ("https://tbtc.bitaps.com/", {"tx": "", "addr": ""}),
    "BlockCypher.com": (
        "https://live.blockcypher.com/btc-testnet/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "Blockchain.info": (
        "https://www.blockchain.com/btc-testnet/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "Blockstream.info": (
        "https://blockstream.info/testnet/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "mempool.space": (
        "https://mempool.space/testnet/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "smartbit.com.au": (
        "https://testnet.smartbit.com.au/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "system default": (
        "blockchain://000000000933ea01ad0ee984209779baaec3ced90fa3f408719526f8d77f4943/",
        {"tx": "tx/", "addr": "address/"},
    ),
}

signet_block_explorers = {
    "bc-2.jp": ("https://explorer.bc-2.jp/", {"tx": "tx/", "addr": "address/"}),
    "mempool.space": (
        "https://mempool.space/signet/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "bitcoinexplorer.org": (
        "https://signet.bitcoinexplorer.org/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "wakiyamap.dev": (
        "https://signet-explorer.wakiyamap.dev/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "ex.signet.bublina.eu.org": (
        "https://ex.signet.bublina.eu.org/",
        {"tx": "tx/", "addr": "address/"},
    ),
    "system default": ("blockchain:/", {"tx": "tx/", "addr": "address/"}),
}
regtest_block_explorers = {
    "localhost:5000": ("http://localhost:5000/", {"tx": "tx/", "addr": "address/"}),
}

_block_explorer_default_api_loc = {"tx": "tx/", "addr": "address/"}


def block_explorer_info(network: bdk.Network) -> Dict[str, Dict]:
    if network in [
        bdk.Network.TESTNET,
    ]:
        return testnet_block_explorers
    elif network in [bdk.Network.REGTEST]:
        return regtest_block_explorers
    elif network == bdk.Network.SIGNET:
        return signet_block_explorers
    return mainnet_block_explorers


def block_explorer_tuple(
    network_settings: "NetworkConfig",
) -> Optional[Tuple[str, dict]]:
    return block_explorer_info(network_settings.network).get(
        network_settings.block_explorer
    )


def block_explorer_URL(
    network_settings: "NetworkConfig", kind: str, item: str
) -> Optional[str]:
    be_tuple = block_explorer_tuple(network_settings)
    if not be_tuple:
        return
    explorer_url, explorer_dict = be_tuple
    kind_str = explorer_dict.get(kind)
    if kind_str is None:
        return
    if explorer_url[-1] != "/":
        explorer_url += "/"
    url_parts = [explorer_url, kind_str, item]
    return "".join(url_parts)


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


def parse_json(message):
    # TODO: check \r\n pattern
    n = message.find(b"\n")
    if n == -1:
        return None, message
    try:
        j = json.loads(message[0:n].decode("utf8"))
    except:
        j = None
    return j, message[n + 1 :]


def setup_thread_excepthook():
    """
    Workaround for `sys.excepthook` thread bug from:
    http://bugs.python.org/issue1230540

    Call once from the main thread before creating any threads.
    """

    init_original = threading.Thread.__init__

    def init(self, *args, **kwargs):

        init_original(self, *args, **kwargs)
        run_original = self.run

        def run_with_except_hook(*args2, **kwargs2):
            try:
                run_original(*args2, **kwargs2)
            except Exception:
                sys.excepthook(*sys.exc_info())

        self.run = run_with_except_hook

    threading.Thread.__init__ = init


def send_exception_to_crash_reporter(e: BaseException):
    from .base_crash_reporter import send_exception_to_crash_reporter

    send_exception_to_crash_reporter(e)


def versiontuple(v):
    return tuple(map(int, (v.split("."))))


def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    # backwards compatibility for JSONDecodeError
    except ValueError:
        logger.exception("")
        raise FileImportFailed(_("Invalid JSON code."))
    except BaseException as e:
        logger.exception("")
        raise FileImportFailed(e)
    return data


def write_json_file(path, data):
    try:
        with open(path, "w+", encoding="utf-8") as f:
            json.dump(data, f, indent=4, sort_keys=True, cls=MyEncoder)
    except (IOError, os.error) as e:
        logger.exception("")
        raise FileExportFailed(e)


def os_chmod(path, mode):
    """os.chmod aware of tmpfs"""
    try:
        os.chmod(path, mode)
    except OSError as e:
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", None)
        if xdg_runtime_dir and is_subpath(path, xdg_runtime_dir):
            logger.info(f"Tried to chmod in tmpfs. Skipping... {e!r}")
        else:
            raise


def make_dir(path, allow_symlink=True):
    """Make directory if it does not yet exist."""
    if not os.path.exists(path):
        if not allow_symlink and os.path.islink(path):
            raise Exception("Dangling link: " + path)
        os.mkdir(path)
        os_chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def is_subpath(long_path: str, short_path: str) -> bool:
    """Returns whether long_path is a sub-path of short_path."""
    try:
        common = os.path.commonpath([long_path, short_path])
    except ValueError:
        return False
    short_path = standardize_path(short_path)
    common = standardize_path(common)
    return short_path == common


class TxMinedInfo(NamedTuple):
    height: int  # height of block that mined tx
    conf: Optional[
        int
    ] = None  # number of confirmations, SPV verified. >=0, or None (None means unknown)
    timestamp: Optional[int] = None  # timestamp of block that mined tx
    txpos: Optional[int] = None  # position of tx in serialized block
    header_hash: Optional[str] = None  # hash of block that mined tx
    wanted_height: Optional[int] = None  # in case of timelock, min abs block height

    def short_id(self) -> Optional[str]:
        if self.txpos is not None and self.txpos >= 0:
            assert self.height > 0
            return f"{self.height}x{self.txpos}"
        return None


AS_LIB_USER_I_WANT_TO_MANAGE_MY_OWN_ASYNCIO_LOOP = False  # used by unit tests

_asyncio_event_loop = None  # type: Optional[asyncio.AbstractEventLoop]


def get_asyncio_loop() -> asyncio.AbstractEventLoop:
    """Returns the global asyncio event loop we use."""
    if loop := _asyncio_event_loop:
        return loop
    if AS_LIB_USER_I_WANT_TO_MANAGE_MY_OWN_ASYNCIO_LOOP:
        if loop := get_running_loop():
            return loop
    raise Exception("event loop not created yet")


def create_and_start_event_loop() -> Tuple[
    asyncio.AbstractEventLoop, asyncio.Future, threading.Thread
]:
    global _asyncio_event_loop
    if _asyncio_event_loop is not None:
        raise Exception("there is already a running event loop")

    # asyncio.get_event_loop() became deprecated in python3.10. (see https://github.com/python/cpython/issues/83710)
    # We set a custom event loop policy purely to be compatible with code that
    # relies on asyncio.get_event_loop().
    # - in python 3.8-3.9, asyncio.Event.__init__, asyncio.Lock.__init__,
    #   and similar, calls get_event_loop. see https://github.com/python/cpython/pull/23420
    class MyEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def get_event_loop(self):
            # In case electrum is being used as a library, there might be other
            # event loops in use besides ours. To minimise interfering with those,
            # if there is a loop running in the current thread, return that:
            running_loop = get_running_loop()
            if running_loop is not None:
                return running_loop
            # Otherwise, return our global loop:
            return get_asyncio_loop()

    asyncio.set_event_loop_policy(MyEventLoopPolicy())

    loop = asyncio.new_event_loop()
    _asyncio_event_loop = loop

    def on_exception(loop, context):
        """Suppress spurious messages it appears we cannot control."""
        SUPPRESS_MESSAGE_REGEX = re.compile(
            "SSL handshake|Fatal read error on|" "SSL error in data received"
        )
        message = context.get("message")
        if message and SUPPRESS_MESSAGE_REGEX.match(message):
            return
        loop.default_exception_handler(context)

    def run_event_loop():
        try:
            loop.run_until_complete(stopping_fut)
        finally:
            # clean-up
            global _asyncio_event_loop
            _asyncio_event_loop = None

    loop.set_exception_handler(on_exception)
    # loop.set_debug(True)
    stopping_fut = loop.create_future()
    loop_thread = threading.Thread(
        target=run_event_loop,
        name="EventLoop",
    )
    loop_thread.start()
    # Wait until the loop actually starts.
    # On a slow PC, or with a debugger attached, this can take a few dozens of ms,
    # and if we returned without a running loop, weird things can happen...
    t0 = time.monotonic()
    while not loop.is_running():
        time.sleep(0.01)
        if time.monotonic() - t0 > 5:
            raise Exception(
                "been waiting for 5 seconds but asyncio loop would not start!"
            )
    return loop, stopping_fut, loop_thread


def is_ip_address(x: Union[str, bytes]) -> bool:
    if isinstance(x, bytes):
        x = x.decode("utf-8")
    try:
        ipaddress.ip_address(x)
        return True
    except ValueError:
        return False


def is_localhost(host: str) -> bool:
    if str(host) in (
        "localhost",
        "localhost.",
    ):
        return True
    if host[0] == "[" and host[-1] == "]":  # IPv6
        host = host[1:-1]
    try:
        ip_addr = ipaddress.ip_address(host)  # type: Union[IPv4Address, IPv6Address]
        return ip_addr.is_loopback
    except ValueError:
        pass  # not an IP
    return False


def is_private_netaddress(host: str) -> bool:
    if is_localhost(host):
        return True
    if host[0] == "[" and host[-1] == "]":  # IPv6
        host = host[1:-1]
    try:
        ip_addr = ipaddress.ip_address(host)  # type: Union[IPv4Address, IPv6Address]
        return ip_addr.is_private
    except ValueError:
        pass  # not an IP
    return False


_event_listeners = defaultdict(set)  # type: Dict[str, Set[str]]


def event_listener(func):
    classname, method_name = func.__qualname__.split(".")
    assert method_name.startswith("on_event_")
    classpath = f"{func.__module__}.{classname}"
    _event_listeners[classpath].add(method_name)
    return func


_NetAddrType = TypeVar("_NetAddrType")


T = TypeVar("T")


def get_running_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Returns the asyncio event loop that is *running in this thread*, if any."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def error_text_str_to_safe_str(err: str) -> str:
    """Converts an untrusted error string to a sane printable ascii str.
    Never raises.
    """
    return error_text_bytes_to_safe_str(err.encode("ascii", errors="backslashreplace"))


def error_text_bytes_to_safe_str(err: bytes) -> str:
    """Converts an untrusted error bytes text to a sane printable ascii str.
    Never raises.

    Note that naive ascii conversion would be insufficient. Fun stuff:
    >>> b = b"my_long_prefix_blabla" + 21 * b"\x08" + b"malicious_stuff"
    >>> s = b.decode("ascii")
    >>> print(s)
    malicious_stuffblabla
    """
    # convert to ascii, to get rid of unicode stuff
    ascii_text = err.decode("ascii", errors="backslashreplace")
    # do repr to handle ascii special chars (especially when printing/logging the str)
    return repr(ascii_text)


class CannotBumpFee(Exception):
    def __str__(self):
        return _("Cannot bump fee") + ":\n\n" + Exception.__str__(self)


class CannotDoubleSpendTx(Exception):
    def __str__(self):
        return _("Cannot cancel transaction") + ":\n\n" + Exception.__str__(self)


class CannotCPFP(Exception):
    def __str__(self):
        return _("Cannot create child transaction") + ":\n\n" + Exception.__str__(self)


class InternalAddressCorruption(Exception):
    def __str__(self):
        return _(
            "Wallet file corruption detected. "
            "Please restore your wallet from seed, and compare the addresses in both files"
        )


def balance_dict(bdkbalance):
    return {
        "immature": bdkbalance.immature,
        "trusted_pending": bdkbalance.trusted_pending,
        "untrusted_pending": bdkbalance.untrusted_pending,
        "confirmed": bdkbalance.confirmed,
        "spendable": bdkbalance.spendable,
        "total": bdkbalance.total,
    }


def remove_duplicates_keep_order(seq):
    seen = set()
    result = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


class TaskThread(QThread):
    """Thread that runs background tasks.  Callbacks are guaranteed
    to happen in the context of its parent."""

    class Task(NamedTuple):
        task: Callable
        cb_success: Optional[Callable]
        cb_done: Optional[Callable]
        cb_error: Optional[Callable]
        cancel: Optional[Callable] = None

    doneSig = Signal(object, object, object)

    def __init__(self, parent, on_error=None):
        QThread.__init__(self, parent)
        self.on_error = on_error
        self.tasks = queue.Queue()
        self._cur_task = None  # type: Optional[TaskThread.Task]
        self._stopping = False
        self.doneSig.connect(self.on_done)
        self.start()

    def add(self, task, on_success=None, on_done=None, on_error=None, *, cancel=None):
        if self._stopping:
            logger.warning(f"stopping or already stopped but tried to add new task.")
            return
        on_error = on_error or self.on_error
        task_ = TaskThread.Task(task, on_success, on_done, on_error, cancel=cancel)
        self.tasks.put(task_)

    def add_and_start(
        self, task, on_success=None, on_done=None, on_error=None, *, cancel=None
    ):
        self.add(
            task,
            on_success=on_success,
            on_done=on_done,
            on_error=on_error,
            cancel=cancel,
        )
        self.start()

    def run(self):
        while True:
            if self._stopping:
                break
            task = self.tasks.get()  # type: TaskThread.Task
            self._cur_task = task
            if not task or self._stopping:
                break
            try:
                result = task.task()
                self.doneSig.emit(result, task.cb_done, task.cb_success)
            except BaseException:
                self.doneSig.emit(sys.exc_info(), task.cb_done, task.cb_error)

    def on_done(self, result, cb_done, cb_result):
        # This runs in the parent's thread.
        if cb_done:
            cb_done(result)
        if cb_result:
            cb_result(result)

    def stop(self):
        self._stopping = True
        # try to cancel currently running task now.
        # if the task does not implement "cancel", we will have to wait until it finishes.
        task = self._cur_task
        if task and task.cancel:
            task.cancel()
        # cancel the remaining tasks in the queue
        while True:
            try:
                task = self.tasks.get_nowait()
            except queue.Empty:
                break
            if task and task.cancel:
                task.cancel()
        self.tasks.put(None)  # in case the thread is still waiting on the queue
        self.exit()
        self.wait()


class NoThread:
    "This is great for debugging purposes"

    def __init__(self, *args):
        pass

    def add_and_start(
        self,
        task,
        on_success=None,
        on_done=None,
        on_error=None,
    ):
        result = None
        try:
            if task:
                result = task()
            if on_success:
                on_success(result)
        except Exception as e:
            if on_error:
                on_error(sys.exc_info())
        if on_done:
            on_done(result)
