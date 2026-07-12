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

import inspect
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtGui import QColor, QImage, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.pythonbdk_types import Balance
from bitcoin_safe.signals import UpdateFilter, UpdateFilterReason
from bitcoin_safe.wallet import Wallet

from ...helpers import TestConfig
from .helpers import Shutter, main_window_context


def _images_differ(left: QImage, right: QImage) -> bool:
    if left.size() != right.size():
        return True

    for y in range(left.height()):
        for x in range(left.width()):
            if left.pixel(x, y) != right.pixel(x, y):
                return True
    return False


def _build_dark_palette(original_palette: QPalette) -> QPalette:
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#111111"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#181818"))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#222222"))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.Button, QColor("#202020"))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f5f5f5"))
    return dark_palette


def _build_light_palette() -> QPalette:
    light_palette = QPalette()
    light_palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    light_palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f2f2f2"))
    light_palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    light_palette.setColor(QPalette.ColorRole.Button, QColor("#f0f0f0"))
    light_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
    return light_palette


def _stub_wallet_balance_queries(monkeypatch) -> None:
    """Keep palette-switch tests focused on UI refresh instead of backend balance calls."""
    monkeypatch.setattr(Wallet, "get_balance", lambda self: Balance())


def test_wallet_details_screen_rethemes_keystore_card_on_palette_change(
    qapp: QApplication,
    qtbot: QtBot,
    monkeypatch,
    mytest_start_time: datetime,
    test_config_main_chain: TestConfig,
    wallet_file: str = "bacon.wallet",
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config_main_chain)
    original_palette = QPalette(qapp.palette())
    _stub_wallet_balance_queries(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore[arg-type]

        temp_wallet = Path(tempfile.mkdtemp()) / wallet_file
        shutil.copy(str(Path("tests") / "data" / wallet_file), str(temp_wallet))

        qt_wallet = main_window.open_wallet(str(temp_wallet))
        assert qt_wallet is not None
        qt_wallet.settings_node.select()
        qtbot.wait(50)

        key_store_ui = next(iter(qt_wallet.wallet_descriptor_ui.keystore_uis.getAllTabData().values()))

        light_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
        light_image = QImage(str(light_path))
        light_background = key_store_ui.background_color.name()

        try:
            qapp.setPalette(_build_dark_palette(original_palette))
            qtbot.waitUntil(
                lambda: key_store_ui.background_color.name() != light_background,
                timeout=5000,
            )
            dark_background = key_store_ui.background_color.name()
            dark_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
            dark_image = QImage(str(dark_path))
        finally:
            qapp.setPalette(original_palette)
            qtbot.wait(10)

        assert _images_differ(light_image, dark_image)
        assert dark_background != light_background


def test_wallet_tabs_retheme_on_palette_change(
    qapp: QApplication,
    qtbot: QtBot,
    monkeypatch,
    mytest_start_time: datetime,
    test_config_main_chain: TestConfig,
    wallet_file: str = "bacon.wallet",
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config_main_chain)
    original_palette = QPalette(qapp.palette())
    _stub_wallet_balance_queries(monkeypatch)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore[arg-type]

        temp_wallet = Path(tempfile.mkdtemp()) / wallet_file
        shutil.copy(str(Path("tests") / "data" / wallet_file), str(temp_wallet))

        qt_wallet = main_window.open_wallet(str(temp_wallet))
        assert qt_wallet is not None
        qtbot.wait(50)

        def current_recipient_widget():
            return qt_wallet.uitx_creator.column_recipients.recipients.get_recipient_group_boxes()[
                0
            ].recipient_widget

        descriptor_edit = qt_wallet.wallet_descriptor_ui.edit_descriptor.edit.input_field
        tab_nodes = {
            "history": qt_wallet.hist_node,
            "addresses": qt_wallet.address_node,
            "send": qt_wallet.send_node,
            "details": qt_wallet.settings_node,
        }
        if plugins_node := qt_wallet.get_plugins_node():
            tab_nodes["plugins"] = plugins_node

        light_images: dict[str, QImage] = {}
        light_descriptor_base = descriptor_edit.palette().color(QPalette.ColorRole.Base).name()
        qt_wallet.send_node.select()
        qtbot.wait(50)
        light_recipient_widget = current_recipient_widget()
        light_label_base = (
            light_recipient_widget.label_line_edit.label_edit.palette().color(QPalette.ColorRole.Base).name()
        )
        light_category_base = (
            light_recipient_widget.label_line_edit.category_edit.palette()
            .color(QPalette.ColorRole.Base)
            .name()
        )
        light_fiat_base = light_recipient_widget.fiat_spin_box.palette().color(QPalette.ColorRole.Base).name()

        for name, node in tab_nodes.items():
            node.select()
            qtbot.wait(50)
            light_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
            light_images[name] = QImage(str(light_path))

        try:
            qapp.setPalette(_build_dark_palette(original_palette))
            qtbot.waitUntil(
                lambda: (
                    descriptor_edit.palette().color(QPalette.ColorRole.Base).name() != light_descriptor_base
                ),
                timeout=5000,
            )
            qt_wallet.send_node.select()
            qtbot.wait(50)
            qtbot.waitUntil(
                lambda: (
                    current_recipient_widget()
                    .label_line_edit.label_edit.palette()
                    .color(QPalette.ColorRole.Base)
                    .name()
                    != light_label_base
                ),
                timeout=5000,
            )

            dark_images: dict[str, QImage] = {}
            for name, node in tab_nodes.items():
                node.select()
                qtbot.wait(50)
                dark_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
                dark_images[name] = QImage(str(dark_path))

            dark_descriptor_base = descriptor_edit.palette().color(QPalette.ColorRole.Base).name()
            dark_recipient_widget = current_recipient_widget()
            dark_label_base = (
                dark_recipient_widget.label_line_edit.label_edit.palette()
                .color(QPalette.ColorRole.Base)
                .name()
            )
            dark_category_base = (
                dark_recipient_widget.label_line_edit.category_edit.palette()
                .color(QPalette.ColorRole.Base)
                .name()
            )
            dark_fiat_base = (
                dark_recipient_widget.fiat_spin_box.palette().color(QPalette.ColorRole.Base).name()
            )
        finally:
            qapp.setPalette(original_palette)
            qtbot.wait(10)

        for name in tab_nodes:
            assert _images_differ(light_images[name], dark_images[name]), name

        assert dark_descriptor_base != light_descriptor_base
        assert dark_label_base != light_label_base
        assert dark_category_base != light_category_base
        assert dark_fiat_base != light_fiat_base


def test_welcome_and_wizard_retheme_on_palette_change(
    qapp: QApplication,
    qtbot: QtBot,
    monkeypatch,
    mytest_start_time: datetime,
    test_config: TestConfig,
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config)
    original_palette = QPalette(qapp.palette())
    _stub_wallet_balance_queries(monkeypatch)

    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore[arg-type]

        qtbot.waitUntil(
            lambda: bool(main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)),
            timeout=10000,
        )  # type: ignore[arg-type]
        welcome_node = main_window.tab_wallets.root.findNodeByWidget(main_window.welcome_screen)
        assert welcome_node is not None
        welcome_node.select()
        qtbot.wait(50)
        welcome_light_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
        welcome_light_image = QImage(str(welcome_light_path))
        welcome_light_background = main_window.welcome_screen.card_connect_devices.background_color.name()

        qt_protowallet = main_window.open_qtprotowallet_setup(
            m_of_n=(2, 3),
            wallet_id="wizard_probe",
            show_tutorial=True,
        )
        assert qt_protowallet is not None
        assert qt_protowallet.wizard is not None
        wizard = qt_protowallet.wizard
        wizard.node.select()
        qtbot.wait(50)
        wizard_light_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
        wizard_light_image = QImage(str(wizard_light_path))

        try:
            qapp.setPalette(_build_dark_palette(original_palette))
            qtbot.waitUntil(
                lambda: (
                    main_window.welcome_screen.card_connect_devices.background_color.name()
                    != welcome_light_background
                ),
                timeout=5000,
            )

            welcome_node.select()
            qtbot.wait(50)
            welcome_dark_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
            welcome_dark_image = QImage(str(welcome_dark_path))

            wizard.node.select()
            qtbot.wait(50)
            wizard_dark_path = shutter.save_screenshot(main_window, qtbot, shutter.name)
            wizard_dark_image = QImage(str(wizard_dark_path))
        finally:
            qapp.setPalette(original_palette)
            qtbot.wait(10)

        assert _images_differ(welcome_light_image, welcome_dark_image)
        assert _images_differ(wizard_light_image, wizard_dark_image)


def test_hist_list_category_colors_retheme_on_palette_change(
    qapp: QApplication,
    qtbot: QtBot,
    monkeypatch,
    mytest_start_time: datetime,
    test_config_main_chain: TestConfig,
    wallet_file: str = "bacon.wallet",
) -> None:
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{mytest_start_time.timestamp()}_{inspect.getframeinfo(frame).function}")

    shutter.create_symlink(test_config=test_config_main_chain)
    original_palette = QPalette(qapp.palette())
    _stub_wallet_balance_queries(monkeypatch)
    light_palette = _build_light_palette()
    dark_palette = _build_dark_palette(light_palette)

    with main_window_context(test_config=test_config_main_chain) as main_window:
        QTest.qWaitForWindowExposed(main_window, timeout=10000)  # type: ignore[arg-type]

        temp_wallet = Path(tempfile.mkdtemp()) / wallet_file
        shutil.copy(str(Path("tests") / "data" / wallet_file), str(temp_wallet))

        qt_wallet = main_window.open_wallet(str(temp_wallet))
        assert qt_wallet is not None
        qt_wallet.hist_node.select()
        qtbot.wait(50)

        hist_list = qt_wallet.history_list_with_toolbar.hist_list
        target_row: int | None = None

        qapp.setPalette(light_palette)
        qtbot.wait(50)

        for row in range(hist_list._source_model.rowCount()):
            txid_item = hist_list._source_model.item(row, hist_list.Columns.TXID)
            assert txid_item is not None
            wallet = hist_list.get_wallet(txid=txid_item.text())
            if not wallet:
                continue
            fulltxdetail = wallet.get_dict_fulltxdetail().get(txid_item.text())
            if not fulltxdetail:
                continue
            involved_addresses = list(fulltxdetail.involved_addresses())
            if not involved_addresses:
                continue

            category = "ThemeProbe"
            wallet.labels.set_addr_category(involved_addresses[0], category, timestamp="now")
            hist_list.update_with_filter(
                UpdateFilter(
                    addresses=[involved_addresses[0]],
                    categories=[category],
                    reason=UpdateFilterReason.CategoryChange,
                )
            )
            target_row = row
            break

        assert target_row is not None

        def current_category_background() -> str:
            item = hist_list._source_model.item(target_row, hist_list.Columns.CATEGORIES)
            assert item is not None
            return item.background().color().name()

        light_category_background = current_category_background()

        try:
            qapp.setPalette(dark_palette)
            qtbot.waitUntil(
                lambda: current_category_background() != light_category_background,
                timeout=5000,
            )
            dark_category_background = current_category_background()
        finally:
            qapp.setPalette(original_palette)
            qtbot.wait(10)

        assert dark_category_background != light_category_background
