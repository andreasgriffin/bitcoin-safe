# Current official remote plugins import these modules from the packaged app.
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
# Listing them here keeps the macOS app and Windows exe builds in sync.


"""PyInstaller hidden imports needed by packaged desktop builds.

External plugins are loaded dynamically from the user config directory, so
PyInstaller cannot discover every host-side module they import while analyzing
the main application entrypoint.
"""

EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS: tuple[str, ...] = (
    "bitcoin_safe.plugin_framework.external_plugin_resources",
    "bitcoin_safe.plugin_framework.paid_plugin_client",
    "bitcoin_safe.plugin_framework.plugin_bundle",
    "bitcoin_safe.plugin_framework.plugin_conditions",
    "bitcoin_safe.plugin_framework.plugin_server",
    "bitcoin_safe.plugin_framework.subscription_manager",
    "bitcoin_safe.plugin_framework.subscription_price_lookup",
)

OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS: tuple[str, ...] = (
    "bitcoin_safe.category_info",
    "bitcoin_safe.config",
    "bitcoin_safe.constants",
    "bitcoin_safe.fx",
    "bitcoin_safe.gui.qt.amount_currency_selector",
    "bitcoin_safe.gui.qt.category_manager.category_core",
    "bitcoin_safe.gui.qt.category_manager.category_list",
    "bitcoin_safe.gui.qt.category_manager.category_menu",
    "bitcoin_safe.gui.qt.currency_combobox",
    "bitcoin_safe.gui.qt.currency_converter",
    "bitcoin_safe.gui.qt.gpg_verify",
    "bitcoin_safe.gui.qt.my_treeview",
    "bitcoin_safe.gui.qt.notification_bar",
    "bitcoin_safe.gui.qt.sidebar.sidebar_tree",
    "bitcoin_safe.gui.qt.sign_message",
    "bitcoin_safe.gui.qt.ui_tx.base_column",
    "bitcoin_safe.gui.qt.ui_tx.spinbox",
    "bitcoin_safe.gui.qt.util",
    "bitcoin_safe.gui.qt.wrappers",
    "bitcoin_safe.i18n",
    "bitcoin_safe.pythonbdk_types",
    "bitcoin_safe.signature_manager",
    "bitcoin_safe.signals",
    "bitcoin_safe.tx",
    "bitcoin_safe.util",
    "bitcoin_safe.wallet",
)

EXTERNAL_PLUGIN_HIDDENIMPORTS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *EXTERNAL_PLUGIN_HOST_HIDDENIMPORTS,
            *OFFICIAL_EXTERNAL_PLUGIN_HIDDENIMPORTS,
        )
    )
)
