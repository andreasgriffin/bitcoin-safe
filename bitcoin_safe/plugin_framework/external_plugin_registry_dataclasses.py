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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bitcoin_safe_lib.storage import SaveAllClass, filtered_for_init
from btcpay_tools.config import BTCPayConfig

from bitcoin_safe.plugin_framework.plugin_bundle import RuntimePluginBundle
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_identity import PluginSource as PluginClientSource

logger = logging.getLogger(__name__)

SOURCE_MANIFEST_FILENAME = "source.toml"
SOURCE_SIGNATURE_SUFFIX = ".asc"
SUPPORTED_PLUGIN_API_VERSION = "1"


class ExternalPluginError(Exception):
    pass


@dataclass(frozen=True)
class PluginSourceAuthConfig(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {**SaveAllClass.known_classes}
    kind: str = "none"
    bearer_token: str | None = None

    def headers(self) -> dict[str, str]:
        if self.kind == "bearer" and self.bearer_token:
            return {"Authorization": f"Bearer {self.bearer_token}"}
        return {}


@dataclass(frozen=True)
class PluginSource(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {
        **SaveAllClass.known_classes,
        PluginSourceAuthConfig.__name__: PluginSourceAuthConfig,
    }
    source_id: str
    display_name: str
    manifest_url: str
    pinned_source_public_key: str
    auth_config: PluginSourceAuthConfig
    enabled: bool = True
    last_seen_source_serial: int = 0
    last_checked_at: str | None = None
    last_error: str | None = None

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=None)
        raw_auth_config = dct.get("auth_config")
        if isinstance(raw_auth_config, dict):
            dct["auth_config"] = PluginSourceAuthConfig.from_dump(raw_auth_config)
        return cls(**filtered_for_init(dct, cls))


@dataclass(frozen=True)
class ExternalPluginCatalogEntry(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {**SaveAllClass.known_classes, BTCPayConfig.__name__: BTCPayConfig}
    source_id: str
    source_display_name: str
    bundle_id: str
    version: str
    display_name: str
    description: str
    provider: str
    entrypoint: str
    plugin_api_version: str
    app_version_specifier: str
    folder_hash: str
    release_ref: str
    btcpay_config: BTCPayConfig | None = None
    installed_version: str | None = None
    installed_folder_hash: str | None = None
    update_available: bool = False

    @property
    def path(self) -> str:
        return f"plugins/{self.bundle_id}"

    def dump(self) -> dict[str, Any]:
        d = super().dump()
        d.update(self.__dict__.copy())
        d.pop("installed_version", None)
        d.pop("installed_folder_hash", None)
        d.pop("update_available", None)
        if self.btcpay_config is not None:
            d["btcpay_config"] = self.btcpay_config.model_dump(mode="json", by_alias=True)
        return d

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=None)
        raw_btcpay_config = dct.get("btcpay_config")
        if isinstance(raw_btcpay_config, dict):
            dct["btcpay_config"] = BTCPayConfig.model_validate(raw_btcpay_config)
        return cls(**filtered_for_init(dct, cls))


@dataclass(frozen=True)
class VerifiedPluginSourceManifest(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {
        **SaveAllClass.known_classes,
        ExternalPluginCatalogEntry.__name__: ExternalPluginCatalogEntry,
    }
    source_id: str
    display_name: str
    source_serial: int
    signer_fingerprint: str
    manifest_url: str
    plugins: tuple[ExternalPluginCatalogEntry, ...]

    def plugin_by_bundle_id(self, bundle_id: str) -> ExternalPluginCatalogEntry | None:
        for plugin in self.plugins:
            if plugin.bundle_id == bundle_id:
                return plugin
        return None

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=None)
        plugins: list[ExternalPluginCatalogEntry] = []
        for raw_plugin in dct.get("plugins", []):
            if isinstance(raw_plugin, ExternalPluginCatalogEntry):
                plugins.append(raw_plugin)
            elif isinstance(raw_plugin, dict):
                plugins.append(ExternalPluginCatalogEntry.from_dump(raw_plugin))
        dct["plugins"] = tuple(plugins)
        return cls(**filtered_for_init(dct, cls))


@dataclass(frozen=True)
class InstalledSourcePluginMetadata(SaveAllClass):
    VERSION = "0.0.1"
    known_classes = {**SaveAllClass.known_classes}
    bundle_id: str
    source_id: str
    version: str
    folder_hash: str
    installed_at: str
    trusted_auto_allow_signer: bool
    verified_signer_fingerprint: str
    last_verification_ok: bool = True
    last_verification_error: str | None = None


@dataclass(frozen=True)
class VerifiedExternalPluginBundle:
    bundle_id: str
    source_id: str
    version: str
    plugin_dir: Path
    folder_hash: str
    verified_signer_fingerprint: str
    trusted_auto_allow_signer: bool
    runtime_bundle: RuntimePluginBundle

    @property
    def class_names(self) -> set[str]:
        return {client_cls.__name__ for client_cls in self.runtime_bundle.client_classes}

    @property
    def plugin_ids(self) -> set[str]:
        return {
            PluginClient.build_plugin_id(
                plugin_source=PluginClientSource.EXTERNAL,
                plugin_bundle_id=self.bundle_id,
                class_name=client_cls.__name__,
            )
            for client_cls in self.runtime_bundle.client_classes
        }
