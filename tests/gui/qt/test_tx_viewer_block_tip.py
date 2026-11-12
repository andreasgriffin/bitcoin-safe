#
# Bitcoin-Safe
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

from typing import Any
from unittest.mock import patch

import pytest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer

from ...helpers import TestConfig
from .helpers import main_window_context

RAW_TX = "0200000000010130e2288abc2259145cbd255a0cc94fe7226d26130b216100a9d631d7f31a5b090100000000fdffffff024894f31c01000000225120a450dee7d2d0f14d720b359f23660fed35c031de2d54e8fb0db8bd9f6b1ee35829ee250000000000220020b7f7e21184e2bacaa6346674bd9f619eb7619f316864d8c82564fde6735e7a3c0247304402203b76bd679a0f6ec4846a791247a5551771db6147a92f42e76ec4c079d3caf60502204f1bed609ee20c271faae2042c1d2727923650aea9439df78da45384e5979f1d01210370a2b7a566702a384ceb8e9f9f4c9ae8a4b4904b832c4de2cf19f3289285e20300000000"


@pytest.mark.marker_qt_2
def test_block_tip_height_arriving_during_initial_reload_is_not_missed(
    qapp: QApplication,
    qtbot: QtBot,
    test_config: TestConfig,
) -> None:
    """A block tip change emitted while the viewer runs its first reload must still re-evaluate
    the nlocktime warning, because the signal is only emitted once per height change."""
    original_reload = UITx_Viewer.reload
    reevaluations: list[int] = []
    fired = {"done": False}

    def reload_and_emit_tip(self: UITx_Viewer, *args: Any, **kwargs: Any) -> None:
        original_reload(self, *args, **kwargs)
        if not fired["done"]:
            fired["done"] = True
            # the block tip fetch completes while the viewer is still initializing
            self.mempool_manager.signal_block_tip_height_changed.emit(850_000)

    with main_window_context(test_config=test_config) as main_window:
        original_handler = UITx_Viewer._on_block_tip_height_changed

        def tracking_handler(self: UITx_Viewer, height: int) -> None:
            reevaluations.append(height)
            original_handler(self, height)

        with (
            patch.object(UITx_Viewer, "reload", reload_and_emit_tip),
            patch.object(UITx_Viewer, "_on_block_tip_height_changed", tracking_handler),
        ):
            main_window.signals.open_tx_like.emit(RAW_TX)
            QApplication.processEvents()

        assert fired["done"], "the initial reload was never run"
        assert reevaluations == [850_000]
