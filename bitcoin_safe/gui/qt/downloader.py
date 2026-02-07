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

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, cast

import requests
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from bitcoin_safe_lib.gui.qt.signal_tracker import SignalProtocol
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.util import default_timeout
from bitcoin_safe.util_os import show_file_in_explorer

logger = logging.getLogger(__name__)


class DownloadWorker(QObject):
    progress = cast(SignalProtocol[[int]], pyqtSignal(int))
    signal_finished = cast(SignalProtocol[[]], pyqtSignal())
    aborted = cast(SignalProtocol[[]], pyqtSignal())

    def __init__(self, url, destination_dir, proxies: dict | None) -> None:
        """Initialize instance."""
        super().__init__()
        self.url = url
        self.destination_dir = Path(destination_dir)
        self.proxies = proxies
        self.filename: Path = self.destination_dir / Path(url).name
        self.highlight_filename: Path | None = None
        self._loop_in_thread = LoopInThread()

    def start(self) -> None:
        """Start the download in a background event loop thread."""

        async def _runner() -> None:
            await asyncio.to_thread(self._download)

        def _on_success(_: Any) -> None:
            self.signal_finished.emit()

        def _on_error(exc_info: tuple[type[BaseException], BaseException, Any]) -> None:
            _, err, _ = exc_info
            logger.debug(f"{self.__class__.__name__}: {err}")
            self.aborted.emit()
            logger.warning(str(err))

        def _on_done(_: Any) -> None:
            self._loop_in_thread.stop()

        self._loop_in_thread.run_task(
            _runner(),
            on_success=_on_success,
            on_error=_on_error,
            on_done=_on_done,
        )

    def _download(self) -> None:
        """Perform the download and emit progress updates."""
        response = requests.get(
            self.url, stream=True, timeout=default_timeout(self.proxies), proxies=self.proxies
        )
        response.raise_for_status()
        content_length = response.headers.get("content-length")

        with open(self.filename, "wb") as f:
            dl = 0
            total = int(content_length) if content_length is not None else None
            for data in response.iter_content(chunk_size=4096):
                dl += len(data)
                f.write(data)
                if total:
                    self.progress.emit(int(100 * dl / total))
            # For unknown content-length, only update once the download completes
            if total is None:
                self.progress.emit(100)


class Downloader(QWidget):
    finished = cast(SignalProtocol[[DownloadWorker]], pyqtSignal(DownloadWorker))

    def __init__(self, url, destination_dir, proxies: dict | None) -> None:
        """Initialize instance."""
        super().__init__()
        self.url = url
        self.destination_dir = Path(destination_dir)
        self.filename = Path(url).name  # Extract filename from URL
        self.proxies = proxies
        self.initUI()

    def initUI(self) -> None:
        """InitUI."""
        self.setWindowTitle(self.tr("Download Progress"))
        self._layout = QVBoxLayout(self)

        # Use the filename in the button text
        self.startButton = QPushButton(self.tr("Download {}").format(self.filename))
        download_icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
        self.startButton.setIcon(download_icon)
        self.startButton.clicked.connect(self.startDownload)
        self._layout.addWidget(self.startButton)

        self.progress = QProgressBar()
        self.progress.setGeometry(0, 0, 300, 25)
        self._layout.addWidget(self.progress)
        self.progress.hide()

        # Use the filename in the button text
        self.showFileButton = QPushButton(self.tr("Open download folder: {}").format(self.filename))
        open_icon = (self.style() or QStyle()).standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        self.showFileButton.setIcon(open_icon)
        self.showFileButton.clicked.connect(self.showFile)
        self._layout.addWidget(self.showFileButton)
        self.showFileButton.hide()

        self.setGeometry(400, 400, 300, 100)

    def startDownload(self) -> None:
        """StartDownload."""
        self.startButton.hide()
        self.progress.show()
        self.mythread = DownloadWorker(self.url, str(self.destination_dir), proxies=self.proxies)
        self.mythread.progress.connect(self.progress.setValue)
        self.mythread.signal_finished.connect(self.downloadFinished)
        self.mythread.aborted.connect(self.download_aborted)
        self.mythread.start()

    def downloadFinished(self) -> None:
        """DownloadFinished."""
        self.progress.hide()
        self.showFileButton.show()
        self.finished.emit(self.mythread)

    def download_aborted(self) -> None:
        """Download aborted."""
        self.startButton.show()
        self.progress.hide()
        self.progress.setValue(0)
        # self.showFileButton.show()
        # self.finished.emit(self.mythread)

    def showFile(self) -> None:
        """ShowFile."""
        filename = self.mythread.highlight_filename or self.mythread.filename
        show_file_in_explorer(filename=filename)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Example usage
    downloader = Downloader(
        "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow_1.8.4-1_amd64.deb",
        "/tmp",
        proxies=None,
    )
    downloader.show()
    sys.exit(app.exec())
