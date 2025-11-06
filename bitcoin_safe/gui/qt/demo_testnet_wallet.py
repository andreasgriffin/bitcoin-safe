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
import shutil
from pathlib import Path

import bdkpython as bdk

from bitcoin_safe.gui.qt.util import resource_path

from ...config import UserConfig

logger = logging.getLogger(__name__)


def copy_testnet_demo_wallet(config: UserConfig) -> list[Path]:
    """Adds a demo wallet if startet in testnet."""
    demo_wallet_files: list[Path] = []
    if config.network == bdk.Network.BITCOIN:
        # NEVER do this on mainnet
        return []

    def copy_to_wallet_dir(name: str) -> Path | None:
        """Copy to wallet dir."""
        assert config.network != bdk.Network.BITCOIN, "Forbidden! Cannot create demo wallets for mainnet"
        demo_wallet_file = Path(resource_path("gui", "demo_wallets", config.network.name, name))
        destination = Path(config.wallet_dir) / demo_wallet_file.name
        if demo_wallet_file.exists() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(demo_wallet_file, destination)
            return destination
        return None

    if config.network in [
        bdk.Network.REGTEST,
    ]:
        if destination := copy_to_wallet_dir("demo-public-regtest.wallet"):
            demo_wallet_files.append(destination)

    if config.network in [bdk.Network.SIGNET]:
        if destination := copy_to_wallet_dir("demo-public-signet.wallet"):
            demo_wallet_files.append(destination)

    if config.network in [
        bdk.Network.TESTNET,
    ]:
        if destination := copy_to_wallet_dir("demo-public-testnet.wallet"):
            demo_wallet_files.append(destination)

    if config.network in [bdk.Network.TESTNET4]:
        if destination := copy_to_wallet_dir("demo-public-testnet4.wallet"):
            demo_wallet_files.append(destination)

    return demo_wallet_files
