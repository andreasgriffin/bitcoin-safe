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

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import logging
import marshal
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from urllib.parse import ParseResult, unquote, urljoin, urlparse

import tomllib  # pyright: ignore[reportMissingImports]
from bitcoin_safe_lib.storage import BaseSaveableClass, filtered_for_init
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from bitcoin_safe import __version__
from bitcoin_safe.config import UserConfig
from bitcoin_safe.constants import APP_NAME
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
from bitcoin_safe.plugin_framework.plugin_source_download import (
    MAX_ARCHIVE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PLUGIN_METADATA_BYTES,
    MAX_SIGNATURE_BYTES,
    fetch_plugin_source_bytes,
    require_safe_plugin_source_url,
    validate_plugin_archive_members,
)
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
_ORIGINAL_FETCH_BYTES = fetch_bytes


@dataclass(frozen=True)
class _PluginArtifactLayout:
    package_name: str
    entrypoint_relative_path: Path
    bytecode_cache_tag: str | None


class _SignedPluginArtifactFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve one verified plugin namespace without invoking path-based importers."""

    def __init__(
        self,
        namespace: str,
        bundle_dir: Path,
        layout: _PluginArtifactLayout,
    ) -> None:
        self.namespace = namespace
        self.bundle_dir = bundle_dir
        self.layout = layout
        self.package_root = bundle_dir / layout.package_name
        self.package_namespace = f"{namespace}.{layout.package_name}"

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        del path, target
        if fullname == self.namespace:
            return importlib.machinery.ModuleSpec(
                fullname,
                self,
                is_package=True,
                origin=str(self.bundle_dir),
            )
        if fullname != self.package_namespace and not fullname.startswith(f"{self.package_namespace}."):
            return None

        relative_parts = fullname.split(".")[len(self.namespace.split(".")) :]
        artifact = self._artifact_path(relative_parts)
        if artifact is None:
            return None
        artifact_path, is_package = artifact
        return importlib.machinery.ModuleSpec(
            fullname,
            self,
            is_package=is_package,
            origin=str(artifact_path),
        )

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        del spec
        return None

    def exec_module(self, module: ModuleType) -> None:
        spec = module.__spec__
        if spec is None or spec.origin is None:
            raise ImportError(f"Missing artifact specification for {module.__name__}")
        artifact_path = Path(spec.origin)
        module.__file__ = str(artifact_path)
        if spec.submodule_search_locations is not None:
            # An empty path prevents PathFinder from searching unsigned filesystem paths.
            module.__path__ = []
        if module.__name__ == self.namespace:
            return
        try:
            if artifact_path.suffix == ".py":
                code = compile(artifact_path.read_bytes(), str(artifact_path), "exec")
            else:
                payload = artifact_path.read_bytes()
                if payload[:4] != importlib.util.MAGIC_NUMBER or len(payload) <= 16:
                    raise ImportError(f"Invalid signed bytecode artifact: {artifact_path}")
                code = marshal.loads(payload[16:])
                if not isinstance(code, type(compile("", "", "exec"))):
                    raise ImportError(f"Invalid signed bytecode code object: {artifact_path}")
            exec(code, module.__dict__)
        except OSError as exc:
            raise ImportError(f"Could not read signed plugin artifact {artifact_path}: {exc}") from exc

    def _artifact_path(self, relative_parts: list[str]) -> tuple[Path, bool] | None:
        if not relative_parts or relative_parts[0] != self.layout.package_name:
            return None
        parts = relative_parts[1:]
        relative_module = Path(*parts) if parts else Path()
        source_path = self.package_root / relative_module
        is_entrypoint = (
            bool(parts) and relative_module.with_suffix(".py") == self.layout.entrypoint_relative_path
        )
        if self.layout.bytecode_cache_tag is None or is_entrypoint:
            module_path = source_path.with_suffix(".py") if parts else source_path / "__module__.py"
            package_path = source_path / "__init__.py"
        else:
            bytecode_root = (
                self.package_root / "_bytecode" / self.layout.bytecode_cache_tag / self.layout.package_name
            )
            module_path = (bytecode_root / relative_module).with_suffix(".pyc")
            package_path = bytecode_root / relative_module / "__init__.pyc"
        if module_path.is_file():
            return module_path, False
        if package_path.is_file():
            return package_path, True
        return None


def _normalize_fingerprint(value: object) -> str:
    return str(value).replace(" ", "").upper()


@dataclass(frozen=True)
class _RemotePluginSourceUrl:
    manifest_url: str
    archive_repo_url: str

    def archive_url(self, release_ref: str) -> str:
        """Return the archive download URL for a release ref.

        Example: ``https://github.com/org/repo`` + ``main`` ->
        ``https://github.com/org/repo/archive/main.zip``.
        """
        return f"{self.archive_repo_url}/archive/{release_ref}.zip"

    @classmethod
    def from_manifest_url(cls, manifest_url: str) -> _RemotePluginSourceUrl | None:
        """Parse a remote manifest URL into normalized manifest and archive repo URLs.

        Examples:
        - ``https://dummy.example/org/repo/raw/branch/main/source.toml``
        - ``https://github.com/org/repo/blob/main/source.toml``
        - ``https://raw.githubusercontent.com/org/repo/main/source.toml``
        """
        parsed = urlparse(manifest_url)
        if parsed.scheme not in ("http", "https"):
            return None

        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 4:
            return None

        if parsed.netloc == "raw.githubusercontent.com":
            if len(path_parts) < 4 or path_parts[-1] != SOURCE_MANIFEST_FILENAME:
                return None
            owner, repo = path_parts[0], path_parts[1]
            return cls(
                manifest_url=cls._build_url(parsed, parsed.path.rstrip("/")),
                archive_repo_url=cls._build_url(parsed, f"/{owner}/{repo}", netloc="github.com"),
            )

        repo_path = cls._repo_path_from_web_manifest_parts(path_parts)
        if repo_path is None or path_parts[-1] != SOURCE_MANIFEST_FILENAME:
            return None

        normalized_manifest_path = cls._normalized_web_manifest_path(path_parts)
        return cls(
            manifest_url=cls._build_url(parsed, normalized_manifest_path),
            archive_repo_url=cls._build_url(parsed, repo_path),
        )

    @classmethod
    def from_repo_url(cls, repo_url: str) -> _RemotePluginSourceUrl | None:
        """Build normalized source URLs from a remote repository URL.

        Examples:
        - ``https://dummy.example/org/repo`` ->
          ``https://dummy.example/org/repo/raw/branch/main/source.toml``
        - ``https://github.com/org/repo.git`` ->
          ``https://github.com/org/repo/raw/main/source.toml``
        """
        parsed = urlparse(repo_url)
        if parsed.scheme not in ("http", "https"):
            return None

        repo_path = parsed.path.rstrip("/")
        if repo_path.endswith(".git"):
            repo_path = repo_path[:-4]
        path_parts = [part for part in repo_path.split("/") if part]
        if len(path_parts) != 2:
            return None
        if path_parts[-1] == SOURCE_MANIFEST_FILENAME:
            return None

        if parsed.netloc == "github.com":
            manifest_path = f"{repo_path}/raw/main/{SOURCE_MANIFEST_FILENAME}"
        else:
            manifest_path = f"{repo_path}/raw/branch/main/{SOURCE_MANIFEST_FILENAME}"

        return cls(
            manifest_url=cls._build_url(parsed, manifest_path),
            archive_repo_url=cls._build_url(parsed, repo_path),
        )

    @staticmethod
    def _normalized_web_manifest_path(path_parts: list[str]) -> str:
        """Normalize web manifest paths, rewriting GitHub ``blob`` paths to ``raw``.

        Example: ``["org", "repo", "blob", "main", "source.toml"]`` ->
        ``/org/repo/raw/main/source.toml``.
        """
        if len(path_parts) >= 5 and path_parts[2] == "blob":
            return "/" + "/".join([path_parts[0], path_parts[1], "raw", *path_parts[3:]])
        return "/" + "/".join(path_parts)

    @staticmethod
    def _repo_path_from_web_manifest_parts(path_parts: list[str]) -> str | None:
        """Extract ``/owner/repo`` from a web manifest path.

        Examples:
        - ``["org", "repo", "raw", "main", "source.toml"]`` -> ``/org/repo``
        - ``["org", "repo", "blob", "main", "source.toml"]`` -> ``/org/repo``
        """
        if len(path_parts) >= 5 and path_parts[2] in {"raw", "blob"}:
            return f"/{path_parts[0]}/{path_parts[1]}"
        return None

    @staticmethod
    def _build_url(parsed: ParseResult, path: str, netloc: str | None = None) -> str:
        """Rebuild a URL with a new path and optional host override.

        Example: parsed ``https://raw.githubusercontent.com/org/repo/main/source.toml``
        with path ``/org/repo`` and netloc ``github.com`` ->
        ``https://github.com/org/repo``.
        """
        return parsed._replace(
            netloc=netloc or parsed.netloc,
            path=path,
            params="",
            query="",
            fragment="",
        ).geturl()


def suggested_plugin_source_display_name(source_url: str) -> str | None:
    """Return a short source label derived from a plugin manifest or repo URL."""
    remote_source_url = _RemotePluginSourceUrl.from_manifest_url(source_url)
    if remote_source_url is None:
        remote_source_url = _RemotePluginSourceUrl.from_repo_url(source_url)
    if remote_source_url is None:
        return None

    parsed = urlparse(remote_source_url.archive_repo_url)
    repo_name = Path(parsed.path.rstrip("/")).name
    if not repo_name:
        return None

    provider = "GitHub" if parsed.netloc == "github.com" else "Gitea"
    return f"{provider} {repo_name}"


class ExternalPluginRegistry(BaseSaveableClass):
    VERSION = "0.0.1"
    REPOSITORY_FILENAME = "plugin-repository.json"
    STARTUP_SOURCE_REFRESH_COOLDOWN = timedelta(hours=1)
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
        self._plugin_finders: dict[str, _SignedPluginArtifactFinder] = {}

    @classmethod
    def from_dump(cls, dct: dict[str, Any], class_kwargs: dict | None = None):
        super()._from_dump(dct, class_kwargs=class_kwargs)

        return cls(**filtered_for_init(dct, cls))

    @classmethod
    def from_config(cls, config: UserConfig) -> ExternalPluginRegistry:
        try:
            return ExternalPluginRegistry._from_file(
                filename=str(cls.get_repository_path(config)),
                class_kwargs={ExternalPluginRegistry.__name__: {"config": config}},
            )
        except Exception:
            return ExternalPluginRegistry(config=config)

    def dump(self) -> dict[str, Any]:
        d = super().dump()
        d["sources"] = self.sources
        d["source_catalogs"] = self.source_catalogs
        d["installed_plugins"] = self.installed_plugins
        return d

    def save(self) -> None:  # type: ignore[override]
        super().save(self.repository_path)

    @classmethod
    def root_dir(cls, config: UserConfig) -> Path:
        return Path(config.config_dir) / "plugins"

    @property
    def repository_path(self) -> Path:
        return self.get_repository_path(self.config)

    @classmethod
    def get_repository_path(cls, config: UserConfig) -> Path:
        return cls.root_dir(config) / cls.REPOSITORY_FILENAME

    @classmethod
    def _repository_path_for_config(cls, config: UserConfig) -> Path:
        return Path(config.config_dir) / "plugins" / cls.REPOSITORY_FILENAME

    @property
    def installed_dir(self) -> Path:
        return self.root_dir(self.config) / "installed"

    @property
    def cache_dir(self) -> Path:
        return self.root_dir(self.config) / "cache"

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
        entries_by_bundle_id: dict[str, ExternalPluginCatalogEntry] = {}
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
                entries_by_bundle_id[plugin.bundle_id] = replace(
                    plugin,
                    installed_version=installed_version,
                    installed_folder_hash=installed_folder_hash,
                    update_available=update_available,
                )
        for metadata in installed_metadata.values():
            if metadata.bundle_id in entries_by_bundle_id:
                continue
            fallback_entry = self._fallback_entry(metadata)
            if fallback_entry is None:
                continue
            entries_by_bundle_id[metadata.bundle_id] = fallback_entry
        return sorted(
            entries_by_bundle_id.values(),
            key=lambda entry: (entry.display_name.lower(), entry.bundle_id),
        )

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
                catalog_entry=plugin,
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
                    catalog_entry=metadata.catalog_entry,
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
                    catalog_entry=metadata.catalog_entry,
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
        catalog_entry = metadata.catalog_entry
        if catalog_entry is None:
            catalog_entry = manifest.plugin_by_bundle_id(metadata.bundle_id)
        if catalog_entry is None:
            raise ExternalPluginError(
                f"Source {metadata.source_id} does not provide plugin {metadata.bundle_id}."
            )

        plugin_spec = self._load_plugin_metadata(metadata_file)
        if plugin_spec.bundle_id != metadata.bundle_id:
            raise ExternalPluginError(f"{bundle_dir.name} bundle id metadata mismatch.")
        self._validate_plugin_metadata(catalog_entry, plugin_spec)
        layout = self._resolve_plugin_artifact_layout(bundle_dir, plugin_spec)
        namespace = self._plugin_namespace(metadata.bundle_id, metadata.folder_hash)
        module_name = f"{namespace}.{layout.package_name}.{layout.entrypoint_relative_path.with_suffix('').as_posix().replace('/', '.')}"
        module = self._load_module(namespace, module_name, bundle_dir, layout)
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
            self._fetch_source_bytes(archive_url, source.auth_config, MAX_ARCHIVE_BYTES, "plugin archive")
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
        manifest_bytes = self._fetch_source_bytes(
            manifest_url, auth_config, MAX_MANIFEST_BYTES, "source manifest"
        )
        signature_bytes = self._fetch_source_bytes(
            manifest_url + SOURCE_SIGNATURE_SUFFIX, auth_config, MAX_SIGNATURE_BYTES, "source signature"
        )

        # Start with an empty verifier so no previously trusted/imported keys can match here.
        verifyer = SignatureVerifyer(list_of_known_keys=None, proxies=None)
        # Import exactly the pinned source cert; only this cert and its valid subkeys are allowed.
        imported_key = verifyer.import_public_key_block(pinned_source_public_key)
        expected_fingerprint = _normalize_fingerprint(imported_key.fingerprint)
        with tempfile.TemporaryDirectory(prefix="bitcoin-safe-source-manifest-") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            manifest_path = temp_dir / SOURCE_MANIFEST_FILENAME
            signature_path = temp_dir / f"{SOURCE_MANIFEST_FILENAME}{SOURCE_SIGNATURE_SUFFIX}"
            manifest_path.write_bytes(manifest_bytes)
            signature_path.write_bytes(signature_bytes)
            # Verification can only succeed if the signature chains back to that imported cert.
            # Any other key, even one trusted elsewhere, is absent from this verifier and will fail.
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

    def _fetch_source_bytes(
        self,
        url: str,
        auth_config: PluginSourceAuthConfig,
        max_bytes: int,
        purpose: str,
    ) -> bytes:
        if fetch_bytes is not _ORIGINAL_FETCH_BYTES:
            return fetch_bytes(url, auth_config.headers(), self._requests_proxy_info())
        return fetch_plugin_source_bytes(
            url=url,
            headers=auth_config.headers(),
            proxy_info=self._requests_proxy_info(),
            max_bytes=max_bytes,
            purpose=purpose,
        )

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
            return self._fetch_source_bytes(
                metadata_url, auth_config, MAX_PLUGIN_METADATA_BYTES, "plugin metadata"
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

        remote_source_url = _RemotePluginSourceUrl.from_manifest_url(manifest_url)
        if remote_source_url is None:
            raise ExternalPluginError(f"Could not derive archive URL from plugin source URL {manifest_url}.")
        return remote_source_url.archive_url(release_ref)

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
                f"Plugin {plugin.bundle_id} is not compatible with this {APP_NAME} version."
            )

    @staticmethod
    def _bump_release_component(release: tuple[int, ...], index: int) -> tuple[int, ...]:
        release_parts = list(release)
        release_parts[index] += 1
        for release_index in range(index + 1, len(release_parts)):
            release_parts[release_index] = 0
        return tuple(release_parts)

    @staticmethod
    def _format_release(release: tuple[int, ...]) -> str:
        return ".".join(str(part) for part in release)

    @classmethod
    def _expand_caret_specifier(
        cls,
        raw_version: str,
        app_version_specifier: str,
    ) -> tuple[str, str]:
        try:
            version = Version(raw_version.strip())
        except InvalidVersion as exc:
            raise ExternalPluginError(
                f"Invalid {APP_NAME} version requirement {app_version_specifier!r}."
            ) from exc

        release = version.release
        upper_index = next((index for index, part in enumerate(release) if part != 0), len(release) - 1)
        upper_release = cls._bump_release_component(release, upper_index)
        return (f">={version}", f"<{cls._format_release(upper_release)}")

    @classmethod
    def _expand_tilde_specifier(
        cls,
        raw_version: str,
        app_version_specifier: str,
    ) -> tuple[str, str]:
        try:
            version = Version(raw_version.strip())
        except InvalidVersion as exc:
            raise ExternalPluginError(
                f"Invalid {APP_NAME} version requirement {app_version_specifier!r}."
            ) from exc

        release = version.release
        upper_index = 0 if len(release) == 1 else 1
        upper_release = cls._bump_release_component(release, upper_index)
        return (f">={version}", f"<{cls._format_release(upper_release)}")

    @classmethod
    def _normalize_app_version_specifier(cls, app_version_specifier: str) -> str:
        clauses: list[str] = []
        for raw_clause in app_version_specifier.split(","):
            clause = raw_clause.strip()
            if not clause:
                continue
            if clause.startswith("^"):
                clauses.extend(cls._expand_caret_specifier(clause[1:], app_version_specifier))
                continue
            if clause.startswith("~") and not clause.startswith("~="):
                clauses.extend(cls._expand_tilde_specifier(clause[1:], app_version_specifier))
                continue
            clauses.append(clause)

        if not clauses:
            raise ExternalPluginError(f"Invalid {APP_NAME} version requirement {app_version_specifier!r}.")
        return ",".join(clauses)

    @classmethod
    def _is_plugin_compatible(cls, app_version_specifier: str) -> bool:
        try:
            specifier_set = SpecifierSet(cls._normalize_app_version_specifier(app_version_specifier))
            app_version = Version(__version__)
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise ExternalPluginError(
                f"Invalid {APP_NAME} version requirement {app_version_specifier!r}."
            ) from exc
        return specifier_set.contains(app_version, prereleases=True)

    def _write_source(self, source: PluginSource) -> None:
        self.sources[source.source_id] = source

    def _fallback_entry(self, metadata: InstalledSourcePluginMetadata) -> ExternalPluginCatalogEntry | None:
        if metadata.catalog_entry is None:
            return None
        if not self._is_plugin_compatible(metadata.catalog_entry.app_version_specifier):
            return None
        return replace(
            metadata.catalog_entry,
            installed_version=metadata.version,
            installed_folder_hash=metadata.folder_hash,
            update_available=False,
        )

    @staticmethod
    def _normalize_manifest_url(manifest_url: str) -> str:
        parsed = urlparse(manifest_url)
        require_safe_plugin_source_url(manifest_url)
        if parsed.scheme in ("http", "https"):
            remote_source_url = _RemotePluginSourceUrl.from_manifest_url(manifest_url)
            if remote_source_url is not None:
                return remote_source_url.manifest_url

            remote_repo_url = _RemotePluginSourceUrl.from_repo_url(manifest_url)
            if remote_repo_url is not None:
                return remote_repo_url.manifest_url

            normalized_path = parsed.path.rstrip("/")
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
            validate_plugin_archive_members(members)
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
    def _plugin_namespace(bundle_id: str, folder_hash: str) -> str:
        normalized_bundle_id = "".join(character if character.isalnum() else "_" for character in bundle_id)
        if not normalized_bundle_id or normalized_bundle_id[0].isdigit():
            normalized_bundle_id = f"bundle_{normalized_bundle_id}"
        return f"bitcoin_safe_external_plugin_{normalized_bundle_id}_{folder_hash}"

    @staticmethod
    def _resolve_plugin_artifact_layout(
        bundle_dir: Path, plugin_spec: PluginMetadataModel
    ) -> _PluginArtifactLayout:
        entrypoint_path = Path(plugin_spec.entrypoint)
        package_name = entrypoint_path.parts[0]
        entrypoint_relative_path = Path(*entrypoint_path.parts[1:])
        package_root = bundle_dir / package_name
        source_package_init = package_root / "__init__.py"
        source_entrypoint = bundle_dir / entrypoint_path
        cache_tag = sys.implementation.cache_tag
        available_tags = sorted(path.name for path in (package_root / "_bytecode").glob("*") if path.is_dir())
        if source_package_init.is_file() and source_entrypoint.is_file():
            return _PluginArtifactLayout(package_name, entrypoint_relative_path, None)
        if cache_tag is None or cache_tag not in available_tags:
            available = ", ".join(available_tags) or "none"
            raise ExternalPluginError(
                f"{bundle_dir.name} has no signed bytecode for cache tag {cache_tag!r}; available: {available}."
            )
        bytecode_root = package_root / "_bytecode" / cache_tag / package_name
        if not (bytecode_root / "__init__.pyc").is_file() or not source_entrypoint.is_file():
            raise ExternalPluginError(f"{bundle_dir.name} has an incomplete signed bytecode artifact layout.")
        return _PluginArtifactLayout(package_name, entrypoint_relative_path, cache_tag)

    def _unload_plugin_namespace(self, namespace: str) -> None:
        finder = self._plugin_finders.pop(namespace, None)
        if finder is not None and finder in sys.meta_path:
            sys.meta_path.remove(finder)
        for module_name in [
            name for name in sys.modules if name == namespace or name.startswith(f"{namespace}.")
        ]:
            sys.modules.pop(module_name, None)

    def _load_module(
        self,
        namespace: str,
        module_name: str,
        plugin_dir: Path,
        layout: _PluginArtifactLayout,
    ) -> ModuleType:
        self._unload_plugin_namespace(namespace)
        finder = _SignedPluginArtifactFinder(namespace, plugin_dir, layout)
        sys.meta_path.insert(0, finder)
        self._plugin_finders[namespace] = finder
        try:
            return importlib.import_module(module_name)
        except Exception:
            self._unload_plugin_namespace(namespace)
            raise

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
