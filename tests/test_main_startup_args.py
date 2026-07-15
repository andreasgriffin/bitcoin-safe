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

import logging
from unittest.mock import Mock, patch

import bdkpython as bdk
from _pytest.logging import LogCaptureFixture

import bitcoin_safe.__main__ as app_main


def test_parse_args_keeps_valid_network() -> None:
    """Test valid network values are preserved."""
    startup_args = app_main.parse_args(["--network", "bitcoin"])

    assert startup_args.network == bdk.Network.BITCOIN


def test_parse_args_keeps_testnet4_network() -> None:
    """Test testnet4 stays supported."""
    startup_args = app_main.parse_args(["--network", "testnet4"])

    assert startup_args.network == bdk.Network.TESTNET4


def test_parse_args_ignores_invalid_network(caplog: LogCaptureFixture) -> None:
    """Test invalid network values are ignored with a warning."""
    with caplog.at_level(logging.WARNING, logger=app_main.__name__):
        startup_args = app_main.parse_args(["--network", "main"])

    assert startup_args.network is None
    assert "Ignoring invalid --network value 'main'" in caplog.text
    assert "bitcoin, regtest, signet, testnet, testnet4" in caplog.text


def test_parse_args_ignores_unknown_flags(caplog: LogCaptureFixture) -> None:
    """Test unknown flags are logged and ignored."""
    with caplog.at_level(logging.WARNING, logger=app_main.__name__):
        startup_args = app_main.parse_args(["--profile", "--foo", "wallet.psbt"])

    assert startup_args.profile is True
    assert startup_args.open_files_at_startup == ["wallet.psbt"]
    assert "Ignoring unknown startup arguments" in caplog.text
    assert "--foo" in caplog.text


def test_parse_args_keeps_file_arguments() -> None:
    """Test positional startup files are preserved."""
    startup_args = app_main.parse_args(["file1.wallet", "file2.psbt"])

    assert startup_args.open_files_at_startup == ["file1.wallet", "file2.psbt"]


def test_main_uses_sanitized_network() -> None:
    """Test main forwards the sanitized network to MainWindow."""
    startup_args = app_main.parse_args(["--network", "main", "wallet.psbt"])
    app = Mock()
    window = Mock()

    with (
        patch.object(app_main, "QApplication", return_value=app),
        patch.object(app_main, "check_compatibility"),
        patch.object(app_main, "is_gnome_dark_mode", return_value=False),
        patch.object(app_main, "set_dark_palette"),
        patch.object(app_main, "MainWindow", return_value=window) as main_window_cls,
    ):
        app_main.main(startup_args)

    main_window_cls.assert_called_once_with(network=None, open_files_at_startup=["wallet.psbt"])
    window.show.assert_called_once()
    app.exec.assert_called_once()
