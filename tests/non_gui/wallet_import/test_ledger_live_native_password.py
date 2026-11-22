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

"""Native Ledger Live app.json tests, with independent Node crypto implementation.

Synthetic PUBLIC ONLY data; never store real wallet backups or passwords.
"""

import base64
import hashlib
import json
import shutil
import subprocess

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bitcoin_safe.wallet_import.adapters import load_file, load_json_obj
from bitcoin_safe.wallet_import.ledger_live_db import decrypt_ledger_live_accounts
from bitcoin_safe.wallet_import.model import ExchangeError

from .test_wallet_exchange import xpub


def node_encrypt_accounts(rows: list[dict], password: str) -> str:
    if not shutil.which("node"):
        pytest.skip("Node.js is used to check implementation against Ledger crypto.ts")
    js = r"""
const crypto = require('node:crypto');
const rows = JSON.parse(process.argv[1]);
const password = process.argv[2];
const iv = Buffer.from('e1ffba802ac8fd0291018effc200ffff','hex');
const key = crypto.pbkdf2Sync(password, iv.toString(), 10000, 32, 'sha512');
const cipher = crypto.createCipheriv('aes-256-cbc',key,iv);
const encrypted = Buffer.concat([iv,Buffer.from(':'),cipher.update(JSON.stringify(rows),'utf8'),cipher.final()]);
process.stdout.write(encrypted.toString('base64'));
"""
    return subprocess.run(
        ["node", "-e", js, json.dumps(rows), password], check=True, stdout=subprocess.PIPE
    ).stdout.decode()


def rows_fixture():
    return [
        {
            "type": "Account",
            "currencyId": "bitcoin",
            "name": "Main Ledger BTC",
            "xpub": xpub(),
            "derivationMode": "native_segwit",
            "freshAddressPath": "84'/0'/0'/0/0",
            "freshAddressIndex": 8,
            "index": 0,
            "balance": "10000",
        },
        {
            "type": "Account",
            "currencyId": "bitcoin_cash",
            "name": "IGNORE bitcoincash",
            "xpub": xpub(),
            "derivationMode": "native_segwit",
        },
        {
            "type": "Account",
            "currencyId": "ethereum",
            "name": "IGNORE ethereum",
            "xpub": xpub(),
            "derivationMode": "native_segwit",
        },
    ]


def test_native_ledger_live_password_from_node_encrypted_app_json(tmp_path):
    password = "Wallet-password-🔒"
    encrypted = node_encrypt_accounts(rows_fixture(), password)
    source = tmp_path / "app.json"
    source.write_text(
        json.dumps(
            {
                "data": {
                    "accounts": encrypted,
                    "wallet": "DO_NOT_EXPOSE_PRIVATE_CONTACTS",
                    "trustchain": "DO_NOT_EXPOSE_SYNC_KEY",
                }
            }
        )
    )
    wallets = load_file(source, password=password, hint="ledger")
    assert len(wallets) == 1
    w = wallets[0]
    assert w.source_wallet == "ledger-live"
    assert w.name == "Main Ledger BTC"
    assert w.network == "mainnet"
    assert w.address_type == "wpkh"
    assert w.descriptor.startswith("wpkh(")
    assert w.keystores[0].key_origin == "m/84h/0h/0h"
    assert w.next_receive_index == 8
    public_json = w.to_json()
    for sentinel in ("DO_NOT_EXPOSE_PRIVATE_CONTACTS", "DO_NOT_EXPOSE_SYNC_KEY", password, encrypted):
        assert sentinel not in public_json
    assert any("app password unlocked" in msg for msg in w.warnings)
    with pytest.raises(ExchangeError, match="Incorrect Ledger Live password"):
        load_file(source, password="wrong-password", hint="ledger")
    with pytest.raises(ExchangeError, match="use --ask-password"):
        load_file(source, hint="ledger")
    # Autodetection works even without explicit --format.
    assert len(load_file(source, password=password)) == 1


def test_plaintext_ledger_app_json_requires_no_password(tmp_path):
    source = tmp_path / "app.json"
    source.write_text(json.dumps({"data": {"accounts": rows_fixture(), "trustchain": "inaccessible"}}))
    wallets = load_file(source, hint="ledger")
    assert len(wallets) == 1
    with pytest.raises(ExchangeError, match="plaintext"):
        load_file(source, hint="ledger", password="unused")


def test_ledger_native_legacy_evp_md5_encryption():
    password = "old-ledger-password"
    data = json.dumps(rows_fixture()).encode()
    derived, last = b"", b""
    while len(derived) < 48:
        last = hashlib.md5(last + password.encode()).digest()
        derived += last
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(derived[:32]), modes.CBC(derived[32:48])).encryptor()
    old = base64.b64encode(cipher.update(padded) + cipher.finalize()).decode()
    assert len(decrypt_ledger_live_accounts(old, password)) == 3
    with pytest.raises(ExchangeError, match="Incorrect Ledger Live password"):
        decrypt_ledger_live_accounts(old, "bad")


def test_ledger_invalid_ciphertext_does_not_echo_private_data():
    for encrypted in ("!", "dG9vc2hvcnQ=", base64.b64encode(b"0" * 45).decode()):
        with pytest.raises(ExchangeError) as exc:
            decrypt_ledger_live_accounts(encrypted, "password")
        assert encrypted not in str(exc.value)


def test_ledger_nested_wrong_format_fails(tmp_path):
    path = tmp_path / "bad-app.json"
    path.write_text(json.dumps({"data": {"accounts": "not base64", "wallet": {"accounts": []}}}))
    with pytest.raises(ExchangeError, match="base64"):
        load_file(path, password="password")


def test_alternative_bitcoin_forks_rejected():
    for coin in ("bitcoin_cash", "bitcoin_gold", "bitcoin_sv", "litecoin"):
        with pytest.raises(ExchangeError, match="not a supported Bitcoin"):
            load_json_obj(
                {"type": "Account", "currencyId": coin, "xpub": xpub(), "derivationMode": "native_segwit"},
                hint="ledger",
            )


def test_individual_ledger_account_rejects_ignored_password():
    with pytest.raises(ExchangeError, match="plaintext"):
        load_json_obj(
            {"type": "Account", "currencyId": "bitcoin", "xpub": xpub(), "derivationMode": "native_segwit"},
            hint="ledger",
            password="password",
        )


def test_ledger_live_address_verification_from_xpub():
    from bitcoin_safe.wallet_import.adapters import _public_key
    from bitcoin_safe.wallet_import.verification import address_from_public_keys

    key = _public_key(xpub(), path="m/84h/0h/0h")
    addr = address_from_public_keys([key], "wpkh", "mainnet", 0, 5)
    row = {
        "type": "Account",
        "currencyId": "bitcoin",
        "name": "Verified",
        "xpub": xpub(),
        "derivationMode": "native_segwit",
        "freshAddress": addr,
        "freshAddressPath": "84'/0'/0'/0/5",
    }
    w = load_json_obj(row, hint="ledger")[0]
    assert w.extra["address_verification"] == {"branch": 0, "index": 5}
    with pytest.raises(ExchangeError, match="does not match public account xpub"):
        load_json_obj({**row, "freshAddress": "bc1qwrongaddress"}, hint="ledger")
