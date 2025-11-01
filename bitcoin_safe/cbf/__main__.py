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


import asyncio
import sys
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import bdkpython as bdk
from bdkpython import Descriptor, IpAddress, Peer, Persister, Wallet
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bitcoin_safe.client import UpdateInfo

from .cbf_sync import CbfSync


# --- MainWindow ---
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.syncer: Optional[CbfSync] = None
        self._bridge_tasks: list[Future[Any]] = []

        self.setWindowTitle("CBF Demo - PyQt6 Interface")
        self.resize(600, 550)

        # # bacon descriptor
        DEFAULT_DESCRIPTOR = "wpkh([9a6a2580/84h/0h/0h]xpub6DEzNop46vmxR49zYWFnMwmEfawSNmAMf6dLH5YKDY463twtvw1XD7ihwJRLPRGZJz799VPFzXHpZu6WdhT29WnaeuChS6aZHZPFmqczR5K/0/*)"
        DEFAULT_CHANGE = "wpkh([9a6a2580/84h/0h/0h]xpub6DEzNop46vmxR49zYWFnMwmEfawSNmAMf6dLH5YKDY463twtvw1XD7ihwJRLPRGZJz799VPFzXHpZu6WdhT29WnaeuChS6aZHZPFmqczR5K/1/*)"

        form = QFormLayout()
        self.network_input = QComboBox()
        for network in bdk.Network:
            self.network_input.addItem(network.name, network)
        self.network_input.setCurrentIndex(0)
        self.ip_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("8333")
        self.start_height = QLineEdit("0")
        self.desc_input = QLineEdit(DEFAULT_DESCRIPTOR)
        self.change_input = QLineEdit(DEFAULT_CHANGE)
        form.addRow("Network:", self.network_input)
        form.addRow("Start block height:", self.start_height)
        form.addRow("Peer IP:", self.ip_input)
        form.addRow("Peer Port:", self.port_input)
        form.addRow("Descriptor:", self.desc_input)
        form.addRow("Change Descriptor:", self.change_input)
        self.peers = []

        # Buttons for node control and sync control
        self.build_button = QPushButton("Build Node")
        self.build_button.clicked.connect(self.on_build_node)
        self.delete_button = QPushButton("Delete Node")
        self.delete_button.clicked.connect(self.on_delete_node)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.build_button)
        button_layout.addWidget(self.delete_button)
        button_layout.addStretch()

        self.start_time = datetime.now()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(button_layout)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_view)

    @classmethod
    def format_timedelta(cls, td: timedelta) -> str:
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    @classmethod
    def weighted_past_time(
        cls,
        current_height: int,
        past_time: timedelta,
        bip141_activation: int = 481_824,
        pre_factor: int = 4,
        post_factor: int = 1,
    ) -> timedelta:
        """
        Return `past_time` after weighting the portion that corresponds to
        blocks *before* SegWit activation (`≤ bip141_activation`) by
        `pre_factor`, and the portion after activation by `post_factor`.

        ─ If current_height ≤ 0        → just return `past_time`.
        ─ If current_height ≤ activation
            every block seen so far is pre-SegWit  → weight × `pre_factor`.
        ─ If current_height > activation
            pre-ratio = activation / current_height
            post-ratio = 1 − pre-ratio
        """
        if past_time <= timedelta(0):
            return past_time  # nothing to weight
        if current_height <= 0:
            return past_time  # avoid div-by-zero / negative heights

        # --- fraction of blocks processed so far that are pre-SegWit -------------
        pre_blocks = min(current_height, bip141_activation)
        pre_ratio = pre_blocks / max(1, current_height)
        post_ratio = 1.0 - pre_ratio

        weighted_secs = past_time.total_seconds() * (pre_ratio * pre_factor + post_ratio * post_factor)
        return timedelta(seconds=weighted_secs)

    def on_log_info(self, log: bdk.Info):
        if isinstance(log, bdk.Info.PROGRESS):
            self.progress_bar.setValue(int(log.progress * 100))

            passed_time = datetime.now() - self.start_time

            estimated_time = timedelta(
                seconds=passed_time.total_seconds() / max(0.001, log.progress) * (1 - log.progress)
            )
            self.progress_bar.setFormat(
                f"{int(log.progress * 100)}%   ETA: {self.format_timedelta(estimated_time)}.  Past: {self.format_timedelta(passed_time)}"
            )
        else:
            self.log_view.append(str(log))

    def on_log_warning(self, log: bdk.Warning):
        self.log_view.append(str(log))

    def log_message(self, message: str):
        self.log_view.append(message)
        print(message)

    def _cancel_bridge_tasks(self) -> None:
        for task in self._bridge_tasks:
            if task and not task.done():
                task.cancel()
        self._bridge_tasks.clear()

    async def _bridge(
        self,
        coro: Callable[[], Coroutine[Any, Any, Any]],
        callback: Callable[[Any], None],
    ) -> None:
        try:
            while True:
                result = await coro()
                if result is None:
                    continue

                QTimer.singleShot(0, lambda res=result: callback(res))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.log_message(f"Bridge error: {exc}")

    def _start_bridge_tasks(self) -> None:
        if not self.syncer:
            return

        self._cancel_bridge_tasks()
        bridges = [
            self.syncer.loop_in_thread.run_background(self._bridge(self.syncer.next_log, self.log_message)),
            self.syncer.loop_in_thread.run_background(self._bridge(self.syncer.next_info, self.on_log_info)),
            self.syncer.loop_in_thread.run_background(
                self._bridge(self.syncer.next_warning, self.on_log_warning)
            ),
            self.syncer.loop_in_thread.run_background(
                self._bridge(self.syncer.next_update_info, self.on_update)
            ),
        ]

        for task in bridges:
            self.syncer.register_task(task)
            self._bridge_tasks.append(task)

    def create_syncer(self) -> bool:
        """
        Initialize the CbfSync instance with current inputs.
        Returns True on success, False on failure.
        """
        try:
            network = self.network_input.currentData()
            ip_parts = list(map(int, self.ip_input.text().split(".")))
            ip = IpAddress.from_ipv4(*ip_parts)
            port = int(self.port_input.text())
            peer = Peer(address=ip, port=port, v2_transport=False)
            self.peers.append(peer)
            desc = Descriptor(self.desc_input.text(), network=network)
            change = Descriptor(self.change_input.text(), network=network)
        except Exception as e:
            QMessageBox.critical(self, "Input Error", str(e))
            return False

        persister = Persister.new_in_memory()
        self.wallet = Wallet(desc, change, network, persister)
        addresses = self.wallet.reveal_addresses_to(keychain=bdk.KeychainKind.EXTERNAL, index=0)
        self.log_message(f"Receive address: {addresses[0].address}")
        self.syncer = CbfSync(wallet_id="demo")
        self._start_bridge_tasks()
        return True

    def on_update(self, update: UpdateInfo):
        self.wallet.apply_update(update=update.update)
        self.log_message(f"Wallet balance {self.wallet.balance().total.to_sat()}")

    def on_build_node(self):
        """Build the node without starting synchronization."""
        if self.syncer is None:
            self.create_syncer()
        if not self.syncer:
            return
        if self.syncer.node_running():
            self.log_message("Delete the node first")
            return
        self.syncer.build_node(
            wallet=self.wallet,
            peers=self.peers,
            recovery_height=int(self.start_height.text()),
            proxy_info=None,
            data_dir=Path("."),
            cbf_connections=2,
            is_new_wallet=True,
        )
        self.log_message("Node built successfully.")

    def on_delete_node(self):
        """Delete the current built node."""
        if self.syncer is None:
            self.log_message("No node to delete. Build a node first.")
            return

        if not self.syncer.node_running():
            self.log_message("No node running")
            return

        try:
            self._cancel_bridge_tasks()
            self.syncer.shutdown_node()
            self.log_message("Node deleted successfully.")
        except Exception as e:
            self.log_message(f"Failed to delete node: {e}")

    def closeEvent(self, a0: Optional[QCloseEvent]) -> None:
        if self.syncer is not None:
            self._cancel_bridge_tasks()
            self.close()
        super().closeEvent(a0)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
