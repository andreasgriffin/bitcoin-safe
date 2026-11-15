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
"""Attribute verified input signatures to the keystore fingerprints that produced them.

The signature verifier returns the public keys behind valid ECDSA signatures. This
module maps those keys back to wallet keystores by deriving each keystore's child key
at the input's wallet derivation (keychain, index) and comparing the key hash to the
signing key's hash. bdk performs the derivation, so no separate BIP32 implementation is needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import bdkpython as bdk
from bitcoin_safe_lib.util import network_kind
from btclib.hashes import hash160

from bitcoin_safe.input_signature_verifier import InputResult
from bitcoin_safe.keystore import KeyStore


def derived_key_hash(keystore: KeyStore, keychain_index: bdk.KeychainAndIndex, network: bdk.Network) -> bytes:
    """Return the HASH160 of a keystore's compressed child public key at ``/<keychain>/<index>``."""
    keychain_number = 0 if keychain_index.keychain == bdk.KeychainKind.EXTERNAL else 1
    descriptor = bdk.Descriptor(
        f"wpkh({keystore.xpub}/{keychain_number}/{keychain_index.index})", network_kind(network)
    )
    script_pubkey = descriptor.derive_address(0, network).script_pubkey().to_bytes()
    # A P2WPKH script_pubkey is OP_0 <20-byte HASH160(pubkey)>.
    return script_pubkey[2:]


def attribute_input_signers(
    result: InputResult,
    keychain_index: bdk.KeychainAndIndex | None,
    keystores: Sequence[KeyStore],
    network: bdk.Network,
) -> tuple[str, ...]:
    """Map an input's valid signing pubkeys to keystore fingerprints.

    Only wallet-owned inputs have a known derivation, so ``keychain_index`` is None
    for inputs the wallet does not own, which yields no fingerprints.
    """
    if keychain_index is None or not result.signer_pubkeys:
        return ()
    fingerprints: list[str] = []
    for signer_pubkey in result.signer_pubkeys:
        signer_hash = hash160(signer_pubkey)
        for keystore in keystores:
            if derived_key_hash(keystore, keychain_index, network) == signer_hash:
                fingerprints.append(keystore.fingerprint)
                break
    return tuple(fingerprints)


def signers_per_input(
    results: Sequence[InputResult],
    keychain_indices: Sequence[bdk.KeychainAndIndex | None],
    keystores: Sequence[KeyStore],
    network: bdk.Network,
) -> list[tuple[str, ...]]:
    """Attribute every input in transaction order."""
    return [
        attribute_input_signers(result, keychain_index, keystores, network)
        for result, keychain_index in zip(results, keychain_indices, strict=True)
    ]
