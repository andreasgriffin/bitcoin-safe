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

from bitcoin_qr_tools.data import Data, DataType

from bitcoin_safe.gui.qt.buttonedit import ButtonEdit
from bitcoin_safe.gui.qt.custom_edits import MyTextEdit
from bitcoin_safe.gui.qt.export_data import ExportDataSimple
from bitcoin_safe.signals import SignalsMin
from bitcoin_safe.wallet import Wallet

logger = logging.getLogger(__name__)


import bdkpython as bdk
from bitcoin_qr_tools.multipath_descriptor import MultipathDescriptor
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent

from ...pdfrecovery import make_and_open_pdf
from .util import Message, MessageType, icon_path


class DescriptorEdit(ButtonEdit):
    signal_change = pyqtSignal(str)

    def __init__(
        self,
        network: bdk.Network,
        signals_min: SignalsMin,
        get_wallet: Optional[Callable[[], Wallet]] = None,
        signal_update: pyqtSignal = None,
    ) -> None:
        super().__init__(
            input_field=MyTextEdit(preferred_height=50),
            button_vertical_align=Qt.AlignmentFlag.AlignBottom,
            signal_update=signal_update,
        )
        self.signals_min = signals_min
        self.network = network

        def do_pdf() -> None:
            if not get_wallet:
                Message(
                    self.tr("Wallet setup not finished. Please finish before creating a Backup pdf."),
                    type=MessageType.Error,
                )
                return

            make_and_open_pdf(get_wallet())

        from bitcoin_qr_tools.data import Data

        def custom_handle_camera_input(data: Data, parent) -> None:
            self.setText(str(data.data_as_string()))
            self.signal_change.emit(str(data.data_as_string()))

        self.add_copy_button()
        self.add_button(icon_path("qr-code.svg"), self.show_export_widget, tooltip="Show QR code")
        if get_wallet is not None:
            self.add_pdf_buttton(do_pdf)
        self.add_qr_input_from_camera_button(
            network=self.network,
            custom_handle_input=custom_handle_camera_input,
        )
        self.set_validator(self._check_if_valid)

    def show_export_widget(self):
        if not self._check_if_valid():
            Message(self.tr("Descriptor not valid"))
            return
        data = Data(
            MultipathDescriptor.from_descriptor_str(self.text(), self.network), DataType.MultiPathDescriptor
        )
        widget = ExportDataSimple(
            data=data,
            signals_min=self.signals_min,
            enable_clipboard=False,
            enable_usb=False,
        )
        widget.show()

    def _check_if_valid(self) -> bool:
        if not self.text():
            return True
        try:
            MultipathDescriptor.from_descriptor_str(self.text(), self.network)
            return True
        except:
            return False

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        # print(e.type(), e.modifiers(),  [key for key in Qt.Key if  key.value == e.key() ] , e.matches(QKeySequence.StandardKey.Paste) )
        # If it's a regular key press
        if e.type() == QEvent.Type.KeyRelease:
            self.signal_change.emit(self.text())
        # If it's another type of shortcut, let the parent handle it
        else:
            super().keyReleaseEvent(e)
