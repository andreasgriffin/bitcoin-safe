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

This module maps compressed public keys and Taproot x-only key origins back to
wallet keystores. It uses bdk to derive each keystore's child key at the input's
wallet derivation (keychain, index), then compares compressed public key hashes.
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


def fingerprint_for_pubkey(
    pubkey: bytes, keychain_index: bdk.KeychainAndIndex, keystores: Sequence[KeyStore], network: bdk.Network
) -> str | None:
    """Match a compressed or x-only derived public key to a wallet keystore."""
    # Taproot key origins omit the Y parity of the derived internal key.
    pubkey_hashes = (
        {hash160(b"\x02" + pubkey), hash160(b"\x03" + pubkey)} if len(pubkey) == 32 else {hash160(pubkey)}
    )
    return next(
        (
            keystore.fingerprint
            for keystore in keystores
            if derived_key_hash(keystore, keychain_index, network) in pubkey_hashes
        ),
        None,
    )


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
        if fingerprint := fingerprint_for_pubkey(signer_pubkey, keychain_index, keystores, network):
            fingerprints.append(fingerprint)
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
