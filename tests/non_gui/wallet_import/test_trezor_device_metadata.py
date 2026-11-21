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

"""Trezor legacy device-assisted metadata, checked against upstream source vectors.

The tests never contact real hardware, and do not require any user wallet.
"""

import json

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bitcoin_safe.wallet_import import ExchangeError, load_file
from bitcoin_safe.wallet_import.adapters import from_trezor_account
from bitcoin_safe.wallet_import.trezor_metadata import (
    apply_trezor_mtdt_labels,
    decrypt_legacy_mtdt,
    derive_legacy_metadata_key,
)

from .test_wallet_exchange import xpub

MASTER_HEX = "20c8bf0701213cdcf4c2f56fd0096c1772322d42fb9c4d0ddf6bb122d713d2f3"
ACCOUNT_XPUB = "xpub6CVKsQYXc9awxgV1tWbG4foDvdcnieK2JkbpPEBKB5WwAPKBZ1mstLbKVB4ov7QzxzjaxNK6EfmNY5Jsk2cG26EVcEkycGW4tchT2dyUhrx"
EXPECTED = "828652b66f2e6f919fbb7fe4c9609d4891ed531c6fac4c28441e53ebe577ac85.mtdt"
AES_KEY = "9bc3736f0b45cd681854a724b5bba67b9da1e50bc9983fd2dd56e53e74b75480"


def _ciphertext(doc, key):
    # Synthetic metadata encrypted independently with the documented Suite layout.
    iv = bytes(range(12))
    combined = AESGCM(key).encrypt(iv, json.dumps(doc).encode(), None)
    return iv + combined[-16:] + combined[:-16]


def test_trezor_suite_official_metadata_derivation_vector():
    filename, key = derive_legacy_metadata_key(bytes.fromhex(MASTER_HEX), ACCOUNT_XPUB)
    assert filename == EXPECTED
    assert key.hex() == AES_KEY
    assert derive_legacy_metadata_key(bytes.fromhex(MASTER_HEX), ACCOUNT_XPUB, encryption_version=2)[
        0
    ].endswith("_v2.mtdt")


def test_trezor_mtdt_device_master_labels(tmp_path):
    labels = {
        "version": "1.0.0",
        "accountLabel": "Hardware account",
        "addressLabels": {"bc1qexample": "lunch"},
        "outputLabels": {"aa" * 32: {"0": "gift", "4": "savings"}},
    }
    path = tmp_path / EXPECTED
    path.write_bytes(_ciphertext(labels, bytes.fromhex(AES_KEY)))
    wallet = from_trezor_account({"symbol": "btc", "accountType": "normal", "descriptor": xpub()})
    assert (
        apply_trezor_mtdt_labels(
            wallet, path, account_key=ACCOUNT_XPUB, device_master=bytes.fromhex(MASTER_HEX)
        )
        == 4
    )
    assert wallet.extra["trezor_account_label"] == "Hardware account"
    assert {(x.type, x.ref, x.label) for x in wallet.labels} == {
        ("addr", "bc1qexample", "lunch"),
        ("output", "aa" * 32 + ":0", "gift"),
        ("output", "aa" * 32 + ":4", "savings"),
    }
    exported = wallet.to_json()
    assert MASTER_HEX not in exported and AES_KEY not in exported
    assert "Hardware account" in exported


def test_trezor_encrypted_metadata_wrong_key_fails_closed(tmp_path):
    path = tmp_path / EXPECTED
    blob = _ciphertext({"version": "1.0.0"}, bytes.fromhex(AES_KEY))
    path.write_bytes(blob)
    with pytest.raises(ExchangeError, match="authentication failed"):
        decrypt_legacy_mtdt(blob, device_master=b"\xff" * 32, account_key=ACCOUNT_XPUB)


def test_metadata_wrong_filename_after_successful_decrypt(tmp_path):
    path = tmp_path / "other.mtdt"
    path.write_bytes(_ciphertext({"version": "1.0.0"}, bytes.fromhex(AES_KEY)))
    with pytest.raises(ExchangeError, match="filename does not match"):
        apply_trezor_mtdt_labels(
            from_trezor_account({"symbol": "btc", "accountType": "normal", "descriptor": xpub()}),
            path,
            account_key=ACCOUNT_XPUB,
            device_master=bytes.fromhex(MASTER_HEX),
        )


def test_trezor_mtdt_file_requires_explicit_usb(tmp_path):
    file = tmp_path / "account.json"
    file.write_text(json.dumps({"symbol": "btc", "accountType": "normal", "descriptor": xpub()}))
    with pytest.raises(ExchangeError, match="provided together"):
        load_file(file, hint="trezor", trezor_metadata="example.mtdt")
    with pytest.raises(ExchangeError, match="provided together"):
        load_file(file, hint="trezor", trezor_usb=True)
    with pytest.raises(ExchangeError, match="metadata account key"):
        load_file(file, hint="trezor", trezor_usb=True, trezor_metadata="example.mtdt")


def test_trezor_mtdt_flow_uses_usb_only_after_explicit_opt_in(tmp_path, monkeypatch):
    from bitcoin_safe.wallet_import import trezor_metadata

    file = tmp_path / "account.json"
    file.write_text(json.dumps({"symbol": "btc", "accountType": "normal", "descriptor": xpub()}))
    label_file = tmp_path / EXPECTED
    label_file.write_bytes(
        _ciphertext({"version": "1.0.0", "accountLabel": "Device-approved"}, bytes.fromhex(AES_KEY))
    )
    calls = []

    def fake_device_key(encryption_version):
        calls.append(encryption_version)
        return bytes.fromhex(MASTER_HEX)

    monkeypatch.setattr(trezor_metadata, "get_legacy_master_key_from_usb", fake_device_key)
    results = load_file(
        file, hint="trezor", trezor_usb=True, trezor_metadata=label_file, trezor_account_key=ACCOUNT_XPUB
    )
    assert calls == [1]
    assert results[0].extra["trezor_account_label"] == "Device-approved"


def test_old_gpg_wrapper_no_longer_supported(tmp_path):
    file = tmp_path / "accounts.json.gpg"
    file.write_bytes(b"\x8c\x0d" + b"not a native wallet format")
    with pytest.raises(ExchangeError, match="Binary wallet format not recognized"):
        load_file(file, password="unused", hint="bitbox")


def test_trezor_usb_call_is_correct_and_request_is_opt_in(monkeypatch):
    import sys
    from types import ModuleType

    import bitcoin_safe.wallet_import.trezor_metadata as tm

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Client(Session):
        pass

    calls = []
    fake_misc = ModuleType("trezorlib.misc")
    fake_tools = ModuleType("trezorlib.tools")
    fake_client = ModuleType("trezorlib.client")

    def encrypt_keyvalue(session, path, key, value, *, ask_on_encrypt, ask_on_decrypt):
        calls.append((session, path, key, value, ask_on_encrypt, ask_on_decrypt))
        return bytes.fromhex(MASTER_HEX)

    fake_misc.encrypt_keyvalue = encrypt_keyvalue
    fake_tools.parse_path = lambda p: ("PARSED", p)
    fake_client.get_default_client = lambda name: Client()
    fake_client.get_default_session = lambda client: Session()
    trezorlib = ModuleType("trezorlib")
    trezorlib.misc = fake_misc
    trezorlib.tools = fake_tools
    monkeypatch.setitem(sys.modules, "trezorlib", trezorlib)
    monkeypatch.setitem(sys.modules, "trezorlib.misc", fake_misc)
    monkeypatch.setitem(sys.modules, "trezorlib.tools", fake_tools)
    monkeypatch.setitem(sys.modules, "trezorlib.client", fake_client)
    assert tm.get_legacy_master_key_from_usb() == bytes.fromhex(MASTER_HEX)
    assert calls[0][1:] == (
        ("PARSED", "m/10015'/0'"),
        "Enable labeling?",
        bytes.fromhex("fedcba98765432100123456789abcdeffedcba98765432100123456789abcdef"),
        True,
        True,
    )
    tm.get_legacy_master_key_from_usb(encryption_version=2)
    assert calls[-1][-2:] == (False, False)
