#
# Bitcoin-Safe
# Copyright (C) 2024-2026 Andreas Griffin
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

import logging
import tempfile
from pathlib import Path

import pysequoia
import pytest

from bitcoin_safe.signature_manager import (
    KnownGPGKeys,
    PGPDecodingError,
    PGPMissingSignature,
    SignatureVerifyer,
)

logger = logging.getLogger(__name__)


class _MockResponse:
    def __init__(self, status_code: int, content: bytes = b"", json_payload: dict | None = None) -> None:
        self.status_code = status_code
        self.content = content
        self._json_payload = json_payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP error: {self.status_code}")

    def json(self) -> dict:
        return self._json_payload


def _mock_sparrow_manifest_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    release_api_url = "https://api.github.com/repos/sparrowwallet/sparrow/releases/tags/1.8.4"
    manifest_url = (
        "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt"
    )
    sig_url = (
        "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt.asc"
    )

    fixture_dir = Path(__file__).resolve().parents[1] / "data"
    manifest_bytes = (fixture_dir / "sparrow-1.8.4-manifest.txt").read_bytes()
    sig_bytes = (fixture_dir / "sparrow-1.8.4-manifest.txt.asc").read_bytes()
    requested_urls: list[str] = []

    def fake_get(url: str, timeout: int, proxies: dict | None) -> _MockResponse:
        del timeout, proxies
        requested_urls.append(url)
        if url == release_api_url:
            return _MockResponse(
                200,
                json_payload={
                    "tag_name": "1.8.4",
                    "assets": [
                        {"name": "sparrow-1.8.4-manifest.txt", "browser_download_url": manifest_url},
                        {"name": "sparrow-1.8.4-manifest.txt.asc", "browser_download_url": sig_url},
                    ],
                },
            )
        if url == manifest_url:
            return _MockResponse(200, content=manifest_bytes)
        if url == sig_url:
            return _MockResponse(200, content=sig_bytes)
        return _MockResponse(404)

    monkeypatch.setattr("bitcoin_safe.signature_manager.requests.get", fake_get)
    return requested_urls


def _make_signed_message(mode: pysequoia.SignatureMode) -> tuple[pysequoia.Cert, str]:
    mode_name = "clear" if mode == pysequoia.SignatureMode.CLEAR else "inline"
    cert = pysequoia.Cert.generate(user_id=f"{mode_name}@example.com")
    signed_message = pysequoia.sign(
        cert.secrets.signer(),
        f"hello from {mode_name} mode".encode(),
        mode=mode,
    ).decode("utf-8")
    return cert, signed_message


def _tamper_armored_message(signed_message: str) -> str:
    lines = signed_message.splitlines()
    for index, line in enumerate(lines):
        if line and not line.startswith("-----") and not line.startswith("Hash:"):
            replacement = "A" if line[0] != "A" else "B"
            lines[index] = replacement + line[1:]
            return "\n".join(lines) + ("\n" if signed_message.endswith("\n") else "")
    raise AssertionError("Could not find a line to tamper with.")


def test_download_manifest_and_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download manifest and verify."""
    requested_urls = _mock_sparrow_manifest_download(monkeypatch)
    manager = SignatureVerifyer(list_of_known_keys=KnownGPGKeys.all(), proxies=None)

    with tempfile.TemporaryDirectory() as tempdir:
        logger.debug(f"tempdir {tempdir}")
        # Download the manifest signature.
        sig_filename = manager.get_signature_from_web(Path(tempdir) / "Sparrow-1.8.4-x86_64.dmg")
        assert sig_filename
        logger.debug(f"sig_filename {sig_filename}")
        manifest_file = Path(tempdir) / "sparrow-1.8.4-manifest.txt"
        assert sig_filename == Path(tempdir) / "sparrow-1.8.4-manifest.txt.asc"
        assert "https://api.github.com/repos/sparrowwallet/sparrow/releases/tags/1.8.4" in requested_urls
        assert (
            "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt"
            in requested_urls
        )
        assert (
            "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt.asc"
            in requested_urls
        )
        # Verify the signature against the known public key.
        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        assert manager._verify_file(
            public_keys=[public_key],
            binary_file=manifest_file,
            signature_file=sig_filename,
        )


def test_verify_detached_signature_with_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls = _mock_sparrow_manifest_download(monkeypatch)
    manager = SignatureVerifyer(list_of_known_keys=KnownGPGKeys.all(), proxies=None)

    with tempfile.TemporaryDirectory() as tempdir:
        sig_filename = manager.get_signature_from_web(Path(tempdir) / "Sparrow-1.8.4-x86_64.dmg")
        assert sig_filename

        manifest_file = Path(tempdir) / "sparrow-1.8.4-manifest.txt"
        assert "https://api.github.com/repos/sparrowwallet/sparrow/releases/tags/1.8.4" in requested_urls

        verified, fingerprint = manager.verify_detached_signature_with_fingerprint(
            manifest_file,
            sig_filename,
        )

        assert verified
        assert fingerprint == "D4D0D3202FC06849A257B38DE94618334C674B40"


def test_download_manifest_and_verify_wrong_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download manifest and verify wrong signature."""
    requested_urls = _mock_sparrow_manifest_download(monkeypatch)
    manager = SignatureVerifyer(list_of_known_keys=KnownGPGKeys.all(), proxies=None)

    with tempfile.TemporaryDirectory() as tempdir:
        logger.debug(f"tempdir {tempdir}")
        # Download the signature to a temp directory.
        sig_filename = manager.get_signature_from_web(Path(tempdir) / "Sparrow-1.8.4-x86_64.dmg")
        assert sig_filename
        logger.debug(f"sig_filename {sig_filename}")

        manifest_file = Path(tempdir) / "sparrow-1.8.4-manifest.txt"
        assert sig_filename == Path(tempdir) / "sparrow-1.8.4-manifest.txt.asc"
        assert "https://api.github.com/repos/sparrowwallet/sparrow/releases/tags/1.8.4" in requested_urls
        assert (
            "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt"
            in requested_urls
        )
        assert (
            "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow-1.8.4-manifest.txt.asc"
            in requested_urls
        )

        with open(sig_filename) as file:
            right_rig_content = file.read()

        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        # Correct signature should verify.
        assert manager._verify_file(
            public_keys=[public_key],
            binary_file=manifest_file,
            signature_file=sig_filename,
        )

        # Overwrite with a corrupted signature and ensure verification fails.
        wrong_sig_content = right_rig_content.replace("iQIzBAABCgAdFi", "QIzBAABCgAdFi")
        with open(sig_filename, "w") as file:
            file.write(wrong_sig_content)

        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        # Wrong signature should not verify.
        assert not manager._verify_file(
            public_keys=[public_key],
            binary_file=manifest_file,
            signature_file=sig_filename,
        )


OPENSATS_PUBLIC_KEY_BLOCK = """-----BEGIN PGP PUBLIC KEY BLOCK-----
Comment: 8198 A185 30A5 22A0 9561  2439 89C4 A25E 69A5 DE7F
Comment: Gigi <dergigi@pm.me>
Comment: Gigi D. <gigi@opensats.org>

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
nghMBFghgxaGDXLZFxE=
=FotA
-----END PGP PUBLIC KEY BLOCK-----
"""

OPENSATS_FINGERPRINT = "8198A18530A522A09561243989C4A25E69A5DE7F"


@pytest.fixture
def opensats_keyserver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve the OpenSats public key instead of contacting keys.openpgp.org."""

    class _KeyserverResponse:
        status_code = 200
        text = OPENSATS_PUBLIC_KEY_BLOCK

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, *args: object, **kwargs: object) -> _KeyserverResponse:
        assert url.endswith(OPENSATS_FINGERPRINT)
        return _KeyserverResponse()

    monkeypatch.setattr("bitcoin_safe.signature_manager.requests.get", fake_get)


@pytest.mark.usefixtures("opensats_keyserver")
def test_verify_signed_message_block_opensats_canary() -> None:
    """Verify a known OpenSats canary PGP-signed message."""

    signed_message = """-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA256

OpenSats has never been pressured to give up non-public information on grantees
and forced to keep quiet about it. OpenSats has never been pressured by outside
entities to stop funding certain people or projects.

This canary is linked at [0] and will be re-signed at the beginning of the
following months:

* February
* May
* August
* November

We include the latest Bitcoin block hash in each update to establish that the
signature was not pre-generated:

* Height: `927617`
* Block hash: `000000000000000000004b913d729e4a49bd60aca58619e131458c1b8e41750b`

[0] https://opensats.org/transparency

-----BEGIN PGP SIGNATURE-----

iQIzBAEBCAAdFiEEgZihhTClIqCVYSQ5icSiXmml3n8FAmk8ezcACgkQicSiXmml
3n/Rpg//VLUsuuPevfPSq1A2/Fcd4WtuPIZt2m5mS/041LnWIhwS8PnAZVtOphOf
GGoufOvXZYR0cdihfRVdtuHEJV8JHazoL99lUtO8Xp5UTe3Y+WLg7M8c2gkg7EsW
LveX4eDq5iDdA/QWibAekCE2ameo1XyLrL9v1R5IpSWeKI7kZCuT2drfr0T9uTso
8zbDnV8ocOIlpXmwYaY+jFPutRdg0K3fH8kPuVclTLz9CXbcQo2hbNTDqOjhvv/z
k1f4ULOC/zIlkoCwWmvoFMI+imDIkIaq3TWU4bjW2aNihrrqDUQ4CmFKgGBKWLSO
EJMEbB0o/9uEJCowG9FIQWRpzcbPcp+JogUzjHG3Uo6onSREGHZm8OgcGFMJe4pi
+Zj6xAIMRTXDvLOcv8B3JLWWhY4W4WfWnFWy7c/WYwEhASIDzMn0FGx1+kMJO6tT
ARhy8HodJn+2YXWNwfVDo2EukrNaRYV1d0CzAlrz2Q/EGlAnnFe3MGDlWvrUespp
UsSIdVnxoa6wK61YNV4VJPKhbLDes7uBRL9q5JAHrI3okeOStxBBERlG6463XMys
XoDqBd8dRcHGwPqLJW3onZ8Rehb6sIdXQrZqQpRDe2Vdd1z+2Wln5jrv+E62LDYP
kEM8Jtcf183QgWT6hgT3oFoYRqj64Boh6Zn5s4HAR1Bph665rPk=
=fkt4
-----END PGP SIGNATURE-----
"""

    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    # Download and import the public key embedded in the signed message.
    downloaded_key, fingerprint = manager.download_public_key_from_signed_message(signed_message)

    public_key = manager.import_public_key_block(downloaded_key)
    assert public_key

    # Verify that the canary signature matches the expected fingerprint.
    signer_keys, error = manager.verify_signed_message_block(signed_message, downloaded_key)
    assert signer_keys, error
    assert manager._normalize_fingerprint(signer_keys[0].fingerprint) == fingerprint == OPENSATS_FINGERPRINT

    # Modifying the message should invalidate the signature.
    changed_message = signed_message
    changed_message = changed_message[:100] + changed_message[102:]

    signer_keys, error = manager.verify_signed_message_block(changed_message, downloaded_key)
    assert not signer_keys


@pytest.mark.parametrize(
    "mode",
    [
        pysequoia.SignatureMode.CLEAR,
        pysequoia.SignatureMode.INLINE,
    ],
)
def test_parse_signed_pgp_message_accepts_bytes_variants(mode: pysequoia.SignatureMode) -> None:
    """Test steps:
    - Generate a signed message in the parametrized mode.
    - Pass the payload as raw bytes.
    - Parse it through the signed-message parser.
    - Assert the original bytes and a signature packet are returned.
    """
    _cert, signed_message = _make_signed_message(mode)
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    message_bytes, signatures = manager.parse_signed_pgp_message(signed_message.encode("utf-8"))

    assert message_bytes == signed_message.encode("utf-8")
    assert signatures
    assert manager._normalize_fingerprint(signatures[0].issuer_fingerprint)


def test_parse_signed_pgp_message_rejects_unsigned_encrypted_payload() -> None:
    """Test steps:
    - Generate an encrypted payload without adding a signature.
    - Parse it through the signed-message parser.
    - Assert parsing fails with a missing-signature error.
    """
    cert = pysequoia.Cert.generate(user_id="encrypted@example.com")
    encrypted_payload = pysequoia.encrypt(b"hello", recipients=[cert])
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    with pytest.raises(PGPMissingSignature, match="Signed message contains no signatures"):
        manager.parse_signed_pgp_message(encrypted_payload)


def test_parse_signed_pgp_message_rejects_invalid_payload() -> None:
    """Test steps:
    - Build a payload that is not valid OpenPGP data.
    - Parse it through the signed-message parser.
    - Assert parsing fails with a decoding error.
    """
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    with pytest.raises(PGPDecodingError, match="Could not parse signed PGP message"):
        manager.parse_signed_pgp_message(b"not a pgp payload")


def test_extract_unverified_clear_signed_message_plaintext() -> None:
    """Test steps:
    - Sign cleartext containing lines that OpenPGP must dash-escape.
    - Surround the armored message with multiple newlines.
    - Extract the plaintext without importing the signer certificate.
    - Assert the original content and line endings are restored.
    """
    cert = pysequoia.Cert.generate(user_id="cleartext@example.com")
    plaintext = b"first address\r\n- address starting with a dash\r\nFrom address book\r\n"
    signed_message = pysequoia.sign(
        cert.secrets.signer(),
        plaintext,
        mode=pysequoia.SignatureMode.CLEAR,
    )
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    extracted = manager.extract_unverified_signed_message_plaintext(
        f"\n\n{signed_message.decode('utf-8')}\n\n"
    )

    assert extracted == plaintext


def test_extract_unverified_inline_signed_message_plaintext() -> None:
    """Test steps:
    - Sign binary plaintext as an inline OpenPGP message.
    - Surround the armored message with multiple newlines.
    - Extract the literal packet without importing the signer certificate.
    - Assert the payload bytes are unchanged.
    """
    cert = pysequoia.Cert.generate(user_id="inline-plaintext@example.com")
    plaintext = b"inline plaintext\x00with binary data"
    signed_message = pysequoia.sign(
        cert.secrets.signer(),
        plaintext,
        mode=pysequoia.SignatureMode.INLINE,
    )
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    extracted = manager.extract_unverified_signed_message_plaintext(b"\n\n" + signed_message + b"\n\n")

    assert extracted == plaintext


def test_extract_unverified_detached_signature_rejects_missing_plaintext() -> None:
    """Test steps:
    - Create a detached signature, which carries no plaintext packet.
    - Attempt unverified plaintext extraction.
    - Assert extraction reports the missing payload.
    """
    cert = pysequoia.Cert.generate(user_id="detached@example.com")
    signature = pysequoia.sign(
        cert.secrets.signer(),
        b"detached plaintext",
        mode=pysequoia.SignatureMode.DETACHED,
    )
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    with pytest.raises(PGPDecodingError, match="exactly one plaintext payload"):
        manager.extract_unverified_signed_message_plaintext(signature)


def test_verify_signed_message_block_rejects_partially_verified_signature_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test steps:
    - Build a valid signed message and parse its real signature packet.
    - Pretend the message contains that packet twice.
    - Pretend the verifier only validated one signature.
    - Assert the full message verification is rejected.
    """

    class _VerifiedSignature:
        def __init__(self, certificate: str, signing_key: str) -> None:
            self.certificate = certificate
            self.signing_key = signing_key

    class _VerificationResult:
        def __init__(self, valid_sigs: list[_VerifiedSignature]) -> None:
            self.valid_sigs = valid_sigs

    cert, signed_message = _make_signed_message(pysequoia.SignatureMode.INLINE)
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)
    message_bytes, signatures = manager.parse_signed_pgp_message(signed_message)
    assert len(signatures) == 1
    signature = signatures[0]

    monkeypatch.setattr(
        manager,
        "parse_signed_pgp_message",
        lambda _signed_message: (message_bytes, [signature, signature]),
    )
    monkeypatch.setattr(
        "bitcoin_safe.signature_manager.pysequoia.verify",
        lambda **_kwargs: _VerificationResult(
            [
                _VerifiedSignature(
                    certificate=str(cert.fingerprint),
                    signing_key=str(signature.issuer_fingerprint),
                )
            ]
        ),
    )

    signer_keys, error = manager.verify_signed_message_block(signed_message, str(cert))

    assert not signer_keys
    assert error == "Failed verification"


@pytest.mark.parametrize(
    "mode",
    [
        pysequoia.SignatureMode.CLEAR,
        pysequoia.SignatureMode.INLINE,
    ],
)
def test_verify_signed_message_block_accepts_signed_message_variants(
    mode: pysequoia.SignatureMode,
) -> None:
    """Test steps:
    - Generate a fresh certificate.
    - Sign a message in the parametrized mode.
    - Verify with the matching public certificate.
    - Assert verification succeeds and resolves the primary fingerprint.
    """
    cert, signed_message = _make_signed_message(mode)
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    signer_keys, error = manager.verify_signed_message_block(signed_message, str(cert))

    assert signer_keys, error
    assert manager._normalize_fingerprint(signer_keys[0].fingerprint) == manager._normalize_fingerprint(
        cert.fingerprint
    )


@pytest.mark.parametrize(
    "mode",
    [
        pysequoia.SignatureMode.CLEAR,
        pysequoia.SignatureMode.INLINE,
    ],
)
def test_verify_signed_message_block_rejects_modified_signed_message_variants(
    mode: pysequoia.SignatureMode,
) -> None:
    """Test steps:
    - Sign a valid message in the parametrized mode.
    - Modify one non-armor content line.
    - Verify with the original public certificate.
    - Assert verification fails and returns an error.
    """
    cert, signed_message = _make_signed_message(mode)
    tampered_message = _tamper_armored_message(signed_message)
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    signer_keys, error = manager.verify_signed_message_block(tampered_message, str(cert))

    assert not signer_keys
    assert error


@pytest.mark.parametrize(
    "mode",
    [
        pysequoia.SignatureMode.CLEAR,
        pysequoia.SignatureMode.INLINE,
    ],
)
def test_verify_signed_message_block_rejects_wrong_public_key_for_signed_message_variants(
    mode: pysequoia.SignatureMode,
) -> None:
    """Test steps:
    - Sign a message with one generated certificate.
    - Create a different public certificate.
    - Verify the signed text with the wrong certificate.
    - Assert verification fails because the signer does not match.
    """
    _signing_cert, signed_message = _make_signed_message(mode)
    wrong_cert = pysequoia.Cert.generate(user_id="wrong@example.com")
    manager = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    signer_keys, error = manager.verify_signed_message_block(signed_message, str(wrong_cert))

    assert not signer_keys
    assert error
