#
# Bitcoin Safe
# Copyright (C) 2026 Andreas Griffin
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
#

from __future__ import annotations

import datetime
import os
import platform

import pytest

from bitcoin_safe.constants import MIN_RELAY_FEE
from bitcoin_safe.signature_manager import Asset, GitHubRelease


def _disable_fx_update(self) -> None:
    self.rates = {
        "BTC": {"name": "Bitcoin", "unit": "BTC", "value": 1.0, "type": "crypto"},
        "SATS": {"name": "Satoshis", "unit": "Sats", "value": 100_000_000.0, "type": "crypto"},
        "USD": {"name": "US Dollar", "unit": "$", "value": 100_000.0, "type": "fiat"},
        "EUR": {"name": "Euro", "unit": "EUR", "value": 92_000.0, "type": "fiat"},
    }
    self.config.rates = self.rates.copy()
    self._task_set_data = None
    self.signal_data_updated.emit()


def _disable_mempool_fetch(self, force=False) -> None:
    del force
    self.data.recommended = {
        "fastestFee": 12.0,
        "halfHourFee": 4.0,
        "hourFee": float(MIN_RELAY_FEE),
        "economyFee": float(MIN_RELAY_FEE),
        "minimumFee": float(MIN_RELAY_FEE),
    }
    self.data.mempool_blocks = [
        {
            "blockSize": 975_000,
            "blockVSize": 975_000,
            "nTx": 1_800,
            "totalFees": 1_200_000,
            "medianFee": 12.0,
            "feeRange": [12.0, 20.0],
        },
        {
            "blockSize": 940_000,
            "blockVSize": 940_000,
            "nTx": 1_500,
            "totalFees": 800_000,
            "medianFee": 4.0,
            "feeRange": [4.0, 12.0],
        },
        {
            "blockSize": 910_000,
            "blockVSize": 910_000,
            "nTx": 1_200,
            "totalFees": 500_000,
            "medianFee": float(MIN_RELAY_FEE),
            "feeRange": [float(MIN_RELAY_FEE), 4.0],
        },
    ]
    self.data.mempool_dict = {
        "count": 4_500,
        "vsize": 2_825_000,
        "total_fee": 2_500_000,
        "fee_histogram": [],
    }
    self.time_of_data = datetime.datetime.now()
    self._task_set_data = None
    self.signal_data_updated.emit()


def _fake_github_releases(self) -> list[GitHubRelease]:
    del self
    tag = "99.0.0"
    asset_extension_by_system = {
        "Darwin": "dmg",
        "Linux": "AppImage",
        "Windows": "exe",
    }
    asset_architecture = (
        "arm64" if platform.system() == "Darwin" and "arm" in platform.machine().lower() else "x86_64"
    )
    asset_extension = asset_extension_by_system.get(platform.system(), "AppImage")
    asset_name = f"bitcoin-safe-{tag}-{asset_architecture}.{asset_extension}"
    return [
        GitHubRelease(
            tag=tag,
            prerelease=False,
            assets=[
                Asset(
                    tag=tag,
                    url=f"https://example.com/{asset_name}",
                    name=asset_name,
                )
            ],
        )
    ]


@pytest.fixture(autouse=True)
def disable_startup_network_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep GUI tests deterministic by disabling live startup HTTP fetches."""

    monkeypatch.setattr("bitcoin_safe.fx.FX.update", _disable_fx_update)
    monkeypatch.setattr(
        "bitcoin_safe.mempool_manager.MempoolManager.set_data_from_mempoolspace",
        _disable_mempool_fetch,
    )
    current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    if "tests/gui/qt/test_update_notification_bar.py" not in current_test:
        monkeypatch.setattr(
            "bitcoin_safe.signature_manager.GitHubAssetDownloader.get_releases",
            _fake_github_releases,
        )


@pytest.fixture(autouse=True)
def mock__ask_if_full_scan(monkeypatch):
    """
    GUI tests that create new wallets ask whether the wallet was used before.
    Force the dialog to return False so tests consistently choose the "quick scan"/new wallet path.
    """

    # Patch the bound method on MainWindow so calls bypass the UI prompt
    monkeypatch.setattr("bitcoin_safe.gui.qt.main.MainWindow._ask_if_full_scan", lambda self: True)
    yield


@pytest.fixture(autouse=True)
def mock__ask_if_wallet_should_remain_open(monkeypatch):
    """
    GUI tests that create new wallets ask whether the wallet was used before.
    Force the dialog to return False so tests consistently choose the "quick scan"/new wallet path.
    """

    # Patch the bound method on MainWindow so calls bypass the UI prompt
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.main.MainWindow._ask_if_wallet_should_remain_open", lambda self: False
    )
    yield
