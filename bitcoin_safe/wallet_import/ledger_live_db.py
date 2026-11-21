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

"""Read-only Ledger Live Desktop app.json password-lock import.

Audited against LedgerHQ/ledger-live (develop):
  apps/ledger-live-desktop/src/main/db/crypto.ts
  apps/ledger-live-desktop/src/main/db/index.ts
  apps/ledger-live-desktop/src/helpers/accountModel.ts

The native password-lock encrypts app.data.accounts with AES-256-CBC:
PBKDF2-HMAC-SHA512(password, Buffer(IV).toString('utf8'), 10000, 32).
New ciphertexts are base64(IV[16] + b':' + CBC/PKCS7); some older
versions used Node createCipher with OpenSSL EVP_BytesToKey/MD5, no IV marker.

This adapter decrypts *only accounts*, not wallet metadata, Ledger Sync
trustchains, seeds, or other unrelated sensitive data. It never writes the
plaintext account list to disk. The hardware device PIN is NOT an app password.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .model import ExchangeError, PasswordRequired, WalletExchange

MAX_ACCOUNT_CIPHERTEXT = 32 * 1024 * 1024


def _evp_bytes_to_key(password: bytes) -> tuple[bytes, bytes]:
    """OpenSSL's deprecated createCipher AES-256-CBC password KDF (no salt)."""
    derived, last = b"", b""
    while len(derived) < 48:
        last = hashlib.md5(last + password, usedforsecurity=False).digest()
        derived += last
    return derived[:32], derived[32:48]


def decrypt_ledger_live_accounts(encoded: str, password: str) -> list[dict[str, Any]]:
    """Decrypt the encrypted accounts field from native Ledger Live app.json.

    Fails closed on wrong passwords/invalid JSON. The raw accounts list is
    an in-memory intermediate for conversion to public wallet metadata.
    """
    if not isinstance(encoded, str) or not isinstance(password, str):
        raise ExchangeError("Ledger Live encrypted account data requires --ask-password")
    if len(encoded) > (MAX_ACCOUNT_CIPHERTEXT * 4 // 3 + 256):
        raise ExchangeError("Ledger Live encrypted account data exceeds size limit")
    try:
        cipherbytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ExchangeError("Malformed Ledger Live account encryption (invalid base64)") from exc
    if len(cipherbytes) < 16 or len(cipherbytes) > MAX_ACCOUNT_CIPHERTEXT:
        raise ExchangeError("Malformed Ledger Live encrypted accounts length")
    if cipherbytes[16:17] == b":":
        if len(cipherbytes) < 33 or len(cipherbytes[17:]) % 16:
            raise ExchangeError("Malformed Ledger Live AES-CBC ciphertext length")
        iv = cipherbytes[:16]
        # Node's Buffer.toString() uses U+FFFD replacement on malformed UTF-8.
        key = hashlib.pbkdf2_hmac(
            "sha512",
            password.encode("utf8"),
            iv.decode("utf8", errors="replace").encode("utf8"),
            10000,
            dklen=32,
        )
        payload = cipherbytes[17:]
    else:
        if len(cipherbytes) % 16:
            raise ExchangeError("Malformed legacy Ledger Live ciphertext length")
        key, iv = _evp_bytes_to_key(password.encode("utf8"))
        payload = cipherbytes
    try:
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = dec.update(payload) + dec.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        if len(plain) > MAX_ACCOUNT_CIPHERTEXT:
            raise ValueError("Decrypted data too large")
        obj = json.loads(plain.decode("utf8"))
        # Ledger's db/index.ts accepts the historical {data: ...} envelope.
        if isinstance(obj, dict) and "data" in obj:
            obj = obj["data"]
        if not isinstance(obj, list) or any(not isinstance(row, dict) for row in obj):
            raise ValueError("Decrypted Ledger accounts are not an account list")
        if len(obj) > 10000:
            raise ValueError("Too many accounts")
    except (ValueError, UnicodeDecodeError, TypeError, OverflowError) as exc:
        raise ExchangeError(
            "Incorrect Ledger Live password or unsupported/corrupted app.json accounts"
        ) from exc
    return obj


def is_ledger_live_app(obj: Any) -> bool:
    """Identify Ledger desktop namespace, not an arbitrary JSON with accounts."""
    return isinstance(obj, dict) and isinstance(obj.get("data"), dict) and "accounts" in obj["data"]


def from_ledger_live_app(obj: dict[str, Any], password: str | None = None) -> list[WalletExchange]:
    """Convert native Ledger Live Desktop app.json into public Bitcoin accounts.

    Only accesses data.accounts; the adjacent encrypted data.wallet and
    data.trustchain fields are never decrypted or propagated.
    """
    if not is_ledger_live_app(obj):
        raise ExchangeError("Not a Ledger Live Desktop app.json database")
    saved = obj["data"]["accounts"]
    if isinstance(saved, str):
        if password is None:
            raise PasswordRequired("Ledger Live Desktop app.json accounts are encrypted; use --ask-password")
        rows = decrypt_ledger_live_accounts(saved, password)
        unlocked = True
    elif isinstance(saved, list):
        if password is not None:
            raise ExchangeError("Ledger Live app.json accounts are plaintext; remove --ask-password")
        rows = saved
        unlocked = False
    else:
        raise ExchangeError("Unsupported Ledger Live Desktop accounts storage format")

    from .adapters import from_ledger_account

    wallets: list[WalletExchange] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ExchangeError("Invalid Ledger Live account entry")
        if row.get("type") not in (None, "Account"):
            continue
        currency = row.get("currencyId")
        if currency is None and isinstance(row.get("currency"), dict):
            currency = row["currency"].get("id")
        if not isinstance(currency, str):
            # Native Ledger raw accounts must have a currencyId.
            continue
        if currency.lower() not in (
            "bitcoin",
            "bitcoin_testnet",
            "bitcoin_regtest",
            "bitcoin_signet",
            "bitcoin_testnet4",
        ):
            continue
        account = from_ledger_account(row)
        if not account.keystores or not account.keystores[0].xpub:
            account.warnings.append(
                "Ledger saved account has no public account xpub; recover it using an unlocked Ledger signer"
            )
        if unlocked:
            account.warnings.append(
                "Ledger Live Desktop app password unlocked public account metadata; hardware keys remain on the signer"
            )
        wallets.append(account)
    if not wallets:
        raise ExchangeError("Ledger Live app.json contains no supported Bitcoin account with public metadata")
    return wallets
