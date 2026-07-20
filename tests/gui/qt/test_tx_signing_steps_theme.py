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

from unittest.mock import Mock

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.tx_signing_steps import SigningDevice, TxSigningDeviceCard
from bitcoin_safe.hardware_signers import HardwareSigners


def test_tx_signing_device_card_refreshes_theme_dependent_ui_on_palette_change(qtbot) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = QPalette(app.palette())
    light_palette = QPalette(original_palette)
    light_palette.setColor(QPalette.ColorRole.Window, QColor("#efefef"))
    light_palette.setColor(QPalette.ColorRole.WindowText, QColor("#101010"))
    light_palette.setColor(QPalette.ColorRole.Text, QColor("#101010"))
    light_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#101010"))
    light_palette.setColor(QPalette.ColorRole.Dark, QColor("#101010"))
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#111111"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f5f5f5"))
    dark_palette.setColor(QPalette.ColorRole.Dark, QColor("#f5f5f5"))

    app.setPalette(light_palette)
    card = TxSigningDeviceCard(
        device=SigningDevice(
            fingerprint="44250C36",
            label="Signer 1",
            hardware_signer=HardwareSigners.generic,
            wallet_ids=["demo-public-regtest"],
        ),
        signature_importers=[],
        psbt=Mock(),
        network=Mock(),
        wallet_functions=Mock(),
        loop_in_thread=Mock(),
    )
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)

    try:
        light_background = card.background_color
        assert isinstance(light_background, QColor)
        light_title_color = card.header_title.palette().color(card.header_title.foregroundRole())
        light_subtitle_color = card.header_subtitle.palette().color(card.header_subtitle.foregroundRole())
        light_icon = card.header_icon.pixmap()
        assert light_icon is not None and not light_icon.isNull()
        light_icon_image = light_icon.toImage()

        app.setPalette(dark_palette)
        QApplication.sendEvent(card, QEvent(QEvent.Type.ApplicationPaletteChange))
        qtbot.waitUntil(
            lambda: (
                isinstance(card.background_color, QColor)
                and card.background_color.name() != light_background.name()
            ),
            timeout=5000,
        )

        assert isinstance(card.background_color, QColor)
        assert card.background_color.name() == "#111111"
        assert card.header_title.palette().color(card.header_title.foregroundRole()).name() == "#f5f5f5"
        assert card.header_subtitle.palette().color(card.header_subtitle.foregroundRole()).name() != (
            light_subtitle_color.name()
        )

        dark_icon = card.header_icon.pixmap()
        assert dark_icon is not None and not dark_icon.isNull()
        assert dark_icon.toImage() != light_icon_image
        assert card.header_title.palette().color(card.header_title.foregroundRole()) != light_title_color
    finally:
        app.setPalette(original_palette)
        QApplication.sendEvent(card, QEvent(QEvent.Type.ApplicationPaletteChange))
        card.close()
