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

from types import SimpleNamespace

import bdkpython as bdk
from bitcoin_qr_tools.data import Data, DataType
from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QIcon, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QPushButton
from pytestqt.qtbot import QtBot

from bitcoin_safe.gui.qt.export_data import FileToolButton, QrToolButton, SyncChatToolButton
from bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer import UITx_Viewer
from bitcoin_safe.gui.qt.util import remember_theme_state
from bitcoin_safe.signals import SignalsMin
from tests.non_gui.test_psbt_util import p2wsh_psbt_0_1of1


def _solid_icon(color_name: str) -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color_name))
    return QIcon(pixmap)


def _icon_color(icon: QIcon) -> QColor:
    return icon.pixmap(16, 16).toImage().pixelColor(0, 0)


def test_file_toolbutton_refreshes_button_and_menu_icons_on_palette_change(qtbot: QtBot, monkeypatch) -> None:
    button = FileToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
    )
    qtbot.addWidget(button)

    refreshed_icon = _solid_icon("red")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.export_data.svg_tools.get_QIcon",
        lambda _icon_name: refreshed_icon,
    )

    button.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert _icon_color(button.icon()) == QColor("red")
    file_action = next(action for action in button._menu.actions() if action.text() == button.tr("File"))
    assert _icon_color(file_action.icon()) == QColor("red")


def test_qr_toolbutton_refreshes_icon_on_palette_change(qtbot: QtBot, loop_in_thread, monkeypatch) -> None:
    button = QrToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        signals_min=SignalsMin(),
        network=bdk.Network.REGTEST,
        loop_in_thread=loop_in_thread,
    )
    qtbot.addWidget(button)

    refreshed_icon = _solid_icon("green")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.export_data.svg_tools.get_QIcon",
        lambda _icon_name: refreshed_icon,
    )

    remember_theme_state(button)
    updated_palette = QPalette(button.palette())
    updated_palette.setColor(QPalette.ColorRole.WindowText, QColor("#55ff55"))
    button.setPalette(updated_palette)
    button.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert button.icon().cacheKey() == refreshed_icon.cacheKey()


def test_sync_chat_toolbutton_refreshes_icon_on_palette_change(qtbot: QtBot, monkeypatch) -> None:
    button = SyncChatToolButton(
        data=Data(p2wsh_psbt_0_1of1.extract_tx(), DataType.Tx, bdk.Network.REGTEST),
        network=bdk.Network.REGTEST,
        sync_client=None,
    )
    qtbot.addWidget(button)

    refreshed_icon = _solid_icon("blue")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.export_data.svg_tools.get_QIcon",
        lambda _icon_name: refreshed_icon,
    )

    button.changeEvent(QEvent(QEvent.Type.PaletteChange))

    assert _icon_color(button.icon()) == QColor("blue")


def test_tx_viewer_refresh_action_button_icons_updates_all_buttons(qapp: QApplication, monkeypatch) -> None:
    refreshed_icon = _solid_icon("magenta")
    monkeypatch.setattr(
        "bitcoin_safe.gui.qt.ui_tx.ui_tx_viewer.svg_tools.get_QIcon",
        lambda _icon_name: refreshed_icon,
    )

    viewer = SimpleNamespace(
        button_edit_tx=QPushButton(),
        button_cpfp_tx=QPushButton(),
        button_rbf=QPushButton(),
        button_back=QPushButton(),
        button_save_local_tx=QPushButton(),
        button_send=QPushButton(),
    )

    UITx_Viewer._refresh_action_button_icons(viewer)

    assert _icon_color(viewer.button_edit_tx.icon()) == QColor("magenta")
    assert _icon_color(viewer.button_cpfp_tx.icon()) == QColor("magenta")
    assert _icon_color(viewer.button_rbf.icon()) == QColor("magenta")
    assert _icon_color(viewer.button_back.icon()) == QColor("magenta")
    assert _icon_color(viewer.button_save_local_tx.icon()) == QColor("magenta")
    assert _icon_color(viewer.button_send.icon()) == QColor("magenta")
