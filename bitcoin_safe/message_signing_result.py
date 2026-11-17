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

"""Match returned Bitcoin message signatures to wallet descriptor keys."""

import base64
from dataclasses import dataclass

import bdkpython as bdk
from hwilib import _base58, _bech32
from hwilib.key import ExtendedKey, parse_path

from bitcoin_safe.i18n import translate
from bitcoin_safe.keystore import KeyStore
from bitcoin_safe.message_signature_verifyer import MessageSignatureVerifyer, hash160


@dataclass(frozen=True)
class MessageSigningInfo:
    """Public information needed to check a signature for a derivation path."""

    bip32_path: str
    network: bdk.Network
    keystores: tuple[KeyStore, ...]

    def snapshot(self, bip32_path: str | None = None) -> "MessageSigningInfo":
        keystores = tuple(keystore.clone() for keystore in self.keystores)
        for keystore in keystores:
            keystore.mnemonic = None
        return MessageSigningInfo(
            bip32_path if bip32_path is not None else self.bip32_path, self.network, keystores
        )


@dataclass(frozen=True)
class MessageSigningResult:
    signature: str
    signer: KeyStore | None = None
    address: str = ""
    armored: str = ""
    error: str = ""


def verify_signing_result(
    message: str, signing_info: MessageSigningInfo, returned: str
) -> MessageSigningResult:
    verifier = MessageSignatureVerifyer()
    signature = returned.strip()
    claimed_address = ""
    if signature.startswith("-----BEGIN BITCOIN SIGNED MESSAGE-----"):
        try:
            claimed_address, returned_message, signature = verifier._parse_bip137_block(signature)
        except Exception:
            return MessageSigningResult(
                returned, error=translate("signatures", "Could not parse the returned signed message.")
            )
        if returned_message != message:
            return MessageSigningResult(
                returned,
                error=translate("signatures", "The returned message differs from the requested message."),
            )
    try:
        recovery_id, compressed, compact = verifier._decode_signature(signature)
        digest = verifier._hash_message(message.encode("utf-8"))
        key = verifier._recover_public_key(compact, digest, recovery_id)
        verifier._ensure_signature_matches(key, compact, digest)
        public_key = verifier._public_key_bytes(key, True)
        path = parse_path(signing_info.bip32_path)
    except Exception:
        return MessageSigningResult(
            returned, error=translate("signatures", "The signature or derivation path could not be verified.")
        )

    matches = []
    for signer in signing_info.keystores:
        try:
            origin = parse_path(signer.key_origin)
            if path[: len(origin)] != origin:
                continue
            relative_path = path[len(origin) :]
            if any(index >= 2**31 for index in relative_path):
                continue
            derivation = bdk.DerivationPath("m" + "".join(f"/{index}" for index in relative_path))
            derived = bdk.DescriptorPublicKey.from_string(signer.xpub).derive(derivation)
            derived_xpub = str(derived).rsplit("]", 1)[-1]
            if ExtendedKey.deserialize(derived_xpub).pubkey == public_key:
                matches.append(signer)
        except Exception:
            continue
    if len(matches) != 1:
        return MessageSigningResult(
            returned,
            error=translate("signatures", "Could not uniquely match the signature to a wallet signer."),
        )

    pubkey = verifier._public_key_bytes(key, compressed)
    key_hash = hash160(pubkey)
    header = base64.b64decode(signature)[0]
    mainnet = signing_info.network == bdk.Network.BITCOIN
    if header >= 39:
        hrp = "bc" if mainnet else "bcrt" if signing_info.network == bdk.Network.REGTEST else "tb"
        address = _bech32.encode(hrp, 0, key_hash)
    elif header >= 35:
        address = _base58.encode_check(bytes([5 if mainnet else 196]) + hash160(b"\x00\x14" + key_hash))
    else:
        address = _base58.encode_check(bytes([0 if mainnet else 111]) + key_hash)
    if claimed_address:
        try:
            if not verifier._verify_once(claimed_address, message, signature):
                raise ValueError("Address mismatch")
        except Exception:
            return MessageSigningResult(
                returned, error=translate("signatures", "The returned address could not be verified.")
            )
        address = claimed_address
    if not address:
        return MessageSigningResult(
            returned, error=translate("signatures", "The signing address could not be derived.")
        )
    armored = (
        f"-----BEGIN BITCOIN SIGNED MESSAGE-----\n{message}\n"
        f"-----BEGIN BITCOIN SIGNATURE-----\n{address}\n{signature}\n-----END BITCOIN SIGNATURE-----"
    )
    try:
        parsed_address, parsed_message, parsed_signature = verifier._parse_bip137_block(armored)
        if parsed_message != message or not verifier._verify_once(
            parsed_address, parsed_message, parsed_signature
        ):
            armored = ""
    except Exception:
        armored = ""
    return MessageSigningResult(signature, matches[0], address, armored)
