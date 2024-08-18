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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from bitcoin_qr_tools.qr_widgets import EnlargableImageWidget

from bitcoin_safe.gui.qt.qr_types import QrType, QrTypes
from bitcoin_safe.gui.qt.synced_tab_widget import SyncedTabWidget
from bitcoin_safe.pdfrecovery import TEXT_24_WORDS

logger = logging.getLogger(__name__)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .util import screenshot_path


@dataclass
class HardwareSigner:
    name: str
    display_name: str
    usb_preferred: bool
    qr_type: Optional[QrType] = None

    @property
    def generate_seed_png(self):
        return f"{self.name}-generate-seed.png"

    @property
    def wallet_export_png(self):
        return f"{self.name}-wallet-export.png"

    @property
    def view_seed_png(self):
        return f"{self.name}-view-seed.png"

    @property
    def register_multisig_decriptor_png(self):
        return f"{self.name}-register-multisig-decriptor.png"


class HardwareSigners:
    coldcard = HardwareSigner("coldcard", "Coldcard - Mk4", usb_preferred=False)
    q = HardwareSigner("q", "Coldcard - Q", usb_preferred=False, qr_type=QrTypes.bbqr)
    bitbox02 = HardwareSigner("bitbox02", "Bitbox02", usb_preferred=True)
    specterdiy = HardwareSigner(
        "specterdiy", "Specter DIY", usb_preferred=False, qr_type=QrTypes.specterdiy_descriptor_export
    )
    jade = HardwareSigner("jade", "Jade", usb_preferred=True)
    foundation_passport = HardwareSigner(
        "passport", "Foundation - Passport", usb_preferred=False, qr_type=QrTypes.ur
    )


class ScreenshotsTutorial(QWidget):
    enabled_hardware_signers = [
        HardwareSigners.q,
        HardwareSigners.coldcard,
        HardwareSigners.bitbox02,
        HardwareSigners.jade,
        HardwareSigners.specterdiy,
    ]

    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.title = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.title.setFont(font)
        self.title.setWordWrap(True)

        self._layout.addWidget(self.title)
        self.sync_tab = SyncedTabWidget(group=group, parent=self)
        self._layout.addWidget(self.sync_tab)

    def add_image_tab(
        self, image_path: str, tab_title: str, size_hint: Tuple[int, int]
    ) -> Optional[Tuple[EnlargableImageWidget, QWidget]]:
        if not Path(screenshot_path(image_path)).exists():
            logger.warning(
                f"{self.__class__.__name__}:  {screenshot_path(image_path)} doesnt exist. Cannot load the image tab"
            )
            return None
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        image_widget = EnlargableImageWidget(size_hint=size_hint)
        image_widget.load_from_file(screenshot_path(image_path))
        tab_layout.addWidget(image_widget)
        self.sync_tab.addTab(tab, tab_title)
        return image_widget, tab

    def set_title(self, text: str) -> None:
        self.title.setText(text)


class ScreenshotsGenerateSeed(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget | None = None) -> None:
        super().__init__(group, parent)

        self.image_widgets: Dict[str, EnlargableImageWidget] = {}
        self.tabs: Dict[str, QWidget] = {}

        for hardware_signer in self.enabled_hardware_signers:
            result = self.add_image_tab(
                hardware_signer.generate_seed_png, hardware_signer.display_name, size_hint=(400, 50)
            )
            if result:
                image_widget, tab = result
                self.image_widgets[hardware_signer.name] = image_widget
                self.tabs[hardware_signer.name] = tab
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(
            self.tr(
                "Generate {number} secret seed words on each hardware signer and write them on the recovery sheet"
            ).format(number=TEXT_24_WORDS)
        )


class ScreenshotsExportXpub(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget | None = None) -> None:
        super().__init__(group, parent)

        for hardware_signer in self.enabled_hardware_signers:
            self.add_image_tab(
                hardware_signer.wallet_export_png, hardware_signer.display_name, size_hint=(400, 50)
            )
        self.sync_tab.setMinimumSize(800, 500)
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("How-to export the wallet information from the hardware signer"))


class ScreenshotsViewSeed(ScreenshotsTutorial):
    def __init__(
        self,
        title_text=None,
        group: str = "tutorial",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(group, parent)

        for hardware_signer in self.enabled_hardware_signers:
            self.add_image_tab(
                hardware_signer.view_seed_png, hardware_signer.display_name, size_hint=(400, 50)
            )

        self.title.setWordWrap(True)
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(
            self.tr(
                "Compare the {number} words on the backup paper to the hardware signer.\nIf you make a mistake here, your money is lost!"
            ).format(number=TEXT_24_WORDS)
        )


class ScreenshotsRegisterMultisig(ScreenshotsTutorial):
    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            group,
            parent,
        )
        self.setMinimumSize(500, 300)

        for hardware_signer in self.enabled_hardware_signers:
            self.add_image_tab(
                hardware_signer.register_multisig_decriptor_png,
                hardware_signer.display_name,
                size_hint=(400, 50),
            )
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("Import the multisig information in the hardware signer"))
