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


import logging
from typing import Iterable

import bdkpython as bdk
from bitcoin_qr_tools.data import Data
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.export_data import (
    FileToolButton,
    QrToolButton,
    SyncChatToolButton,
)
from bitcoin_safe.gui.qt.keystore_ui import SignerUI
from bitcoin_safe.signer import (
    AbstractSignatureImporter,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from bitcoin_safe.threading_manager import ThreadingManager

from ...signals import SignalsMin
from .sync_tab import SyncTab

logger = logging.getLogger(__name__)


class HorizontalImportExportQR(QGroupBox):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager | None,
        signature_importers: Iterable[SignatureImporterQR],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.button_export = QrToolButton(
            data=Data.from_psbt(psbt, network=network),
            network=network,
            signals_min=signals_min,
            threading_parent=threading_parent,
            parent=parent,
            button_prefix="1. ",
        )
        self.button_export.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        if signature_importers:
            signer_ui = SignerUI(list(signature_importers)[:1], psbt, network, button_prefix="2. ")
            signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
            self.button_import = signer_ui

            self._layout.addWidget(self.button_export)
            self._layout.addWidget(self.button_import)

        self.updateUI()

    def updateUI(self):
        self.setTitle(self.tr("QR"))


class HorizontalImportExportUSB(QGroupBox):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        signature_importers: Iterable[SignatureImporterUSB],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        signer_ui = SignerUI(
            signature_importers,
            psbt,
            network,
        )
        signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
        self.button_usb = signer_ui

        self._layout.addWidget(self.button_usb)

        self.updateUI()

    def updateUI(self):
        self.setTitle(self.tr("USB"))


class HorizontalImportExportFile(QGroupBox):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        signature_importers: Iterable[SignatureImporterFile],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.button_export = FileToolButton(
            data=Data.from_psbt(psbt, network=network),
            wallet_id=None,
            network=network,
            parent=self,
            button_prefix="1. ",
        )
        self.button_export.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        if signature_importers:
            signer_ui = SignerUI(list(signature_importers)[:1], psbt, network, button_prefix="2. ")
            signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
            self.button_import = signer_ui

            self._layout.addWidget(self.button_export)
            self._layout.addWidget(self.button_import)

        self.updateUI()

    def updateUI(self):
        self.setTitle(self.tr("File"))


class HorizontalImportExportClipboard(QGroupBox):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        sync_tabs: dict[str, SyncTab] | None,
        signature_importers: Iterable[SignatureImporterFile],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        data = Data.from_psbt(psbt, network=network)

        self.button_sync_share = SyncChatToolButton(
            data=data, network=network, sync_tabs=sync_tabs, parent=self, button_prefix="1. "
        )
        self.button_sync_share.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout.addWidget(self.button_sync_share)

        if signature_importers:
            signer_ui = SignerUI(list(signature_importers)[:1], psbt, network, button_prefix="2. ")
            signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
            self.button_import = signer_ui

            self._layout.addWidget(self.button_import)

        self.updateUI()

    def updateUI(self):
        self.setTitle(self.tr("Share"))


class HorizontalImportExportWallet(QGroupBox):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        signature_importers: Iterable[SignatureImporterWallet],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        if signature_importers:
            self.signer_ui = SignerUI(list(signature_importers)[:1], psbt, network)
            self.signer_ui.layout_keystore_buttons.setContentsMargins(0, 0, 0, 0)
            self.button_import = self.signer_ui

            self._layout.addWidget(self.button_import)

        self.updateUI()

    def updateUI(self):
        self.setTitle(self.tr("Seed"))


class HorizontalImportExportAll(QWidget):
    def __init__(
        self,
        psbt: bdk.PartiallySignedTransaction,
        network: bdk.Network,
        sync_tabs: dict[str, SyncTab] | None,
        signals_min: SignalsMin,
        threading_parent: ThreadingManager | None,
        signature_importers: Iterable[AbstractSignatureImporter],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._layout = QHBoxLayout(self)
        org_spacing = self._layout.spacing()
        self._layout.setSpacing(max(org_spacing, 40))
        signals_min.language_switch.connect(self.updateUi)

        # qr
        qr_signers = [
            signature_importer
            for signature_importer in signature_importers
            if isinstance(signature_importer, SignatureImporterQR)
        ]
        self.qr = (
            HorizontalImportExportQR(
                psbt=psbt,
                network=network,
                signals_min=signals_min,
                threading_parent=threading_parent,
                signature_importers=qr_signers,
            )
            if qr_signers
            else None
        )
        if self.qr:
            self._layout.addWidget(self.qr)

        # usb
        usb_signers = [
            signature_importer
            for signature_importer in signature_importers
            if isinstance(signature_importer, SignatureImporterUSB)
        ]
        self.usb = (
            HorizontalImportExportUSB(signature_importers=usb_signers, network=network, psbt=psbt)
            if usb_signers
            else None
        )
        if self.usb:
            self._layout.addWidget(self.usb)

        # file
        file_signers = [
            signature_importer
            for signature_importer in signature_importers
            if isinstance(signature_importer, SignatureImporterFile)
        ]
        self.file = (
            HorizontalImportExportFile(
                psbt=psbt,
                network=network,
                signature_importers=file_signers,
            )
            if file_signers
            else None
        )
        if self.file:
            self._layout.addWidget(self.file)

        # clipboard
        self.clipboard = HorizontalImportExportClipboard(
            psbt=psbt, network=network, signature_importers=file_signers, sync_tabs=sync_tabs
        )
        self._layout.addWidget(self.clipboard)

        # seed
        wallet_signers = [
            signature_importer
            for signature_importer in signature_importers
            if isinstance(signature_importer, SignatureImporterWallet)
        ]
        self.wallet_importers = (
            HorizontalImportExportWallet(
                psbt=psbt,
                network=network,
                signature_importers=wallet_signers,
            )
            if wallet_signers
            else None
        )
        if self.wallet_importers:
            self._layout.addWidget(self.wallet_importers)

    def updateUi(self):
        if self.qr:
            self.qr.updateUI()
        if self.usb:
            self.usb.updateUI()
        if self.file:
            self.file.updateUI()
        if self.clipboard:
            self.clipboard.updateUI()
