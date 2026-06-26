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

from PyQt6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from bitcoin_safe.plugin_framework.plugin_source_widget import AddPluginSourceDialog


def test_add_plugin_source_dialog_autofills_display_name(qapp: QApplication, qtbot: QtBot) -> None:
    dialog = AddPluginSourceDialog()
    qtbot.addWidget(dialog)

    dialog.manifest_url_edit.setText("https://github.com/andreasgriffin/bitcoin-safe-plugins")

    assert dialog.display_name_edit.text() == "GitHub bitcoin-safe-plugins"


def test_add_plugin_source_dialog_keeps_manual_display_name(qapp: QApplication, qtbot: QtBot) -> None:
    dialog = AddPluginSourceDialog()
    qtbot.addWidget(dialog)

    dialog.manifest_url_edit.setText("https://github.com/andreasgriffin/bitcoin-safe-plugins")
    dialog.display_name_edit.setText("My Plugin Source")
    dialog.manifest_url_edit.setText("https://github.com/andreasgriffin/plugins")

    assert dialog.display_name_edit.text() == "My Plugin Source"


def test_add_plugin_source_dialog_updates_auto_display_name_when_url_changes(
    qapp: QApplication, qtbot: QtBot
) -> None:
    dialog = AddPluginSourceDialog()
    qtbot.addWidget(dialog)

    dialog.manifest_url_edit.setText("https://github.com/andreasgriffin/bitcoin-safe-plugins")
    dialog.manifest_url_edit.setText("https://dummy.example/andreasgriffin/plugins")

    assert dialog.display_name_edit.text() == "Gitea plugins"
