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

"""Electrum wallet storage: BIE1 password decryption and WATCH-ONLY import.

Based on spesmilo/electrum electrum/storage.py, crypto.py, wallet.py,
keystore.py. Passwords and decrypted source documents stay in memory; no
password or seed is retained in interchange JSON. Does NOT attempt to decrypt
individual seed/xprv entries: it is unnecessary for public-wallet migration.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import zlib
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bitcoin_safe.xpub_utils import check_xpub_origin_depth_and_child_number

from .descriptors import add_checksum, norm_path, origin_expression, strip_checksum
from .model import OUTPOINT, TXID, ExchangeError, Keystore, Label, WalletExchange

N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
MAX_DECOMPRESSED = 32 * 1024 * 1024


def is_electrum_encrypted(raw: bytes) -> bool:
    try:
        b = base64.b64decode(raw.strip(), validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(b) >= 85 and b[:4] in (b"BIE1", b"BIE2")


def decrypt_electrum(raw: bytes, password: str) -> bytes:
    """Decrypt Electrum BIE1 whole-file storage (PBKDF2 + ECIES + zlib).

    BIE2 is hardware-xpub-protected: a user password alone cannot unlock it.
    """
    try:
        data = base64.b64decode(raw.strip(), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ExchangeError("Malformed Electrum encrypted file") from exc
    if data[:4] == b"BIE2":
        raise ExchangeError(
            "Electrum BIE2 requires its hardware-derived xpub password; export an unencrypted watch-only copy using Electrum"
        )
    if len(data) < 85 or data[:4] != b"BIE1" or (len(data) - 4 - 33 - 32) % 16:
        raise ExchangeError("Not an Electrum BIE1 encrypted wallet")
    if not isinstance(password, str):
        raise ExchangeError("Electrum wallet password is required")
    try:
        secret = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), b"", 1024)
        scalar = int.from_bytes(secret, "big") % N
        if scalar == 0:
            raise ValueError("invalid scalar")
        private_key = ec.derive_private_key(scalar, ec.SECP256K1())
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), data[4:37])
        shared = private_key.exchange(ec.ECDH(), peer)
        # Electrum ECIES hashes the *compressed public point* of the ECDH secret.
        # ECDH() returns its x-coordinate; compressed prefix is determined using
        # scalar multiplication (e.g. coincurve). Recover y parity via
        # multiplication using the public affine coordinates below.
        compressed = _ecdh_compressed(private_key, peer, shared)
        deriv = hashlib.sha512(compressed).digest()
        iv, aes_key, mac_key = deriv[:16], deriv[16:32], deriv[32:]
        mac = hmac.new(mac_key, data[:-32], "sha256").digest()
        if not hmac.compare_digest(mac, data[-32:]):
            raise ValueError("mac mismatch")
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(data[37:-32]) + decryptor.finalize()
        unpad = padding.PKCS7(128).unpadder()
        compressed_data = unpad.update(padded) + unpad.finalize()
        # Limit decompression output; do not allow zip-bomb storage files.
        obj = zlib.decompressobj()
        plaintext = obj.decompress(compressed_data, MAX_DECOMPRESSED + 1)
        if len(plaintext) > MAX_DECOMPRESSED or obj.unconsumed_tail or not obj.eof:
            raise ValueError("invalid or oversized zlib content")
        plaintext += obj.flush()
        if len(plaintext) > MAX_DECOMPRESSED:
            raise ValueError("oversized Electrum wallet")
        json.loads(plaintext.decode("utf-8"))
        return plaintext
    except (ValueError, UnicodeError, OverflowError, json.JSONDecodeError) as exc:
        raise ExchangeError("Incorrect Electrum password or corrupt encrypted wallet") from exc


def _ecdh_compressed(
    private_key: ec.EllipticCurvePrivateKey, peer: ec.EllipticCurvePublicKey, shared_x: bytes
) -> bytes:
    """Compute compressed ECDH shared public point, using secp256k1 math.

    The X-coordinate alone does not determine Y parity; cryptography's ECDH
    API only returns X, so we use the peer point and the scalar.
    """
    from .sparrow_crypto import _compressed, _scalar_mul

    nums = peer.public_numbers()
    return _compressed(_scalar_mul(private_key.private_numbers().private_value, (nums.x, nums.y)))


def _find_network(xpubs: list[Keystore]) -> str:
    from .descriptors import infer_network

    return infer_network(xpubs)


def _from_key(raw: dict[str, Any]) -> Keystore:
    from .adapters import _public_key

    ks = _public_key(
        raw.get("xpub"),
        fingerprint=raw.get("root_fingerprint"),
        path=raw.get("derivation"),
        device=raw.get("hw_type") or raw.get("type"),
        label=raw.get("label"),
        source="hardware"
        if raw.get("type") == "hardware"
        else "software"
        if raw.get("type") in ("bip32", "old")
        else "watch-only",
    )
    ks.derivation_suffix = "/<0;1>/*"
    if raw.get("seed"):
        ks.recovery_material = "SEED_REDACTED"
    elif raw.get("xprv") or raw.get("keypairs"):
        ks.recovery_material = "PRIVATE_KEY_REDACTED"
    # Password-protected keystore entries are not decrypted: xpubs suffice.
    return ks


def _parse_reference_labels(w: WalletExchange, labels: Any) -> None:
    if not isinstance(labels, dict):
        return
    for ref, value in labels.items():
        if not isinstance(ref, str) or not isinstance(value, str):
            continue
        if TXID.fullmatch(ref):
            w.add_label(Label("tx", ref.lower(), value))
        elif OUTPOINT.fullmatch(ref):
            w.add_label(Label("output", ref.lower(), value))
        elif re.match(r"^(bc1|tb1|bcrt1|[123mn2])[a-zA-Z0-9]{10,}$", ref, re.I):
            w.add_label(Label("addr", ref, value))
        else:
            w.extra.setdefault("unclassified_label_refs", 0)
            w.extra["unclassified_label_refs"] += 1


def missing_cosigner_origins(wallet: WalletExchange) -> list[int]:
    return [
        i
        for i, key in enumerate(wallet.keystores, 1)
        if not key.fingerprint or key.fingerprint == "00000000" or not key.key_origin
    ]


def complete_cosigner_origins(wallet: WalletExchange, origins: dict[int, tuple[str, str]]) -> None:
    """Add user-supplied origins to an Electrum descriptor.

    Xpubs cannot reveal master fingerprints. Check the path components that are
    encoded in the account xpub and reject conflicts with existing metadata.
    """
    wallet_type = str(wallet.extra.get("electrum_wallet_type", ""))
    multi = bool(re.fullmatch(r"\d+of\d+", wallet_type))
    if wallet.source_wallet != "electrum" or not (multi or wallet_type in ("standard", "xpub", "old")):
        raise ExchangeError("Signer origins can only be supplied for an Electrum deterministic wallet")
    if not wallet.descriptor or not wallet.threshold:
        raise ExchangeError("Electrum descriptor is unavailable")
    resolved: list[tuple[Keystore, str, str]] = []
    for index, (fingerprint, origin) in origins.items():
        if not 1 <= index <= len(wallet.keystores):
            raise ExchangeError("Invalid Electrum signer number")
        fingerprint = fingerprint.strip().lower()
        origin = norm_path(origin.strip()) or ""
        if fingerprint == "00000000":
            raise ExchangeError("Enter the genuine signer fingerprint, not the 00000000 placeholder")
        if not re.fullmatch(r"[0-9a-f]{8}", fingerprint) or not re.fullmatch(r"m(?:/[0-9]+h?)*", origin):
            raise ExchangeError("Enter an eight-character fingerprint and a valid derivation path")
        key = wallet.keystores[index - 1]
        if not key.xpub:
            raise ExchangeError(f"Electrum signer {index} has no account xpub")
        try:
            check_xpub_origin_depth_and_child_number(key.xpub, origin)
        except ValueError as exc:
            raise ExchangeError(f"Electrum signer {index}: {exc}") from exc
        pieces = origin.split("/")[1:]
        if len(pieces) >= 2 and pieces[0] in {"44h", "48h", "49h", "84h", "86h"}:
            expected_coin = "0h" if wallet.network == "mainnet" else "1h"
            if wallet.network != "unknown" and pieces[1] != expected_coin:
                raise ExchangeError(
                    f"Electrum signer {index} derivation path does not match the wallet network"
                )
        if key.fingerprint and key.fingerprint != "00000000" and key.fingerprint.lower() != fingerprint:
            raise ExchangeError(f"Electrum signer {index} fingerprint disagrees with the wallet file")
        if key.key_origin and norm_path(key.key_origin) != origin:
            raise ExchangeError(f"Electrum signer {index} derivation path disagrees with the wallet file")
        resolved.append((key, fingerprint, origin))
    for key, fingerprint, origin in resolved:
        key.fingerprint, key.key_origin = fingerprint, origin
    parts = [origin_expression(key) for key in wallet.keystores]
    if multi:
        inner = f"sortedmulti({wallet.threshold},{','.join(parts)})"
        expression = {"pkh": f"sh({inner})", "sh-wsh": f"sh(wsh({inner}))", "wsh": f"wsh({inner})"}.get(
            wallet.address_type or ""
        )
    else:
        expression = {
            "pkh": f"pkh({parts[0]})",
            "sh-wpkh": f"sh(wpkh({parts[0]}))",
            "wpkh": f"wpkh({parts[0]})",
        }.get(wallet.address_type or "")
    if not expression:
        raise ExchangeError("Unsupported Electrum descriptor")
    wallet.descriptor = add_checksum(expression)
    wallet.receive_descriptor = add_checksum(expression.replace("/<0;1>/*", "/0/*"))
    wallet.change_descriptor = add_checksum(expression.replace("/<0;1>/*", "/1/*"))


def from_electrum(data: dict[str, Any], name: str = "Electrum wallet") -> WalletExchange:
    if not isinstance(data, dict) or "wallet_type" not in data:
        raise ExchangeError("Not an Electrum wallet document")
    wallet_type = data.get("wallet_type")
    w = WalletExchange("electrum", str(data.get("wallet_name") or name))
    keys = []
    multi = re.fullmatch(r"(\d+)of(\d+)", str(wallet_type))
    if multi:
        m, n = int(multi.group(1)), int(multi.group(2))
        if not 1 <= m <= n <= 15:
            raise ExchangeError("Invalid Electrum multisig threshold")
        for i in range(1, n + 1):
            v = data.get(f"x{i}")
            if not isinstance(v, dict):
                raise ExchangeError(f"Electrum multisig is missing signer x{i}")
            keys.append(_from_key(v))
        w.threshold = m
    elif wallet_type in ("standard", "xpub", "old"):
        v = data.get("keystore")
        if not isinstance(v, dict):
            raise ExchangeError("Electrum deterministic wallet lacks a keystore")
        keys.append(_from_key(v))
        w.threshold = 1
    elif wallet_type == "imported":
        source_keystore = data.get("keystore") or {}
        if isinstance(source_keystore, dict) and (
            source_keystore.get("keypairs") or source_keystore.get("xprv")
        ):
            keys.append(
                Keystore(source="software", label="Imported keys", recovery_material="PRIVATE_KEY_REDACTED")
            )
        w.warnings.append(
            "Electrum imported-address/key wallet is not HD; no complete descriptor is available"
        )
    else:
        raise ExchangeError(f"Unsupported Electrum wallet type: {str(wallet_type)[:60]}")
    w.keystores = keys
    w.network = _find_network(keys) if keys else "unknown"
    w.extra["network_inferred_from_keys"] = True
    stored_addrs = data.get("addresses")
    if isinstance(stored_addrs, dict):
        addr_list = [
            a
            for group in ("receiving", "change")
            for a in (stored_addrs.get(group) or [])
            if isinstance(a, str)
        ]
        if any(a.startswith("bcrt1") for a in addr_list):
            if w.network == "mainnet":
                raise ExchangeError("Electrum address/network mismatch")
            w.network = "regtest"
            w.extra["network_inferred_from_keys"] = False
        elif any(a.startswith("bc1") for a in addr_list) and w.network not in ("mainnet", "unknown"):
            raise ExchangeError("Electrum address/network mismatch")
    raw_keys = [data[f"x{i}"] for i in range(1, len(keys) + 1)] if multi else [data.get("keystore")]
    for index, (key, raw) in enumerate(zip(keys, raw_keys, strict=False), 1):
        if not isinstance(raw, dict) or str(raw.get("seed_type") or "").lower() != "bip39":
            continue
        phrase = raw.get("seed")
        if not isinstance(phrase, str) or raw.get("passphrase"):
            continue
        from .sparrow_seed_public import recover_bip39_public_key

        try:
            if recover_bip39_public_key(key, phrase, w.network) and w.network not in ("mainnet", "unknown"):
                key.non_mainnet_seed = phrase
        except ExchangeError as exc:
            if str(exc) != "Invalid or encrypted BIP39 mnemonic":
                raise
            w.warnings.append(f"Electrum signer {index}: BIP39 seed is encrypted or invalid")
    w.gap_limit = int(data["gap_limit"]) if isinstance(data.get("gap_limit"), int) else None
    w.extra["electrum_wallet_type"] = str(wallet_type)
    w.extra["electrum_format_version"] = (
        data.get("seed_version") if isinstance(data.get("seed_version"), int) else None
    )
    w.extra["electrum_keystore_encryption"] = bool(data.get("use_encryption"))
    # Electrum xpub version bytes indicate script type (and purpose), not merely seed_type.
    if keys and all(k.xpub for k in keys):
        prefixes = {k.raw_xpub_prefix for k in keys}
        if len(prefixes) != 1:
            w.warnings.append("Electrum cosigners have incompatible xpub version bytes")
        else:
            prefix = next(iter(prefixes))
            script = {
                "xpub": "pkh",
                "tpub": "pkh",
                "ypub": "sh-wpkh",
                "upub": "sh-wpkh",
                "zpub": "wpkh",
                "vpub": "wpkh",
                "Ypub": "sh-wsh",
                "Upub": "sh-wsh",
                "Zpub": "wsh",
                "Vpub": "wsh",
            }.get(prefix or "")
            w.address_type = script
            if script:
                if multi:
                    parts = [origin_expression(k) for k in keys]
                    inner = f"sortedmulti({w.threshold},{','.join(parts)})"
                    expression = {
                        "pkh": f"sh({inner})",
                        "sh-wsh": f"sh(wsh({inner}))",
                        "wsh": f"wsh({inner})",
                    }.get(script)
                    # Electrum standard multisig uses legacy p2sh, not pkh.
                else:
                    expression = {
                        "pkh": f"pkh({origin_expression(keys[0])})",
                        "sh-wpkh": f"sh(wpkh({origin_expression(keys[0])}))",
                        "wpkh": f"wpkh({origin_expression(keys[0])})",
                    }.get(script)
                if expression:
                    w.descriptor = add_checksum(expression)
                    w.receive_descriptor = add_checksum(
                        strip_checksum(w.descriptor).replace("/<0;1>/*", "/0/*")
                    )
                    w.change_descriptor = add_checksum(
                        strip_checksum(w.descriptor).replace("/<0;1>/*", "/1/*")
                    )
    if keys and not w.descriptor:
        w.warnings.append(
            "Electrum descriptor could not be established; export an explicit public descriptor"
        )
    for i, ks in enumerate(keys):
        if ks.recovery_material:
            w.warnings.append(
                f"Signer {i + 1}: BIP39 seed retained for test-network signing"
                if ks.non_mainnet_seed
                else f"Signer {i + 1} has {ks.recovery_material}; no recovery material copied"
            )
    # Confirm reconstructed policies against wallet's stored addresses.
    # This catches wrong branch paths / multisig order before any migration.
    if w.descriptor and isinstance(data.get("addresses"), dict):
        if not w.address_type:
            raise ExchangeError("Cannot verify addresses without a script type")
        from .verification import address_from_public_keys

        verified = {}
        for field, branch in (("receiving", 0), ("change", 1)):
            addresses = data["addresses"].get(field)
            if not isinstance(addresses, list):
                continue
            checked = 0
            for i, address in enumerate(addresses[:3]):
                if not isinstance(address, str):
                    continue
                generated = address_from_public_keys(
                    w.keystores, w.address_type, w.network, branch, i, w.threshold or 1
                )
                if generated != address:
                    raise ExchangeError(
                        f"Electrum {field} address {i} does not match reconstructed descriptor"
                    )
                checked += 1
            if checked:
                verified[field] = checked
        if verified:
            w.extra["address_verification"] = verified
    _parse_reference_labels(w, data.get("labels"))
    for raw in data.get("frozen_addresses") or []:
        if isinstance(raw, str) and raw not in w.frozen_addresses:
            w.frozen_addresses.append(raw)
    frozen = data.get("frozen_coins") or data.get("frozen_utxos") or []
    if isinstance(frozen, dict):
        frozen = list(frozen)
    for ref in frozen:
        if isinstance(ref, str) and OUTPOINT.fullmatch(ref):
            w.add_frozen_outpoint(ref)
    if data.get("addresses"):
        w.extra["address_history_stored"] = True
    return w
