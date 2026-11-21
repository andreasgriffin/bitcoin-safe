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

"""Recover public cosigner metadata from Sparrow BIP39 seed rows.

Seeds are decrypted locally in RAM. Mainnet seeds are not retained; eligible
test-network seeds may be retained for signing. Sensitive Python bytes cannot
be reliably zeroized; process wallet files only on trusted systems.

H2 seed encryption: drongo DeterministicSeed + AESKeyCrypter (Argon2id,
AES-256-CBC-PKCS7), Sparrow KeystoreDao. BIP39 + BIP32 derivation.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .descriptors import b58decode_check, b58encode_check, normalize_xpub
from .model import ExchangeError, Keystore
from .sparrow_crypto import N, _compressed, _scalar_mul

if TYPE_CHECKING:
    from .h2_python import _MVStore

G = (
    0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
    0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8,
)
PATH = re.compile(r"^m(?:/[0-9]+['hH]?){1,10}$")
MAX_SEED_ROWS = 1000


def _fingerprint(pub: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(pub).digest()).digest()[:4]


def _read_path(path: Any) -> list[int]:
    if not isinstance(path, str) or not PATH.fullmatch(path):
        raise ExchangeError("Missing or unsupported Sparrow seed account derivation path")
    indexes = []
    for part in path.split("/")[1:]:
        hardened = part.endswith(("'", "h", "H"))
        n = int(part[:-1] if hardened else part)
        if n >= (1 << 31):
            raise ExchangeError("Sparrow seed derivation index outside BIP32 range")
        indexes.append(n | 0x80000000 if hardened else n)
    return indexes


def _derived_account_pub(mnemonic: str, path: str, mainnet: bool, passphrase: str = "") -> tuple[str, str]:
    """Derive BIP32 account public data from BIP39 mnemonic, never xprv."""
    words = mnemonic.split()
    if len(words) not in (12, 15, 18, 21, 24) or len(mnemonic) > 1024:
        raise ExchangeError("Invalid Sparrow BIP39 seed length")
    if not all(word.isalpha() for word in words):
        raise ExchangeError("Unexpected Sparrow BIP39 mnemonic word encoding")
    mnemonic_utf8 = unicodedata.normalize("NFKD", mnemonic).encode("utf-8")
    salt = b"mnemonic" + unicodedata.normalize("NFKD", passphrase).encode("utf-8")
    seed = hashlib.pbkdf2_hmac("sha512", mnemonic_utf8, salt, 2048, 64)
    digest = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    scalar = int.from_bytes(digest[:32], "big")
    if not 0 < scalar < N:
        raise ExchangeError("Invalid BIP32 master key")
    chain = digest[32:]
    pub = _compressed(_scalar_mul(scalar, G))
    master_fingerprint = _fingerprint(pub)
    parent_fingerprint = b"\x00" * 4
    indexes = _read_path(path)
    for child in indexes:
        parent_fingerprint = _fingerprint(pub)
        if child & 0x80000000:
            payload = b"\x00" + scalar.to_bytes(32, "big") + child.to_bytes(4, "big")
        else:
            payload = pub + child.to_bytes(4, "big")
        digest = hmac.new(chain, payload, hashlib.sha512).digest()
        tweak = int.from_bytes(digest[:32], "big")
        if tweak >= N:
            raise ExchangeError("Invalid Sparrow BIP32 child")
        scalar = (scalar + tweak) % N
        if scalar == 0:
            raise ExchangeError("Invalid Sparrow BIP32 child")
        chain = digest[32:]
        pub = _compressed(_scalar_mul(scalar, G))
    prefix = bytes.fromhex("0488b21e" if mainnet else "043587cf")
    payload = (
        prefix
        + bytes([len(indexes)])
        + parent_fingerprint
        + (indexes[-1] if indexes else 0).to_bytes(4, "big")
        + chain
        + pub
    )
    return b58encode_check(payload), master_fingerprint.hex()


def infer_standard_origin_from_bip39(
    mnemonic: str, account_xpub: str, mainnet: bool, passphrase: str = ""
) -> tuple[str, str] | None:
    """Recover an origin path only if BIP39 derivation matches a stored xpub.

    Search is deliberately bounded to known account layouts. A public xpub
    contains BIP32 depth and final child index, but cannot reveal all parents.
    If no exact match is proven, do not invent a path/fingerprint.
    """
    if not isinstance(account_xpub, str) or not account_xpub:
        return None
    canonical, _, _ = normalize_xpub(account_xpub)
    payload = b58decode_check(canonical)
    depth = payload[4]
    child = int.from_bytes(payload[9:13], "big")
    coin = "0h" if mainnet else "1h"
    if child & 0x80000000 == 0:
        return None
    account = child & 0x7FFFFFFF
    candidates = []
    if depth == 3:
        for purpose in (44, 49, 84, 86):
            candidates.append(f"m/{purpose}h/{coin}/{account}h")
    elif depth == 4 and account in (1, 2):
        # BIP48: last child is script type. Account is at level 3, not
        # exposed in the account-level xpub. Search only 0..9; no guesses.
        for account_index in range(10):
            candidates.append(f"m/48h/{coin}/{account_index}h/{account}h")
    for path in candidates:
        derived, fingerprint = _derived_account_pub(mnemonic, path, mainnet=mainnet, passphrase=passphrase)
        if derived == canonical:
            return path, fingerprint
    return None


def recover_bip39_public_key(keystore: Keystore, mnemonic: str, network: str) -> bool:
    """Recover only metadata proven against the source account key."""
    if network == "unknown":
        return False
    from bdkpython import Mnemonic

    try:
        Mnemonic.from_string(mnemonic)
    except Exception as exc:
        raise ExchangeError("Invalid or encrypted BIP39 mnemonic") from exc
    if not keystore.key_origin and keystore.xpub:
        inferred = infer_standard_origin_from_bip39(mnemonic, keystore.xpub, network == "mainnet")
        if inferred:
            keystore.key_origin = inferred[0]
    if not keystore.key_origin:
        return False
    xpub, fingerprint = _derived_account_pub(mnemonic, keystore.key_origin, network == "mainnet")
    if keystore.xpub and keystore.xpub != xpub:
        raise ExchangeError("BIP39 seed and stored account xpub disagree")
    if (
        keystore.fingerprint
        and keystore.fingerprint != "00000000"
        and keystore.fingerprint.lower() != fingerprint
    ):
        raise ExchangeError("BIP39 seed and master fingerprint disagree")
    keystore.xpub, keystore.fingerprint = xpub, fingerprint
    return True


def _seed_mnemonic(
    seed_row: dict[str, Any], password: str | None, bip39_passphrase: str | None = None
) -> str:
    """Decrypt one supported seed using user's Sparrow file password.

    Never return these strings to the public export, warnings, exceptions,
    logging, or filesystem. Callers must drop references after derivation.
    """
    if seed_row.get("type") != 0:
        raise ExchangeError("Sparrow seed-derived xpub currently supports BIP39 only")
    if seed_row.get("needsPassphrase") and bip39_passphrase is None:
        raise ExchangeError("Sparrow BIP39 seed needs an additional passphrase")
    plain = seed_row.get("mnemonicString")
    if isinstance(plain, str) and plain:
        return plain
    if seed_row.get("deriver") != 4 or seed_row.get("crypter") != 1:
        raise ExchangeError("Unsupported Sparrow seed encryption variant")
    cipher = seed_row.get("encryptedBytes")
    iv = seed_row.get("initialisationVector")
    salt = seed_row.get("keySalt")
    if (
        not isinstance(cipher, bytes)
        or not 16 <= len(cipher) <= 4096
        or len(cipher) % 16
        or not isinstance(iv, bytes)
        or len(iv) != 16
        or not isinstance(salt, bytes)
        or len(salt) != 16
    ):
        raise ExchangeError("Malformed encrypted Sparrow seed")
    if password is None:
        raise ExchangeError("Encrypted Sparrow BIP39 seed requires its wallet password")
    key = hash_secret_raw(
        password.encode("utf-8"),
        salt,
        time_cost=10,
        memory_cost=256 * 1024,
        parallelism=4,
        hash_len=32,
        type=Type.ID,
    )
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(cipher) + decryptor.finalize()
    try:
        unpadder = PKCS7(128).unpadder()
        raw = unpadder.update(padded) + unpadder.finalize()
        return raw.decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ExchangeError("Could not decrypt Sparrow software seed with this password") from exc


def augment_public_rows_from_seeds(
    store: _MVStore, public_data: dict[str, Any], password: str | None, bip39_passphrase: str | None = None
) -> int:
    """Recover public keys and retain verified test-network BIP39 seeds in memory."""
    # Imported locally to avoid circular import and keep default reader independent.
    from .h2_python import COLUMN_NAME, CREATE_TABLE, H2DecodeError, _MVStore

    if not isinstance(store, _MVStore):
        raise ExchangeError("Sparrow H2 reader not available")
    schemas = {s["schema"]: s for s in public_data["schemas"]}
    catalog = store.meta.get("name.table.0")
    if not catalog:
        raise H2DecodeError("Missing H2 SQL catalog for Sparrow seeds")
    found_seed_table: dict[str, dict[int, dict[str, Any]]] = {}
    for _, entry in store.map_id(int(catalog, 16), key_kind="long", value_kind="row", columns=4):
        if len(entry) != 4 or not isinstance(entry[3], str):
            continue
        match = CREATE_TABLE.match(entry[3])
        if not match or match.group(1) not in schemas or match.group(2) != "seed":
            continue
        schema = match.group(1)
        if schema in found_seed_table:
            raise H2DecodeError("Duplicate Sparrow seed table")
        column_names = COLUMN_NAME.findall(entry[3])
        if len(column_names) > 256:
            raise H2DecodeError("Oversized Sparrow seed table")
        map_name = store.meta.get(f"name.table.{entry[0]}")
        if not map_name:
            raise H2DecodeError("Missing Sparrow seed table map")
        rows = store.map_id(int(map_name, 16), key_kind="long", value_kind="row", columns=len(column_names))
        if len(rows) > MAX_SEED_ROWS:
            raise H2DecodeError("Too many Sparrow software seed records")
        if len(set(column_names)) != len(column_names) or "id" not in column_names:
            raise H2DecodeError("Invalid Sparrow seed table columns")
        records: dict[int, dict[str, Any]] = {}
        for _, values in rows:
            if len(values) != len(column_names):
                raise H2DecodeError("Invalid Sparrow seed table row")
            record = dict(zip(column_names, values, strict=True))
            seed_id = record["id"]
            if not isinstance(seed_id, int) or seed_id in records:
                raise H2DecodeError("Invalid Sparrow seed identifier")
            records[seed_id] = record
        found_seed_table[schema] = records
    count = 0
    for schema, section in schemas.items():
        seeds = found_seed_table.get(schema, {})
        networks = {w["network"] for w in section.get("wallet", [])}
        if len(networks) != 1:
            raise ExchangeError("Cannot derive Sparrow seed public keys for mixed-network schemas")
        network = next(iter(networks))
        if not isinstance(network, int) or network not in (0, 1, 2, 3, 4):
            raise ExchangeError("Unsupported Sparrow network for seed public derivation")
        for key_row in section.get("keystore", []):
            seed_id = key_row.get("seed")
            if seed_id is None:
                continue
            if seed_id not in seeds:
                raise H2DecodeError("Missing Sparrow seed referenced by keystore")
            if key_row.get("source") != 2:
                raise ExchangeError("Sparrow seed reference is not a software signer")
            seed_record = seeds[seed_id]
            # Mainnet mnemonics are used only inside this iteration.
            if seed_record.get("type") != 0:
                continue
            if seed_record.get("needsPassphrase") and bip39_passphrase is None:
                key_row["bip39PassphraseRequired"] = True
                continue
            mnemonic = _seed_mnemonic(seed_record, password, bip39_passphrase)
            try:
                path = key_row.get("derivationPath")
                if not path and key_row.get("extendedPublicKey"):
                    inferred = infer_standard_origin_from_bip39(
                        mnemonic,
                        key_row["extendedPublicKey"],
                        mainnet=network == 0,
                        passphrase=bip39_passphrase or "",
                    )
                    if inferred:
                        path = key_row["derivationPath"] = inferred[0]
                if not path:
                    key_row["originPathUnknown"] = True
                    continue
                xpub, fingerprint = _derived_account_pub(
                    mnemonic,
                    path,
                    mainnet=(network == 0),
                    passphrase=bip39_passphrase or "",
                )
                if network != 0 and not seed_record.get("needsPassphrase") and not bip39_passphrase:
                    key_row["bip39Mnemonic"] = mnemonic
            finally:
                del mnemonic
            if key_row.get("extendedPublicKey"):
                a, _, _ = normalize_xpub(key_row["extendedPublicKey"])
                b, _, _ = normalize_xpub(xpub)
                if a != b:
                    raise ExchangeError("Sparrow derived account key conflicts with saved public key")
            if key_row.get("masterFingerprint") and str(key_row["masterFingerprint"]).lower() != fingerprint:
                raise ExchangeError("Sparrow derived fingerprint conflicts with saved public origin")
            key_row["extendedPublicKey"] = xpub
            key_row["masterFingerprint"] = fingerprint
            key_row["derivedPublicFromSeed"] = True
            count += 1
    return count
