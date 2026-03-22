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

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.gui.qt.language_chooser import LanguageChooser

from ...helpers import TestConfig


class DummySignals(QObject):
    language_switch = pyqtSignal()
    currency_switch = pyqtSignal()


def make_chooser(config: TestConfig) -> LanguageChooser:
    signals = DummySignals()
    return LanguageChooser(
        config=config,
        signals_language_switch=[signals.language_switch],
        signals_currency_switch=signals.currency_switch,
        parent=None,
    )


def test_choose_startup_language_uses_exact_locale(
    qapp: QApplication, test_config_main_chain: TestConfig
) -> None:
    chooser = make_chooser(test_config_main_chain)

    assert chooser.find_matching_language_code("de_DE", chooser.get_languages()) == "de_DE"


def test_get_os_language_code_prefers_ui_language(
    monkeypatch, qapp: QApplication, test_config_main_chain: TestConfig
) -> None:
    chooser = make_chooser(test_config_main_chain)

    class FakeLocale:
        def uiLanguages(self) -> list[str]:
            return ["de-DE", "en-US"]

        def name(self) -> str:
            return "en_US"

    monkeypatch.setattr("bitcoin_safe.gui.qt.language_chooser.QLocale.system", lambda: FakeLocale())

    assert chooser.get_os_language_code() == "de_DE"


def test_choose_startup_language_uses_same_language_fallback(
    monkeypatch, qapp: QApplication, test_config_main_chain: TestConfig
) -> None:
    chooser = make_chooser(test_config_main_chain)
    monkeypatch.setattr(chooser, "get_os_language_code", lambda: "de_AT")
    dialog_called = False

    def fail_dialog(_parent) -> str:
        nonlocal dialog_called
        dialog_called = True
        return "en_US"

    monkeypatch.setattr(chooser, "dialog_choose_language", fail_dialog)

    assert chooser.choose_startup_language(None) == "de_DE"
    assert dialog_called is False


def test_choose_startup_language_opens_dialog_when_language_is_unavailable(
    monkeypatch, qapp: QApplication, test_config_main_chain: TestConfig
) -> None:
    chooser = make_chooser(test_config_main_chain)
    monkeypatch.setattr(chooser, "get_os_language_code", lambda: "nl_NL")
    dialog_called = False

    def choose_dialog(_parent) -> str:
        nonlocal dialog_called
        dialog_called = True
        return "fr_FR"

    monkeypatch.setattr(chooser, "dialog_choose_language", choose_dialog)

    assert chooser.choose_startup_language(None) == "fr_FR"
    assert dialog_called is True
