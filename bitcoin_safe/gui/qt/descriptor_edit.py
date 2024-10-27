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
from typing import Callable, Optional

from bitcoin_qr_tools.data import Data
from bitcoin_qr_tools.multipath_descriptor import (
    MultipathDescriptor as BitcoinQRMultipathDescriptor,
)

from bitcoin_safe.descriptors import MultipathDescriptor
from bitcoin_safe.gui.qt.analyzers import DescriptorAnalyzer
from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import AnalyzerTextEdit
from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.threading_manager import ThreadingManager
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


import bdkpython as bdk
from PyQt6.QtCore import Qt, pyqtBoundSignal, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout

from ...pdfrecovery import make_and_open_pdf
from ...wallet import DescriptorExportTools
from .util import Message, MessageType, icon_path


class DescriptorExport(QDialog):
    def __init__(
        self,
        descriptor: MultipathDescriptor,
        signals_min: SignalsMin,
        network: bdk.Network,
        parent=None,
        threading_parent: ThreadingManager | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Export Descriptor"))
        self.setModal(True)

        self.descriptor = descriptor
        self.data = Data.from_multipath_descriptor(descriptor)
        self.setMinimumSize(500, 250)

        self.export_widget = ExportDataSimple(
            data=self.data,
            signals_min=signals_min,
            enable_clipboard=False,
            enable_usb=False,
            network=network,
            threading_parent=threading_parent,
        )

        self._layout = QVBoxLayout(self)
        self._layout.addWidget(self.export_widget)

    def get_coldcard_str(self, wallet_id: str) -> str:
        return DescriptorExportTools.get_coldcard_str(wallet_id=wallet_id, descriptor=self.descriptor)


class DescriptorEdit(ButtonEdit):
    signal_descriptor_change = pyqtSignal(str)

    def __init__(
        self,
        network: bdk.Network,
        signals_min: SignalsMin,
        get_lang_code: Callable[[], str],
        get_wallet: Optional[Callable[[], Wallet]] = None,
        signal_update: pyqtBoundSignal | None = None,
        threading_parent: ThreadingManager | None = None,
    ) -> None:
        super().__init__(
            input_field=AnalyzerTextEdit(),
            button_vertical_align=Qt.AlignmentFlag.AlignBottom,
            signal_update=signal_update,
            signals_min=signals_min,
            threading_parent=threading_parent,
        )  # type: ignore
        self.threading_parent = threading_parent
        self.signals_min = signals_min
        self.network = network
        self.input_field

        def do_pdf() -> None:
            if not get_wallet:
                Message(
                    self.tr("Wallet setup not finished. Please finish before creating a Backup pdf."),
                    type=MessageType.Error,
                )
                return

            make_and_open_pdf(get_wallet(), lang_code=get_lang_code())

        self.add_copy_button()
        self.add_button(icon_path("qr-code.svg"), self.show_export_widget, tooltip="Show QR code")
        if get_wallet is not None:
            self.add_pdf_buttton(do_pdf)
        self.add_qr_input_from_camera_button(
            network=self.network,
        )
        self.signal_data.connect(self._custom_handle_camera_input)
        self.input_field.setAnalyzer(DescriptorAnalyzer(self.network, parent=self))
        self.input_field.textChanged.connect(self.on_input_field_textChanged)

    def on_input_field_textChanged(self):
        self.signal_descriptor_change.emit(self.text_cleaned())

    def _custom_handle_camera_input(self, data: Data) -> None:
        self.setText(str(data.data_as_string()))
        self.signal_descriptor_change.emit(self._clean_text(str(data.data_as_string())))

    def show_export_widget(self):
        if not self._check_if_valid():
            Message(self.tr("Descriptor not valid"))
            return

        try:
            dialog = DescriptorExport(
                descriptor=MultipathDescriptor.from_descriptor_str(self.text(), self.network),
                signals_min=self.signals_min,
                parent=self,
                network=self.network,
                threading_parent=self.threading_parent,
            )
            dialog.show()
        except:
            logger.error(
                f"Could not create a DescriptorExport for {self.__class__.__name__} with text {self.text()}"
            )
            return

    def _clean_text(self, text: str) -> str:
        return text.strip().replace("\n", "")

    def text_cleaned(self) -> str:
        return self._clean_text(self.text())

    def _check_if_valid(self) -> bool:
        if not self.text():
            return True

        return BitcoinQRMultipathDescriptor.is_valid(self.text_cleaned(), network=self.network)
