import logging
from typing import Tuple

from bitcoin_safe.gui.qt.qr_components.image_widget import EnlargableImageWidget
from bitcoin_safe.gui.qt.synced_tab_widget import SyncedTabWidget

logger = logging.getLogger(__name__)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .util import icon_path


class ScreenshotsTutorial(QWidget):
    def __init__(self, group: str = "tutorial", parent: QWidget = None) -> None:
        super().__init__(parent)

        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)  # Left, Top, Right, Bottom margins

        self.title = QLabel("")
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
        image_widget.load_from_file(icon_path(image_path))
        tab.layout().addWidget(image_widget)
        self.sync_tab.addTab(tab, tab_title)
        return image_widget, tab


class ScreenshotsGenerateSeed(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget = None) -> None:
        super().__init__(group, parent)

        self.title.setText("Generate 24 secret seed words on each hardware signer")

        self.add_image_tab("coldcard-generate24.png", "Coldcard")


class ScreenshotsExportXpub(ScreenshotsTutorial):
    def __init__(self, group: str = "tutorial", parent: QWidget = None) -> None:
        super().__init__(group, parent)

        self.title.setText("1. Export the wallet information from the hardware signer")

        self.add_image_tab("coldcard-wallet-export.png", "Coldcard", size_hint=(400, 50))


class ScreenshotsViewSeed(ScreenshotsTutorial):
    def __init__(
        self,
        title="Compare the 24 words on the backup paper to 'View Seed Words' from Coldcard.\nIf you make a mistake here, your money is lost!",
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.title.setText(title)
        self.title.setWordWrap(True)

        self.add_image_tab("coldcard-view-seed.png", "Coldcard")


class ScreenshotsResetSigner(ScreenshotsTutorial):
    def __init__(
        self,
        title="Reset the hardware signer.",
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.title.setText(title)

        self.add_image_tab("coldcard-destroy-seed.png", "Coldcard")


class ScreenshotsRestoreSigner(ScreenshotsTutorial):
    def __init__(
        self,
        title="Restore the hardware signer.",
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.title.setText(title)

        self.add_image_tab("coldcard-import-seed.png", "Coldcard")


class ScreenshotsRegisterMultisig(ScreenshotsTutorial):
    def __init__(
        self,
        title="Import the multisig information in the hardware signer",
        group: str = "tutorial",
        parent: QWidget = None,
    ) -> None:
        super().__init__(group, parent)

        self.title.setText(title)

        self.add_image_tab("coldcard-register-multisig-decriptor.png", "Coldcard")
