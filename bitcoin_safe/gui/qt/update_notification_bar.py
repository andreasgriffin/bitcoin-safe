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

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any, cast

from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, LoopInThread, MultipleStrategy
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget

from bitcoin_safe.gui.qt.downloader import Downloader, DownloadWorker
from bitcoin_safe.gui.qt.notification_bar import NotificationBar
from bitcoin_safe.gui.qt.util import svg_tools
from bitcoin_safe.signals import SignalsMin

from ... import __version__
from ...html_utils import html_f
from ...signature_manager import (
    Asset,
    GitHubAssetDownloader,
    KnownGPGKeys,
    SignatureVerifyer,
)
from ...util import fast_version
from .util import Message, MessageType, set_margins

logger = logging.getLogger(__name__)


class UpdateNotificationBar(NotificationBar):
    Linux_Recognized_endings = [
        "AppImage",
        "deb",
        "rpm",
        "flatpak",
        "snap",
        "pkg.tar.zst",  # Arch
        "apk",  # Alpine
        "eopkg",  # Solus
        "tar.gz",
        "tar.xz",
        "tar.bz2",
    ]
    Mac_Recognized_endings = [
        "dmg",
        "pkg",
    ]
    Win_Recognized_endings = [
        "exe",
        "msi",
        "msix",
        "appx",
        "zip",  # common for portable apps
    ]

    signal_on_success = cast(SignalProtocol[[]], pyqtSignal())

    key = KnownGPGKeys.andreasgriffin

    def __init__(
        self,
        signals_min: SignalsMin,
        loop_in_thread: LoopInThread,
        proxies: dict | None,
        parent=None,
    ) -> None:
        """Initialize instance."""
        self.proxies = proxies
        super().__init__(
            text="",
            optional_button_text="",
            callback_optional_button=self.check,
            has_close_button=True,
            parent=parent,
        )
        self.loop_in_thread = loop_in_thread
        self.signals_min = signals_min
        refresh_icon = svg_tools.get_QIcon("bi--arrow-clockwise.svg")
        self.optionalButton.setIcon(refresh_icon)

        self.verifyer = SignatureVerifyer(list_of_known_keys=[self.key], proxies=self.proxies)
        self.assets: list[Asset] = []
        self.setVisible(False)

        self.download_container = QWidget()
        self.download_container_layout = QHBoxLayout(self.download_container)

        set_margins(
            self.download_container_layout,
            {
                Qt.Edge.TopEdge: 1,
                Qt.Edge.BottomEdge: 5,
            },
        )
        self.download_container_layout.setSpacing(self.download_container_layout.spacing() // 2)
        self.add_styled_widget(self.download_container)

        self.refresh()
        self.signals_min.language_switch.connect(self.refresh)

    def get_asset_tag(self) -> str | None:
        """Get asset tag."""
        if self.assets:
            tag = self.assets[-1].tag
            return tag
        else:
            return None

    def is_new_version_available(self) -> bool:
        """Is new version available."""
        tag = self.get_asset_tag()
        if not tag:
            return False
        return fast_version(tag) > fast_version(__version__)

    def refresh(self) -> None:
        """Refresh."""
        self.optionalButton.setText(self.tr("Check for Update"))

        # clear layout
        while self.download_container_layout.count():
            if (layout_item := self.download_container_layout.takeAt(0)) and (
                _widget := layout_item.widget()
            ):
                _widget.close()

        self.download_container.setVisible(bool(self.assets))
        if self.assets:
            if self.is_new_version_available():
                self.icon_label.setText(
                    self.tr("New version available {tag}").format(tag=self.get_asset_tag())
                )
                self.optionalButton.setVisible(False)
                self.setVisible(True)

                for asset in self.assets:
                    downloader = Downloader(
                        url=asset.url, destination_dir=tempfile.gettempdir(), proxies=self.proxies
                    )
                    downloader.finished.connect(self.on_download_finished)
                    self.download_container_layout.addWidget(downloader)
            else:
                self.icon_label.setText(self.tr("You have already the newest version."))
                self.optionalButton.setVisible(True)
        else:
            self.icon_label.setText(self.tr("No update found"))
            self.optionalButton.setVisible(True)

    def on_download_finished(self, download_thread: DownloadWorker) -> None:
        """On download finished."""
        sig_file_path = self.verifyer.get_signature_from_web(download_thread.filename)
        if not sig_file_path:
            Message(self.tr("Could not verify the download. Please try again later."), parent=self)
            self.refresh()
            self.setVisible(False)
            return

        destination = self.get_download_folder()
        was_signature_verified = None

        was_signature_verified = self.verifyer.verify_signature(
            download_thread.filename, expected_public_key=self.key
        )
        if not was_signature_verified:
            Message(
                self.tr("Signature doesn't match!!! Please try again."),
                type=MessageType.Error,
                parent=self,
            )
            self.refresh()
            self.setVisible(False)
            return

        self.icon_label.setText(html_f(self.tr("Signature verified."), color="green", bf=True))

        # overwrite the download_thread.filename so the show-button still works
        download_thread.filename = self.move_and_overwrite(download_thread.filename, destination)
        if sig_file_path:
            self.move_and_overwrite(sig_file_path, destination)

        self.post_download_and_verify_action(download_thread)

    @staticmethod
    def move_and_overwrite(source: Path, destination: Path) -> Path:
        # convert destination to destination with filename
        """Move and overwrite."""
        if destination.is_dir():
            destination = destination / source.name

        if os.path.exists(destination):
            os.remove(destination)
        shutil.move(source, destination)
        return destination

    @staticmethod
    def get_download_folder() -> Path:
        """Get download folder."""
        return Path.home() / "Downloads"

    def post_download_and_verify_action(self, download_thread: DownloadWorker) -> None:
        """Post-download action after successful verification."""
        download_path = download_thread.filename
        if self._is_appimage_tarball(download_path):
            try:
                extracted_files = self._extract_tarball(download_path, download_path.parent)
                extracted_appimage = self._select_appimage_file(extracted_files)
                if extracted_appimage and extracted_appimage.exists():
                    download_thread.highlight_filename = extracted_appimage
            except (tarfile.TarError, OSError, ValueError) as exc:
                logger.error("Failed to extract update archive %s: %s", download_path, exc)
                Message(self.tr("Failed to extract update archive."), type=MessageType.Error, parent=self)

    @staticmethod
    def _is_appimage_tarball(download_path: Path) -> bool:
        return download_path.name.lower().endswith("appimage.tar.gz")

    @staticmethod
    def _is_within_directory(base_dir: Path, target_path: Path) -> bool:
        base_dir_resolved = base_dir.resolve()
        target_path_resolved = target_path.resolve(strict=False)
        return base_dir_resolved == target_path_resolved or base_dir_resolved in target_path_resolved.parents

    @staticmethod
    def _select_appimage_file(paths: list[Path]) -> Path | None:
        appimage_paths = [path for path in paths if path.name.lower().endswith(".appimage")]
        if not appimage_paths:
            return None
        return max(appimage_paths, key=lambda path: path.stat().st_size)

    def _extract_tarball(self, archive_path: Path, destination: Path) -> list[Path]:
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getmembers()
            for member in members:
                member_path = destination / member.name
                if not self._is_within_directory(destination, member_path):
                    raise ValueError(f"Unsafe tar entry: {member.name}")
            tar.extractall(destination)
        return [(destination / member.name).resolve() for member in members if member.isfile()]

    def get_filtered_assets(self, assets: list[Asset]) -> list[Asset]:
        """Get filtered assets."""
        filtered_assets: list[Asset] = []

        system = platform.system()
        machine = platform.machine().lower()

        # Normalize architecture
        current_arch_aliases = ["arm64", "aarch64"] if "arm" in machine else ["x86_64", "amd64"]

        for asset in assets:
            # --- OS FORMAT FILTERING ---
            if system == "Windows" and not any(
                asset.name.endswith(ending) for ending in self.Win_Recognized_endings
            ):
                continue

            elif system == "Linux" and not any(
                asset.name.endswith(ending) for ending in self.Linux_Recognized_endings
            ):
                continue

            elif system == "Darwin":
                if not any(asset.name.endswith(ending) for ending in self.Mac_Recognized_endings):
                    continue

                lower_name = asset.name.lower()

                # Extract arch tags found in filename
                arch_tags = re.findall(r"(arm64|aarch64|x86_64|amd64)", lower_name)

                if arch_tags and current_arch_aliases:  # only enforce filtering if tags exist
                    if not any(tag in current_arch_aliases for tag in arch_tags):
                        continue

            # --- CHECK IF ASSET BELONGS TO THIS KEY ---
            if not self.key.get_tag_if_mine(asset.name):
                continue

            filtered_assets.append(asset)

        return filtered_assets

    def check(self) -> None:
        """Check."""

        async def do() -> Any:
            """Do."""
            return GitHubAssetDownloader(self.key.repository, proxies=self.proxies).get_assets_latest()

        def on_done(result) -> None:
            """On done."""
            pass

        def on_success(assets: list[Asset] | None) -> None:
            # filter the assets, by recognized and for the platform

            """On success."""
            if not assets:
                return
            self.assets = self.get_filtered_assets(assets)
            self.refresh()
            self.signal_on_success.emit()

        def on_error(packed_error_info: ExcInfo | None) -> None:
            """On error."""
            logger.error(f"error in fetching update info {packed_error_info}")

        self.loop_in_thread.run_task(
            do(),
            on_done=on_done,
            on_success=on_success,
            on_error=on_error,
            key=f"{id(self)}notificationbar",
            multiple_strategy=MultipleStrategy.CANCEL_OLD_TASK,
        )

    def check_and_make_visible(self) -> None:
        """Check and make visible."""
        self.check()
        self.setVisible(True)
