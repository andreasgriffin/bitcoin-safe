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
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from pytestqt.qtbot import QtBot

from bitcoin_safe.cbf.cbf_sync import CbfSync
from bitcoin_safe.wallet import Wallet

from .helpers import TestConfig
from .setup_bitcoin_core import TEST_DIR, mine_blocks
from .util import wait_for_sync

logger = logging.getLogger(__name__)

CBF_DATA_DIR = TEST_DIR / "cbf_data"


def remove_cbf_data(data_dir=CBF_DATA_DIR) -> None:
    """Remove persisted CBF data between runs for clean state."""
    if data_dir and data_dir.exists():
        shutil.rmtree(data_dir)


@dataclass
class TestWalletHandle:
    wallet: Wallet
    backend: str
    cbf_tasks: list[asyncio.Future]
    bitcoin_core: Path

    def close(self):
        """Cancel background tasks and close wallet resources."""
        for task in self.cbf_tasks:
            task.cancel()
        self.wallet.close()

    def sync(self, qtbot: QtBot, timeout: float = 10_000):
        """Sync the wallet using the configured backend."""
        logger.info("start sync")
        wait_for_sync(qtbot=qtbot, wallet=self.wallet, timeout=timeout)

    def mine(self, qtbot: QtBot, blocks=1, address=None, timeout: float = 10_000):
        """Mine to the wallet and wait until detected."""

        bdk_wallet = self.wallet.bdkwallet
        txs = bdk_wallet.transactions()
        prev_balance = self.wallet.get_balance().total
        address = (
            address
            if address
            else str(bdk_wallet.next_unused_address(keychain=bdk.KeychainKind.EXTERNAL).address)
        )
        block_hashes = mine_blocks(
            self.bitcoin_core,
            blocks,
            address=address,
        )
        attempts = 0
        max_attempts = 40
        while len(bdk_wallet.transactions()) - len(txs) < len(block_hashes):
            attempts += 1
            try:
                wait_for_sync(
                    qtbot=qtbot, wallet=self.wallet, timeout=timeout, minimum_funds=prev_balance + 1
                )
            except RuntimeError as exc:
                logger.error(f"Stopping mine wait loop: {exc}")
                # raise
            if attempts >= max_attempts:
                raise RuntimeError("Test wallet sync did not detect mined blocks in time")
        logger.debug(f"Test Wallet balance is: {bdk_wallet.balance().total.to_sat()}")


def _start_cbf_tasks(wallet: Wallet) -> tuple[list[asyncio.Future]]:
    """Start background tasks to consume CBF info/warnings/updates."""
    assert wallet.client, "Wallet backend not initialized"
    cbf_client = wallet.client.client
    assert isinstance(cbf_client, CbfSync), "CBF client expected"

    tasks: list[asyncio.Future] = []

    async def _ininite_monitor(getter, label: str):
        while True:
            try:
                msg = await getter()
                if msg:
                    logger.info("%s %s", label, msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("%s stream error: %s", label, exc)
                await asyncio.sleep(1)

    tasks.append(wallet.loop_in_thread.run_background(_ininite_monitor(cbf_client.next_info, "cbf info")))
    tasks.append(wallet.loop_in_thread.run_background(_ininite_monitor(cbf_client.next_warning, "cbf warn")))
    tasks.append(wallet.loop_in_thread.run_background(_ininite_monitor(wallet.update, "cbf wallet.update")))

    return tasks


def create_test_wallet(
    wallet_id: str,
    descriptor_str: str,
    keystores: Iterable,
    backend: str,
    config: TestConfig,
    bitcoin_core: Path,
    loop_in_thread: LoopInThread,
    is_new_wallet=False,
) -> TestWalletHandle:
    """Build a Wallet ready for tests and start CBF background tasks if needed."""
    wallet = Wallet(
        id=wallet_id,
        descriptor_str=descriptor_str,
        keystores=list(keystores),
        network=config.network,
        config=config,
        loop_in_thread=loop_in_thread,
        is_new_wallet=is_new_wallet,
    )
    wallet.init_blockchain()
    cbf_tasks: list[asyncio.Future] = []
    if backend == "cbf":
        cbf_tasks = _start_cbf_tasks(wallet)

    return TestWalletHandle(
        wallet=wallet,
        backend=backend,
        cbf_tasks=cbf_tasks,
        bitcoin_core=bitcoin_core,
    )
