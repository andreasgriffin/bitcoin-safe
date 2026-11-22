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

"""Network-independent, public BIP32 metadata utilities."""

from __future__ import annotations

import re

from hwilib import _base58
from hwilib.errors import BadArgumentError

_XPUB_VERSIONS = {bytes.fromhex("0488b21e"), bytes.fromhex("043587cf")}
_PATH_COMPONENT = re.compile(r"([0-9]+)(h?)\Z")


def b58decode_check(value: str) -> bytes:
    """Decode Base58Check and reject an invalid checksum or alphabet."""
    try:
        payload = _base58.decode_check(value)
    except BadArgumentError as exc:
        raise ValueError("Invalid base58 character") from exc
    if not payload:
        raise ValueError("Base58Check too short")
    return payload


def check_xpub_origin_depth_and_child_number(xpub: str, key_origin: str) -> None:
    """Check only the origin depth and final child number encoded in an xpub/tpub.

    The extended public key encodes its BIP32 depth and the index (including
    its hardened bit) of the final derivation step. Reject origins that
    disagree with either field. This does NOT authenticate earlier (especially
    hardened) path components, the master fingerprint, or the Bitcoin network
    within the testnet family. Verify those using a trusted source/device.

    Raises ValueError for malformed input or contradictory metadata.
    """
    payload = b58decode_check(xpub)
    if len(payload) != 78 or payload[:4] not in _XPUB_VERSIONS or payload[45] not in (2, 3):
        raise ValueError("Expected a serialized xpub or tpub")
    if not isinstance(key_origin, str):
        raise ValueError("Xpub origin must be a derivation path")
    normalized = key_origin.strip().replace("'", "h").replace("H", "h")
    if normalized == "m":
        parts = []
    elif normalized.startswith("m/"):
        parts = normalized[2:].split("/")
    else:
        raise ValueError("Xpub origin must start with m/")

    if len(parts) != payload[4]:
        raise ValueError("Xpub origin depth does not match xpub")

    final_child = None
    for part in parts:
        match = _PATH_COMPONENT.fullmatch(part)
        if match is None:
            raise ValueError("Xpub origin contains an invalid child index")
        index = int(match.group(1))
        if not 0 <= index < 2**31:
            raise ValueError("Xpub origin child index is outside BIP32 range")
        final_child = index | (0x80000000 if match.group(2) else 0)

    if final_child is not None and final_child != int.from_bytes(payload[9:13], "big"):
        raise ValueError("Xpub origin final child number does not match xpub")
