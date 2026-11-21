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

"""Trezor Suite legacy .mtdt labeling, derived using an explicitly approved USB device.

SOURCE: trezor/trezor-suite suite/metadata/src/{metadataUtils,metadataLabelingConstants}.ts
The `cipherKeyValue(encrypt=True)` device response is a *derived metadata
secret*, NOT a seed and NOT the user's BIP39 passphrase. It is used in memory.
This is intentionally NOT a Suite Sync/Evolu or device-PIN decoder.
"""

from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .descriptors import b58encode_check
from .model import OUTPOINT, TXID, ExchangeError, Label, WalletExchange

DEVICE_PATH = "m/10015'/0'"
DEVICE_KEY_LABEL = "Enable labeling?"
DEVICE_KEY_VALUE = bytes.fromhex("fedcba98765432100123456789abcdeffedcba98765432100123456789abcdef")
HMAC_SEED = bytes.fromhex("0123456789abcdeffedcba9876543210")
MAX_METADATA_BYTES = 16 * 1024 * 1024


def derive_legacy_metadata_key(
    device_master: bytes, account_key: str, encryption_version: int = 1
) -> tuple[str, bytes]:
    """Derive Trezor legacy account-label file name and AES key.

    `account_key` must be the exact metadata key used by Suite (normally the
    account xpub, but some chain/version records use the account descriptor).
    Master bytes must come from the connected/authorized Trezor device.
    """
    if not isinstance(device_master, bytes) or len(device_master) != 32:
        raise ExchangeError("Trezor labeling device key must be 32 bytes")
    if not isinstance(account_key, str) or not account_key.strip():
        raise ExchangeError("Trezor metadata account key (original xpub/descriptor) is required")
    if encryption_version not in (1, 2):
        raise ExchangeError("Unsupported Trezor legacy metadata encryption version")
    metadata_key = b58encode_check(hmac.digest(device_master, account_key.encode("utf-8"), "sha256"))
    digest = hmac.digest(metadata_key.encode("utf-8"), HMAC_SEED, "sha512")
    suffix = "" if encryption_version == 1 else f"_v{encryption_version}"
    return digest[:32].hex() + suffix + ".mtdt", digest[32:]


def get_legacy_master_key_from_usb(encryption_version: int = 1) -> bytes:
    """Ask one connected Trezor for the metadata key; requires trezorlib and approval.

    Does not prompt for the PIN on the host. On supported devices, any
    hidden-wallet passphrase must be selected on the Trezor. Older devices
    without on-device passphrase entry default to the standard wallet;
    mismatched metadata filenames then fail closed.
    """
    if encryption_version not in (1, 2):
        raise ExchangeError("Unsupported Trezor legacy metadata encryption version")
    try:
        from trezorlib import misc, tools
        from trezorlib.client import get_default_client, get_default_session
    except ImportError as exc:
        raise ExchangeError(
            "Trezor USB metadata needs the optional trezorlib package: pip install trezor"
        ) from exc
    try:
        with get_default_client("Wallet Exchange: legacy labels") as client:
            session = get_default_session(client)
            with session:
                master = misc.encrypt_keyvalue(
                    session,
                    tools.parse_path(DEVICE_PATH),
                    DEVICE_KEY_LABEL,
                    DEVICE_KEY_VALUE,
                    ask_on_encrypt=(encryption_version == 1),
                    ask_on_decrypt=(encryption_version == 1),
                )
                if not isinstance(master, bytes) or len(master) != 32:
                    raise ExchangeError("Trezor supplied an unexpected metadata key length")
                return master
    except ExchangeError:
        raise
    except Exception as exc:
        # Avoid echoing transport exceptions (which can contain device details).
        raise ExchangeError(
            "Trezor USB metadata-key request failed or was rejected; check the device and selected wallet"
        ) from exc


def decrypt_legacy_mtdt(
    ciphertext: bytes, device_master: bytes, account_key: str, encryption_version: int = 1
) -> tuple[str, dict[str, Any]]:
    """Authenticated AES-256-GCM decryption of raw Suite .mtdt bytes, in memory.

    File layout is 12-byte IV || 16-byte tag || ciphertext (Suite metadataUtils.ts).
    Returns the *derived filename* for validation by the caller and JSON dict.
    """
    if not isinstance(ciphertext, bytes) or len(ciphertext) < 29 or len(ciphertext) > MAX_METADATA_BYTES:
        raise ExchangeError("Invalid or oversized Trezor .mtdt encrypted file")
    filename, aes_key = derive_legacy_metadata_key(
        device_master, account_key, encryption_version=encryption_version
    )
    iv, tag, encrypted = ciphertext[:12], ciphertext[12:28], ciphertext[28:]
    try:
        plaintext = AESGCM(aes_key).decrypt(iv, encrypted + tag, None)
        result = json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, ValueError, UnicodeDecodeError, TypeError) as exc:
        raise ExchangeError(
            "Trezor metadata authentication failed: wrong device/wallet/account key or damaged file"
        ) from exc
    if not isinstance(result, dict) or result.get("version") != "1.0.0":
        raise ExchangeError("Unsupported Trezor metadata record; expected labeling version 1.0.0")
    return filename, result


def apply_trezor_mtdt_labels(
    wallet: WalletExchange,
    path: str | Path,
    account_key: str,
    device_master: bytes,
    encryption_version: int = 1,
) -> int:
    """Merge Trezor legacy account labeling into one already-imported wallet.

    Rejects a mismatched filename: it is derived from the wallet-specific
    device secret and original account key. Never includes that secret in the
    WalletExchange object or serialized output.
    """
    if wallet.source_wallet != "trezor-suite":
        raise ExchangeError("Trezor metadata requires a Trezor Suite account import")
    p = Path(path)
    if p.stat().st_size > MAX_METADATA_BYTES:
        raise ExchangeError("Trezor .mtdt exceeds size limit")
    expected_name, data = decrypt_legacy_mtdt(
        p.read_bytes(),
        device_master=device_master,
        account_key=account_key,
        encryption_version=encryption_version,
    )
    if p.name != expected_name:
        raise ExchangeError("Trezor .mtdt filename does not match the selected device and account key")
    count = 0
    account_label = data.get("accountLabel")
    if isinstance(account_label, str) and account_label:
        wallet.extra["trezor_account_label"] = account_label
        count += 1
    addr = data.get("addressLabels") or {}
    if not isinstance(addr, dict):
        raise ExchangeError("Invalid Trezor address labels")
    for address, label in addr.items():
        if isinstance(address, str) and isinstance(label, str) and label:
            wallet.add_label(Label("addr", address, label))
            count += 1
    outputs = data.get("outputLabels") or {}
    if not isinstance(outputs, dict):
        raise ExchangeError("Invalid Trezor output labels")
    for txid, positions in outputs.items():
        if not isinstance(txid, str) or not TXID.fullmatch(txid):
            raise ExchangeError("Invalid Trezor labeled transaction ID")
        if not isinstance(positions, dict):
            raise ExchangeError("Invalid Trezor output-label indexes")
        for vout, label in positions.items():
            if not isinstance(vout, str) or not vout.isdecimal() or not isinstance(label, str):
                raise ExchangeError("Invalid Trezor output label")
            ref = f"{txid}:{int(vout)}"
            if not OUTPOINT.fullmatch(ref):
                raise ExchangeError("Invalid Trezor output reference")
            wallet.add_label(Label("output", ref, label))
            count += 1
    wallet.warnings.append(
        "Trezor legacy .mtdt labels decrypted using an authorized device-derived key (not a PIN); verify account selection"
    )
    return count
