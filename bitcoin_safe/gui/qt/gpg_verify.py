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

from dataclasses import dataclass, field

import pgpy
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import translate
from ...signature_manager import (
    SignatureVerifyer,
    keyserver_url_for_fingerprint,
)

PUBLIC_KEY_PLACEHOLDER = """-----BEGIN PGP PUBLIC KEY BLOCK-----
...
-----END PGP PUBLIC KEY BLOCK-----"""


@dataclass
class GpgVerificationResult:
    """Container for PGP verification outcome."""

    message: str
    signer_keys: list[pgpy.PGPKey] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.signer_keys)


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


def verify_gpg_signed_message(
    signed_message: str,
    parent: QWidget | None = None,
) -> GpgVerificationResult:
    """Verify an ASCII-armored PGP signed message, optionally requesting a key."""
    if not signed_message.strip():
        return GpgVerificationResult(translate("gpg", "Signed PGP message is required."), signer_keys=[])

    verifyer = SignatureVerifyer(list_of_known_keys=None, proxies=None)

    signer_keys, error = verifyer.verify_signed_message_block(signed_message)

    if not signer_keys:
        # give  a second chance with manual key entry
        manual_key = prompt_for_public_key(parent, str(error) if error else "")
        if manual_key:
            signer_keys, error = verifyer.verify_signed_message_block(signed_message, manual_key)

    if signer_keys:
        body = translate("gpg", "PGP signature is valid.")
        for signer_key in signer_keys:
            fingerprint = str(signer_key.fingerprint)
            link = keyserver_url_for_fingerprint(fingerprint)
            if link:
                body += f' ({translate("gpg", "Fingerprint")}: <a href="{link}">{fingerprint}</a>)'
            else:
                body += f" ({translate('gpg', 'Fingerprint')}: {fingerprint})"
    else:
        body = error or translate("gpg", "PGP signature verification failed.")

    return GpgVerificationResult(body, signer_keys)
