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


import inspect
import logging
from datetime import datetime

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.address_comparer import AddressComparer
from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.ui_tx import UITx_Viewer
from tests.gui.qt.test_setup_wallet import close_wallet, get_tab_with_title, save_wallet

from ...test_helpers import test_config  # type: ignore
from ...test_setup_bitcoin_core import Faucet, bitcoin_core, faucet  # type: ignore
from .test_helpers import (  # type: ignore
    CheckedDeletionContext,
    Shutter,
    close_wallet,
    do_modal_click,
    get_tab_with_title,
    get_widget_top_level,
    main_window_context,
    save_wallet,
    test_start_time,
)

logger = logging.getLogger(__name__)


@pytest.mark.marker_qt_2
def test_psbt_warning_poision(
    qapp: QApplication,
    qtbot: QtBot,
    test_start_time: datetime,
    test_config: UserConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:  # bitcoin_core: Path,
    frame = inspect.currentframe()
    assert frame
    shutter = Shutter(qtbot, name=f"{test_start_time.timestamp()}_{inspect.getframeinfo(frame).function    }")

    shutter.create_symlink(test_config=test_config)
    with main_window_context(test_config=test_config) as main_window:
        QTest.qWaitForWindowExposed(main_window)  # type: ignore  # This will wait until the window is fully exposed
        assert main_window.windowTitle() == "Bitcoin Safe - REGTEST"

        shutter.save(main_window)

        org_ADDRESS_SIMILARITY_THRESHOLD = AddressComparer.ADDRESS_SIMILARITY_THRESHOLD
        AddressComparer.ADDRESS_SIMILARITY_THRESHOLD = 32_000

        psbt = "cHNidP8BAKgBAAAAAcgPfvBnxr9qF0o5tGN7Yi700GJKITISfTB25evv/et7AQAAAAD9////A6APAAAAAAAAFgAUXCz4WFk4ANrLn8kusAPQ2+Ic0ZCgDwAAAAAAACIAIP5+mYK492G9BpTSXRVmlsINAPyeZ+BbswhLDxCS61v/JtmXAAAAAAAiACDYrIlFGPEykE16uVcbeRxB4aCyhbhitXY1kRc4GvpHtfMLAABPAQQ1h88EApdQj4AAAAI3TSBpfcsjErxWbW7+K4tU2p6/TnBriteYduNbUJ4O9wItTl11LzxH4f2/d0TTjLmN6zrPREFoE9yEg+S9AkX/qRSVryXvMAAAgAEAAIAAAACAAgAAgE8BBDWHzwQbRllDgAAAAkitfn+2yQwdQ8dXOXV6vO2Zso8C/2H+MtXw9ZjOtW1WAtJLqqIQmSaIaMWNj8lf7HaeNEncI+kU/ECkQ+KFjKmGFGFVKWQwAACAAQAAgAAAAIACAACAAAEA/VoBAQAAAAABAakvWHNzJ17xblA9QOL0EXRcUYAwL4qjZuq0ovU9ioHsAAAAAAD9////AkCcAAAAAAAAFgAUbY8H0Xk7T37O+Uz0G7jWzhzT2z+L+ZcAAAAAACIAIHQluxNKgjKW9D1pcYrVFUulolDSot2cB2+nUyyc5XK0BABHMEQCIAhwYcTRjfvFqv0Z9uUpI4ZWz42enHyGV1CCFiEUQ5WeAiBK0zCWUm1evI/OaK3Xx/eb2rkTOGtS42EbBLLv9u5oGwFIMEUCIQDd7J3nbwYAs24cRvDjK7nadvF4OcadRbwivFzwVzn0VQIgKMykT3UdEJV2vSPwq4LdyMogPulVaPYgwHgYeJXiapoBR1IhAjdvV2a9+BkCJM/rKvWQfBgp2AvgfUDFFZkWkSXrduuqIQKURqBDnTV3cMVo9wuihKiT3YEsJFKW1sT4U6/rhzwCklKu8wsAAAEBK4v5lwAAAAAAIgAgdCW7E0qCMpb0PWlxitUVS6WiUNKi3ZwHb6dTLJzlcrQBBUdSIQKG5xW3iX3O0l5O7NasvqoxCpW63kvjxQTt+o4Qhj1mECECqav5dMbFkm0qsC0ADq0s5CDRXj2Jrut4L4US/4W4TUpSriIGAobnFbeJfc7SXk7s1qy+qjEKlbreS+PFBO36jhCGPWYQHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAAAAAAiBgKpq/l0xsWSbSqwLQAOrSzkINFePYmu63gvhRL/hbhNShxhVSlkMAAAgAEAAIAAAACAAgAAgAEAAAAAAAAAAAABAUdSIQLZyBMiiLsHGtSx2nyq9ABzY2Yhu901nOxzXuEMaw0jNSEDMFDbnxOXNQTw+yBcmixX/oY5qVDF/J0LedWagKWU2bVSriICAtnIEyKIuwca1LHafKr0AHNjZiG73TWc7HNe4QxrDSM1HJWvJe8wAACAAQAAgAAAAIACAACAAAAAAAEAAAAiAgMwUNufE5c1BPD7IFyaLFf+hjmpUMX8nQt51ZqApZTZtRxhVSlkMAAAgAEAAIAAAACAAgAAgAAAAAABAAAAAAEBR1IhAuUSbT2a+i0iwnGfhNMFh2aPA9s5MgYjfVA1zf5Gky6fIQMeMhD8WBfUF++O4Yw1pWTzfNT3GmIfHkJcRilAfrcR1VKuIgIC5RJtPZr6LSLCcZ+E0wWHZo8D2zkyBiN9UDXN/kaTLp8cYVUpZDAAAIABAACAAAAAgAIAAIABAAAAAQAAACICAx4yEPxYF9QX747hjDWlZPN81PcaYh8eQlxGKUB+txHVHJWvJe8wAACAAQAAgAAAAIACAACAAQAAAAEAAAAA"
        main_window.open_tx_like_in_tab(psbt)
        shutter.save(main_window)

        i = main_window.get_tab_with_title(main_window.tab_wallets, "PSBT 8109...a65a")
        assert i is not None
        tab = main_window.tab_wallets.widget(i)
        assert isinstance(tab, UITx_Viewer)

        assert tab.address_poisoning_warning_bar.isVisible()
        assert (
            "Warning! This transaction involves deceptively similar addresses. It may be an address poisoning attack."
            in tab.address_poisoning_warning_bar.textLabel.text()
        )
        assert (
            "bcrt1<u>q</u>lelfnq4c7asm6p556fw32e5kcgxsply7vls9hvcgfv83pyhtt0l<u>s</u><u>c</u><u>s</u><u>6</u><u>q</u><u>a</u><u>0</u>"
            in tab.address_poisoning_warning_bar.textLabel.text()
        )
        assert (
            "bcrt1<u>q</u>tsk0skze8qqd4juleyhtqq7sm03pe5v<u>s</u><u>7</u><u>s</u><u>6</u><u>q</u><u>a</u><u>0</u>"
            in tab.address_poisoning_warning_bar.textLabel.text()
        )

        # end
        shutter.save(main_window)
        AddressComparer.ADDRESS_SIMILARITY_THRESHOLD = org_ADDRESS_SIMILARITY_THRESHOLD
