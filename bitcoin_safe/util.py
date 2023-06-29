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
import base64
from .i18n import _

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


def cache_method(func):
    "Only use this method with arguments that can be represented as a string"

    def wrapper(self, *args, **kwargs):
        cache_key = f"{func.__name__}({args, kwargs})"
        if self.cache.get(cache_key):
            return self.cache.get(cache_key)

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


# note: this is not a NamedTuple as then its json encoding cannot be customized
class Satoshis(object):
    __slots__ = ("value",)

    def __new__(cls, value):
        self = super(Satoshis, cls).__new__(cls)
        # note: 'value' sometimes has msat precision
        self.value = int(value)
        return self

    def __repr__(self):
        return f"Satoshis({self.value})"

    def __str__(self):
        # note: precision is truncated to satoshis here
        return format_satoshis(self.value)

    def __eq__(self, other):
        return self.value == other.value

    def __ne__(self, other):
        return not (self == other)

    def __add__(self, other):
        return Satoshis(self.value + other.value)

    def str_with_unit(self):
        return format_satoshis(self.value, str_unit=True)


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


def format_satoshis_plain(
    x: Union[int, float, Decimal, str],  # amount in satoshis,
    *,
    decimal_point: int = 8,  # how much to shift decimal point to left (default: sat->BTC)
) -> str:
    """Display a satoshi amount scaled.  Always uses a '.' as a decimal
    point and has no thousands separator"""
    if parse_max_spend(x):
        return f"max({x})"
    assert isinstance(x, (int, float, Decimal)), f"{x!r} should be a number"
    scale_factor = pow(10, decimal_point)
    return "{:.8f}".format(Decimal(x) / scale_factor).rstrip("0").rstrip(".")


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


def format_satoshis(
    x: Union[int, float, Decimal, str, Satoshis, None],  # amount in satoshis
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
        result += " BTC"
    return result


FEERATE_PRECISION = 1  # num fractional decimal places for sat/byte fee rates
_feerate_quanta = Decimal(10) ** (-FEERATE_PRECISION)


def format_fee_satoshis(fee, *, num_zeros=0, precision=None):
    return format_satoshis(fee)


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

_block_explorer_default_api_loc = {"tx": "tx/", "addr": "address/"}


def block_explorer_info(network: bdk.Network):
    if network in [bdk.Network.TESTNET, bdk.Network.REGTEST]:
        return testnet_block_explorers
    elif network == bdk.Network.SIGNET:
        return signet_block_explorers
    return mainnet_block_explorers


def block_explorer_tuple(config: "UserConfig") -> Optional[Tuple[str, dict]]:
    custom_be = config.get("block_explorer_custom")
    if custom_be:
        if isinstance(custom_be, str):
            return custom_be, _block_explorer_default_api_loc
        if isinstance(custom_be, (tuple, list)) and len(custom_be) == 2:
            return tuple(custom_be)
        logger.warning(
            f"not using 'block_explorer_custom' from config. "
            f"expected a str or a pair but got {custom_be!r}"
        )
        return None
    else:
        # using one of the hardcoded block explorers
        return block_explorer_info(config.network_settings.network).get(
            config.block_explorer
        )


def block_explorer_URL(config: "UserConfig", kind: str, item: str) -> Optional[str]:
    be_tuple = block_explorer_tuple(config)
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


def decode_serialized_string(input_string):
    input_string = input_string.strip()

    # Regular expression for a serialized transaction (hex string)
    serialized_transaction_pattern = re.compile("^[a-fA-F0-9]*$")

    # Regular expression for a Bitcoin address (starts with 1, 3 or bc1)
    bitcoin_address_pattern = re.compile("^(1|3|bc1)[a-zA-Z0-9]*$")

    # Check if the input string matches the pattern for a serialized transaction
    if serialized_transaction_pattern.fullmatch(input_string):
        # Check if it's a txid
        if len(input_string) == 64:
            return "txid"
        # Check if it's a PSBT
        elif input_string.lower().startswith("70736274ff"):
            return bdk.PartiallySignedTransaction(bytes.fromhex(input_string))
        # Check if it's a serialized transaction
        elif len(input_string) > 40:
            return bdk.Transaction(hex_to_serialized(input_string))

    # Check if the input string matches the pattern for a Bitcoin address
    elif bitcoin_address_pattern.fullmatch(input_string):
        return bdk.Address(input_string)

    # Check for base64 PSBT
    elif input_string.startswith("cHNidP"):
        try:
            # Attempt to decode the base64 string
            decoded = base64.b64decode(input_string)
            # Check if decoded string starts with the magic bytes for PSBT
            if decoded[:5] == b"psbt\xff":
                return bdk.PartiallySignedTransaction(input_string)
        except Exception:
            pass

    # Regular expression for a serialized transaction (hex string)
    serialized_transaction_pattern = re.compile("^[a-fA-F0-9]*$")

    # Regular expression for a Bitcoin address (starts with 1, 3 or bc1)
    bitcoin_address_pattern = re.compile("^(1|3|bc1)[a-zA-Z0-9]*$")

    # Check if the input string matches the pattern for a serialized transaction
    if (
        serialized_transaction_pattern.fullmatch(input_string)
        and len(input_string) > 40
    ):  # 40 is arbitrary, but a tx should be longer than this
        return bdk.Transaction(serialized_to_hex(input_string))

    # Check if the input string matches the pattern for a Bitcoin address
    elif bitcoin_address_pattern.fullmatch(input_string):
        return bdk.Address(input_string)

    # If it matches neither pattern
    return None


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


class OrderedDictWithIndex(OrderedDict):
    """An OrderedDict that keeps track of the positions of keys.

    Note: very inefficient to modify contents, except to add new items.
    """

    def __init__(self):
        super().__init__()
        self._key_to_pos = {}
        self._pos_to_key = {}

    def _recalc_index(self):
        self._key_to_pos = {key: pos for (pos, key) in enumerate(self.keys())}
        self._pos_to_key = {pos: key for (pos, key) in enumerate(self.keys())}

    def pos_from_key(self, key):
        return self._key_to_pos[key]

    def value_from_pos(self, pos):
        key = self._pos_to_key[pos]
        return self[key]

    def popitem(self, *args, **kwargs):
        ret = super().popitem(*args, **kwargs)
        self._recalc_index()
        return ret

    def move_to_end(self, *args, **kwargs):
        ret = super().move_to_end(*args, **kwargs)
        self._recalc_index()
        return ret

    def clear(self):
        ret = super().clear()
        self._recalc_index()
        return ret

    def pop(self, *args, **kwargs):
        ret = super().pop(*args, **kwargs)
        self._recalc_index()
        return ret

    def update(self, *args, **kwargs):
        ret = super().update(*args, **kwargs)
        self._recalc_index()
        return ret

    def __delitem__(self, *args, **kwargs):
        ret = super().__delitem__(*args, **kwargs)
        self._recalc_index()
        return ret

    def __setitem__(self, key, *args, **kwargs):
        is_new_key = key not in self
        ret = super().__setitem__(key, *args, **kwargs)
        if is_new_key:
            pos = len(self) - 1
            self._key_to_pos[key] = pos
            self._pos_to_key[pos] = key
        return ret


def multisig_type(wallet_type):
    """If wallet_type is mofn multi-sig, return [m, n],
    otherwise return None."""
    if not wallet_type:
        return None
    match = re.match(r"(\d+)of(\d+)", wallet_type)
    if match:
        match = [int(x) for x in match.group(1, 2)]
    return match


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


def list_enabled_bits(x: int) -> Sequence[int]:
    """e.g. 77 (0b1001101) --> (0, 2, 3, 6)"""
    binary = bin(x)[2:]
    rev_bin = reversed(binary)
    return tuple(i for i, b in enumerate(rev_bin) if b == "1")


def resolve_dns_srv(host: str):
    srv_records = dns.resolver.resolve(host, "SRV")
    # priority: prefer lower
    # weight: tie breaker; prefer higher
    srv_records = sorted(srv_records, key=lambda x: (x.priority, -x.weight))

    def dict_from_srv_record(srv):
        return {
            "host": str(srv.target),
            "port": srv.port,
        }

    return [dict_from_srv_record(srv) for srv in srv_records]


def randrange(bound: int) -> int:
    """Return a random integer k such that 1 <= k < bound, uniformly
    distributed across that range."""
    # secrets.randbelow(bound) returns a random int: 0 <= r < bound,
    # hence transformations:
    return secrets.randbelow(bound - 1) + 1


class CallbackManager:
    # callbacks set by the GUI or any thread
    # guarantee: the callbacks will always get triggered from the asyncio thread.

    def __init__(self):
        self.callback_lock = threading.Lock()
        self.callbacks = defaultdict(list)  # note: needs self.callback_lock

    def register_callback(self, func, events):
        with self.callback_lock:
            for event in events:
                self.callbacks[event].append(func)

    def unregister_callback(self, callback):
        with self.callback_lock:
            for callbacks in self.callbacks.values():
                if callback in callbacks:
                    callbacks.remove(callback)

    def trigger_callback(self, event, *args):
        """Trigger a callback with given arguments.
        Can be called from any thread. The callback itself will get scheduled
        on the event loop.
        """
        loop = get_asyncio_loop()
        assert loop.is_running(), "event loop not running"
        with self.callback_lock:
            callbacks = self.callbacks[event][:]
        for callback in callbacks:
            # FIXME: if callback throws, we will lose the traceback
            if asyncio.iscoroutinefunction(callback):
                asyncio.run_coroutine_threadsafe(callback(*args), loop)
            elif get_running_loop() == loop:
                # run callback immediately, so that it is guaranteed
                # to have been executed when this method returns
                callback(*args)
            else:
                loop.call_soon_threadsafe(callback, *args)


callback_mgr = CallbackManager()
trigger_callback = callback_mgr.trigger_callback
register_callback = callback_mgr.register_callback
unregister_callback = callback_mgr.unregister_callback
_event_listeners = defaultdict(set)  # type: Dict[str, Set[str]]


class EventListener:
    def _list_callbacks(self):
        for c in self.__class__.__mro__:
            classpath = f"{c.__module__}.{c.__name__}"
            for method_name in _event_listeners[classpath]:
                method = getattr(self, method_name)
                assert callable(method)
                assert method_name.startswith("on_event_")
                yield method_name[len("on_event_") :], method

    def register_callbacks(self):
        for name, method in self._list_callbacks():
            # logger.debug(f'registering callback {method}')
            register_callback(method, [name])

    def unregister_callbacks(self):
        for name, method in self._list_callbacks():
            # logger.debug(f'unregistering callback {method}')
            unregister_callback(method)


def event_listener(func):
    classname, method_name = func.__qualname__.split(".")
    assert method_name.startswith("on_event_")
    classpath = f"{func.__module__}.{classname}"
    _event_listeners[classpath].add(method_name)
    return func


_NetAddrType = TypeVar("_NetAddrType")


class NetworkRetryManager(Generic[_NetAddrType]):
    """Truncated Exponential Backoff for network connections."""

    def __init__(
        self,
        *,
        max_retry_delay_normal: float,
        init_retry_delay_normal: float,
        max_retry_delay_urgent: float = None,
        init_retry_delay_urgent: float = None,
    ):
        self._last_tried_addr = (
            {}
        )  # type: Dict[_NetAddrType, Tuple[float, int]]  # (unix ts, num_attempts)

        # note: these all use "seconds" as unit
        if max_retry_delay_urgent is None:
            max_retry_delay_urgent = max_retry_delay_normal
        if init_retry_delay_urgent is None:
            init_retry_delay_urgent = init_retry_delay_normal
        self._max_retry_delay_normal = max_retry_delay_normal
        self._init_retry_delay_normal = init_retry_delay_normal
        self._max_retry_delay_urgent = max_retry_delay_urgent
        self._init_retry_delay_urgent = init_retry_delay_urgent

    def _trying_addr_now(self, addr: _NetAddrType) -> None:
        last_time, num_attempts = self._last_tried_addr.get(addr, (0, 0))
        # we add up to 1 second of noise to the time, so that clients are less likely
        # to get synchronised and bombard the remote in connection waves:
        cur_time = time.time() + random.random()
        self._last_tried_addr[addr] = cur_time, num_attempts + 1

    def _on_connection_successfully_established(self, addr: _NetAddrType) -> None:
        self._last_tried_addr[addr] = time.time(), 0

    def _can_retry_addr(
        self, addr: _NetAddrType, *, now: float = None, urgent: bool = False
    ) -> bool:
        if now is None:
            now = time.time()
        last_time, num_attempts = self._last_tried_addr.get(addr, (0, 0))
        if urgent:
            max_delay = self._max_retry_delay_urgent
            init_delay = self._init_retry_delay_urgent
        else:
            max_delay = self._max_retry_delay_normal
            init_delay = self._init_retry_delay_normal
        delay = self.__calc_delay(
            multiplier=init_delay, max_delay=max_delay, num_attempts=num_attempts
        )
        next_time = last_time + delay
        return next_time < now

    @classmethod
    def __calc_delay(
        cls, *, multiplier: float, max_delay: float, num_attempts: int
    ) -> float:
        num_attempts = min(num_attempts, 100_000)
        try:
            res = multiplier * 2**num_attempts
        except OverflowError:
            return max_delay
        return max(0, min(max_delay, res))

    def _clear_addr_retry_times(self) -> None:
        self._last_tried_addr.clear()


class MySocksProxy(aiorpcx.SOCKSProxy):
    async def open_connection(self, host=None, port=None, **kwargs):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(loop=loop)
        protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
        transport, _ = await self.create_connection(
            lambda: protocol, host, port, **kwargs
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer

    @classmethod
    def from_proxy_dict(cls, proxy: dict = None) -> Optional["MySocksProxy"]:
        if not proxy:
            return None
        username, pw = proxy.get("user"), proxy.get("password")
        if not username or not pw:
            auth = None
        else:
            auth = aiorpcx.socks.SOCKSUserAuth(username, pw)
        addr = aiorpcx.NetAddress(proxy["host"], proxy["port"])
        if proxy["mode"] == "socks4":
            ret = cls(addr, aiorpcx.socks.SOCKS4a, auth)
        elif proxy["mode"] == "socks5":
            ret = cls(addr, aiorpcx.socks.SOCKS5, auth)
        else:
            raise NotImplementedError  # http proxy not available with aiorpcx
        return ret


class JsonRPCClient:
    def __init__(self, session: aiohttp.ClientSession, url: str):
        self.session = session
        self.url = url
        self._id = 0

    async def request(self, endpoint, *args):
        self._id += 1
        data = '{"jsonrpc": "2.0", "id":"%d", "method": "%s", "params": %s }' % (
            self._id,
            endpoint,
            json.dumps(args),
        )
        async with self.session.post(self.url, data=data) as resp:
            if resp.status == 200:
                r = await resp.json()
                result = r.get("result")
                error = r.get("error")
                if error:
                    return "Error: " + str(error)
                else:
                    return result
            else:
                text = await resp.text()
                return "Error: " + str(text)

    def add_method(self, endpoint):
        async def coro(*args):
            return await self.request(endpoint, *args)

        setattr(self, endpoint, coro)


T = TypeVar("T")


def random_shuffled_copy(x: Iterable[T]) -> List[T]:
    """Returns a shuffled copy of the input."""
    x_copy = list(x)  # copy
    random.shuffle(x_copy)  # shuffle in-place
    return x_copy


def test_read_write_permissions(path) -> None:
    # note: There might already be a file at 'path'.
    #       Make sure we do NOT overwrite/corrupt that!
    temp_path = "%s.tmptest.%s" % (path, os.getpid())
    echo = "fs r/w test"
    try:
        # test READ permissions for actual path
        if os.path.exists(path):
            with open(path, "rb") as f:
                f.read(1)  # read 1 byte
        # test R/W sanity for "similar" path
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(echo)
        with open(temp_path, "r", encoding="utf-8") as f:
            echo2 = f.read()
        os.remove(temp_path)
    except Exception as e:
        raise IOError(e) from e
    if echo != echo2:
        raise IOError("echo sanity-check failed")


class nullcontext:
    """Context manager that does no additional processing.
    This is a ~backport of contextlib.nullcontext from Python 3.10
    """

    def __init__(self, enter_result=None):
        self.enter_result = enter_result

    def __enter__(self):
        return self.enter_result

    def __exit__(self, *excinfo):
        pass

    async def __aenter__(self):
        return self.enter_result

    async def __aexit__(self, *excinfo):
        pass


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
