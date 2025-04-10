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
from pathlib import Path
from typing import Dict, Optional, Tuple

from bitcoin_qr_tools.gui.qr_widgets import EnlargableImageWidgetWithButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QKeyEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.synced_tab_widget import SyncedTabWidget
from bitcoin_safe.i18n import translate
from bitcoin_safe.pdfrecovery import TEXT_24_WORDS

from ...hardware_signers import HardwareSigners
from .util import adjust_bg_color_for_darkmode, icon_path, screenshot_path

logger = logging.getLogger(__name__)


class ScreenshotsTutorial(QWidget):
    enabled_hardware_signers = HardwareSigners.as_list()  # activate all of them

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
    ) -> Optional[Tuple[EnlargableImageWidgetWithButton, QWidget]]:
        if not Path(screenshot_path(image_path)).exists():
            logger.warning(
                f"{self.__class__.__name__}:  {screenshot_path(image_path)} doesnt exist. Cannot load the image tab"
            )
            return None
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        image_widget = EnlargableImageWidgetWithButton(size_hint=size_hint)
        image_widget.load_from_file(screenshot_path(image_path))
        tab_layout.addWidget(image_widget)
        self.sync_tab.addTab(tab, tab_title)
        return image_widget, tab

    def set_title(self, text: str) -> None:
        self.title.setText(text)

    def keyPressEvent(self, event: QKeyEvent | None):
        if not event:
            return super().keyPressEvent(event)

        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return

        super().keyPressEvent(event)


class SeedWarningBar(NotificationBar):
    def __init__(self) -> None:
        super().__init__(
            text="",
            optional_button_text="",
            has_close_button=False,
        )
        self.set_background_color(adjust_bg_color_for_darkmode(QColor("#FFDF00")))
        self.set_icon(QIcon(icon_path("warning.png")))

        self.optionalButton.setVisible(False)

    def setText(self, value: Optional[str]):
        self.textLabel.setText(value if value else "")


class ScreenshotsGenerateSeed(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget | None = None) -> None:
        super().__init__(group, parent)

        self.image_widgets: Dict[str, EnlargableImageWidgetWithButton] = {}
        self.tabs: Dict[str, QWidget] = {}

        self.never_label = SeedWarningBar()
        self._layout.insertWidget(1, self.never_label)

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

        self.never_label.setText(
            translate("tutorial", "Never share the {number} secret words with anyone!").format(
                number=TEXT_24_WORDS
            )
            + "\n"
            + translate("tutorial", "Never type them into any computer or cellphone!")
            + "\n"
            + translate("tutorial", "Never make a picture of them!")
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
