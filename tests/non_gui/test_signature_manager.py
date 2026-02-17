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

import logging
import tempfile
from pathlib import Path

import pytest

from bitcoin_safe.signature_manager import KnownGPGKeys, SignatureVerifyer

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
    assert str(signer_keys[0].fingerprint) == fingerprint == "8198A18530A522A09561243989C4A25E69A5DE7F"

    # Modifying the message should invalidate the signature.
    changed_message = signed_message
    changed_message = changed_message[:100] + changed_message[102:]

    signer_keys, error = manager.verify_signed_message_block(changed_message, downloaded_key)
    assert not signer_keys
