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
from typing import Dict, List, Optional, Type

import bdkpython as bdk
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.gui.qt.export_data import DataGroupBox, HorizontalImportExportGroups
from bitcoin_safe.gui.qt.import_export import HorizontalImportExportAll
from bitcoin_safe.gui.qt.keystore_ui import SignedUI, SignerUI
from bitcoin_safe.gui.qt.step_progress_bar import StepProgressContainer
from bitcoin_safe.signals import Signals
from bitcoin_safe.signer import (
    AbstractSignatureImporter,
    SignatureImporterClipboard,
    SignatureImporterFile,
    SignatureImporterQR,
    SignatureImporterUSB,
    SignatureImporterWallet,
)
from bitcoin_safe.threading_manager import ThreadingManager

logger = logging.getLogger(__name__)


class HorizontalImporters(HorizontalImportExportGroups):
    def __init__(
        self,
        signature_importers: List[AbstractSignatureImporter],
        psbt: bdk.Psbt,
        network: bdk.Network,
    ) -> None:
        super().__init__()
        self.signature_importers = signature_importers
        self.psbt = psbt
        self.network = network

        self._add(self.group_qr, SignatureImporterQR)
        self._add(self.group_file, SignatureImporterFile)
        self._add(self.group_usb, SignatureImporterUSB)
        self._add(self.group_share, SignatureImporterClipboard)
        self._add(self.group_seed, SignatureImporterWallet)

    def _add(self, group: DataGroupBox, cls: Type[AbstractSignatureImporter]) -> None:
        importer = self._get_importer(cls)
        group.setVisible(bool(importer))
        if importer:
            signerui = SignerUI(
                [importer],
                self.psbt,
                self.network,
            )
            group._layout.addWidget(signerui)
            group.setData(signerui)

    def _get_importer(self, cls: Type[AbstractSignatureImporter]) -> Optional[AbstractSignatureImporter]:
        for importer in self.signature_importers:
            if isinstance(importer, cls):
                return importer
        return None


class TxSigningSteps(StepProgressContainer):
    def __init__(
        self,
        signature_importer_dict: Dict[str, List[AbstractSignatureImporter]],
        psbt: bdk.Psbt,
        network: bdk.Network,
        signals: Signals,
        parent: QWidget | None = None,
        threading_parent: ThreadingManager | None = None,
    ) -> None:
        step_labels = []
        self.sub_indices: List[int] = []
        for i, (wallet_id, signature_importer_list) in enumerate(signature_importer_dict.items()):
            # export
            step_labels.append((self.tr("Create and collect {n}. signature").format(n=i + 1)))

        super().__init__(
            step_labels=step_labels,
            parent=parent,
            use_resizing_stacked_widget=False,
            signals_min=signals,
            threading_parent=threading_parent,
        )

        self.psbt = psbt
        self.network = network
        self.signals = signals
        self.signature_importer_dict = signature_importer_dict

        first_non_signed_index = None
        # fill ui
        for i, (wallet_id, signature_importer_list) in enumerate(signature_importer_dict.items()):
            self.set_custom_widget(
                self._get_idx(i, 0), self.create_export_import_widget(signature_importer_list)
            )
            # set the index, to the first unsigned step
            if first_non_signed_index is None and (not signature_importer_list[0].signature_available):
                first_non_signed_index = i
                self.set_current_index(self._get_idx(i, 0))

    def _get_idx(self, i: int, j: int) -> int:
        return i

    def _get_name(self, i: int, j: int) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        return f"{i+1}.{alphabet[j]}"

    def set_current_index(self, index: int) -> None:
        super().set_current_index(index)

    def go_to_next_index(self) -> None:
        if self.current_index() + 1 < self.count():
            self.set_current_index(self.current_index() + 1)
        else:
            pass
            # do not mark as completed,.. Only successful signing can do this
            # self.step_bar.set_mark_current_step_as_completed(True)

    def go_to_previous_index(self) -> None:
        self.step_bar.set_mark_current_step_as_completed(False)

        if self.current_index() - 1 >= 0:
            self.set_current_index(self.current_index() - 1)

    def create_export_import_widget(self, signature_importers: List[AbstractSignatureImporter]) -> QWidget:
        widget = HorizontalImportExportAll(
            psbt=self.psbt,
            network=self.network,
            signals_min=self.signals_min,
            threading_parent=self.threading_parent,
            signature_importers=signature_importers,
            sync_tabs={
                wallet_id: qt_wallet.sync_tab
                for wallet_id, qt_wallet in self.signals.get_qt_wallets().items()
            },
        )
        return widget

    def create_import_widget(self, signature_importers: List[AbstractSignatureImporter]) -> QWidget:
        if signature_importers[0].signature_available:
            return SignedUI(
                self.tr("Transaction signed with the private key belonging to {label}").format(
                    label=signature_importers[0].key_label
                ),
                self.psbt,
                self.network,
            )
        else:
            return HorizontalImporters(
                signature_importers,
                self.psbt,
                self.network,
            )


if __name__ == "__main__":
    import sys

    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # dialog = TxSigningSteps(2, [], [])
    # dialog.show()

    sys.exit(app.exec())
