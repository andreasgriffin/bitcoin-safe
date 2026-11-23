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

from __future__ import annotations

import bdkpython as bdk
import pytest

from bitcoin_safe.input_signature_verifier import InputResult, InputVerdict
from bitcoin_safe.input_signer_attribution import attribute_input_signers, fingerprint_for_pubkey
from bitcoin_safe.keystore import KeyStore

# Testnet account xpub derived at m/84h/1h/0h from the BIP39 "abandon ... about" seed. Its child at /0/5 has the
# compressed pubkey below, as produced by bdk's DescriptorPublicKey.derive.
_XPUB = "tpubDC8msFGeGuwnKG9Upg7DM2b4DaRqg3CUZa5g8v2SRQ6K4NSkxUgd7HsL2XVWbVm39yBA4LAxysQAm397zwQSQoQgewGiYZqrA9DsP4zbQ1M"
_CHILD_0_5 = bytes.fromhex("03610008903596be72b0be7ed0dc9c2165fa6c82677ad77c706641a771a9bea2fd")
_OTHER_KEY = bytes.fromhex("03380288dab1b19dac3e3c0c55e1005c954933e590a44d381bdc6dffd07bc5c023")
_KEYSTORE = KeyStore(
    xpub=_XPUB, fingerprint="73C5DA0A", key_origin="m/84h/1h/0h", network=bdk.Network.TESTNET
)
_NETWORK = bdk.Network.TESTNET


@pytest.mark.parametrize(
    "keychain,index,pubkey",
    [
        (bdk.KeychainKind.EXTERNAL, 0, "cc8a4bc64d897bddc5fbc2f670f7a8ba0b386779106cf1223c6fc5d7cd6fc115"),
        (bdk.KeychainKind.EXTERNAL, 1, "83dfe85a3151d2517290da461fe2815591ef69f2b18a2ce63f01697a8b313145"),
        (bdk.KeychainKind.INTERNAL, 0, "399f1b2f4393f29a18c937859c5dd8a77350103157eb880f02e8c08214277cef"),
    ],
)
def test_bip86_xonly_internal_key_matches_keystore(
    keychain: bdk.KeychainKind, index: int, pubkey: str
) -> None:
    # BIP86 account from the "abandon ... about" mnemonic. Its first external
    # child has odd Y; the other two children have even Y.
    keystore = KeyStore(
        xpub="xpub6BgBgsespWvERF3LHQu6CnqdvfEvtMcQjYrcRzx53QJjSxarj2afYWcLteoGVky7D3UKDP9QyrLprQ3VCECoY49yfdDEHGCtMMj92pReUsQ",
        fingerprint="73C5DA0A",
        key_origin="m/86h/0h/0h",
        network=bdk.Network.BITCOIN,
    )
    derivation = bdk.KeychainAndIndex(keychain=keychain, index=index)

    assert fingerprint_for_pubkey(bytes.fromhex(pubkey), derivation, [keystore], bdk.Network.BITCOIN) == (
        "73C5DA0A"
    )
    wrong_index = bdk.KeychainAndIndex(keychain=keychain, index=index + 2)
    assert fingerprint_for_pubkey(bytes.fromhex(pubkey), wrong_index, [keystore], bdk.Network.BITCOIN) is None


def test_compressed_key_with_wrong_parity_is_not_attributed() -> None:
    derivation = bdk.KeychainAndIndex(keychain=bdk.KeychainKind.EXTERNAL, index=5)

    assert fingerprint_for_pubkey(b"\x02" + _CHILD_0_5[1:], derivation, [_KEYSTORE], _NETWORK) is None


def test_valid_signature_is_attributed_to_keystore_at_derivation() -> None:
    result = InputResult(InputVerdict.valid, (_CHILD_0_5,))
    keychain_index = bdk.KeychainAndIndex(keychain=bdk.KeychainKind.EXTERNAL, index=5)

    signers = attribute_input_signers(result, keychain_index, [_KEYSTORE], _NETWORK)

    assert signers == ("73C5DA0A",)


def test_key_not_derived_from_keystore_is_not_attributed() -> None:
    result = InputResult(InputVerdict.valid, (_OTHER_KEY,))
    keychain_index = bdk.KeychainAndIndex(keychain=bdk.KeychainKind.EXTERNAL, index=5)

    assert attribute_input_signers(result, keychain_index, [_KEYSTORE], _NETWORK) == ()


def test_wrong_index_is_not_attributed() -> None:
    result = InputResult(InputVerdict.valid, (_CHILD_0_5,))
    keychain_index = bdk.KeychainAndIndex(keychain=bdk.KeychainKind.EXTERNAL, index=6)

    assert attribute_input_signers(result, keychain_index, [_KEYSTORE], _NETWORK) == ()


def test_unowned_input_has_no_fingerprints() -> None:
    result = InputResult(InputVerdict.valid, (_CHILD_0_5,))

    assert attribute_input_signers(result, None, [_KEYSTORE], _NETWORK) == ()
