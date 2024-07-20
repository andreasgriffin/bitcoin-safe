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
from typing import Tuple

from bitcoin_qr_tools.qr_widgets import EnlargableImageWidget

from bitcoin_safe.gui.qt.synced_tab_widget import SyncedTabWidget

logger = logging.getLogger(__name__)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .util import screenshot_path


class ScreenshotsTutorial(QWidget):
    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(parent)

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.title = QLabel()
        font = QFont()
        font.setPointSize(12)
        self.title.setFont(font)

        self.layout().addWidget(self.title)
        self.sync_tab = SyncedTabWidget(group=group, parent=self)
        self.layout().addWidget(self.sync_tab)

    def add_image_tab(
        self, image_path: str, tab_title: str, size_hint: Tuple[int, int] = None
    ) -> Tuple[EnlargableImageWidget, QWidget]:
        tab = QWidget()
        tab.setLayout(QVBoxLayout())
        image_widget = EnlargableImageWidget(size_hint=size_hint)
        image_widget.load_from_file(screenshot_path(image_path))
        tab.layout().addWidget(image_widget)
        self.sync_tab.addTab(tab, tab_title)
        return image_widget, tab

    def set_title(self, text: str) -> None:
        self.title.setText(text)


class ScreenshotsGenerateSeed(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget = None) -> None:
        super().__init__(group, parent)

        self.add_image_tab("coldcard-generate-seed.png", "Coldcard - Mk4")
        self.add_image_tab("q-generate-seed.png", "Coldcard - Q")
        # self.add_image_tab("bitbox02-generate-seed.png", "Bitbox02", size_hint=(500, 50))
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("Generate 24 secret seed words on each hardware signer"))


class ScreenshotsExportXpub(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget = None) -> None:
        super().__init__(group, parent)

        self.add_image_tab("coldcard-wallet-export.png", "Coldcard - Mk4", size_hint=(400, 50))
        self.add_image_tab("q-wallet-export.png", "Coldcard - Q", size_hint=(400, 50))
        # self.add_image_tab("bitbox02-wallet-export.png", "Bitbox02", size_hint=(500, 50))
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("1. Export the wallet information from the hardware signer"))


class ScreenshotsViewSeed(ScreenshotsTutorial):
    def __init__(
        self,
        title_text=None,
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.add_image_tab("coldcard-view-seed.png", "Coldcard - Mk4")
        self.add_image_tab("q-view-seed.png", "Coldcard - Q")
        # self.add_image_tab("bitbox02-view-seed.png", "Bitbox02", size_hint=(500, 50))

        self.title.setWordWrap(True)
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(
            self.tr(
                "Compare the 24 words on the backup paper to 'View Seed Words' from Coldcard.\nIf you make a mistake here, your money is lost!"
            )
        )


class ScreenshotsResetSigner(ScreenshotsTutorial):
    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.add_image_tab("coldcard-destroy-seed.png", "Coldcard - Mk4", size_hint=(500, 50))
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("Reset the hardware signer."))


class ScreenshotsRestoreSigner(ScreenshotsTutorial):
    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.add_image_tab("coldcard-import-seed.png", "Coldcard - Mk4", size_hint=(500, 50))
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("Restore the hardware signer."))


class ScreenshotsRegisterMultisig(ScreenshotsTutorial):
    def __init__(
        self,
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(
            group,
            parent,
        )

        self.add_image_tab("coldcard-register-multisig-decriptor.png", "Coldcard - Mk4", size_hint=(500, 50))
        self.add_image_tab("q-register-multisig-decriptor.png", "Coldcard - Q", size_hint=(500, 50))
        self.updateUi()

    def updateUi(self) -> None:
        self.set_title(self.tr("Import the multisig information in the hardware signer"))
