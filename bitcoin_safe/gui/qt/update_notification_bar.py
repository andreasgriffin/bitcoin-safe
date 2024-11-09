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
from typing import Any, List, Optional

from packaging import version
from PyQt6.QtWidgets import QHBoxLayout, QStyle, QWidget

from bitcoin_safe.gui.qt.downloader import Downloader, DownloadThread
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.threading_manager import TaskThread, ThreadingManager

from ... import __version__
from ...html_utils import html_f
from ...signals import SignalsMin
from ...signature_manager import (
    Asset,
    GitHubAssetDownloader,
    KnownGPGKeys,
    SignatureVerifyer,
)
from .util import Message, MessageType

logger = logging.getLogger(__name__)


class UpdateNotificationBar(NotificationBar, ThreadingManager):
    key = KnownGPGKeys.andreasgriffin

    def __init__(
        self, signals_min: SignalsMin, parent=None, threading_parent: ThreadingManager | None = None
    ) -> None:
        self.download_container = QWidget()
        self.download_container_layout = QHBoxLayout(self.download_container)
        current_margins = self.download_container_layout.contentsMargins()
        self.download_container_layout.setContentsMargins(
            current_margins.left(), 1, current_margins.right(), 0
        )  # Left, Top, Right, Bottom margins
        self.download_container_layout.setSpacing(self.download_container_layout.spacing() // 2)

        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=lambda: self.check(),
            additional_widget=self.download_container,
            has_close_button=True,
            parent=parent,
            threading_parent=threading_parent,
        )
        self.signals_min = signals_min
        refresh_icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
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

    def refresh(self) -> None:
        self.optionalButton.setText(self.tr("Check for Update"))

        # clear layout
        while self.download_container_layout.count():
            if (layout_item := self.download_container_layout.takeAt(0)) and (
                _widget := layout_item.widget()
            ):
                _widget.deleteLater()

        self.download_container.setVisible(bool(self.assets))
        if self.assets:
            if self.is_new_version_available():
                self.textLabel.setText(
                    self.tr("New version available {tag}").format(tag=self.get_asset_tag())
                )
                self.optionalButton.setVisible(False)
                self.setVisible(True)

                for asset in self.assets:
                    downloader = Downloader(url=asset.url, destination_dir=tempfile.gettempdir())
                    downloader.finished.connect(self.on_download_finished)
                    self.download_container_layout.addWidget(downloader)
            else:
                self.textLabel.setText(self.tr("You have already the newest version."))
                self.optionalButton.setVisible(True)
        else:
            self.textLabel.setText(self.tr("No update found"))
            self.optionalButton.setVisible(True)

    def on_download_finished(self, download_thread: DownloadThread) -> None:
        sig_file_path = self.verifyer.get_signature_from_web(download_thread.filename)
        if not sig_file_path:
            Message(self.tr("Could not verify the download. Please try again later."))
            self.refresh()
            self.setVisible(False)
            return

        destination = self.get_download_folder()
        was_signature_verified = None

        was_signature_verified = self.verifyer.verify_signature(
            download_thread.filename, expected_public_key=self.key
        )
        if not was_signature_verified:
            Message(self.tr("Signature doesn't match!!! Please try again."), type=MessageType.Error)
            self.refresh()
            self.setVisible(False)
            return

        self.textLabel.setText(html_f(self.tr("Signature verified."), color="green", bf=True))

        # overwrite the download_thread.filename so the show-button still works
        download_thread.filename = self.move_and_overwrite(download_thread.filename, destination)
        if sig_file_path:
            self.move_and_overwrite(sig_file_path, destination)

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
                [
                    asset.name.endswith(ending)
                    for ending in ["AppImage", "deb", "rpm", "flatpak", "snap", "pkg.tar.zst"]
                ]
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

    def check(self) -> None:
        def do() -> Any:
            return GitHubAssetDownloader(self.key.repository).get_assets_latest()

        def on_done(result) -> None:
            pass

        def on_success(assets: List[Asset]) -> None:
            # filter the assets, by recognized and for the platform

            self.assets = self.get_filtered_assets(assets)
            self.refresh()

        def on_error(packed_error_info) -> None:
            logger.error(f"error in fetching update info {packed_error_info}")

        self.append_thread(TaskThread().add_and_start(do, on_success, on_done, on_error))

    def check_and_make_visible(self) -> None:
        self.check()
        self.setVisible(True)
