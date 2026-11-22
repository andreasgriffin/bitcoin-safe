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

"""Public-data importer for Wasabi wallet JSON.

Never fabricate the signing origin of an account xpub. A BIP32 xpub reveals
its depth and last child number, but not its complete hardened ancestry.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from hwilib._base58 import encode_check as b58encode_check

from .adapters import _public_key, _resolve_network
from .descriptors import (
    add_checksum,
    b58decode_check,
    descriptor_for_keys,
    norm_path,
    strip_checksum,
)
from .model import ExchangeError, Label, WalletExchange

_ORIGIN = re.compile(r"^m(?:/[0-9]+h?)+$")


def _check_wasabi_origin(path: str, account_xpub: str, network: str, purpose: int) -> str:
    """Reject contradictory signing origins; never infer an absent ancestor.

    Full BIP32 hardened ancestry cannot be authenticated with a public xpub.
    This verifies everything independently encoded in the xpub (depth and
    last child number) and the expected Wasabi account purpose/coin type.
    """
    canonical = norm_path(path)
    if not canonical or not _ORIGIN.fullmatch(canonical):
        raise ExchangeError("Wasabi account derivation path is missing or malformed")
    components = canonical.split("/")[1:]
    # Wasabi's account xpub uses BIP84/86 purpose'/coin'/account'.
    if len(components) != 3 or components[0] != f"{purpose}h":
        raise ExchangeError("Wasabi account origin has an unexpected purpose or BIP32 depth")
    # Wasabi intentionally uses Bitcoin coin type 0' on RegTest, unlike
    # TestNet/TestNet4/Signet which use coin type 1'. This is documented by
    # Wasabi itself and must not be "fixed" to BIP44's usual test coin type.
    coin = "0h" if network in ("mainnet", "regtest") else "1h"
    if components[1] != coin or not components[2].endswith("h"):
        raise ExchangeError("Wasabi account origin disagrees with the wallet network or account level")
    try:
        account = int(components[2][:-1])
    except ValueError as exc:
        raise ExchangeError("Invalid Wasabi BIP32 account number") from exc
    if not 0 <= account < 0x80000000:
        raise ExchangeError("Invalid Wasabi BIP32 account number")
    raw = b58decode_check(account_xpub)
    if len(raw) != 78 or raw[4] != len(components):
        raise ExchangeError("Wasabi derivation path depth disagrees with the account xpub")
    encoded_child = int.from_bytes(raw[9:13], "big")
    if encoded_child != (account | 0x80000000):
        raise ExchangeError("Wasabi derivation path account number disagrees with the account xpub")
    return canonical


def _canonical_regtest_xpub(keystore: Any, network: str) -> None:
    """Re-serialize Wasabi's RegTest xpub as a tpub for Bitcoin Safe.

    Wasabi's NBitcoin RegTest wallet export uses mainnet BIP32 public-version
    bytes, even though its output addresses belong to regtest. The xpub / tpub
    prefix is metadata, NOT part of the account key: rewrite ONLY its four
    version bytes (preserve depth, child, chaincode and compressed public key).

    This exception is limited to explicitly-declared RegTest exports; on
    TestNet/Signet a mainnet xpub still fails the ordinary network check.
    """
    if network != "regtest" or not keystore.xpub:
        return
    payload = b58decode_check(keystore.xpub)
    if payload[:4] != bytes.fromhex("0488b21e"):
        return  # Existing tpub is already correct.
    if keystore.raw_xpub_prefix != "xpub":
        raise ExchangeError("Unexpected Wasabi RegTest extended public key format")
    keystore.xpub = b58encode_check(bytes.fromhex("043587cf") + payload[4:])
    keystore.extra["wasabi_regtest_xpub_version_normalized"] = True


def _taproot_bip86_address(keystore: Any, network: str, branch: int, index: int) -> str:
    """Calculate BIP86 P2TR address using only an account public key.

    The internal key is lifted to even Y as defined by BIP341, then tweaked
    with TapTweak. This is ONLY for deriving verified Wasabi BIP86 labels; no
    seed or signing key is accessed. Bech32m is used for witness version 1.
    """
    from .sparrow_crypto import N, _point_add, _point_from_compressed, _scalar_mul
    from .sparrow_h2 import _bech32_encode
    from .verification import G, derive_pubkey

    internal_compressed = derive_pubkey(keystore, branch, index)
    internal_x = internal_compressed[1:]
    internal_even = _point_from_compressed(b"\x02" + internal_x)
    tag = hashlib.sha256(b"TapTweak").digest()
    tweak = int.from_bytes(hashlib.sha256(tag + tag + internal_x).digest(), "big")
    if tweak >= N:
        raise ExchangeError("Invalid BIP86 output-key tweak")
    output = _point_add(internal_even, _scalar_mul(tweak, G)) if tweak else internal_even
    if output is None:
        raise ExchangeError("Invalid BIP86 output key")
    hrp = "bc" if network == "mainnet" else "bcrt" if network == "regtest" else "tb"
    return _bech32_encode(hrp, 1, output[0].to_bytes(32, "big"))


def from_wasabi(
    data: dict[str, Any], name: str = "Wasabi wallet", password: str | None = None
) -> list[WalletExchange]:
    """Decode public account data without inventing origin derivation paths."""
    if not isinstance(data, dict) or "ExtPubKey" not in data or "BlockchainState" not in data:
        raise ExchangeError("Not a Wasabi KeyManager file")
    if password is not None:
        from .passwords import verify_wasabi_password

        verify_wasabi_password(data, password)
    state = data["BlockchainState"]
    if not isinstance(state, dict):
        raise ExchangeError("Malformed Wasabi BlockchainState")
    net = {
        "main": "mainnet",
        "mainnet": "mainnet",
        "testnet": "testnet",
        "testnet4": "testnet4",
        "regtest": "regtest",
        "signet": "signet",
    }.get(str(state.get("Network", "")).lower(), "unknown")
    if net == "unknown":
        raise ExchangeError("Unsupported Wasabi network; cannot safely infer account")
    account_paths = [
        norm_path(value)
        for value in (data.get("AccountKeyPath"), data.get("TaprootAccountKeyPath"))
        if isinstance(value, str) and value
    ]
    specs = [
        ("Segwit", "ExtPubKey", "AccountKeyPath", "P2WPKH", 84),
        ("Taproot", "TaprootExtPubKey", "TaprootAccountKeyPath", "P2TR", 86),
    ]
    result: list[WalletExchange] = []
    for display, keyname, pathname, script, purpose in specs:
        raw_xpub = data.get(keyname)
        if not isinstance(raw_xpub, str) or not raw_xpub:
            continue
        path = data.get(pathname)
        w = WalletExchange("wasabi", f"{name} ({display})", network=net)
        k = _public_key(
            raw_xpub,
            fingerprint=data.get("MasterFingerprint"),
            path=path if isinstance(path, str) and path.strip() else None,
            device="wasabi",
            source="software" if data.get("EncryptedSecret") is not None else "hardware/watch-only",
        )
        # An embedded [fingerprint/path]xpub origin is allowed, but checked in
        # exactly the same way as the separate AccountKeyPath field. If both
        # spellings are present, refuse inconsistent metadata rather than
        # silently preferring one.
        if isinstance(path, str) and path.strip() and k.key_origin:
            supplied = norm_path(path)
            if supplied != k.key_origin:
                raise ExchangeError("Wasabi embedded key origin disagrees with AccountKeyPath")
        if k.key_origin:
            k.key_origin = _check_wasabi_origin(k.key_origin, k.xpub or "", net, purpose)
        elif path is not None and path != "":
            raise ExchangeError("Wasabi account derivation path is malformed")
        # Check against Wasabi's ORIGINAL key first. Only then adapt RegTest's
        # xpub serialization to Bitcoin Safe's BDK-compatible test-network tpub.
        _canonical_regtest_xpub(k, net)
        if data.get("EncryptedSecret") is not None:
            k.recovery_material = "PRIVATE_KEY_REDACTED"
            w.warnings.append(
                "Wasabi private signing material was not copied"
                + ("; BIP38 password verified" if password is not None else "")
            )
        w.keystores = [k]
        _resolve_network(w)
        if k.key_origin:
            w.descriptor = descriptor_for_keys([k], script)
        else:
            # A correct address can be produced from an account xpub alone,
            # but the GUI must not label a made-up path as the signing origin.
            # Keep the account available as public metadata; require the true
            # path before presenting a signing-capable descriptor.
            w.descriptor = None
            w.warnings.append(
                "Wasabi account derivation path is missing; verify the genuine "
                "account path from Wasabi before importing this signer. "
                "No account-0 path was assumed."
            )
        w.address_type = script
        w.threshold = 1
        w.gap_limit = data.get("MinGapLimit") if isinstance(data.get("MinGapLimit"), int) else None
        birth = state.get("BirthHeight")
        if isinstance(birth, int) or isinstance(birth, str) and birth.isdecimal():
            w.birth_height = int(birth)
        if w.descriptor:
            d = strip_checksum(w.descriptor)
            w.receive_descriptor = add_checksum(d.replace("/<0;1>/*", "/0/*"))
            w.change_descriptor = add_checksum(d.replace("/<0;1>/*", "/1/*"))
        rows = data.get("HdPubKeys") or []
        for r in rows:
            if (
                not isinstance(r, dict)
                or not isinstance(r.get("FullKeyPath"), str)
                or not isinstance(r.get("Label"), str)
                or not r["Label"]
            ):
                continue
            full_path = norm_path(r["FullKeyPath"])
            # Wasabi's one file contains several independent accounts. A label
            # for a *different* supported account is not an unresolved label
            # for this one, and must not be offered to the wrong wallet.
            if full_path and k.key_origin:
                if any(
                    [
                        other != k.key_origin and full_path.startswith(other + "/")
                        for other in account_paths
                        if other
                    ]
                ):
                    continue
            # Associate a label only with this account's exact public
            # derivation path. Verify the saved per-address compressed pubkey
            # against our derived public key before creating an address label.
            match = None
            if w.descriptor and k.key_origin and full_path and script in ("P2WPKH", "P2TR"):
                match = re.fullmatch(re.escape(k.key_origin) + r"/([01])/([0-9]+)", full_path)
            if match:
                branch, index = map(int, match.groups())
                if index < 2**31:
                    from .verification import address_from_public_keys, derive_pubkey

                    derived_pub = derive_pubkey(k, branch, index)
                    embedded_pub = r.get("PubKey")
                    if embedded_pub is None or (
                        isinstance(embedded_pub, str) and embedded_pub.lower() == derived_pub.hex()
                    ):
                        address = (
                            address_from_public_keys([k], "wpkh", net, branch, index)
                            if script == "P2WPKH"
                            else _taproot_bip86_address(k, net, branch, index)
                        )
                        w.add_label(Label("addr", address, r["Label"]))
                        continue
            w.extra.setdefault("unresolved_path_labels", []).append(
                {"path": r["FullKeyPath"], "label": r["Label"]}
            )
        if w.extra.get("unresolved_path_labels"):
            w.warnings.append(
                "Some Wasabi labels could not be converted from account paths. "
                "You may supply a BIP-329 labels file in the import screen."
            )
        if data.get("ExcludedCoinsFromCoinJoin"):
            w.extra["coinjoin_exclusion_count"] = len(data["ExcludedCoinsFromCoinJoin"])
            w.warnings.append("Wasabi CoinJoin exclusions are not spend freezes")
        result.append(w)
    if not result:
        raise ExchangeError("Wasabi wallet has no supported Bitcoin account xpub")
    return result
