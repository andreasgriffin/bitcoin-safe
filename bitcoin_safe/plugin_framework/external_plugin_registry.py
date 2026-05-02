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

import importlib
import importlib.util
import json
import logging
import shutil
import sys
import tempfile
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.parse import unquote, urljoin, urlparse

import pgpy
import tomllib  # pyright: ignore[reportMissingImports]
from bitcoin_safe_lib.storage import BaseSaveableClass
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from bitcoin_safe import __version__
from bitcoin_safe.config import UserConfig
from bitcoin_safe.network_utils import ProxyInfo, fetch_bytes
from bitcoin_safe.plugin_framework.external_plugin_registry_dataclasses import (
    SOURCE_MANIFEST_FILENAME,
    SOURCE_SIGNATURE_SUFFIX,
    SUPPORTED_PLUGIN_API_VERSION,
    ExternalPluginCatalogEntry,
    ExternalPluginError,
    InstalledSourcePluginMetadata,
    PluginSource,
    PluginSourceAuthConfig,
    VerifiedExternalPluginBundle,
    VerifiedPluginSourceManifest,
)
from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
from bitcoin_safe.plugin_framework.plugin_bundle import (
    PluginBundleModule,
    PluginRuntimeContext,
    normalize_runtime_plugin_bundle,
    plugin_bundle_client_classes,
)
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_source_hash import compute_plugin_folder_hash
from bitcoin_safe.plugin_framework.plugin_source_models import (
    PLUGIN_PYPROJECT_FILENAME,
    PluginMetadataModel,
    PluginSourceModelError,
    SourceManifestModel,
    parse_plugin_pyproject,
    parse_source_manifest,
    resolve_plugin_metadata_path,
)
from bitcoin_safe.signature_manager import KnownGPGKeys, SignatureVerifyer, SimpleGPGKey

logger = logging.getLogger(__name__)


class ExternalPluginRegistry(BaseSaveableClass):
    VERSION = "0.0.1"
    REPOSITORY_FILENAME = "plugin-repository.json"
    STARTUP_SOURCE_REFRESH_COOLDOWN = timedelta(hours=1)
    _loaded_plugin_dirs: set[Path] = set()
    known_classes = {
        **BaseSaveableClass.known_classes,
        PluginSourceAuthConfig.__name__: PluginSourceAuthConfig,
        PluginSource.__name__: PluginSource,
        ExternalPluginCatalogEntry.__name__: ExternalPluginCatalogEntry,
        VerifiedPluginSourceManifest.__name__: VerifiedPluginSourceManifest,
        InstalledSourcePluginMetadata.__name__: InstalledSourcePluginMetadata,
    }
    trusted_auto_allow_signers: tuple[SimpleGPGKey, ...] = (KnownGPGKeys.andreasgriffin,)

    def __init__(
        self,
        config: UserConfig | PluginRuntimeContext,
        sources: dict[str, PluginSource] | None = None,
        source_catalogs: dict[str, VerifiedPluginSourceManifest] | None = None,
        installed_plugins: dict[str, InstalledSourcePluginMetadata] | None = None,
    ) -> None:
        self.config = config.config if isinstance(config, PluginRuntimeContext) else config
        self.sources = sources or {}
        self.last_download_time: datetime | None = None
        self.source_catalogs = source_catalogs or {}
        self.installed_plugins = installed_plugins or {}
        self._trusted_auto_allow_fingerprints = self._compute_trusted_auto_allow_fingerprints()

    @classmethod
    def from_config(cls, config: UserConfig) -> ExternalPluginRegistry:
        repository_path = cls._repository_path_for_config(config)
        if not repository_path.exists():
            return cls(config=config)
        try:
            data = json.loads(repository_path.read_text(encoding="utf-8"))
            return cls.from_dump(data, class_kwargs={cls.__name__: {"config": config}})
        except Exception as exc:
            logger.warning("Could not load external plugin repository %s: %s", repository_path, exc)
            return cls(config=config)

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=None)
        config: UserConfig | None = None
        if class_kwargs:
            class_config = class_kwargs.get(cls.__name__, {}).get("config")
            if isinstance(class_config, UserConfig):
                config = class_config
        if config is None:
            raise ExternalPluginError("External plugin registry requires a runtime config.")

        sources: dict[str, PluginSource] = {}
        for source_id, raw_source in dct.get("sources", {}).items():
            if isinstance(raw_source, PluginSource):
                sources[str(source_id)] = raw_source
            elif isinstance(raw_source, dict):
                sources[str(source_id)] = PluginSource.from_dump(raw_source)

        source_catalogs: dict[str, VerifiedPluginSourceManifest] = {}
        for source_id, raw_catalog in dct.get("source_catalogs", {}).items():
            if isinstance(raw_catalog, VerifiedPluginSourceManifest):
                source_catalogs[str(source_id)] = raw_catalog
            elif isinstance(raw_catalog, dict):
                source_catalogs[str(source_id)] = VerifiedPluginSourceManifest.from_dump(raw_catalog)

        installed_plugins: dict[str, InstalledSourcePluginMetadata] = {}
        for bundle_id, raw_metadata in dct.get("installed_plugins", {}).items():
            if isinstance(raw_metadata, InstalledSourcePluginMetadata):
                installed_plugins[str(bundle_id)] = raw_metadata
            elif isinstance(raw_metadata, dict):
                installed_plugins[str(bundle_id)] = InstalledSourcePluginMetadata.from_dump(raw_metadata)

        return cls(
            config=config,
            sources=sources,
            source_catalogs=source_catalogs,
            installed_plugins=installed_plugins,
        )

    def dump(self) -> dict[str, Any]:
        d = super().dump()
        d["sources"] = self.sources
        d["source_catalogs"] = self.source_catalogs
        d["installed_plugins"] = self.installed_plugins
        return d

    def save(self) -> None:  # type: ignore[override]
        super().save(self.repository_path)

    @property
    def root_dir(self) -> Path:
        return Path(self.config.config_dir) / "plugins"

    @property
    def repository_path(self) -> Path:
        return self.root_dir / self.REPOSITORY_FILENAME

    @classmethod
    def _repository_path_for_config(cls, config: UserConfig) -> Path:
        return Path(config.config_dir) / "plugins" / cls.REPOSITORY_FILENAME

    @property
    def installed_dir(self) -> Path:
        return self.root_dir / "installed"

    @property
    def cache_dir(self) -> Path:
        return self.root_dir / "cache"

    def add_source(
        self,
        manifest_url: str,
        pinned_source_public_key: str,
        auth_config: PluginSourceAuthConfig | None = None,
        display_name: str | None = None,
    ) -> VerifiedPluginSourceManifest:
        auth_config = auth_config or PluginSourceAuthConfig()
        normalized_manifest_url = self._normalize_manifest_url(manifest_url)
        manifest, _manifest_bytes, _signature_bytes, _plugin_metadata_texts = self._fetch_and_verify_manifest(
            manifest_url=normalized_manifest_url,
            pinned_source_public_key=pinned_source_public_key,
            auth_config=auth_config,
            last_seen_source_serial=0,
        )
        if self.load_source(manifest.source_id):
            raise ExternalPluginError(f"Source {manifest.source_id} is already configured.")

        source = PluginSource(
            source_id=manifest.source_id,
            display_name=display_name or manifest.display_name,
            manifest_url=normalized_manifest_url,
            pinned_source_public_key=pinned_source_public_key,
            auth_config=auth_config,
            enabled=True,
            last_seen_source_serial=manifest.source_serial,
            last_checked_at=self._now_iso(),
            last_error=None,
        )
        self._write_source(source)
        self.source_catalogs[source.source_id] = manifest
        self.save()
        return manifest

    async def refresh_sources(
        self,
        source_id: str | None = None,
        recheck_installed: bool = True,
        raise_on_error: bool = True,
    ) -> list[VerifiedPluginSourceManifest]:
        refreshed: list[VerifiedPluginSourceManifest] = []
        errors: list[str] = []
        sources = self.load_sources() if source_id is None else [self._require_source(source_id)]
        enabled_sources = [source for source in sources if source.enabled]
        if enabled_sources:
            self.last_download_time = datetime.now(timezone.utc)
        for source in enabled_sources:
            try:
                manifest, _manifest_bytes, _signature_bytes, _plugin_metadata_texts = (
                    self._fetch_and_verify_manifest(
                        manifest_url=source.manifest_url,
                        pinned_source_public_key=source.pinned_source_public_key,
                        auth_config=source.auth_config,
                        last_seen_source_serial=source.last_seen_source_serial,
                    )
                )
                updated_source = PluginSource(
                    source_id=source.source_id,
                    display_name=source.display_name or manifest.display_name,
                    manifest_url=source.manifest_url,
                    pinned_source_public_key=source.pinned_source_public_key,
                    auth_config=source.auth_config,
                    enabled=source.enabled,
                    last_seen_source_serial=manifest.source_serial,
                    last_checked_at=self._now_iso(),
                    last_error=None,
                )
                self._write_source(updated_source)
                self.source_catalogs[source.source_id] = manifest
                self.save()
                refreshed.append(manifest)
            except ExternalPluginError as exc:
                self._write_source(
                    PluginSource(
                        source_id=source.source_id,
                        display_name=source.display_name,
                        manifest_url=source.manifest_url,
                        pinned_source_public_key=source.pinned_source_public_key,
                        auth_config=source.auth_config,
                        enabled=source.enabled,
                        last_seen_source_serial=source.last_seen_source_serial,
                        last_checked_at=self._now_iso(),
                        last_error=str(exc),
                    )
                )
                self.save()
                errors.append(f"{source.display_name}: {exc}")
                logger.warning("Failed to refresh plugin source %s: %s", source.source_id, exc)

        if recheck_installed:
            self.recheck_installed_plugins()
        if errors and raise_on_error:
            raise ExternalPluginError("; ".join(errors))
        return refreshed

    def should_skip_startup_source_refresh(self) -> bool:
        if self.last_download_time is None:
            return False
        return datetime.now(timezone.utc) - self.last_download_time < self.STARTUP_SOURCE_REFRESH_COOLDOWN

    def _require_source(self, source_id: str) -> PluginSource:
        source = self.load_source(source_id)
        if source is None:
            raise ExternalPluginError(f"Unknown plugin source {source_id}.")
        return source

    def list_available_plugins(self) -> list[ExternalPluginCatalogEntry]:
        installed_metadata = self.load_installed_metadata()
        entries: list[ExternalPluginCatalogEntry] = []
        for source in self.load_sources():
            if not source.enabled:
                continue
            manifest = self.load_cached_source_catalog(source.source_id)
            if manifest is None:
                continue
            for plugin in manifest.plugins:
                if not self._is_plugin_compatible(plugin.app_version_specifier):
                    continue
                # Example:
                # - source A publishes bundle_id = "notes"
                # - source B also publishes bundle_id = "notes"
                # We treat "notes" as one global plugin id, so install/update state is
                # also looked up by bundle id alone.
                installed = installed_metadata.get(plugin.bundle_id)
                installed_version = installed.version if installed else None
                installed_folder_hash = installed.folder_hash if installed else None
                update_available = installed_version is not None and (
                    installed_version != plugin.version or installed_folder_hash != plugin.folder_hash
                )
                entries.append(
                    replace(
                        plugin,
                        installed_version=installed_version,
                        installed_folder_hash=installed_folder_hash,
                        update_available=update_available,
                    )
                )
        return sorted(entries, key=lambda entry: (entry.display_name.lower(), entry.bundle_id))

    async def install_plugin(self, source_id: str, bundle_id: str) -> InstalledSourcePluginMetadata:
        source = self.load_source(source_id)
        if source is None:
            raise ExternalPluginError(f"Unknown plugin source {source_id}.")
        manifest = self.load_cached_source_catalog(source_id)
        if manifest is None:
            raise ExternalPluginError(f"Source {source_id} has not been refreshed successfully yet.")

        plugin = manifest.plugin_by_bundle_id(bundle_id)
        if plugin is None:
            raise ExternalPluginError(f"Source {source_id} does not provide plugin {bundle_id}.")

        with tempfile.TemporaryDirectory(prefix="bitcoin-safe-plugin-install-") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            plugin_dir = self._prepare_plugin_directory(source, plugin, temp_dir)
            metadata_path = resolve_plugin_metadata_path(plugin_dir)
            if metadata_path is None:
                raise ExternalPluginError(f"{bundle_id} is missing {PLUGIN_PYPROJECT_FILENAME}.")
            plugin_spec = self._load_plugin_metadata(metadata_path)
            self._validate_plugin_metadata(plugin, plugin_spec)

            folder_hash = compute_plugin_folder_hash(plugin_dir)
            if folder_hash != plugin.folder_hash:
                raise ExternalPluginError(f"Plugin {bundle_id} does not match the signed manifest hash.")

            installed_target = self.installed_dir / bundle_id
            installed_target.parent.mkdir(parents=True, exist_ok=True)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temp_install_dir = self.cache_dir / f"install-{bundle_id}"
            shutil.rmtree(temp_install_dir, ignore_errors=True)
            shutil.copytree(plugin_dir, temp_install_dir)

            metadata = InstalledSourcePluginMetadata(
                bundle_id=bundle_id,
                source_id=source_id,
                version=plugin.version,
                folder_hash=folder_hash,
                installed_at=self._now_iso(),
                trusted_auto_allow_signer=manifest.signer_fingerprint
                in self._trusted_auto_allow_fingerprints,
                verified_signer_fingerprint=manifest.signer_fingerprint,
                last_verification_ok=True,
                last_verification_error=None,
            )
            backup_dir = installed_target.with_name(installed_target.name + "-backup")
            shutil.rmtree(backup_dir, ignore_errors=True)
            try:
                if installed_target.exists():
                    installed_target.replace(backup_dir)
                temp_install_dir.replace(installed_target)
            except Exception as exc:
                if backup_dir.exists() and not installed_target.exists():
                    backup_dir.replace(installed_target)
                raise ExternalPluginError(f"Could not install plugin {bundle_id}: {exc}") from exc
            finally:
                shutil.rmtree(temp_install_dir, ignore_errors=True)
                shutil.rmtree(backup_dir, ignore_errors=True)
            self.installed_plugins[bundle_id] = metadata
            self.save()
            return metadata

    def recheck_installed_plugins(self) -> list[InstalledSourcePluginMetadata]:
        results: list[InstalledSourcePluginMetadata] = []
        for metadata in self.load_installed_metadata().values():
            installed_path = self.installed_dir / metadata.bundle_id
            if not installed_path.exists():
                continue
            new_metadata = metadata
            try:
                folder_hash = compute_plugin_folder_hash(installed_path)
                if folder_hash != metadata.folder_hash:
                    raise ExternalPluginError("Installed plugin files no longer match the verified manifest.")
                new_metadata = InstalledSourcePluginMetadata(
                    bundle_id=metadata.bundle_id,
                    source_id=metadata.source_id,
                    version=metadata.version,
                    folder_hash=metadata.folder_hash,
                    installed_at=metadata.installed_at,
                    trusted_auto_allow_signer=metadata.trusted_auto_allow_signer,
                    verified_signer_fingerprint=metadata.verified_signer_fingerprint,
                    last_verification_ok=True,
                    last_verification_error=None,
                )
            except ExternalPluginError as exc:
                new_metadata = InstalledSourcePluginMetadata(
                    bundle_id=metadata.bundle_id,
                    source_id=metadata.source_id,
                    version=metadata.version,
                    folder_hash=metadata.folder_hash,
                    installed_at=metadata.installed_at,
                    trusted_auto_allow_signer=metadata.trusted_auto_allow_signer,
                    verified_signer_fingerprint=metadata.verified_signer_fingerprint,
                    last_verification_ok=False,
                    last_verification_error=str(exc),
                )
            self.installed_plugins[metadata.bundle_id] = new_metadata
            results.append(new_metadata)
        self.save()
        return results

    def discover_verified_bundles(
        self,
        context: PluginRuntimeContext,
    ) -> list[VerifiedExternalPluginBundle]:
        bundles: list[VerifiedExternalPluginBundle] = []
        for metadata in self.load_installed_metadata().values():
            if not metadata.last_verification_ok:
                continue
            source = self.load_source(metadata.source_id)
            if source is None or not source.enabled:
                continue
            bundle_dir = self.installed_dir / metadata.bundle_id
            if not bundle_dir.exists():
                continue
            try:
                bundles.append(self._load_installed_bundle(bundle_dir, metadata, context))
            except Exception as exc:
                logger.warning("Skipping installed source plugin %s: %s", metadata.bundle_id, exc)
        return bundles

    def load_source(self, source_id: str) -> PluginSource | None:
        return self.sources.get(source_id)

    def load_sources(self) -> list[PluginSource]:
        return sorted(self.sources.values(), key=lambda source: source.source_id)

    def installed_plugins_for_source(self, source_id: str) -> list[InstalledSourcePluginMetadata]:
        return sorted(
            [
                metadata
                for metadata in self.load_installed_metadata().values()
                if metadata.source_id == source_id
            ],
            key=lambda metadata: metadata.bundle_id,
        )

    def installed_plugin_counts_by_source(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for metadata in self.load_installed_metadata().values():
            counts[metadata.source_id] = counts.get(metadata.source_id, 0) + 1
        return counts

    def remove_source(self, source_id: str) -> None:
        if self.load_source(source_id) is None:
            raise ExternalPluginError(f"Unknown plugin source {source_id}.")
        installed_plugins = self.installed_plugins_for_source(source_id)
        if installed_plugins:
            raise ExternalPluginError(f"Cannot remove source {source_id} while plugins are still installed.")

        del self.sources[source_id]
        self.source_catalogs.pop(source_id, None)
        self.save()

    def remove_installed_plugin(self, bundle_id: str) -> None:
        metadata = self.load_installed_metadata().get(bundle_id)
        if metadata is None:
            raise ExternalPluginError(f"Plugin {bundle_id} is not installed.")
        shutil.rmtree(self.installed_dir / bundle_id, ignore_errors=True)
        self.installed_plugins.pop(bundle_id, None)
        self.save()

    def load_installed_metadata(self) -> dict[str, InstalledSourcePluginMetadata]:
        return dict(self.installed_plugins)

    def load_cached_source_catalog(self, source_id: str) -> VerifiedPluginSourceManifest | None:
        if self.load_source(source_id) is None:
            return None
        return self.source_catalogs.get(source_id)

    def _load_installed_bundle(
        self,
        bundle_dir: Path,
        metadata: InstalledSourcePluginMetadata,
        context: PluginRuntimeContext,
    ) -> VerifiedExternalPluginBundle:
        metadata_file = resolve_plugin_metadata_path(bundle_dir)
        if metadata_file is None:
            raise ExternalPluginError(f"{bundle_dir.name} is missing {PLUGIN_PYPROJECT_FILENAME}.")

        manifest = self.load_cached_source_catalog(metadata.source_id)
        if manifest is None:
            raise ExternalPluginError(f"Source {metadata.source_id} has not been refreshed successfully yet.")
        catalog_entry = manifest.plugin_by_bundle_id(metadata.bundle_id)
        if catalog_entry is None:
            raise ExternalPluginError(
                f"Source {metadata.source_id} does not provide plugin {metadata.bundle_id}."
            )

        plugin_spec = self._load_plugin_metadata(metadata_file)
        if plugin_spec.bundle_id != metadata.bundle_id:
            raise ExternalPluginError(f"{bundle_dir.name} bundle id metadata mismatch.")
        entrypoint = bundle_dir / plugin_spec.entrypoint
        if not entrypoint.exists():
            raise ExternalPluginError(f"{bundle_dir.name} is missing {plugin_spec.entrypoint}.")

        module_name = f"bitcoin_safe_external_plugin_{metadata.bundle_id}_{metadata.folder_hash}"
        module = self._load_module(module_name, entrypoint, bundle_dir)
        bundle_name = bundle_dir.name
        client_classes = plugin_bundle_client_classes(
            cast(PluginBundleModule, module),
            error_type=ExternalPluginError,
            bundle_name=bundle_name,
        )
        additional_class_kwargs_by_client_class: dict[type[PluginClient], dict[str, object]] = {}
        for client_cls in client_classes:
            if issubclass(client_cls, PaidPluginClient):
                if catalog_entry.btcpay_config is None:
                    raise ExternalPluginError(
                        f"{bundle_name} must define BTCPay metadata for {client_cls.__name__}."
                    )
                additional_class_kwargs_by_client_class[client_cls] = {
                    "btcpay_config": catalog_entry.btcpay_config,
                }
        runtime_bundle = normalize_runtime_plugin_bundle(
            module=cast(PluginBundleModule, module),
            context=context,
            auto_allow_plugin_clients=client_classes if metadata.trusted_auto_allow_signer else (),
            bundle_name=bundle_name,
            error_type=ExternalPluginError,
            additional_class_kwargs_by_client_class=additional_class_kwargs_by_client_class,
        )

        return VerifiedExternalPluginBundle(
            bundle_id=metadata.bundle_id,
            source_id=metadata.source_id,
            version=metadata.version,
            plugin_dir=bundle_dir,
            folder_hash=metadata.folder_hash,
            verified_signer_fingerprint=metadata.verified_signer_fingerprint,
            trusted_auto_allow_signer=metadata.trusted_auto_allow_signer,
            runtime_bundle=runtime_bundle,
        )

    def _prepare_plugin_directory(
        self,
        source: PluginSource,
        plugin: ExternalPluginCatalogEntry,
        temp_dir: Path,
    ) -> Path:
        local_root = self._local_manifest_root(source.manifest_url)
        if local_root is not None:
            plugin_dir = local_root / plugin.path
            if not plugin_dir.exists():
                raise ExternalPluginError(f"Plugin path {plugin.path} is missing in the source.")
            return plugin_dir

        archive_path = temp_dir / "source-archive.zip"
        archive_url = self._archive_url_from_manifest_url(source.manifest_url, plugin.release_ref)
        archive_path.write_bytes(
            fetch_bytes(
                url=archive_url, headers=source.auth_config.headers(), proxy_info=self._requests_proxy_info()
            )
        )
        extract_root = temp_dir / "snapshot"
        self._extract_zip_safely(archive_path, extract_root)
        extracted_plugin_dir = self._find_plugin_directory(extract_root, Path(plugin.path))
        if extracted_plugin_dir is None:
            raise ExternalPluginError(f"Could not find {plugin.path} inside the downloaded source archive.")
        return extracted_plugin_dir

    def _fetch_and_verify_manifest(
        self,
        manifest_url: str,
        pinned_source_public_key: str,
        auth_config: PluginSourceAuthConfig,
        last_seen_source_serial: int,
    ) -> tuple[VerifiedPluginSourceManifest, bytes, bytes, dict[str, str]]:
        manifest_bytes = fetch_bytes(
            url=manifest_url, headers=auth_config.headers(), proxy_info=self._requests_proxy_info()
        )
        signature_bytes = fetch_bytes(
            url=manifest_url + SOURCE_SIGNATURE_SUFFIX,
            headers=auth_config.headers(),
            proxy_info=self._requests_proxy_info(),
        )

        verifyer = SignatureVerifyer(list_of_known_keys=None, proxies=None)
        imported_key = verifyer.import_public_key_block(pinned_source_public_key)
        try:
            signature = pgpy.PGPSignature.from_blob(signature_bytes)
            detached_signer_fingerprint = (
                str(signature.signer_fingerprint).replace(" ", "").upper()
                if isinstance(signature, pgpy.PGPSignature)
                else None
            )
        except Exception:
            detached_signer_fingerprint = None
        expected_fingerprint = str(imported_key.fingerprint).replace(" ", "").upper()
        if detached_signer_fingerprint and detached_signer_fingerprint != expected_fingerprint:
            raise ExternalPluginError("Source manifest signer does not match the pinned key.")
        with tempfile.TemporaryDirectory(prefix="bitcoin-safe-source-manifest-") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            manifest_path = temp_dir / SOURCE_MANIFEST_FILENAME
            signature_path = temp_dir / f"{SOURCE_MANIFEST_FILENAME}{SOURCE_SIGNATURE_SUFFIX}"
            manifest_path.write_bytes(manifest_bytes)
            signature_path.write_bytes(signature_bytes)
            verified, signer_fingerprint = verifyer.verify_detached_signature_with_fingerprint(
                manifest_path, signature_path
            )
        if not verified or signer_fingerprint is None:
            raise ExternalPluginError("Source manifest signature verification failed.")
        if signer_fingerprint != expected_fingerprint:
            raise ExternalPluginError("Source manifest signer does not match the pinned key.")

        try:
            manifest_text = manifest_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExternalPluginError(f"Could not decode {SOURCE_MANIFEST_FILENAME}.") from exc
        manifest = self._parse_source_manifest(manifest_text, manifest_url)
        resolved_catalog = self._resolve_source_catalog(manifest, auth_config)
        if isinstance(resolved_catalog, tuple):
            manifest = resolved_catalog[0]
        else:
            manifest = resolved_catalog
        if manifest.source_serial < last_seen_source_serial:
            raise ExternalPluginError("Source manifest serial rolled back.")
        return (
            VerifiedPluginSourceManifest(
                source_id=manifest.source_id,
                display_name=manifest.display_name,
                source_serial=manifest.source_serial,
                signer_fingerprint=signer_fingerprint,
                manifest_url=manifest_url,
                plugins=manifest.plugins,
            ),
            manifest_bytes,
            signature_bytes,
            {},
        )

    def _parse_source_manifest(self, manifest_text: str, manifest_url: str) -> VerifiedPluginSourceManifest:
        try:
            data = tomllib.loads(manifest_text)
        except tomllib.TOMLDecodeError as exc:
            raise ExternalPluginError(f"Could not parse {SOURCE_MANIFEST_FILENAME}: {exc}") from exc
        try:
            manifest = parse_source_manifest(data, SOURCE_MANIFEST_FILENAME)
        except PluginSourceModelError as exc:
            raise ExternalPluginError(str(exc)) from exc
        return self._to_verified_source_manifest(manifest, manifest_url)

    @staticmethod
    def _to_verified_source_manifest(
        manifest: SourceManifestModel, manifest_url: str
    ) -> VerifiedPluginSourceManifest:
        plugins: list[ExternalPluginCatalogEntry] = []
        for entry in manifest.plugins:
            plugins.append(
                ExternalPluginCatalogEntry(
                    source_id=manifest.source_id,
                    source_display_name=manifest.display_name,
                    bundle_id=entry.bundle_id,
                    version="",
                    display_name="",
                    description="",
                    provider="",
                    entrypoint="",
                    plugin_api_version="",
                    app_version_specifier="",
                    folder_hash=entry.folder_hash,
                    release_ref=entry.release_ref,
                )
            )

        return VerifiedPluginSourceManifest(
            source_id=manifest.source_id,
            display_name=manifest.display_name,
            source_serial=manifest.source_serial,
            signer_fingerprint="",
            manifest_url=manifest_url,
            plugins=tuple(plugins),
        )

    def _resolve_source_catalog(
        self,
        manifest: VerifiedPluginSourceManifest,
        auth_config: PluginSourceAuthConfig,
    ) -> VerifiedPluginSourceManifest:
        catalog_entries: list[ExternalPluginCatalogEntry] = []
        for plugin in manifest.plugins:
            try:
                catalog_entry = self._resolve_plugin_catalog_entry(
                    manifest_url=manifest.manifest_url, auth_config=auth_config, plugin=plugin
                )
                catalog_entries.append(catalog_entry)
            except ExternalPluginError as exc:
                logger.warning(
                    "Skipping plugin %s from source %s: %s",
                    plugin.bundle_id,
                    manifest.source_id,
                    exc,
                )
        return VerifiedPluginSourceManifest(
            source_id=manifest.source_id,
            display_name=manifest.display_name,
            source_serial=manifest.source_serial,
            signer_fingerprint=manifest.signer_fingerprint,
            manifest_url=manifest.manifest_url,
            plugins=tuple(catalog_entries),
        )

    def _resolve_plugin_catalog_entry(
        self,
        manifest_url: str,
        auth_config: PluginSourceAuthConfig,
        plugin: ExternalPluginCatalogEntry,
    ) -> ExternalPluginCatalogEntry:
        metadata_text = self._read_plugin_metadata_text(
            manifest_url=manifest_url,
            auth_config=auth_config,
            bundle_id=plugin.bundle_id,
        )
        metadata = self._parse_plugin_metadata_text(metadata_text, PLUGIN_PYPROJECT_FILENAME)
        return self._catalog_entry_from_metadata(plugin=plugin, metadata=metadata)

    @staticmethod
    def _catalog_entry_from_metadata(
        plugin: ExternalPluginCatalogEntry,
        metadata: PluginMetadataModel,
    ) -> ExternalPluginCatalogEntry:
        if metadata.bundle_id != plugin.bundle_id:
            raise ExternalPluginError(f"Plugin metadata for {plugin.bundle_id} has a mismatched bundle_id.")
        return ExternalPluginCatalogEntry(
            source_id=plugin.source_id,
            source_display_name=plugin.source_display_name,
            bundle_id=plugin.bundle_id,
            version=metadata.version,
            display_name=metadata.display_name,
            description=metadata.description,
            provider=metadata.provider,
            entrypoint=metadata.entrypoint,
            plugin_api_version=metadata.plugin_api_version,
            app_version_specifier=metadata.app_version_specifier,
            folder_hash=plugin.folder_hash,
            release_ref=plugin.release_ref,
            btcpay_config=metadata.btcpay_config,
        )

    def _requests_proxy_info(self) -> ProxyInfo | None:
        proxy_url = self.config.network_config.proxy_url
        if not proxy_url:
            return None
        return ProxyInfo.parse(proxy_url)

    def _fetch_plugin_metadata(
        self,
        manifest_url: str,
        auth_config: PluginSourceAuthConfig,
        bundle_id: str,
    ) -> PluginMetadataModel:
        metadata_text = self._read_plugin_metadata_text(
            manifest_url=manifest_url, auth_config=auth_config, bundle_id=bundle_id
        )
        return self._parse_plugin_metadata_text(metadata_text, PLUGIN_PYPROJECT_FILENAME)

    def _read_plugin_metadata_text(
        self,
        manifest_url: str,
        auth_config: PluginSourceAuthConfig,
        bundle_id: str,
    ) -> str:
        local_root = self._local_manifest_root(manifest_url)
        if local_root is not None:
            plugin_dir = local_root / "plugins" / bundle_id
            metadata_path = resolve_plugin_metadata_path(plugin_dir)
            if metadata_path is None:
                raise ExternalPluginError(f"{bundle_id} is missing {PLUGIN_PYPROJECT_FILENAME}.")
            return metadata_path.read_text(encoding="utf-8")

        metadata_url = urljoin(manifest_url, f"plugins/{bundle_id}/{PLUGIN_PYPROJECT_FILENAME}")
        try:
            return fetch_bytes(
                url=metadata_url, headers=auth_config.headers(), proxy_info=self._requests_proxy_info()
            ).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExternalPluginError(f"Could not decode plugin metadata for {bundle_id}.") from exc

    @staticmethod
    def _load_plugin_metadata(path: Path) -> PluginMetadataModel:
        return ExternalPluginRegistry._parse_plugin_metadata_text(
            path.read_text(encoding="utf-8"),
            path.name,
        )

    @staticmethod
    def _parse_plugin_metadata_text(metadata_text: str, file_name: str) -> PluginMetadataModel:
        try:
            raw_data = tomllib.loads(metadata_text)
        except tomllib.TOMLDecodeError as exc:
            raise ExternalPluginError(f"Could not parse {file_name}: {exc}") from exc
        try:
            return parse_plugin_pyproject(raw_data, file_name)
        except PluginSourceModelError as exc:
            raise ExternalPluginError(str(exc)) from exc

    @staticmethod
    def _archive_url_from_manifest_url(manifest_url: str, release_ref: str) -> str:
        parsed = urlparse(manifest_url)
        if parsed.scheme not in ("http", "https"):
            raise ExternalPluginError(
                "Remote plugin archive URL can only be derived from http(s) manifest URLs."
            )

        path_parts = [part for part in parsed.path.split("/") if part]
        if parsed.netloc == "raw.githubusercontent.com":
            if len(path_parts) != 4 or path_parts[-1] != SOURCE_MANIFEST_FILENAME:
                raise ExternalPluginError(
                    f"Could not derive archive URL from plugin source URL {manifest_url}."
                )
            owner, repo = path_parts[0], path_parts[1]
            archive_path = f"/{owner}/{repo}/archive/{release_ref}.zip"
            return parsed._replace(
                netloc="github.com",
                path=archive_path,
                params="",
                query="",
                fragment="",
            ).geturl()

        if len(path_parts) < 5:
            raise ExternalPluginError(f"Could not derive archive URL from plugin source URL {manifest_url}.")
        try:
            raw_index = path_parts.index("raw")
        except ValueError as exc:
            raise ExternalPluginError(
                f"Could not derive archive URL from plugin source URL {manifest_url}."
            ) from exc
        if raw_index < 2 or raw_index + 3 >= len(path_parts):
            raise ExternalPluginError(f"Could not derive archive URL from plugin source URL {manifest_url}.")

        repo_path = "/".join(path_parts[:raw_index])
        archive_path = f"/{repo_path}/archive/{release_ref}.zip"
        return parsed._replace(path=archive_path, params="", query="", fragment="").geturl()

    def _validate_plugin_metadata(
        self,
        plugin: ExternalPluginCatalogEntry,
        plugin_spec: PluginMetadataModel,
    ) -> None:
        if plugin_spec.bundle_id != plugin.bundle_id:
            raise ExternalPluginError(f"Plugin metadata for {plugin.bundle_id} has a mismatched bundle_id.")
        if plugin_spec.version != plugin.version:
            raise ExternalPluginError(f"Plugin metadata for {plugin.bundle_id} has a mismatched version.")
        if plugin_spec.entrypoint != plugin.entrypoint:
            raise ExternalPluginError(f"Plugin metadata for {plugin.bundle_id} has a mismatched entrypoint.")
        if plugin_spec.plugin_api_version != SUPPORTED_PLUGIN_API_VERSION:
            raise ExternalPluginError(
                f"Plugin {plugin.bundle_id} requires unsupported plugin API {plugin_spec.plugin_api_version}."
            )
        if not self._is_plugin_compatible(plugin.app_version_specifier):
            raise ExternalPluginError(
                f"Plugin {plugin.bundle_id} is not compatible with this Bitcoin Safe version."
            )

    @staticmethod
    def _is_plugin_compatible(app_version_specifier: str) -> bool:
        try:
            specifier_set = SpecifierSet(app_version_specifier)
            app_version = Version(__version__)
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise ExternalPluginError(
                f"Invalid Bitcoin Safe version requirement {app_version_specifier!r}."
            ) from exc
        return specifier_set.contains(app_version, prereleases=True)

    def _write_source(self, source: PluginSource) -> None:
        self.sources[source.source_id] = source

    @staticmethod
    def _normalize_manifest_url(manifest_url: str) -> str:
        parsed = urlparse(manifest_url)
        if parsed.scheme in ("http", "https"):
            normalized_path = parsed.path.rstrip("/")
            if normalized_path.endswith(SOURCE_MANIFEST_FILENAME):
                # Example:
                # - keep https://raw.githubusercontent.com/org/repo/main/source.toml
                # - do not rewrite it to a repo-root URL here
                # The install step knows how to derive the archive URL from this form.
                return parsed._replace(path=normalized_path).geturl()
            if normalized_path.endswith(".git"):
                normalized_path = normalized_path[:-4]
            normalized_path = f"{normalized_path}/raw/branch/main/{SOURCE_MANIFEST_FILENAME}"
            return parsed._replace(path=normalized_path, params="", query="", fragment="").geturl()
        if parsed.scheme == "file":
            manifest_path = Path(unquote(parsed.path))
            if manifest_path.is_dir():
                manifest_path = manifest_path / SOURCE_MANIFEST_FILENAME
            normalized_manifest_path = manifest_path.resolve()
            return parsed._replace(path=str(normalized_manifest_path)).geturl()

        manifest_path = Path(manifest_url)
        if manifest_path.is_dir():
            manifest_path = manifest_path / SOURCE_MANIFEST_FILENAME
        if manifest_path.exists():
            return str(manifest_path.resolve())
        return manifest_url

    @staticmethod
    def _local_manifest_root(manifest_url: str) -> Path | None:
        parsed = urlparse(manifest_url)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path)).parent
        path = Path(manifest_url)
        if path.exists():
            return path.parent
        return None

    @staticmethod
    def _find_plugin_directory(root_dir: Path, plugin_path: Path) -> Path | None:
        expected_parts = plugin_path.parts
        for path in root_dir.rglob(plugin_path.name):
            if path.is_dir() and path.parts[-len(expected_parts) :] == expected_parts:
                return path
        return None

    @staticmethod
    def _extract_zip_safely(zip_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.infolist()
            for member in members:
                member_name = member.filename
                if not member_name or member_name.startswith("/"):
                    raise ExternalPluginError(f"Unsafe zip entry {member_name!r} in {zip_path.name}.")

                target_path = (destination / member_name).resolve(strict=False)
                destination_resolved = destination.resolve()
                if destination_resolved != target_path and destination_resolved not in target_path.parents:
                    raise ExternalPluginError(f"Unsafe zip entry {member_name!r} in {zip_path.name}.")
            archive.extractall(destination)

    @staticmethod
    def _module_originates_from_plugin_dir(module: ModuleType, plugin_dir: Path) -> bool:
        module_file = module.__dict__.get("__file__")
        if isinstance(module_file, str):
            module_path = Path(module_file).resolve(strict=False)
            if module_path == plugin_dir or plugin_dir in module_path.parents:
                return True

        module_paths = module.__dict__.get("__path__")
        if module_paths is None:
            return False

        for module_path_entry in module_paths:
            module_path = Path(str(module_path_entry)).resolve(strict=False)
            if module_path == plugin_dir or plugin_dir in module_path.parents:
                return True

        return False

    @classmethod
    def _unload_plugin_modules(cls, plugin_dir: Path) -> None:
        resolved_plugin_dir = plugin_dir.resolve(strict=False)
        loaded_plugin_modules = [
            module_name
            for module_name, module in sys.modules.items()
            if isinstance(module, ModuleType)
            and cls._module_originates_from_plugin_dir(module, resolved_plugin_dir)
        ]
        for module_name in loaded_plugin_modules:
            sys.modules.pop(module_name, None)
        importlib.invalidate_caches()

    @staticmethod
    def _plugin_top_level_module_names(plugin_dir: Path) -> set[str]:
        """Return top-level import names owned by this plugin directory."""
        names: set[str] = set()
        for child in plugin_dir.iterdir():
            if child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
                names.add(child.stem)
                continue
            if child.is_dir() and (child / "__init__.py").exists():
                names.add(child.name)
        return names

    @staticmethod
    def _module_name_matches_prefix(module_name: str, prefixes: set[str]) -> bool:
        return any(module_name == prefix or module_name.startswith(f"{prefix}.") for prefix in prefixes)

    @classmethod
    def _module_originates_from_any_plugin_dir(
        cls,
        module: ModuleType,
        plugin_dirs: set[Path],
    ) -> bool:
        return any(cls._module_originates_from_plugin_dir(module, plugin_dir) for plugin_dir in plugin_dirs)

    @classmethod
    def _matching_loaded_module_names(cls, module_prefixes: set[str]) -> list[str]:
        return [
            loaded_module_name
            for loaded_module_name in list(sys.modules)
            if cls._module_name_matches_prefix(loaded_module_name, module_prefixes)
        ]

    @classmethod
    def _take_conflicting_top_level_modules(
        cls,
        module_prefixes: set[str],
    ) -> dict[str, ModuleType]:
        """
        Remove currently loaded modules that would shadow this plugin's top-level imports.

        Example:
        - plugin A contains ``helper.py`` with ``VALUE = "ONE"``
        - plugin B contains ``helper.py`` with ``VALUE = "TWO"``
        If ``helper`` stays in ``sys.modules``, importing plugin B would silently reuse
        plugin A's helper module. We therefore clear the colliding alias before loading
        plugin B, then restore any non-plugin module afterwards.
        """
        replaced_modules: dict[str, ModuleType] = {}
        tracked_plugin_dirs = set(cls._loaded_plugin_dirs)
        conflicting_module_names = cls._matching_loaded_module_names(module_prefixes)
        for conflicting_module_name in conflicting_module_names:
            conflicting_module = sys.modules.get(conflicting_module_name)
            if not isinstance(conflicting_module, ModuleType):
                sys.modules.pop(conflicting_module_name, None)
                continue
            if not cls._module_originates_from_any_plugin_dir(conflicting_module, tracked_plugin_dirs):
                replaced_modules[conflicting_module_name] = conflicting_module
            sys.modules.pop(conflicting_module_name, None)
        if conflicting_module_names:
            importlib.invalidate_caches()
        return replaced_modules

    @classmethod
    def _drop_plugin_top_level_aliases(
        cls,
        module_prefixes: set[str],
        plugin_dir: Path,
    ) -> None:
        loaded_aliases = [
            loaded_module_name
            for loaded_module_name, loaded_module in list(sys.modules.items())
            if isinstance(loaded_module, ModuleType)
            and cls._module_name_matches_prefix(loaded_module_name, module_prefixes)
            and cls._module_originates_from_plugin_dir(loaded_module, plugin_dir)
        ]
        for loaded_alias in loaded_aliases:
            sys.modules.pop(loaded_alias, None)

    @staticmethod
    def _prepend_plugin_dir_to_sys_path(plugin_dir: Path) -> list[str]:
        original_sys_path = sys.path[:]
        plugin_dir_str = str(plugin_dir)
        sys.path[:] = [
            plugin_dir_str,
            *[path_entry for path_entry in original_sys_path if path_entry != plugin_dir_str],
        ]
        return original_sys_path

    @classmethod
    def _load_module(cls, module_name: str, entrypoint: Path, plugin_dir: Path) -> ModuleType:
        resolved_plugin_dir = plugin_dir.resolve(strict=False)
        cls._unload_plugin_modules(resolved_plugin_dir)

        top_level_module_names = cls._plugin_top_level_module_names(resolved_plugin_dir)
        replaced_modules = cls._take_conflicting_top_level_modules(top_level_module_names)
        original_sys_path = cls._prepend_plugin_dir_to_sys_path(resolved_plugin_dir)

        spec = importlib.util.spec_from_file_location(module_name, entrypoint)
        if spec is None or spec.loader is None:
            raise ExternalPluginError(f"Could not load plugin bundle from {entrypoint}.")

        module = importlib.util.module_from_spec(spec)
        try:
            # Example:
            # - works: `plugin_bundle.py` imports `client`
            # - not expected: `other_module.py` imports `.client`
            # We load `plugin_bundle.py` as the root module for the plugin.
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        finally:
            cls._drop_plugin_top_level_aliases(top_level_module_names, resolved_plugin_dir)
            sys.modules.update(replaced_modules)
            sys.path[:] = original_sys_path
            cls._loaded_plugin_dirs.add(resolved_plugin_dir)
            importlib.invalidate_caches()

    @classmethod
    def _compute_trusted_auto_allow_fingerprints(cls) -> set[str]:
        verifyer = SignatureVerifyer(list_of_known_keys=None, proxies=None)
        fingerprints: set[str] = set()
        for key in cls.trusted_auto_allow_signers:
            public_key = verifyer.import_public_key_block(key.key)
            fingerprints.add(str(public_key.fingerprint).replace(" ", "").upper())
        return fingerprints

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
