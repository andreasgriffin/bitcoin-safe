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

from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import translate
from ...signature_manager import PGPDecodingError, PGPDownloadError, PGPMissingSignature, SignatureVerifyer

PUBLIC_KEY_PLACEHOLDER = """-----BEGIN PGP PUBLIC KEY BLOCK-----
...
-----END PGP PUBLIC KEY BLOCK-----"""


@dataclass
class GpgVerificationResult:
    """Container for PGP verification outcome."""

    success: bool
    message: str
    fingerprint: str | None = None


class PublicKeyDialog(QDialog):
    def __init__(self, parent: QWidget | None, reason: str):
        super().__init__(parent)
        self.setWindowTitle(translate("gpg", "Public key required"))

        label = QLabel(reason + "\n\n" + translate("gpg", "Please paste the signer's public key block."))
        label.setWordWrap(True)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(PUBLIC_KEY_PLACEHOLDER)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.edit)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText()


def prompt_for_public_key(parent: QWidget | None, reason: str) -> str | None:
    dialog = PublicKeyDialog(parent, reason)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    key = dialog.text().strip()
    return key or None


def _keyserver_url(fingerprint: str) -> str:
    """Return keys.openpgp.org URL for a given fingerprint/keyid."""
    fp = fingerprint.replace(" ", "").upper()
    if len(fp) >= 40:
        fp = fp[-40:]
        return f"https://keys.openpgp.org/vks/v1/by-fingerprint/{fp}"
    kid = fp[-16:]
    return f"https://keys.openpgp.org/vks/v1/by-keyid/{kid}"


def verify_gpg_signed_message(
    signed_message: str,
    parent: QWidget | None = None,
) -> GpgVerificationResult:
    """Verify an ASCII-armored PGP signed message, optionally requesting a key."""
    if not signed_message.strip():
        return GpgVerificationResult(False, translate("gpg", "Signed PGP message is required."))

    verifyer = SignatureVerifyer(list_of_known_keys=None, proxies=None)
    key_block = ""
    downloaded = False
    fingerprint: str | None = None

    downloaded = False
    try:
        key_block, fingerprint = verifyer.download_public_key_from_signed_message(signed_message)
        downloaded = True
    except (PGPDecodingError, PGPMissingSignature) as e:
        return GpgVerificationResult(False, str(e), fingerprint)
    except PGPDownloadError as e:
        manual_key = prompt_for_public_key(parent, str(e))
        if manual_key:
            key_block = manual_key
        else:
            return GpgVerificationResult(False, "No public key available", fingerprint)

    success, error, fingerprint_from_verify = verifyer.verify_signed_message_block(signed_message, key_block)
    fingerprint = fingerprint_from_verify or fingerprint

    if success:
        body = translate("gpg", "PGP signature is valid.")
        if fingerprint:
            link = _keyserver_url(fingerprint)
            body += f' ({translate("gpg", "Fingerprint")}: <a href="{link}">{fingerprint}</a>)'
        if downloaded:
            body += f"\n{translate('gpg', 'Public key downloaded automatically.')}"
        return GpgVerificationResult(True, body, fingerprint)

    return GpgVerificationResult(
        False, error or translate("gpg", "PGP signature verification failed."), fingerprint
    )
