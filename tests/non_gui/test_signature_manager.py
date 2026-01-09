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


def test_download_manifest_and_verify() -> None:
    """Test download manifest and verify."""
    manager = SignatureVerifyer(list_of_known_keys=KnownGPGKeys.all(), proxies=None)

    with tempfile.TemporaryDirectory() as tempdir:
        logger.debug(f"tempdir {tempdir}")
        try:
            sig_filename = manager.get_signature_from_web(Path(tempdir) / "Sparrow-1.8.4-x86_64.dmg")
            assert sig_filename
        except Exception as exc:
            pytest.skip(f"Skipping manifest download: {exc}")
        logger.debug(f"sig_filename {sig_filename}")
        manifest_file = Path(tempdir) / "sparrow-1.8.4-manifest.txt"
        assert sig_filename == Path(tempdir) / "sparrow-1.8.4-manifest.txt.asc"
        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        assert manager._verify_file(
            public_key=public_key, binary_file=manifest_file, signature_file=sig_filename
        )


def test_download_manifest_and_verify_wrong_signature() -> None:
    """Test download manifest and verify wrong signature."""
    manager = SignatureVerifyer(list_of_known_keys=KnownGPGKeys.all(), proxies=None)

    with tempfile.TemporaryDirectory() as tempdir:
        logger.debug(f"tempdir {tempdir}")
        try:
            sig_filename = manager.get_signature_from_web(Path(tempdir) / "Sparrow-1.8.4-x86_64.dmg")
            assert sig_filename
        except Exception as exc:
            pytest.skip(f"Skipping manifest download: {exc}")
        logger.debug(f"sig_filename {sig_filename}")

        manifest_file = Path(tempdir) / "sparrow-1.8.4-manifest.txt"
        assert sig_filename == Path(tempdir) / "sparrow-1.8.4-manifest.txt.asc"

        with open(sig_filename) as file:
            right_rig_content = file.read()

        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        # correct signature is ok.
        assert manager._verify_file(
            public_key=public_key, binary_file=manifest_file, signature_file=sig_filename
        )

        # now overwrite the file:
        wrong_sig_content = right_rig_content.replace("iQIzBAABCgAdFi", "QIzBAABCgAdFi")
        with open(sig_filename, "w") as file:
            file.write(wrong_sig_content)

        assert manager.is_signature_file_available(manifest_file)
        public_key = manager.import_public_key_block(KnownGPGKeys.craigraw.key)
        # wrong signature
        assert not manager._verify_file(
            public_key=public_key, binary_file=manifest_file, signature_file=sig_filename
        )
