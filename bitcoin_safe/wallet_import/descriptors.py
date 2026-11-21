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

"""Descriptor checksum, BIP32/SLIP132 public key conversion, safe constructors."""

from __future__ import annotations

import hashlib
import re

from .model import ExchangeError, Keystore

CHARSET = "0123456789()[],'/*abcdefgh@:$%{}IJKLMNOPQRSTUVWXYZ&+-.;<=>?!^_|~ijklmnopqrstuvwxyzABCDEFGH`#\"\\ "
CHECKSUM_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VERSION = {
    0x0488B21E: (0x0488B21E, "mainnet", "xpub"),  # xpub
    0x049D7CB2: (0x0488B21E, "mainnet", "ypub"),
    0x04B24746: (0x0488B21E, "mainnet", "zpub"),
    0x0295B43F: (0x0488B21E, "mainnet", "Ypub"),
    0x02AA7ED3: (0x0488B21E, "mainnet", "Zpub"),
    0x043587CF: (0x043587CF, "testnet", "tpub"),
    0x044A5262: (0x043587CF, "testnet", "upub"),
    0x045F1CF6: (0x043587CF, "testnet", "vpub"),
    0x024289EF: (0x043587CF, "testnet", "Upub"),
    0x02575483: (0x043587CF, "testnet", "Vpub"),
}
PUB_RE = re.compile(
    r"(?P<origin>\[[0-9a-fA-F]{8}(?:/[0-9]+[hH']?)*\])?"
    r"(?P<key>(?:xpub|ypub|zpub|Ypub|Zpub|tpub|upub|vpub|Upub|Vpub)[1-9A-HJ-NP-Za-km-z]+)"
    r"(?P<suffix>(?:/[0-9*;<>hH'\-]+)*)"
)


def _polymod(c: int, value: int) -> int:
    top = c >> 35
    c = ((c & 0x7FFFFFFFF) << 5) ^ value
    for i, g in enumerate((0xF5DEE51989, 0xA9FDCA3312, 0x1BAB10E32D, 0x3706B1677A, 0x644D626FFD)):
        if (top >> i) & 1:
            c ^= g
    return c


def descriptor_checksum(desc: str) -> str:
    c, cls, cls_count = 1, 0, 0
    for ch in desc:
        pos = CHARSET.find(ch)
        if pos < 0:
            raise ExchangeError(f"Character not allowed in descriptor: {ch!r}")
        c = _polymod(c, pos & 31)
        cls = cls * 3 + (pos >> 5)
        cls_count += 1
        if cls_count == 3:
            c = _polymod(c, cls)
            cls = cls_count = 0
    if cls_count:
        c = _polymod(c, cls)
    for _ in range(8):
        c = _polymod(c, 0)
    c ^= 1
    return "".join(CHECKSUM_CHARSET[(c >> (5 * (7 - i))) & 31] for i in range(8))


def strip_checksum(desc: str) -> str:
    desc = desc.strip()
    if "#" in desc:
        value, checksum = desc.rsplit("#", 1)
        if checksum != descriptor_checksum(value):
            raise ExchangeError("Descriptor checksum mismatch")
        return value
    return desc


def add_checksum(desc: str) -> str:
    desc = strip_checksum(desc)
    # Exchange format is watch-only, even if a source wallet has master keys.
    if re.search(r"(?i)(?:xprv|tprv|yprv|zprv|uprv|vprv|Yprv|Zprv|Uprv|Vprv)[1-9A-HJ-NP-Za-km-z]{20,}", desc):
        raise ExchangeError("Private extended keys are forbidden in watch-only descriptors")
    # WIF private keys cannot be retained either. Public compressed keys and
    # xpubs are allowed, but only recognized BIP32 keys create keystores.
    if re.search(r"(?<![0-9A-Za-z])[5KL9c][1-9A-HJ-NP-Za-km-z]{50,51}(?![0-9A-Za-z])", desc):
        raise ExchangeError("Private WIF keys are forbidden in descriptors")
    return desc + "#" + descriptor_checksum(desc)


def b58decode_check(key: str) -> bytes:
    number = 0
    for char in key:
        try:
            number = number * 58 + B58.index(char)
        except ValueError as exc:
            raise ExchangeError("Invalid base58 character") from exc
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    raw = b"\x00" * (len(key) - len(key.lstrip("1"))) + raw
    if len(raw) < 5:
        raise ExchangeError("Base58Check too short")
    payload, check = raw[:-4], raw[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != check:
        raise ExchangeError("Bad Base58Check checksum")
    return payload


def b58encode_check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n = int.from_bytes(data, "big")
    chars = []
    while n:
        n, i = divmod(n, 58)
        chars.append(B58[i])
    return "1" * (len(data) - len(data.lstrip(b"\x00"))) + "".join(reversed(chars))


def normalize_xpub(key: str) -> tuple[str, str, str]:
    """Return (canonical xpub/tpub, network-family, original SLIP132 prefix)."""
    payload = b58decode_check(key)
    if len(payload) != 78 or payload[45] not in (2, 3):
        raise ExchangeError("Not a public BIP32 extended key")
    v = int.from_bytes(payload[:4], "big")
    if v not in VERSION:
        raise ExchangeError("Unsupported extended public key version")
    canonical, network, prefix = VERSION[v]
    return b58encode_check(canonical.to_bytes(4, "big") + payload[4:]), network, prefix


def norm_path(path: str | None) -> str | None:
    if not path:
        return None
    p = str(path).replace("'", "h").replace("H", "h")
    if not p.startswith("m"):
        p = "m/" + p.lstrip("/")
    return p


def origin_expression(ks: Keystore) -> str:
    if not ks.xpub:
        raise ExchangeError("Cannot create a descriptor without a public key")
    origin = ""
    if ks.fingerprint:
        origin = ks.fingerprint.lower()
        p = norm_path(ks.key_origin)
        if p and p != "m":
            origin += "/" + p.removeprefix("m/")
        origin = f"[{origin}]"
    return origin + ks.xpub + (ks.derivation_suffix or "")


def descriptor_for_keys(
    keystores: list[Keystore],
    script_type: str,
    threshold: int | None = None,
    ordered_multisig: bool | None = None,
) -> str | None:
    """Don't guess multisig ordering: pass ordered_multisig=True for multi,
    False for sortedmulti, and None when the policy is unknown.
    """
    if not keystores or any(not k.xpub for k in keystores):
        return None
    aliases = {
        "P2PKH": "pkh",
        "P2WPKH": "wpkh",
        "P2TR": "tr",
        "P2SH_P2WPKH": "sh-wpkh",
        "P2SH-P2WPKH": "sh-wpkh",
        "P2WSH": "wsh",
        "P2SH_P2WSH": "sh-wsh",
        "P2SH-P2WSH": "sh-wsh",
        # Bare P2SH is ambiguous (may be legacy multisig); never guess.
        "P2SH_P2WPKH_V0": "sh-wpkh",
        "bech32": "wpkh",
        "p2sh-segwit": "sh-wpkh",
        "taproot": "tr",
        "p2pkh": "pkh",
        "p2wpkh": "wpkh",
        "p2wpkh-p2sh": "sh-wpkh",
        "p2tr": "tr",
    }
    script = aliases.get(script_type, script_type).lower()
    keys = [origin_expression(k) for k in keystores]
    if len(keys) == 1:
        expression = {
            "pkh": f"pkh({keys[0]})",
            "wpkh": f"wpkh({keys[0]})",
            "sh-wpkh": f"sh(wpkh({keys[0]}))",
            "tr": f"tr({keys[0]})",
        }.get(script)
    else:
        if threshold is None or not 1 <= threshold <= len(keys) or ordered_multisig is None:
            return None
        func = "multi" if ordered_multisig else "sortedmulti"
        inner = f"{func}({threshold},{','.join(keys)})"
        expression = {"wsh": f"wsh({inner})", "sh-wsh": f"sh(wsh({inner}))"}.get(script)
    return add_checksum(expression) if expression else None


def combine_receive_change(receive: str | None, change: str | None) -> str | None:
    if not receive:
        return None
    recv = strip_checksum(receive)
    if "<0;1>" in recv:
        return add_checksum(recv)
    if not change:
        return None
    chg = strip_checksum(change)
    # Convert ONLY if every branch occurrence and the complete rest of the
    # expression match. A mismatch is a migration blocker, not a guess.
    recv_candidates = re.findall(r"/[01]/\*", recv)
    if not recv_candidates or "/0/*" not in recv_candidates:
        return None
    combined_r = recv.replace("/0/*", "/<0;1>/*")
    combined_c = chg.replace("/1/*", "/<0;1>/*")
    if combined_r != combined_c:
        return None
    return add_checksum(combined_r)


def parse_keystores_from_descriptor(descriptor: str) -> list[Keystore]:
    body = strip_checksum(descriptor)
    found: list[Keystore] = []
    for match in PUB_RE.finditer(body):
        key, network, prefix = normalize_xpub(match.group("key"))
        origin = match.group("origin")
        fingerprint, path = None, None
        if origin:
            pieces = origin[1:-1].split("/")
            fingerprint = pieces[0].lower()
            if len(pieces) > 1:
                path = norm_path("/".join(pieces[1:]))
        found.append(
            Keystore(
                xpub=key,
                fingerprint=fingerprint,
                key_origin=path,
                derivation_suffix=match.group("suffix"),
                raw_xpub_prefix=prefix,
            )
        )
    return found


def infer_script_type(desc: str | None) -> str | None:
    if not desc:
        return None
    d = strip_checksum(desc)
    if d.startswith("sh(wsh("):
        return "sh-wsh"
    if d.startswith("wsh("):
        return "wsh"
    if d.startswith("sh(wpkh("):
        return "sh-wpkh"
    for script in ("wpkh", "pkh", "tr"):
        if d.startswith(script + "("):
            return script
    return None


def infer_network(keys: list[Keystore]) -> str:
    families = set()
    for key in keys:
        if key.xpub:
            families.add(normalize_xpub(key.xpub)[1])
    if len(families) > 1:
        raise ExchangeError("Mixed mainnet and non-mainnet public keys")
    return next(iter(families), "unknown")
