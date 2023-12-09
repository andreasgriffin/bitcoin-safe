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
import traceback
import urllib
import threading
import hmac
import stat
import locale
import asyncio
import urllib.request, urllib.parse, urllib.error
import builtins
import json
import time
from typing import NamedTuple, Optional
import ssl
import ipaddress
from ipaddress import IPv4Address, IPv6Address
import random
import secrets
import functools
from abc import abstractmethod, ABC
import socket
import enum

import aiohttp
from aiohttp_socks import ProxyConnector, ProxyType
import aiorpcx
import certifi
import dns.resolver
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

from PySide2 import QtWidgets, QtCore
from PySide2.QtGui import (
    QFont,
    QColor,
    QCursor,
    QPixmap,
    QStandardItem,
    QImage,
    QPalette,
    QIcon,
    QFontMetrics,
    QShowEvent,
    QPainter,
    QHelpEvent,
    QMouseEvent,
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


ca_path = certifi.where()


base_units = {"BTC": 8, "mBTC": 5, "bits": 2, "sat": 0}
base_units_inverse = inv_dict(base_units)
base_units_list = ["BTC", "mBTC", "bits", "sat"]  # list(dict) does not guarantee order

DECIMAL_POINT_DEFAULT = 5  # mBTC


class UnknownBaseUnit(Exception):
    pass


import bdkpython as bdk
import hashlib


def replace_non_alphanumeric(string):
    return re.sub(r"\W+", "_", string)


def hash_string(text):
    return hashlib.sha256(text.encode()).hexdigest()


def cache_method(func):
    "Only use this method with arguments that can be represented as a string"

    def wrapper(self, *args, **kwargs):
        cache_key = f"{func.__name__}({args, kwargs})"
        result = self.cache.get(cache_key)
        if result:
            return result

        result = func(self, *args, **kwargs)
        self.cache[cache_key] = result
        return result

    return wrapper


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


def decimal_point_to_base_unit_name(dp: int) -> str:
    # e.g. 8 -> "BTC"
    try:
        return base_units_inverse[dp]
    except KeyError:
        raise UnknownBaseUnit(dp) from None


def base_unit_name_to_decimal_point(unit_name: str) -> int:
    # e.g. "BTC" -> 8
    try:
        return base_units[unit_name]
    except KeyError:
        raise UnknownBaseUnit(unit_name) from None


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


def to_decimal(x: Union[str, float, int, Decimal]) -> Decimal:
    # helper function mainly for float->Decimal conversion, i.e.:
    #   >>> Decimal(41754.681)
    #   Decimal('41754.680999999996856786310672760009765625')
    #   >>> Decimal("41754.681")
    #   Decimal('41754.681')
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


class Satoshis:
    def __init__(self, value, network: bdk.Network):
        self.network = network
        self.value = int(value)

    def __repr__(self):
        return f"Satoshis({self.value})"

    def __str__(self):
        # note: precision is truncated to satoshis here
        return format_satoshis(self.value, self.network)

    def __eq__(self, other):
        return (self.value == other.value) and (self.network == other.network)

    def __ne__(self, other):
        return not (self == other)

    def __add__(self, other):
        assert self.network == other.network
        return Satoshis(self.value + other.value, self.network)

    def str_with_unit(self):
        return format_satoshis(self.value, self.network, str_unit=True)

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


def json_encode(obj):
    try:
        s = json.dumps(obj, sort_keys=True, indent=4, cls=MyEncoder)
    except TypeError:
        s = repr(obj)
    return s


def json_decode(x):
    try:
        return json.loads(x, parse_float=Decimal)
    except:
        return x


def json_normalize(x):
    # note: The return value of commands, when going through the JSON-RPC interface,
    #       is json-encoded. The encoder used there cannot handle some types, e.g. electrum.util.Satoshis.
    # note: We should not simply do "json_encode(x)" here, as then later x would get doubly json-encoded.
    # see #5868
    return json_decode(json_encode(x))


# taken from Django Source Code
def constant_time_compare(val1, val2):
    """Return True if the two strings are equal, False otherwise."""
    return hmac.compare_digest(to_bytes(val1, "utf8"), to_bytes(val2, "utf8"))


# decorator that prints execution time
_profiler_logger = logger.getChild("profiler")


def profiler(func):
    def do_profile(args, kw_args):
        name = func.__qualname__
        t0 = time.time()
        o = func(*args, **kw_args)
        t = time.time() - t0
        _profiler_logger.debug(f"{name} {t:,.4f} sec")
        return o

    return lambda *args, **kw_args: do_profile(args, kw_args)


def android_ext_dir():
    from android.storage import primary_external_storage_path

    return primary_external_storage_path()


def android_backup_dir():
    pkgname = get_android_package_name()
    d = os.path.join(android_ext_dir(), pkgname)
    if not os.path.exists(d):
        os.mkdir(d)
    return d


def android_data_dir():
    import jnius

    PythonActivity = jnius.autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity.getFilesDir().getPath() + "/data"


def ensure_sparse_file(filename):
    # On modern Linux, no need to do anything.
    # On Windows, need to explicitly mark file.
    if os.name == "nt":
        try:
            os.system('fsutil sparse setflag "{}" 1'.format(filename))
        except Exception as e:
            logger.info(f"error marking file {filename} as sparse: {e}")


def get_headers_dir(config):
    return config.path


def assert_datadir_available(config_path):
    path = config_path
    if os.path.exists(path):
        return
    else:
        raise FileNotFoundError(
            "Electrum datadir does not exist. Was it deleted while running?"
            + "\n"
            + "Should be at {}".format(path)
        )


def assert_file_in_datadir_available(path, config_path):
    if os.path.exists(path):
        return
    else:
        assert_datadir_available(config_path)
        raise FileNotFoundError(
            "Cannot find file but datadir is there."
            + "\n"
            + "Should be at {}".format(path)
        )


def standardize_path(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(path))))


def get_new_wallet_name(wallet_folder: str) -> str:
    """Returns a file basename for a new wallet to be used.
    Can raise OSError.
    """
    i = 1
    while True:
        filename = "wallet_%d" % i
        if filename in os.listdir(wallet_folder):
            i += 1
        else:
            break
    return filename


def is_android_debug_apk() -> bool:
    is_android = "ANDROID_DATA" in os.environ
    if not is_android:
        return False
    from jnius import autoclass

    pkgname = get_android_package_name()
    build_config = autoclass(f"{pkgname}.BuildConfig")
    return bool(build_config.DEBUG)


def get_android_package_name() -> str:
    is_android = "ANDROID_DATA" in os.environ
    assert is_android
    from jnius import autoclass
    from android.config import ACTIVITY_CLASS_NAME

    activity = autoclass(ACTIVITY_CLASS_NAME).mActivity
    pkgname = str(activity.getPackageName())
    return pkgname


def assert_bytes(*args):
    """
    porting helper, assert args type
    """
    try:
        for x in args:
            assert isinstance(x, (bytes, bytearray))
    except:
        print("assert bytes failed", list(map(type, args)))
        raise


def assert_str(*args):
    """
    porting helper, assert args type
    """
    for x in args:
        assert isinstance(x, str)


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


bfh = bytes.fromhex


def xor_bytes(a: bytes, b: bytes) -> bytes:
    size = min(len(a), len(b))
    return (int.from_bytes(a[:size], "big") ^ int.from_bytes(b[:size], "big")).to_bytes(
        size, "big"
    )


def user_dir():
    if "ELECTRUMDIR" in os.environ:
        return os.environ["ELECTRUMDIR"]
    elif "ANDROID_DATA" in os.environ:
        return android_data_dir()
    elif os.name == "posix":
        return os.path.join(os.environ["HOME"], ".electrum")
    elif "APPDATA" in os.environ:
        return os.path.join(os.environ["APPDATA"], "Electrum")
    elif "LOCALAPPDATA" in os.environ:
        return os.path.join(os.environ["LOCALAPPDATA"], "Electrum")
    else:
        # raise Exception("No home directory found in environment variables.")
        return


def resource_path(*parts):
    return os.path.join(pkg_dir, *parts)


# absolute path to python package folder of electrum ("lib")
pkg_dir = os.path.split(os.path.realpath(__file__))[0]


def is_valid_email(s):
    regexp = r"[^@]+@[^@]+\.[^@]+"
    return re.match(regexp, s) is not None


def is_hash256_str(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    if len(text) != 64:
        return False
    return is_hex_str(text)


def is_hex_str(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    try:
        b = bytes.fromhex(text)
    except:
        return False
    # forbid whitespaces in text:
    if len(text) != 2 * len(b):
        return False
    return True


def is_integer(val: Any) -> bool:
    return isinstance(val, int)


def is_non_negative_integer(val: Any) -> bool:
    if is_integer(val):
        return val >= 0
    return False


def is_int_or_float(val: Any) -> bool:
    return isinstance(val, (int, float))


def is_non_negative_int_or_float(val: Any) -> bool:
    if is_int_or_float(val):
        return val >= 0
    return False


def chunks(items, size: int):
    """Break up items, an iterable, into chunks of length size."""
    if size < 1:
        raise ValueError(f"size must be positive, not {repr(size)}")
    for i in range(0, len(items), size):
        yield items[i : i + size]


# Check that Decimal precision is sufficient.
# We need at the very least ~20, as we deal with msat amounts, and
# log10(21_000_000 * 10**8 * 1000) ~= 18.3
# decimal.DefaultContext.prec == 28 by default, but it is mutable.
# We enforce that we have at least that available.
assert (
    decimal.getcontext().prec >= 28
), f"PyDecimal precision too low: {decimal.getcontext().prec}"

# DECIMAL_POINT = locale.localeconv()['decimal_point']  # type: str
DECIMAL_POINT = "."
THOUSANDS_SEP = " "
assert len(DECIMAL_POINT) == 1, f"DECIMAL_POINT has unexpected len. {DECIMAL_POINT!r}"
assert len(THOUSANDS_SEP) == 1, f"THOUSANDS_SEP has unexpected len. {THOUSANDS_SEP!r}"


def unit_str(network: bdk.Network):
    return "BTC" if network is None or network == bdk.Network.BITCOIN else "tBTC"


def format_satoshis(
    x: Union[int, float, Decimal, str, Satoshis, None],  # amount in satoshis
    network: bdk.Network,
    is_diff: bool = False,  # if True, enforce a leading sign (+/-)
    add_thousands_sep: bool = True,  # if True, add whitespaces, for better readability of the numbers
    add_satohis_whitesapces: bool = True,
    str_unit=None,
) -> str:
    decimal_point = 8

    locale = QLocale.system()
    decimal_separator = locale.decimalPoint()

    if x is None:
        return "unknown"
    if parse_max_spend(x):
        return f"max({x})"
    assert isinstance(x, (int, float, Decimal, Satoshis)), f"{x!r} should be a number"
    # lose redundant precision
    x = Decimal(x)

    # format string
    decimal_format = "." + str(decimal_point) if decimal_point > 0 else ""
    if is_diff:
        decimal_format = "+" + decimal_format
    # initial result
    scale_factor = pow(10, decimal_point)
    result = ("{:" + decimal_format + "f}").format(x / scale_factor)

    # add extra decimal places (zeros)
    integer_part, fract_part = result.split(".")

    # add whitespaces as thousands' separator for better readability of numbers
    if add_thousands_sep:
        sign = integer_part[0] if integer_part[0] in ("+", "-") else ""
        if sign == "-":
            integer_part = integer_part[1:]
        integer_part = "{:,}".format(int(integer_part)).replace(",", THOUSANDS_SEP)
        integer_part = sign + integer_part

    if add_satohis_whitesapces:
        fract_part = THOUSANDS_SEP.join(
            [fract_part[0:2], fract_part[2:5], fract_part[5:]]
        )

    result = integer_part + DECIMAL_POINT + fract_part

    def strip(v):
        return (
            str(v)
            .strip()
            .replace(" ", "")
            .replace(THOUSANDS_SEP, "")
            .replace(DECIMAL_POINT, "")
            .replace(",", "")
        )

    # sanity check that the number wasn't changed
    assert int(strip(result)) == int(strip(x))

    if str_unit:
        result += f" {unit_str(network)}"
    return result


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
