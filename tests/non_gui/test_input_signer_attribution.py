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

from bitcoin_safe.input_signature_verifier import InputResult, InputVerdict
from bitcoin_safe.input_signer_attribution import attribute_input_signers
from bitcoin_safe.keystore import KeyStore

# Testnet xpub derived from the BIP39 "abandon ... about" seed. Its child at /0/5 has the
# compressed pubkey below, as produced by bdk's DescriptorPublicKey.derive.
_XPUB = "tpubD6NzVbkrYhZ4XYa9MoLt4BiMZ4gkt2faZ4BcmKu2a9te4LDpQmvEz2L2yDERivHxFPnxXXhqDRkUNnQCpZggCyEZLBktV7VaSmwayqMJy1s"
_CHILD_0_5 = bytes.fromhex("020feca84486dfc16d4cc8643e243cb50eb64d856a25c5caa14659d8e2784854f6")
_OTHER_KEY = bytes.fromhex("03380288dab1b19dac3e3c0c55e1005c954933e590a44d381bdc6dffd07bc5c023")
_KEYSTORE = KeyStore(
    xpub=_XPUB, fingerprint="73C5DA0A", key_origin="m/84h/1h/0h", network=bdk.Network.TESTNET
)
_NETWORK = bdk.Network.TESTNET


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
