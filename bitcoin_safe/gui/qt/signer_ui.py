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

from __future__ import annotations

import logging
from functools import partial
from typing import cast

import bdkpython as bdk
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.custom_edits import (
    FlexibleHeightTextedit,
)
from bitcoin_safe.gui.qt.util import set_no_margins, svg_tools

from ...signer import AbstractSignatureImporter, SignatureImporterUSB

logger = logging.getLogger(__name__)


class SignedUI(FlexibleHeightTextedit):
    def __init__(
        self, text: str, psbt: bdk.Psbt, network: bdk.Network, parent: QWidget | None = None
    ) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.text = text
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QHBoxLayout(self)
        set_no_margins(self.layout_keystore_buttons)

        self.edit_signature = FlexibleHeightTextedit()
        self.edit_signature.setReadOnly(True)
        self.edit_signature.setText(str(self.text))
        self.layout_keystore_buttons.addWidget(self.edit_signature)


class SignerUI(QWidget):
    signal_signature_added = cast(SignalProtocol[[bdk.Psbt]], pyqtSignal(bdk.Psbt))
    signal_tx_received = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))

    def __init__(
        self,
        signature_importer: AbstractSignatureImporter,
        psbt: bdk.Psbt,
        network: bdk.Network,
        button_prefix: str = "",
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signature_importer = signature_importer
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        if isinstance(self.signature_importer, SignatureImporterUSB):
            signal_end_hwi_blocker = cast(
                SignalProtocol[[]], self.signature_importer.usb_gui.signal_end_hwi_blocker
            )
            self.button = SpinningButton(
                text=button_prefix + self.signature_importer.label,
                signal_stop_spinning=signal_end_hwi_blocker,
                enabled_icon=svg_tools.get_QIcon(self.signature_importer.keystore_type.icon_filename),
                timeout=60,
                parent=self,
                svg_tools=svg_tools,
            )
        else:
            self.button = QPushButton(button_prefix + self.signature_importer.label, parent=self)
            self.button.setIcon(svg_tools.get_QIcon(self.signature_importer.keystore_type.icon_filename))

        callback = partial(self.signature_importer.sign, self.psbt)
        self.button.clicked.connect(callback)
        self.layout_keystore_buttons.addWidget(self.button)

        self.signature_importer.signal_signature_added.connect(self.signal_signature_added)
        self.signature_importer.signal_final_tx_received.connect(self.signal_tx_received)


class SignerUIHorizontal(QWidget):
    signal_signature_added = cast(SignalProtocol[[bdk.Psbt]], pyqtSignal(bdk.Psbt))
    signal_tx_received = cast(SignalProtocol[[bdk.Transaction]], pyqtSignal(bdk.Transaction))

    def __init__(
        self,
        signature_importers: list[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
    ) -> None:
        """Initialize instance."""
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self.layout_keystore_buttons = QVBoxLayout(self)

        for signer in self.signature_importers:
            button = QPushButton(signer.label)
            button.setIcon(svg_tools.get_QIcon(signer.keystore_type.icon_filename))
            action = partial(signer.sign, self.psbt)
            button.clicked.connect(action)
            self.layout_keystore_buttons.addWidget(button)

            signer.signal_signature_added.connect(self.signal_signature_added)
            signer.signal_final_tx_received.connect(self.signal_tx_received)
