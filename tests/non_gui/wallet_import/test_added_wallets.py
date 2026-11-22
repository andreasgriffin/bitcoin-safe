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

"""Synthetic tests for additional public-wallet source importers.

No mnemonic, extended private key, or real wallet data is committed here.
"""

import base64
import hashlib
import hmac
import json
import zlib

import pytest
from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bitcoin_safe.wallet_import.adapters import from_sparrow_json, load_file, load_json_obj
from bitcoin_safe.wallet_import.electrum import decrypt_electrum, from_electrum, is_electrum_encrypted
from bitcoin_safe.wallet_import.model import ExchangeError, WalletExchange
from bitcoin_safe.wallet_import.sparrow_crypto import N, _compressed

from .test_wallet_exchange import xpub


def _encrypt_electrum(test_data: dict, password: str, *, magic: bytes = b"BIE1") -> bytes:
    # Independently build Electrum's authenticated ECIES BIE1/BIE2, using its known
    # password KDF and compressed-ECDH protocol. For unit tests only.
    password_seed = hashlib.pbkdf2_hmac("sha512", password.encode(), b"", 1024)
    scalar = int.from_bytes(password_seed, "big") % N
    target = ec.derive_private_key(scalar, ec.SECP256K1())
    ephemeral = ec.generate_private_key(ec.SECP256K1())
    # Cryptography returns x-only ECDH; get full shared point for y parity.
    from bitcoin_safe.wallet_import.sparrow_crypto import _scalar_mul

    public = target.public_key().public_numbers()
    shared = _compressed(_scalar_mul(ephemeral.private_numbers().private_value, (public.x, public.y)))
    d = hashlib.sha512(shared).digest()
    iv, key_e, key_m = d[:16], d[16:32], d[32:]
    raw = zlib.compress(json.dumps(test_data).encode())
    padder = padding.PKCS7(128).padder()
    padded = padder.update(raw) + padder.finalize()
    cipher = Cipher(algorithms.AES(key_e), modes.CBC(iv)).encryptor()
    enc = cipher.update(padded) + cipher.finalize()
    eph_pub = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    )
    body = magic + eph_pub + enc
    return base64.b64encode(body + hmac.new(key_m, body, hashlib.sha256).digest())


def test_electrum_storage_password_and_no_secret_output(tmp_path):
    data = {
        "wallet_type": "standard",
        "seed_version": 55,
        "use_encryption": True,
        "keystore": {
            "type": "bip32",
            "xpub": xpub(0x04B24746),
            "seed": "words that must never escape",
            "root_fingerprint": "beefcafe",
            "derivation": "m/84h/0h/0h",
        },
        "labels": {"b" * 64: "business invoice"},
    }
    source = tmp_path / "electrum-no-extension"
    source.write_bytes(_encrypt_electrum(data, "0000"))
    assert is_electrum_encrypted(source.read_bytes())
    wallet = load_file(source, password="0000")[0]
    assert wallet.source_wallet == "electrum"
    assert wallet.network == "mainnet"
    assert wallet.descriptor.startswith("wpkh(")
    assert wallet.keystores[0].recovery_material == "SEED_REDACTED"
    assert any(label.ref == "b" * 64 for label in wallet.labels)
    wire = wallet.to_json()
    assert "SEED_REDACTED" in wire and "words that must" not in wire
    assert WalletExchange.from_dict(json.loads(wire)).keystores[0].recovery_material == "SEED_REDACTED"
    with pytest.raises(ExchangeError, match="Incorrect Electrum password"):
        load_file(source, password="not-the-password")


def test_electrum_bie2_requires_device_export():
    packet = base64.b64encode(b"BIE2" + b"e" * 81)
    assert is_electrum_encrypted(packet)
    with pytest.raises(ExchangeError, match="BIE2"):
        decrypt_electrum(packet, "0000")


def test_electrum_multisig_policy_sorted_and_markers():
    multi = {
        "wallet_type": "2of3",
        "x1": {"xpub": xpub(0x02575483), "type": "bip32", "xprv": "encrypted-private-value"},
        "x2": {"xpub": xpub(0x02575483), "type": "hardware"},
        "x3": {"xpub": xpub(0x02575483), "type": "hardware"},
        "labels": {},
        "frozen_coins": {"a" * 64 + ":0": True},
    }
    w = from_electrum(multi)
    assert w.threshold == 2 and len(w.keystores) == 3
    assert "sortedmulti(2," in w.descriptor
    assert w.keystores[0].recovery_material == "PRIVATE_KEY_REDACTED"
    assert w.frozen_outpoints == ["a" * 64 + ":0"]
    assert "encrypted-private-value" not in w.to_json()
    assert load_json_obj(multi)[0].source_wallet == "electrum"


def test_electrum_unverifiable_descriptor_fails_closed():

    data = {
        "wallet_type": "standard",
        "keystore": {"type": "bip32", "xpub": xpub(0x04B24746)},
        "addresses": {"receiving": ["bc1q" + "0" * 45]},
    }
    with pytest.raises(ExchangeError, match="does not match"):
        from_electrum(data)


def test_sparrow_redaction_persists_without_seed_value():
    seed_mnemonic = "private recovery phrase should not appear"
    data = {
        "name": "Live",
        "scriptType": "P2WPKH",
        "network": "MAINNET",
        "keystores": [
            {
                "label": "Signer",
                "source": "SW_SEED",
                "walletModel": "SPARROW",
                "extendedPublicKey": xpub(),
                "seed": {"mnemonicString": seed_mnemonic},
            }
        ],
        "defaultPolicy": {"miniscript": {"script": "wpkh(Signer)"}},
    }
    w = from_sparrow_json(data)
    assert w.keystores[0].recovery_material == "SEED_REDACTED"
    assert seed_mnemonic not in w.to_json()
    assert "SEED_REDACTED" in w.to_json()
    with pytest.raises(ExchangeError, match="Invalid recovery material marker"):
        w.keystores[0].recovery_material = "NOT_REDACTED"
        w.to_json()


def test_wasabi_multiple_script_accounts_and_no_private_material():
    obj = {
        "ExtPubKey": xpub(),
        "TaprootExtPubKey": xpub(),
        "MasterFingerprint": "f00dbabe",
        "BlockchainState": {"Network": "Main", "BirthHeight": 838000},
        "EncryptedSecret": "high-risk-secret-stored-here",
        "AccountKeyPath": "m/84h/0h/0h",
        "TaprootAccountKeyPath": "m/86h/0h/0h",
        "MinGapLimit": 31,
        "ExcludedCoinsFromCoinJoin": ["a" * 64 + ":1"],
    }
    wallets = load_json_obj(obj)
    assert len(wallets) == 2
    assert wallets[0].descriptor.startswith("wpkh(") and wallets[1].descriptor.startswith("tr(")
    assert all(w.keystores[0].recovery_material == "PRIVATE_KEY_REDACTED" for w in wallets)
    assert all(w.frozen_outpoints == [] for w in wallets)  # CoinJoin exclusions are NOT freezes
    assert all("high-risk-secret-stored-here" not in w.to_json() for w in wallets)


def test_invalid_labels_and_private_recovery_not_accepted():
    from bitcoin_safe.wallet_import.model import Keystore

    k = Keystore(recovery_material="SEED_REDACTED")
    assert k.public_dict()["recovery_material"] == "SEED_REDACTED"
    k.recovery_material = "not a safe marker"
    with pytest.raises(ExchangeError):
        k.public_dict()


def test_h2_password_verified_against_encrypted_mvstore_sector(tmp_path):
    """Independent synthetic H2 2.1 header encrypted with its AES/XTS scheme."""
    from bitcoin_safe.wallet_import.h2_verify import _aes_block, verify_sparrow_h2_password
    from bitcoin_safe.wallet_import.sparrow_h2 import H2_MAGIC, H2_SPRW_MAGIC, sparrow_h2_file_password

    header = H2_MAGIC + b"12345678" + H2_SPRW_MAGIC + b"1234567890abcdef"
    header += b"\0" * (4096 - len(header))
    pubhex = sparrow_h2_file_password(header, "0000")
    file_key = hashlib.pbkdf2_hmac("sha256", pubhex.encode("utf-16-be"), header[10:18], 10, dklen=16)
    plain = b"H:2,block:2,chunk:0,version:1," + b"\x00" * (4096 - 30)
    assert len(plain) == 4096
    tweak = bytearray(_aes_block(file_key, bytes(16)))
    encrypted = bytearray()
    for offset in range(0, 4096, 16):
        interm = bytes(a ^ b for a, b in zip(plain[offset : offset + 16], tweak, strict=True))
        interim = _aes_block(file_key, interm)
        encrypted.extend(a ^ b for a, b in zip(interim, tweak, strict=True))
        carry = 0
        for j in range(16):
            v = (tweak[j] << 1) + carry
            tweak[j] = v & 255
            carry = v >> 8
        if carry:
            tweak[0] ^= 0x87
    fname = tmp_path / "synthetic.mv.db"
    fname.write_bytes(header + encrypted)
    assert verify_sparrow_h2_password(fname, "0000")
    with pytest.raises(ExchangeError, match="Incorrect Sparrow H2 password"):
        verify_sparrow_h2_password(fname, "nope")


def test_h2_seed_reference_becomes_explicit_redacted_marker():
    from bitcoin_safe.wallet_import.sparrow_h2 import from_sparrow_h2_rows

    from .test_sparrow_h2 import synthetic_h2_rows

    rows = synthetic_h2_rows()
    rows["schemas"][0]["keystore"][0]["seed"] = 123  # ID reference only, NO seed bytes read
    wallets = from_sparrow_h2_rows(rows)
    assert wallets[0].keystores[0].recovery_material == "SEED_REDACTED"
    assert "SEED_REDACTED" in wallets[0].to_json()


def test_h2_actual_unencrypted_file_signature_recognized(tmp_path):
    from bitcoin_safe.wallet_import.sparrow_h2 import is_sparrow_h2

    p = tmp_path / "wallet.mv.db"
    p.write_bytes(b"H:2,block:2,chunk:0,version:1," + b"\0" * 300)
    assert is_sparrow_h2(p)
