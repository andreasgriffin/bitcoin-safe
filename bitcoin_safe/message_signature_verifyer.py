#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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
"""Utilities for verifying Bitcoin signed messages.

This module implements verification of messages signed by Bitcoin private keys
using the **Bitcoin Signed Message** format (i.e., the format used by Core,
Electrum, hardware wallets, etc.).

Key points this module enforces and explains inline:

* The *message magic* prefix (``"\x18Bitcoin Signed Message:\n"``) and a
  varint-encoded message length are prepended before double-SHA256 hashing.
* The signature is expected in Base64, consisting of a 65-byte compact
  recoverable signature: 1 header byte + 64 bytes of (r||s).
* The header byte encodes both the recovery id (0-3) and whether the original
  public key was compressed (adds 4 when compressed), following the de-facto
  standard used by Bitcoin Core.
* We recover the public key from the signature and message hash, then check
  that the provided address corresponds to that key for all supported network
  address types (legacy Base58 P2PKH/P2SH and Bech32 P2WPKH).

The functions include detailed docstrings and inline comments explaining *why*
we do each step, not just *what* we do, to aid reviewers and future maintainers.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from Crypto.Hash import RIPEMD160, SHA256
from ecdsa import BadSignatureError, SECP256k1, VerifyingKey, util
from hwilib import _base58, _bech32
from hwilib.common import sha256

from .i18n import translate


def hash160(data: bytes) -> bytes:
    """Compute RIPEMD160(SHA256(data))."""

    sha = SHA256.new()
    sha.update(data)
    ripe = RIPEMD160.new()
    ripe.update(sha.digest())
    return ripe.digest()


class MessageVerificationError(Exception):
    """Raised when a signed message cannot be verified.

    We raise this error when *format* or *cryptographic* checks fail. The
    higher-level API catches it and returns a friendly `MessageVerificationResult`
    containing a localized error string rather than bubbling exceptions to callers.
    """


@dataclass(frozen=True)
class MessageVerificationResult:
    """Result of verifying a signed message.

    Attributes
    ----------
    match:
        ``True`` if the signature is valid **and** the recovered public key
        corresponds to the provided address; otherwise ``False``.
    warnings:
        Non-fatal issues encountered during verification (e.g., trimming
        whitespace changed the message). These are surfaced to help users
        diagnose formatting pitfalls without failing verification.
    normalized_message:
        The exact message string used for the final verification attempt
        (possibly trimmed). Return this so callers can display precisely
        what was actually verified.
    error:
        Localized explanation when ``match`` is ``False`` (e.g., malformed
        signature, address mismatch). ``None`` on success.
    """

    match: bool
    warnings: list[str]
    normalized_message: str
    error: str | None = None


@dataclass(frozen=True)
class _NetworkParams:
    """Internal container for per-network address parameters."""

    name: str
    p2pkh_prefix: int
    p2sh_prefix: int
    bech32_hrp: str


class MessageSignatureVerifyer:
    """Verify Bitcoin signed messages produced by hardware wallets.

    This class focuses on *message* signatures (not transaction signatures). It supports common Bitcoin
    networks (mainnet, testnet, regtest) and the standard address types that can represent keys used to sign
    messages.
    """

    # Supported networks and their address encoding parameters.
    NETWORKS: tuple[_NetworkParams, ...] = (
        _NetworkParams("mainnet", 0x00, 0x05, "bc"),
        _NetworkParams("testnet", 0x6F, 0xC4, "tb"),
        _NetworkParams("regtest", 0x6F, 0xC4, "bcrt"),
    )

    def verify_message(self, address: str, message: str, signature: str) -> MessageVerificationResult:
        """Verify a Bitcoin signed message against a given address.

        The method attempts verification twice: first as-is, and then with
        surrounding whitespace trimmed. The latter mirrors common wallet UI
        behaviors and avoids false negatives when users accidentally copy
        extra whitespace/newlines.

        Parameters
        ----------
        address:
            Destination address claimed to control the signing key.
        message:
            UTF-8 string that was signed by the wallet.
        signature:
            Base64-encoded 65-byte compact recoverable signature.

        Returns
        -------
        MessageVerificationResult
            Structured result including warnings and any error message.
        """

        warnings: list[str] = []
        error: str | None = None

        try:
            # First attempt: verify with the message exactly as provided.
            if self._verify_once(address, message, signature):
                return MessageVerificationResult(True, warnings, message)
        except MessageVerificationError as exc:
            # Keep the most recent error to surface if the second attempt fails.
            error = str(exc)

        # Some UIs copy trailing newlines/spaces; try again with a trimmed message.
        stripped_message = message.strip()
        if stripped_message != message:
            try:
                if self._verify_once(address, stripped_message, signature):
                    warnings.append(
                        translate(
                            "signatures",
                            "Message had surrounding whitespace. "
                            "Verification succeeded after trimming the message.",
                        )
                    )
                    return MessageVerificationResult(True, warnings, stripped_message)
            except MessageVerificationError as exc:
                error = str(exc)

        # Normalize to what we actually used in the final attempt, to be explicit.
        normalized = stripped_message if stripped_message != message else message
        return MessageVerificationResult(False, warnings, normalized, error)

    def verify_message_asciguarded(self, armored_block: str) -> MessageVerificationResult:
        """Verify a message encoded with the *BIP-0137* ASCII-armored format.

        BIP-0137 (see https://github.com/bitcoin/bips/blob/master/bip-0137.mediawiki)
        standardizes the *QR-friendly* text block that some wallets (e.g., Coldcard)
        display. The format wraps the message, address, and Base64 signature between
        sentinel lines:

        ``-----BEGIN BITCOIN SIGNED MESSAGE-----``
        ``<message lines>``
        ``-----BEGIN BITCOIN SIGNATURE-----``
        ``<address>``
        ``<base64 recoverable signature>``
        ``-----END BITCOIN SIGNATURE-----``

        We parse this structure, reconstruct the original message (joining any
        intermediate lines with ``"\n"`` as defined in BIP-0137), and reuse the
        existing :py:meth:`verify_message` implementation to perform the actual
        cryptographic checks.
        """

        try:
            address, message, signature = self._parse_bip137_block(armored_block)
        except Exception as e:
            return MessageVerificationResult(
                False,
                [],
                str(e),
                """Could not identify the entries (address, message, signature). Example format: 
-----BEGIN BITCOIN SIGNED MESSAGE-----
Test
-----BEGIN SIGNATURE-----
1BqtNgMrDXnCek3cdDVSer4BK7knNTDTSR
ILoOBJK9kVKsdUOnJPPoDtrDtRSQw2pyMo+2r5bdUlNkSLDZLqMs8h9mfDm/alZo3DK6rKvTO0xRPrl6DPDpEik=
-----END BITCOIN SIGNED MESSAGE-----""",
            )

        return self.verify_message(address, message, signature)

    def _parse_bip137_block(self, armored_block: str) -> tuple[str, str, str]:
        """Parse a BIP-0137 ASCII-armored message block.

        This helper performs *format* validation only—it does not attempt any
        cryptographic verification. It mirrors the minimal structure described in
        https://github.com/bitcoin/bips/blob/master/bip-0137.mediawiki, rejecting
        malformed layouts early so callers can surface human-friendly errors.
        """

        # Strip leading/trailing whitespace so callers can pass multi-line strings
        # that include incidental indentation or newlines from source formatting.
        lines = [line.strip() for line in armored_block.strip().splitlines()]

        begin_messages = ["-----BEGIN BITCOIN SIGNED MESSAGE-----"]
        begin_signatures = ["-----BEGIN BITCOIN SIGNATURE-----", "-----BEGIN SIGNATURE-----"]
        end_signatures = [
            "-----END BITCOIN SIGNATURE-----",
            "-----END SIGNATURE-----",
            "-----END BITCOIN SIGNED MESSAGE-----",
        ]

        def find_first_match(lines, options):
            """
            Return the index of the first line in `lines` that matches
            any entry in `options`. Raise ValueError if none match.
            """
            for opt in options:
                if opt in lines:
                    return lines.index(opt)
            raise ValueError(f"No matching sentinel found for: {options}")

        try:
            begin_msg_index = find_first_match(lines, begin_messages)
            begin_sig_index = find_first_match(lines, begin_signatures)
            end_sig_index = find_first_match(lines, end_signatures)
        except ValueError as exc:
            raise MessageVerificationError(
                translate("signatures", "Message is not valid BIP-0137 armored text.")
            ) from exc

        if not (begin_msg_index < begin_sig_index < end_sig_index):
            raise MessageVerificationError(translate("signatures", "BIP-0137 block order is invalid."))

        # The message can span multiple lines; BIP-0137 concatenates them using
        # newlines exactly as shown in the armored block.
        message_lines = lines[begin_msg_index + 1 : begin_sig_index]
        if not message_lines:
            raise MessageVerificationError(
                translate("signatures", "BIP-0137 block is missing the message body.")
            )
        message = "\n".join(message_lines)

        # After the signature header we expect exactly two lines: address and signature.
        signature_section = lines[begin_sig_index + 1 : end_sig_index]
        if len(signature_section) != 2:
            raise MessageVerificationError(
                translate("signatures", "BIP-0137 block must contain address and signature lines.")
            )

        address, signature = signature_section
        return address, message, signature

    def _verify_once(self, address: str, message: str, signature: str) -> bool:
        """Single-pass verification of ``message`` against ``signature`` and
        ``address``.

        Steps:
          1. Hash the message with Bitcoin's message magic and double-SHA256.
          2. Decode the Base64 signature, extract recovery id and compression flag.
          3. Recover the ECDSA public key from the signature and digest.
          4. Ensure the signature actually verifies under that key and digest.
          5. Derive possible addresses from the recovered key and compare to the
             provided ``address`` for all supported formats.
        """

        # Always hash the *exact* bytes that will be presented to the wallet.
        message_bytes = message.encode("utf-8")
        digest = self._hash_message(message_bytes)

        # Parse Base64-encoded compact signature (header + r||s).
        recovery_id, compressed, sig_string = self._decode_signature(signature)

        # Recover the verifying key from the compact signature and digest.
        verifying_key = self._recover_public_key(sig_string, digest, recovery_id)

        # Double-check: the recovered key must verify the signature over the digest.
        self._ensure_signature_matches(verifying_key, sig_string, digest)

        # Prepare both compressed and uncompressed pubkey encodings. Address
        # formats depend on this, particularly for nested/segwit constraints.
        pubkey_bytes = self._public_key_bytes(verifying_key, compressed)
        pubkey_hash = hash160(pubkey_bytes)
        compressed_pubkey_bytes = self._public_key_bytes(verifying_key, True)
        compressed_pubkey_hash = hash160(compressed_pubkey_bytes)

        # Compare the provided address against all supported encodings.
        if self._address_matches(
            address,
            compressed,
            pubkey_hash,
            compressed_pubkey_hash,
        ):
            return True

        # If none match, surface a precise, localized error.
        raise MessageVerificationError(
            translate("signatures", "Address does not match recovered public key.")
        )

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        """Encode an integer using Bitcoin's *compact size* (varint) format.

        This is used by the Bitcoin Signed Message format to prefix the message length. We mirror the encoding
        rules from the protocol (1, 3, 5, or 9 bytes depending on magnitude).
        """
        if value < 0xFD:
            return value.to_bytes(1, "little")
        if value <= 0xFFFF:
            return b"\xfd" + value.to_bytes(2, "little")
        if value <= 0xFFFFFFFF:
            return b"\xfe" + value.to_bytes(4, "little")
        return b"\xff" + value.to_bytes(8, "little")

    @classmethod
    def _message_magic(cls, message: bytes) -> bytes:
        """Prefix message with Bitcoin's standard magic header and length.

        The exact prefix and varint-encoded length ensure wallets sign a *domain-separated* message, so
        signatures cannot be transplanted to transactions and vice versa.
        """
        return b"\x18Bitcoin Signed Message:\n" + cls._encode_varint(len(message)) + message

    @classmethod
    def _hash_message(cls, message: bytes) -> bytes:
        """Compute the double-SHA256 of :func:`_message_magic` applied to ``message``.

        Double hashing matches Bitcoin Core's historical behavior and prevents length-extension quirks that
        could affect single-SHA256 constructions.
        """
        return sha256(sha256(cls._message_magic(message)))

    @staticmethod
    def _decode_signature(signature: str) -> tuple[int, bool, bytes]:
        """Decode a Base64 compact signature and return ``(rec_id, compressed, sig)``.

        The first byte (27..34) encodes recovery id (0..3) plus 4 if the public
        key was compressed at signing time. The remaining 64 bytes are the raw
        ``r||s`` ECDSA pair in big-endian format.
        """
        try:
            decoded = base64.b64decode(signature.strip(), validate=True)
        except (ValueError, binascii.Error) as exc:  # type: ignore[name-defined]
            raise MessageVerificationError(translate("signatures", "Signature is not valid base64.")) from exc

        if len(decoded) != 65:
            raise MessageVerificationError(translate("signatures", "Signature must be 65 bytes long."))

        header = decoded[0]
        # BIP-0137 extends the classic header range (27..34) with additional values
        # to indicate the intended address type. The ranges are:
        #   * 27..30 : legacy P2PKH using an **uncompressed** pubkey (historic)
        #   * 31..34 : P2PKH using a **compressed** pubkey
        #   * 35..38 : P2SH-P2WPKH (compressed pubkey, nested SegWit)
        #   * 39..42 : Bech32 P2WPKH (compressed pubkey, native SegWit)
        # See https://github.com/bitcoin/bips/blob/master/bip-0137.mediawiki for the
        # decoding steps. We normalize these ranges back to 27..30 so the recovery id
        # (lowest two bits) remains consistent with the classic format.
        if header < 27 or header > 42:
            raise MessageVerificationError(translate("signatures", "Signature header byte is invalid."))

        compressed = header >= 31  # all modern encodings imply compressed pubkeys
        normalized_header = header
        if header >= 39:
            normalized_header -= 12
        elif header >= 35:
            normalized_header -= 8
        elif header >= 31:
            normalized_header -= 4

        recovery_id = normalized_header - 27

        if recovery_id > 3:
            # Defensive check: after removing +4, id must be 0..3.
            raise MessageVerificationError(translate("signatures", "Invalid recovery id in signature."))

        return recovery_id, compressed, decoded[1:]

    @staticmethod
    def _recover_public_key(sig_string: bytes, digest: bytes, recovery_id: int) -> VerifyingKey:
        """Recover the ECDSA public key from a compact signature and message digest.

        We obtain up to four candidate keys and pick by ``recovery_id``. If the
        requested index is unavailable or the library cannot recover a key, we
        raise an error rather than guessing.
        """
        try:
            candidates = VerifyingKey.from_public_key_recovery_with_digest(
                sig_string, digest, curve=SECP256k1, sigdecode=util.sigdecode_string
            )
        except Exception as exc:  # ecdsa can raise several internal errors here.
            raise MessageVerificationError(
                translate("signatures", "Unable to recover public key from signature.")
            ) from exc
        if recovery_id >= len(candidates):
            raise MessageVerificationError(
                translate("signatures", "Unable to recover public key from signature.")
            )

        verifying_key = candidates[recovery_id]
        if verifying_key is None:
            raise MessageVerificationError(
                translate("signatures", "Unable to recover public key from signature.")
            )
        return verifying_key

    @staticmethod
    def _ensure_signature_matches(verifying_key: VerifyingKey, sig_string: bytes, digest: bytes) -> None:
        """Check that ``sig_string`` is a valid signature for ``digest`` under
        ``verifying_key``.

        Public-key recovery is not a proof on its own: always verify the signature
        explicitly to catch malformed or ambiguous recoveries.
        """
        try:
            if not verifying_key.verify_digest(sig_string, digest, sigdecode=util.sigdecode_string):
                raise MessageVerificationError(translate("signatures", "Signature does not match message."))
        except BadSignatureError as exc:
            # Normalize any library exception into our domain-specific error.
            raise MessageVerificationError(
                translate("signatures", "Signature does not match message.")
            ) from exc

    @staticmethod
    def _public_key_bytes(verifying_key: VerifyingKey, compressed: bool) -> bytes:
        """Serialize ``verifying_key`` to bytes in compressed or uncompressed form.

        * Compressed: ``0x02/0x03`` + X, where the prefix encodes Y's parity.
        * Uncompressed: ``0x04`` + X + Y.
        """
        assert verifying_key.pubkey
        point = verifying_key.pubkey.point
        x = point.x().to_bytes(32, "big")
        y = point.y().to_bytes(32, "big")
        if compressed:
            prefix = 2 + (y[-1] & 1)
            return bytes([prefix]) + x
        return b"\x04" + x + y

    @classmethod
    def _address_matches(
        cls,
        address: str,
        compressed_signature: bool,
        pubkey_hash: bytes,
        compressed_pubkey_hash: bytes,
    ) -> bool:
        """Check whether ``address`` matches the recovered public key.

        We try Base58 (P2PKH, P2SH-P2WPKH) first and then Bech32 (P2WPKH). If an
        encoding library rejects the string outright, we return ``None`` from the
        helper so the other format can try. Only when a format *parses* but is
        incompatible do we raise a descriptive error.
        """
        base58_match = cls._address_matches_base58(
            address,
            compressed_signature,
            pubkey_hash,
            compressed_pubkey_hash,
        )
        if base58_match is not None:
            return base58_match

        bech32_match = cls._address_matches_bech32(
            address,
            compressed_signature,
            compressed_pubkey_hash,
        )
        if bech32_match is not None:
            return bech32_match

        # Neither decoder recognized the string as a Bitcoin address.
        raise MessageVerificationError("Invalid Bitcoin address.")

    @classmethod
    def _address_matches_base58(
        cls,
        address: str,
        compressed_signature: bool,
        pubkey_hash: bytes,
        compressed_pubkey_hash: bytes,
    ) -> bool | None:
        """Try to match a Base58Check address (P2PKH or P2SH nested SegWit).

        Returns
        -------
        Optional[bool]
            ``True`` or ``False`` if decoding succeeds; ``None`` if the string is
            not even a valid Base58Check address (so Bech32 can be attempted).
        """
        try:
            decoded = _base58.decode_check(address)
        except Exception:
            # Not Base58Check; let Bech32 logic decide next.
            return None

        if len(decoded) != 21:
            raise MessageVerificationError(translate("signatures", "Unsupported Base58 address length."))

        version = decoded[0]
        payload = decoded[1:]
        for network in cls.NETWORKS:
            if version == network.p2pkh_prefix:
                # Legacy P2PKH: payload must equal HASH160(pubkey).
                return payload == pubkey_hash
            if version == network.p2sh_prefix:
                # Nested SegWit P2SH-P2WPKH requires a *compressed* pubkey and
                # a redeem script of 0 <20-byte keyhash>. We reconstruct the
                # redeem script and compare HASH160(redeem_script) to payload.
                if not compressed_signature:
                    raise MessageVerificationError(
                        translate(
                            "signatures",
                            "Signature must use a compressed public key for nested SegWit addresses.",
                        )
                    )
                redeem_script = b"\x00\x14" + compressed_pubkey_hash
                script_hash = hash160(redeem_script)
                return payload == script_hash

        raise MessageVerificationError(translate("signatures", "Unsupported Base58 address version."))

    @classmethod
    def _address_matches_bech32(
        cls,
        address: str,
        compressed_signature: bool,
        compressed_pubkey_hash: bytes,
    ) -> bool | None:
        """Try to match a Bech32 address (native P2WPKH).

        Only witness version 0 with 20-byte program (P2WPKH) is supported here. Other versions (e.g., v1 for
        Taproot) are explicitly rejected to avoid falsely claiming verification against an address type this
        verifier does not support.
        """
        _, hrp, _ = _bech32.bech32_decode(address)
        if hrp is None:
            # Not a Bech32 string; let Base58 logic handle or error upstream.
            return None

        # Validate network by HRP to ensure we don't match an address from a
        # different network with the same 20-byte hash.
        network = next((net for net in cls.NETWORKS if net.bech32_hrp == hrp), None)
        if network is None:
            raise MessageVerificationError(translate("signatures", "Unknown bech32 network."))

        witness_version, program = _bech32.decode(hrp, address)
        if witness_version is None or program is None:
            raise MessageVerificationError(translate("signatures", "Invalid bech32 address."))
        if witness_version != 0:
            raise MessageVerificationError(translate("signatures", "Unsupported bech32 witness version."))
        if len(program) != 20:
            raise MessageVerificationError(
                translate("signatures", "Unsupported bech32 witness program length.")
            )
        if not compressed_signature:
            # Native SegWit always assumes compressed pubkeys.
            raise MessageVerificationError(
                translate("signatures", "Signature must use a compressed public key for SegWit addresses.")
            )

        return bytes(program) == compressed_pubkey_hash

    @staticmethod
    def _to_base58_address(prefix: int, payload: bytes) -> str:
        """Helper to encode a Base58Check address from ``prefix`` and ``payload``.

        This is provided for completeness and potential diagnostics; the verifier does not call it during the
        verification flow.
        """
        return _base58.encode_check(bytes([prefix]) + payload)
