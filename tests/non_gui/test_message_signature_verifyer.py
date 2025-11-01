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

from __future__ import annotations

import base64

from ecdsa import SECP256k1, SigningKey, VerifyingKey, util
from hwilib import _bech32

from bitcoin_safe.message_signature_verifyer import MessageSignatureVerifyer, hash160


def _create_message_signature(message: str, privkey_hex: str, compressed: bool) -> tuple[str, bytes]:
    """Create message signature."""
    message_bytes = message.encode("utf-8")
    digest = MessageSignatureVerifyer._hash_message(message_bytes)
    signing_key = SigningKey.from_string(bytes.fromhex(privkey_hex), curve=SECP256k1)
    signature_string = signing_key.sign_digest_deterministic(digest, sigencode=util.sigencode_string_canonize)

    verifying_key = signing_key.get_verifying_key()
    recovered_candidates = VerifyingKey.from_public_key_recovery_with_digest(
        signature_string, digest, curve=SECP256k1, sigdecode=util.sigdecode_string
    )

    for recovery_id, candidate in enumerate(recovered_candidates):
        if candidate and candidate.to_string() == verifying_key.to_string():
            header = 27 + recovery_id + (4 if compressed else 0)
            signature = base64.b64encode(bytes([header]) + signature_string).decode("ascii")
            pubkey_bytes = MessageSignatureVerifyer._public_key_bytes(verifying_key, compressed)
            return signature, pubkey_bytes

    raise AssertionError("Failed to recover the expected public key")


def test_verify_message_p2pkh() -> None:
    """Test verify message p2pkh."""
    verifyer = MessageSignatureVerifyer()
    privkey_hex = "1" * 64
    message = "Hardware wallet verification"
    signature, pubkey_bytes = _create_message_signature(message, privkey_hex, compressed=False)

    network = MessageSignatureVerifyer.NETWORKS[0]
    pubkey_hash = hash160(pubkey_bytes)
    address = MessageSignatureVerifyer._to_base58_address(network.p2pkh_prefix, pubkey_hash)

    result = verifyer.verify_message(address, message, signature)

    assert result.match
    assert result.warnings == []
    assert result.normalized_message == message


def test_verify_message_p2wpkh_and_nested() -> None:
    """Test verify message p2wpkh and nested."""
    verifyer = MessageSignatureVerifyer()
    privkey_hex = "2" * 64
    message = "SegWit verification"
    signature, pubkey_bytes = _create_message_signature(message, privkey_hex, compressed=True)

    network = MessageSignatureVerifyer.NETWORKS[0]
    pubkey_hash = hash160(pubkey_bytes)
    bech32_address = _bech32.encode(network.bech32_hrp, 0, pubkey_hash)
    redeem_script = b"\x00\x14" + pubkey_hash
    nested_hash = hash160(redeem_script)
    nested_address = MessageSignatureVerifyer._to_base58_address(network.p2sh_prefix, nested_hash)

    assert verifyer.verify_message(bech32_address, message, signature).match
    assert verifyer.verify_message(nested_address, message, signature).match


def test_verify_message_trims_whitespace() -> None:
    """Test verify message trims whitespace."""
    verifyer = MessageSignatureVerifyer()
    privkey_hex = "3" * 64
    message = "Trim me"
    signature, pubkey_bytes = _create_message_signature(message, privkey_hex, compressed=True)

    network = MessageSignatureVerifyer.NETWORKS[0]
    pubkey_hash = hash160(pubkey_bytes)
    address = _bech32.encode(network.bech32_hrp, 0, pubkey_hash)

    noisy_message = f"  {message}\n"
    result = verifyer.verify_message(address, noisy_message, signature)

    assert result.match
    assert result.normalized_message == message
    assert result.warnings == [
        "Message had surrounding whitespace. Verification succeeded after trimming the message."
    ]


def test_verify_message_invalid_signature() -> None:
    """Test verify message invalid signature."""
    verifyer = MessageSignatureVerifyer()
    privkey_hex = "4" * 64
    message = "Invalid signature"
    signature, pubkey_bytes = _create_message_signature(message, privkey_hex, compressed=True)

    network = MessageSignatureVerifyer.NETWORKS[0]
    pubkey_hash = hash160(pubkey_bytes)
    address = _bech32.encode(network.bech32_hrp, 0, pubkey_hash)

    bad_signature = "not-base64"
    result = verifyer.verify_message(address, message, bad_signature)

    assert not result.match
    assert result.error is not None

    # Ensure a signature cannot be used for a different message
    different_message_result = verifyer.verify_message(address, "different", signature)
    assert not different_message_result.match


def _b64_to_bytes(sig_b64: str) -> bytearray:
    """B64 to bytes."""
    try:
        raw = base64.b64decode(sig_b64)
    except Exception as e:
        raise ValueError("Invalid base64 signature") from e
    if len(raw) != 65:
        raise ValueError("Decoded signature must be 65 bytes (recoverable ECDSA signature)")
    return bytearray(raw)


def _bytes_to_b64(raw: bytes | bytearray) -> str:
    """Bytes to b64."""
    return base64.b64encode(bytes(raw)).decode("ascii")


def invalidate_header(signature_b64: str) -> str:
    """Corrupt only the header (recovery byte) of a 65-byte recoverable signature.

    This will typically prevent public-key recovery (and therefore verification).
    """
    sig = _b64_to_bytes(signature_b64)
    # Modify header byte. Use XOR with a value that flips meaningful bits (but not 0).
    # We make sure to change it (in case header is weird) by toggling lower 3 bits + compression bit.
    sig[0] ^= 0x07  # flip recovery id bits (0..3) (simple deterministic change)
    # also flip compression bit (bit 2 in common encodings) to be sure header changes
    sig[0] ^= 0x04
    return _bytes_to_b64(sig)


def invalidate_r(signature_b64: str) -> str:
    """Corrupt the R component of the signature (bytes 1..32).

    This keeps header untouched but makes the signature invalid for verification.
    """
    sig = _b64_to_bytes(signature_b64)
    # R occupies bytes 1..32 (inclusive). We'll flip a pattern across those bytes.
    for i in range(1, 33):
        # XOR with 0xAA on alternating bytes for deterministic corruption
        sig[i] ^= 0xAA if (i % 2 == 0) else 0x55
    return _bytes_to_b64(sig)


def invalidate_s(signature_b64: str) -> str:
    """Corrupt the S component of the signature (bytes 33..64).

    This keeps header and R untouched but makes the signature invalid for verification.
    """
    sig = _b64_to_bytes(signature_b64)
    # S occupies bytes 33..64 inclusive (indices 33..64 -> python indices 33..64)
    for i in range(33, 65):
        # XOR with a different deterministic pattern to avoid accidental collision with R corruption
        sig[i] ^= 0x3C if (i % 3 == 0) else 0xC3
    return _bytes_to_b64(sig)


def test_static():
    """Test static."""

    def check_all(verifyer: MessageSignatureVerifyer, address, message, signature):
        """Check all."""
        result = verifyer.verify_message(address, message, signature)
        assert result.match

        result = verifyer.verify_message(address, message, invalidate_header(signature))
        assert not result.match

        result = verifyer.verify_message(address, message, invalidate_r(signature))
        assert not result.match

        result = verifyer.verify_message(address, message, invalidate_s(signature))
        assert not result.match

    # signet
    message = "test1"
    address = "tb1q0x8hqlzc4x5rrlld50qn6yvj2h7jg49cgqc3dh"
    signature = "IGuLwe0qHi/YdhnhABMLjYi7O+kMxeo6l15GC+ar6NUcKJV4LMZm8vu29U+J0w9SuX8Oik5JGzYO4beWdfO+Rrw="

    verifyer = MessageSignatureVerifyer()
    result = verifyer.verify_message(address, message, signature)
    assert result.match

    check_all(verifyer, address, message, signature)

    # regtest
    message = "test1"
    address = "bcrt1qcjzs4ssz3easw627cn6nhel5z9ns80qf6cdyd3"
    signature = "IGf3B02DcceJBhqh3/vVgXOKOwpshWHs5WvGmzBsIQnYPyWtj5wseXOIQkEc/jw3NjzpMWnIXRaQoHbiDA6Gi4w="

    verifyer = MessageSignatureVerifyer()
    check_all(verifyer, address, message, signature)

    # mainnet
    message = "test1"
    address = "bc1q745cz9krup6y0rcglcneqhluvsyg6gwtnw4r85"
    signature = "HwEe8N9JI/ALgTgT+XCYUm621CzKEp9s1TdicXRN7eeUESwi6A5e5impxIdcOZjnuM6e4Xk9tfGxozNMq2dDYA0="

    verifyer = MessageSignatureVerifyer()
    check_all(verifyer, address, message, signature)

    # mainnet legacy
    message = "test1"
    address = "1KhYNWHDa1Ef5rQEUNKQjufi1Ggm2X5Jw3"
    signature = "IDqaBpfSu2F/U/z38SFptC2LyVfQ7ODfPaJ/LR85MKEJBfKN0a/9OPOT1p2bbwaLzZs5wtFoiYO75mwNvxVcpyo="

    verifyer = MessageSignatureVerifyer()
    check_all(verifyer, address, message, signature)

    # legacy
    message = "test1"
    address = "mtEjYNFGEPryCQwNbBmHRTjrvdkPYw71gE"
    signature = "IDUagVRDc3ApRRIrRccMsWbYOu9Aj8Eq4cRIXFzBGfT7UZAq3+XnoZI/tw6EehSHD/52KuA+q+gy5ilnzIrTwQI="

    verifyer = MessageSignatureVerifyer()
    check_all(verifyer, address, message, signature)
