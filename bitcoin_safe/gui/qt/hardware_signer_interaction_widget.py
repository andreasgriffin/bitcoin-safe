#
# Bitcoin Safe
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
from typing import TYPE_CHECKING, cast

from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon, QKeyEvent
from PyQt6.QtWidgets import (
    QDialogButtonBox,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.gui.qt.wrappers import Menu
from bitcoin_safe.i18n import translate

from ...keystore import KeyStoreImporterTypes
from .util import add_to_buttonbox, create_tool_button, set_no_margins

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def icon_for_label(label: str) -> QIcon:
    """Icon for label."""
    return (
        svg_tools.get_QIcon("bi--key.svg")
        if label.startswith(translate("d", "Recovery"))
        else svg_tools.get_QIcon("bi--key.svg")
    )


class BaseHardwareSignerInteractionWidget(QWidget):
    aboutToClose = cast(SignalProtocol[[QWidget]], pyqtSignal(QWidget))

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)
        self.setWindowIcon(svg_tools.get_QIcon("logo.svg"))
        self._layout = QVBoxLayout(self)
        set_no_margins(self._layout)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.buttonBox = QDialogButtonBox()
        self.help_button: QPushButton | None = None

        self._layout.addWidget(self.buttonBox)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.setAlignment(self.buttonBox, Qt.AlignmentFlag.AlignCenter)

    def add_button(self, button: QPushButton | QToolButton) -> None:
        """Add button."""
        self.buttonBox.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)

    def add_help_button(self, help_widget: QWidget) -> QPushButton:
        """Add help button."""
        self.buttonBoxHelp = QDialogButtonBox()
        help_button = QPushButton(self)
        help_button.setIcon(svg_tools.get_QIcon("bi--question-circle.svg"))
        help_button.clicked.connect(help_widget.show)
        self.buttonBoxHelp.addButton(help_button, QDialogButtonBox.ButtonRole.ActionRole)
        self._layout.addWidget(self.buttonBoxHelp)
        self._layout.setAlignment(self.buttonBoxHelp, Qt.AlignmentFlag.AlignCenter)
        self.help_button = help_button
        return help_button

    def updateUi(self) -> None:
        """UpdateUi."""
        if self.help_button:
            self.help_button.setText(self.tr("Device instructions"))

    def closeEvent(self, a0: QCloseEvent | None):
        """CloseEvent."""
        self.aboutToClose.emit(self)
        super().closeEvent(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        """Close the floating widget on Escape like a dialog."""
        if a0 and a0.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(a0)


class HardwareSignerInteractionWidget(BaseHardwareSignerInteractionWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize instance."""
        super().__init__(parent)

        self.button_import_file: QPushButton | None = None
        self.button_import_qr: QPushButton | None = None
        self.simple_button_export_qr: QPushButton | None = None
        self.button_hwi: QPushButton | None = None
        self.button_export_file: QToolButton | None = None

    def add_import_file_button(self) -> QPushButton:
        """Add import file button."""
        self.button_import_file = add_to_buttonbox(
            self.buttonBox, self.tr(""), KeyStoreImporterTypes.file.icon_filename
        )
        return self.button_import_file

    def add_copy_button(self) -> tuple[QToolButton, Menu]:
        """Add copy button."""
        button, menu = create_tool_button(parent=self)
        button.setIcon(svg_tools.get_QIcon("bi--copy.svg"))
        self.buttonBox.addButton(button, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_export_file = button
        return self.button_export_file, menu

    def add_qr_import_buttonn(self) -> QPushButton:
        """Add qr import buttonn."""
        self.button_import_qr = add_to_buttonbox(
            self.buttonBox, text="", icon_name=KeyStoreImporterTypes.qr.icon_filename
        )
        return self.button_import_qr

    def add_hwi_button(self, signal_end_hwi_blocker: SignalProtocol[[]]) -> QPushButton:
        """Add hwi button."""
        button_hwi = SpinningButton(
            text="",
            signal_stop_spinning=signal_end_hwi_blocker,
            enabled_icon=svg_tools.get_QIcon(KeyStoreImporterTypes.hwi.icon_filename),
            timeout=60,
            parent=self,
        )
        self.buttonBox.addButton(button_hwi, QDialogButtonBox.ButtonRole.ActionRole)
        self.button_hwi = button_hwi
        return button_hwi

    def updateUi(self) -> None:
        """UpdateUi."""
        super().updateUi()
        if self.button_import_file:
            self.button_import_file.setText(self.tr("Import File or Text"))
        if self.button_export_file:
            self.button_export_file.setText(self.tr("Export File"))
        if self.button_import_qr:
            self.button_import_qr.setText(self.tr("QR Code"))
        if self.simple_button_export_qr:
            self.simple_button_export_qr.setText(self.tr("QR Code"))
        if self.button_hwi:
            self.button_hwi.setText(self.tr("USB"))
