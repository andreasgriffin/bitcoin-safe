#
# Bitcoin-Safe
# Copyright (C) 2026 Andreas Griffin
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
#

"""Only metadata actually serialized into the account xpub can be checked."""

import pytest
from hwilib import _base58

from bitcoin_safe.xpub_utils import b58decode_check, check_xpub_origin_depth_and_child_number

PUBKEY = bytes.fromhex("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")


def make_xpub(depth: int, child: int, *, testnet: bool = False) -> str:
    version = bytes.fromhex("043587cf" if testnet else "0488b21e")
    payload = version + bytes([depth]) + b"\x00" * 4 + child.to_bytes(4, "big") + b"\x12" * 32 + PUBKEY
    return _base58.encode_check(payload)


def test_base58check_validation() -> None:
    assert b58decode_check("111E1CgqW") == b"\x00\x00\x00\x01"
    for invalid in ("0", "", "3QJmnh", "111E1CgqX"):
        with pytest.raises(ValueError):
            b58decode_check(invalid)


@pytest.mark.parametrize("testnet", [False, True])
def test_matching_metadata_passes_without_seed(testnet: bool) -> None:
    xpub = make_xpub(3, 0x80000007, testnet=testnet)
    check_xpub_origin_depth_and_child_number(xpub, "m/84h/1h/7h")
    check_xpub_origin_depth_and_child_number(xpub, "m/49'/0'/7'")


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("m/84h/1h/7h/0", "depth"),
        ("m/84h/1h/6h", "final child number"),
        ("m/84h/1h/7", "final child number"),
        ("m/84h/1h/2147483648h", "range"),
        ("m/84h/1h/nope", "invalid child index"),
        ("84h/1h/7h", "start with"),
    ],
)
def test_inconsistent_metadata_is_rejected(path: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        check_xpub_origin_depth_and_child_number(make_xpub(3, 0x80000007), path)


def test_checksum_is_checked_and_master_depth_is_supported() -> None:
    root = make_xpub(0, 0)
    check_xpub_origin_depth_and_child_number(root, "m")
    with pytest.raises(ValueError, match="depth"):
        check_xpub_origin_depth_and_child_number(root, "m/0")
    with pytest.raises(ValueError, match="checksum"):
        check_xpub_origin_depth_and_child_number(root[:-1] + ("1" if root[-1] != "1" else "2"), "m")
