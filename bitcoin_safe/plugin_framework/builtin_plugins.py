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

from pathlib import Path
from typing import cast

import bitcoin_safe.plugin_framework.plugins as plugin_directory
from bitcoin_safe.plugin_framework.plugin_bundle import (
    PluginBundleModule,
    StaticPluginBundleRegistration,
    ensure_plugin_import_path,
    register_static_plugin_bundle,
)
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugins.business_plan import (
    plugin_bundle as business_plan_plugin_bundle,
)
from bitcoin_safe.plugin_framework.plugins.chat_sync import (
    plugin_bundle as chat_sync_plugin_bundle,
)
from bitcoin_safe.plugin_framework.plugins.walletgraph import (
    plugin_bundle as walletgraph_plugin_bundle,
)

# ensure the "plugins" directory is in the path
ensure_plugin_import_path(Path(plugin_directory.__file__).resolve().parent)


# Development plugins can be enabled with a symlink in the repository root, for example:
# `ln -s ../bitcoin-safe-plugins/notification_broadcaster notification_broadcaster`
# Then add a static import plus one tuple entry here:
# `from notification_broadcaster import plugin_bundle as notification_broadcaster_plugin_bundle`
# `register_static_plugin_bundle(notification_broadcaster_plugin_bundle),`


def _bundle_is_available(module: PluginBundleModule) -> bool:
    return any(client_cls.IS_AVAILABLE for client_cls in module.PLUGIN_CLIENTS)


BUILTIN_PLUGIN_BUNDLES: tuple[StaticPluginBundleRegistration, ...] = tuple(
    register_static_plugin_bundle(module)
    for module in (
        cast(PluginBundleModule, business_plan_plugin_bundle),
        cast(PluginBundleModule, chat_sync_plugin_bundle),
        cast(PluginBundleModule, walletgraph_plugin_bundle),
    )
    if _bundle_is_available(module)
)

BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS: dict[type[PluginClient], StaticPluginBundleRegistration] = {
    client_cls: bundle for bundle in BUILTIN_PLUGIN_BUNDLES for client_cls in bundle.module.PLUGIN_CLIENTS
}

BUILTIN_PLUGIN_CLIENT_CLASSES: tuple[type[PluginClient], ...] = tuple(BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS)
AUTO_ALLOW_BUILTIN_PLUGIN_CLIENT_CLASSES: tuple[type[PluginClient], ...] = tuple(
    dict.fromkeys(
        client_cls for bundle in BUILTIN_PLUGIN_BUNDLES for client_cls in bundle.auto_allow_plugin_clients
    )
)
