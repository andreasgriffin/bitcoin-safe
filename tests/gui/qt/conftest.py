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

import os
import platform
from time import monotonic

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.dialogs import WalletIdDialog


def _running_on_github_macos() -> bool:
    return platform.system() == "Darwin" and os.getenv("GITHUB_ACTIONS") == "true"


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


@pytest.fixture(autouse=True)
def patch_wallet_id_dialog_exec_on_github_macos(monkeypatch: pytest.MonkeyPatch):
    """Avoid macOS GitHub runner deadlock in WalletIdDialog.exec()."""
    if not _running_on_github_macos():
        yield
        return

    def safe_exec(self: WalletIdDialog) -> int:
        self.open()
        deadline = monotonic() + 30.0
        while self.result() == 0 and monotonic() < deadline:
            QApplication.processEvents()
            QTest.qWait(10)
        if self.result() == 0:
            self.reject()
        return int(self.result())

    monkeypatch.setattr(WalletIdDialog, "exec", safe_exec)
    yield
