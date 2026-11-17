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

"""Display a returned message signature and its verification status."""

from html import escape

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QPlainTextEdit, QWidget

from bitcoin_safe.constants import FORM_LABEL_FIELD_SPACING, LOGO_NAME
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.icon_label import IconLabel
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.hardware_signers import HardwareSigners
from bitcoin_safe.message_signing_result import MessageSigningInfo, verify_signing_result

from .util import do_copy, svg_tools_hardware_signer


class MessageSignatureDialog(QDialog):
    def __init__(
        self,
        message: str,
        signing_info: MessageSigningInfo,
        signature: str,
        close_all_video_widgets: SignalProtocol[[]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon(LOGO_NAME))
        self.setWindowTitle(self.tr("Signed Message"))
        self.resize(560, 360)
        result = verify_signing_result(message, signing_info, signature)
        layout = QGridLayout(self)
        layout.setColumnMinimumWidth(1, FORM_LABEL_FIELD_SPACING)
        layout.setColumnStretch(2, 1)
        if result.signer:
            layout.addWidget(IconLabel(self.tr("Signer")), 0, 0)
            self.signer_label = IconLabel(parent=self)
            signer_name = result.signer.hardware_signer_label()
            self.signer_label.setText(escape(f"{signer_name} - {result.signer.fingerprint}"))
            hardware_signer = (
                HardwareSigners.from_id(result.signer.hardware_signer_id) or HardwareSigners.generic
            )
            self.signer_label.set_icon(
                hardware_signer.icon_name, sizes=(24, 24), svg_tools_custom=svg_tools_hardware_signer
            )
            if len(signing_info.keystores) > 1:
                tooltip = self.tr("This signature proves control of one key, not the multisig address.")
                self.signer_label.setToolTip(tooltip)
                self.signer_label.icon_label.setToolTip(tooltip)
                self.signer_label.textLabel.setToolTip(tooltip)
            layout.addWidget(self.signer_label, 0, 2)

            layout.addWidget(IconLabel(self.tr("Verified key address")), 1, 0)
            self.address_edit = ButtonEdit(
                close_all_video_widgets=close_all_video_widgets, text=result.address, parent=self
            )
            self.address_edit.setReadOnly(True)
            self.address_edit.add_copy_button()
            layout.addWidget(self.address_edit, 1, 2)

        layout.addWidget(IconLabel(self.tr("Signed message")), 2, 0, Qt.AlignmentFlag.AlignTop)
        self.signature_edit = QPlainTextEdit(result.armored or result.signature)
        self.signature_edit.setReadOnly(True)
        layout.addWidget(self.signature_edit, 2, 2)
        layout.setRowStretch(2, 1)
        self.status_label = IconLabel(parent=self)
        if result.signer:
            self.status_label.setText(self.tr("Signature verified"))
            self.status_label.set_icon("checkmark.svg", sizes=(24, 24))
        else:
            self.status_label.setText(
                escape(self.tr("Signature could not be verified: {reason}").format(reason=result.error))
            )
            self.status_label.textLabel.setWordWrap(True)
        layout.addWidget(self.status_label, 3, 2)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy_button = buttons.addButton(self.tr("Copy"), QDialogButtonBox.ButtonRole.ActionRole)
        assert copy_button
        copy_button.clicked.connect(
            lambda: do_copy(self.signature_edit.toPlainText(), title=self.tr("Signed Message"))
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons, 4, 2)
