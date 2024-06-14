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


import os
import platform
import subprocess
import sys
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, url, destination_dir) -> None:
        super().__init__()
        self.url = url
        self.destination_dir = Path(destination_dir)
        self.filename: Path = self.destination_dir / Path(url).name

    def run(self) -> None:
        response = requests.get(self.url, stream=True, timeout=2)
        content_length = response.headers.get("content-length")

        if content_length is None:  # no content length header
            self.progress.emit(100)
            self.filename.write_bytes(response.content)
        else:
            with open(self.filename, "wb") as f:
                dl = 0
                for data in response.iter_content(chunk_size=4096):
                    dl += len(data)
                    f.write(data)
                    self.progress.emit(int(100 * dl / int(content_length)))
        self.finished.emit()


class Downloader(QWidget):
    finished = pyqtSignal(DownloadThread)

    def __init__(self, url, destination_dir) -> None:
        super().__init__()
        self.url = url
        self.destination_dir = Path(destination_dir)
        self.filename = Path(url).name  # Extract filename from URL
        self.initUI()

    def initUI(self) -> None:
        self.setWindowTitle(self.tr("Download Progress"))
        self.layout = QVBoxLayout()

        # Use the filename in the button text
        self.startButton = QPushButton(self.tr("Download {}").format(self.filename))
        download_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
        self.startButton.setIcon(download_icon)
        self.startButton.clicked.connect(self.startDownload)
        self.layout.addWidget(self.startButton)

        self.progress = QProgressBar()
        self.progress.setGeometry(0, 0, 300, 25)
        self.layout.addWidget(self.progress)
        self.progress.hide()

        # Use the filename in the button text
        self.showFileButton = QPushButton(self.tr("Show {} in Folder").format(self.filename))
        open_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        self.showFileButton.setIcon(open_icon)
        self.showFileButton.clicked.connect(self.showFile)
        self.layout.addWidget(self.showFileButton)
        self.showFileButton.hide()

        self.setLayout(self.layout)
        self.setGeometry(400, 400, 300, 100)

    def startDownload(self) -> None:
        self.startButton.hide()
        self.progress.show()
        self.thread = DownloadThread(self.url, str(self.destination_dir))
        self.thread.progress.connect(self.progress.setValue)
        self.thread.finished.connect(self.downloadFinished)
        self.thread.start()

    def downloadFinished(self) -> None:
        self.progress.hide()
        self.showFileButton.show()
        self.finished.emit(self.thread)

    def showFile(self) -> None:
        filename = self.thread.filename
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["explorer", "/select,", filename])
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", "-R", filename])
            else:  # Linux
                desktop_session = os.environ.get("XDG_CURRENT_DESKTOP")
                if desktop_session and "KDE" in desktop_session:
                    # Attempt to use Dolphin to select the file
                    subprocess.Popen(["dolphin", "--select", filename])
                else:
                    # Fallback for other environments or if the detection is uncertain
                    subprocess.Popen(["xdg-open", filename.parent])
        except Exception as e:
            print(f"Error opening file: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Example usage
    downloader = Downloader(
        "https://github.com/sparrowwallet/sparrow/releases/download/1.8.4/sparrow_1.8.4-1_amd64.deb", "/tmp"
    )
    downloader.show()
    sys.exit(app.exec())
