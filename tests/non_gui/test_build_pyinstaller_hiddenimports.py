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

from tools.build_pyinstaller_hiddenimports import (
    EXTERNAL_PLUGIN_HIDDENIMPORTS,
    EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS,
    OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS,
)


def test_build_pyinstaller_hiddenimports_include_external_plugin_host_api() -> None:
    expected_modules = {
        "bitcoin_safe.plugin_framework.external_plugin_resources",
        "bitcoin_safe.plugin_framework.paid_plugin_client",
        "bitcoin_safe.plugin_framework.plugin_bundle",
        "bitcoin_safe.plugin_framework.plugin_conditions",
        "bitcoin_safe.plugin_framework.plugin_server",
        "bitcoin_safe.plugin_framework.subscription_manager",
        "bitcoin_safe.plugin_framework.subscription_price_lookup",
    }

    assert expected_modules.issubset(EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS)
    assert len(EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS) == len(set(EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS))


def test_build_pyinstaller_hiddenimports_include_official_external_plugin_modules() -> None:
    expected_modules = {
        "bitcoin_safe.gui.qt.amount_currency_selector",
        "bitcoin_safe.gui.qt.currency_converter",
        "bitcoin_safe.gui.qt.ui_tx.spinbox",
        "bitcoin_safe.gui.qt.category_manager.category_core",
        "bitcoin_safe.gui.qt.category_manager.category_list",
        "bitcoin_safe.gui.qt.category_manager.category_menu",
    }

    assert expected_modules.issubset(OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS)
    assert len(OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS) == len(set(OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS))


def test_build_pyinstaller_hiddenimports_merge_host_and_official_modules() -> None:
    assert set(EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS).issubset(EXTERNAL_PLUGIN_HIDDENIMPORTS)
    assert set(OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS).issubset(EXTERNAL_PLUGIN_HIDDENIMPORTS)
    assert len(EXTERNAL_PLUGIN_HIDDENIMPORTS) == len(set(EXTERNAL_PLUGIN_HIDDENIMPORTS))
