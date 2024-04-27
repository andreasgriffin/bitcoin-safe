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
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from packaging import version
from PyQt6.QtWidgets import QHBoxLayout, QStyle, QWidget

from bitcoin_safe.gui.qt.downloader import Downloader, DownloadThread
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.threading_manager import TaskThread

from ... import __version__
from ...html import link
from ...signals import SignalsMin
from ...signature_manager import (
    Asset,
    GitHubAssetDownloader,
    KnownGPGKeys,
    SignatureVerifyer,
)
from .util import Message, MessageType

logger = logging.getLogger(__name__)


class UpdateNotificationBar(NotificationBar):
    key = KnownGPGKeys.andreasgriffin

    def __init__(self, signals_min: SignalsMin, parent=None):
        self.download_container = QWidget()
        self.download_container.setLayout(QHBoxLayout())
        current_margins = self.download_container.layout().contentsMargins()
        self.download_container.layout().setContentsMargins(
            current_margins.left(), 1, current_margins.right(), 0
        )  # Left, Top, Right, Bottom margins
        self.download_container.layout().setSpacing(self.download_container.layout().spacing() // 2)

        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=lambda: self.check(),
            additional_widget=self.download_container,
            has_close_button=True,
            parent=parent,
        )
        self.signals_min = signals_min
        refresh_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self.optionalButton.setIcon(refresh_icon)

        self.verifyer = SignatureVerifyer(list_of_known_keys=[self.key])
        self.assets: List[Asset] = []
        self.setVisible(False)

        self.refresh()
        self.signals_min.language_switch.connect(self.refresh)

    def get_asset_tag(self) -> Optional[str]:
        if self.assets:
            tag = self.assets[-1].tag
            return tag
        else:
            return None

    def is_new_version_available(self) -> bool:
        tag = self.get_asset_tag()
        if not tag:
            return False
        return version.parse(tag) > version.parse(__version__)

    def refresh(self):
        self.optionalButton.setText(self.tr("Check for Update"))

        # clear layout
        while self.download_container.layout().count():
            child = self.download_container.layout().takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.download_container.setVisible(bool(self.assets))
        if self.assets:
            if self.is_new_version_available():
                self.textLabel.setText(self.tr("New version available {tag}").format(self.get_asset_tag()))
                self.optionalButton.setVisible(False)
                self.setVisible(True)
            else:
                self.textLabel.setText(self.tr("You have already the newest version."))
                self.optionalButton.setVisible(True)
        else:
            self.textLabel.setText(self.tr("No update found"))
            self.optionalButton.setVisible(True)

        for asset in self.assets:
            downloader = Downloader(url=asset.url, destination_dir=tempfile.gettempdir())
            downloader.finished.connect(self.on_download_finished)
            self.download_container.layout().addWidget(downloader)

    def on_download_finished(self, download_thread: DownloadThread):
        sig_file_path = self.verifyer.get_signature_from_web(download_thread.filename)
        destination = self.get_download_folder()
        if (
            not self.verifyer.is_gnupg_installed()
            or sig_file_path
            and self.verifyer.verify_signature(download_thread.filename, expected_public_key=self.key)
        ):
            # overwrite the download_thread.filename so the show-button still works
            download_thread.filename = self.move_and_overwrite(download_thread.filename, destination)
            if sig_file_path:
                self.move_and_overwrite(sig_file_path, destination)

            if not self.verifyer.is_gnupg_installed():
                if platform.system() == "Windows":
                    txt = self.tr(
                        """Please install  {link} to automatically verify the signature of the update."""
                    ).format(link=link("https://www.gpg4win.org"))
                elif platform.system() == "Linux":
                    txt = self.tr(
                        """Please install  GPG via "sudo apt-get -y install gpg" to automatically verify the signature of the update."""
                    )
                elif platform.system() == "Darwin":
                    txt = self.tr(
                        """Please install  GPG via "brew install gnupg" to automatically verify the signature of the update."""
                    )
                Message(txt, type=MessageType.Error)

    @staticmethod
    def move_and_overwrite(source: Path, destination: Path) -> Path:
        # convert destination to destination with filename
        if destination.is_dir():
            destination = destination / source.name

        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(source, destination)
        return destination

    @staticmethod
    def get_download_folder() -> Path:
        return Path.home() / "Downloads"

    def get_filtered_assets(self, assets: List[Asset]) -> List[Asset]:
        filtered_assets: List[Asset] = []
        for asset in assets:
            if platform.system() == "Windows" and not any(
                [asset.name.endswith(ending) for ending in ["exe", "msi"]]
            ):
                continue
            elif platform.system() == "Linux" and not any(
                [asset.name.endswith(ending) for ending in ["AppImage", "deb", "rpm"]]
            ):
                continue
            elif platform.system() == "Darwin" and not any(
                [asset.name.endswith(ending) for ending in ["dmg"]]
            ):
                continue

            # check if the asset can be recognized
            if not self.key.get_tag_if_mine(asset.name):
                continue

            filtered_assets.append(asset)
        return filtered_assets

    def check(self):
        def do():
            return GitHubAssetDownloader(self.key.repository).get_assets_latest()

        def on_done(result):
            pass

        def on_success(assets: List[Asset]):
            # filter the assets, by recognized and for the platform

            self.assets = self.get_filtered_assets(assets)
            self.refresh()

        def on_error(packed_error_info):
            logger.error(f"error in fetching update info {packed_error_info}")

        TaskThread(self, signals_min=self.signals_min).add_and_start(do, on_success, on_done, on_error)

    def check_and_make_visible(self):
        self.check()
        self.setVisible(True)
