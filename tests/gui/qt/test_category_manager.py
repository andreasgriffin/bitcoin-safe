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

import inspect
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.my_treeview import MyItemDataRole
from tests.gui.qt.test_setup_wallet import close_wallet

from .helpers import Shutter, main_window_context


@pytest.mark.marker_qt_2
def test_category_manager_add_and_merge(
    qapp: QApplication,
    qtbot: QtBot,
    mytest_start_time: datetime,
    test_config: UserConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure categories can be added and merged through the category manager."""

    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore

        temp_dir = Path(tempfile.mkdtemp()) / "0.2.0.wallet"
        wallet_path = Path("tests") / "data" / "0.2.0.wallet"
        shutil.copy(str(wallet_path), str(temp_dir))

        qt_wallet = main_window.open_wallet(str(temp_dir))
        assert qt_wallet

        main_window.open_category_manager()
        category_manager = qt_wallet.category_manager
        category_manager.updateUi()
        category_manager.category_list.update_content()

        existing_categories = list(qt_wallet.wallet.labels.categories)
        assert existing_categories

        new_category = "Test Merge Category"

        for target in [
            "bitcoin_safe.gui.qt.category_manager.category_core.prompt_new_category",
            "bitcoin_safe.gui.qt.category_manager.category_manager.prompt_new_category",
        ]:
            monkeypatch.setattr(target, lambda *args, **kwargs: new_category)

        category_manager.add_category()
        category_manager.category_list.update_content()

        assert new_category in qt_wallet.wallet.labels.categories

        target_category = existing_categories[0]

        for target in [
            "bitcoin_safe.gui.qt.category_manager.category_core.prompt_merge_category",
            "bitcoin_safe.gui.qt.category_manager.category_manager.prompt_merge_category",
        ]:
            monkeypatch.setattr(target, lambda *args, **kwargs: target_category)
        monkeypatch.setattr(category_manager, "get_used_addresses", lambda category, addresses=None: [])

        category_manager.category_list.select_rows(
            [target_category, new_category],
            category_manager.category_list.key_column,
            role=MyItemDataRole.ROLE_CLIPBOARD_DATA,
        )

        assert len(category_manager.category_list.get_selected_category_infos()) == 2, (
            "expected both categories to be selected for merge"
        )

        category_manager.on_button_merge()
        category_manager.category_list.update_content()

        assert new_category not in qt_wallet.wallet.labels.categories
        assert target_category in qt_wallet.wallet.labels.categories
        assert len(qt_wallet.wallet.labels.categories) == len(existing_categories)

        shutter.save(main_window)
        close_wallet(
            shutter=shutter,
            test_config=test_config,
            wallet_name=qt_wallet.wallet.id,
            qtbot=qtbot,
            main_window=main_window,
        )
