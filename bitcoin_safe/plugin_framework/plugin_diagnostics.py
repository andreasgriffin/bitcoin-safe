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

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import appdirs
import tomllib  # pyright: ignore[reportMissingImports]

from bitcoin_safe.plugin_framework.plugin_source_models import (
    parse_plugin_pyproject,
    resolve_plugin_metadata_path,
)

logger = logging.getLogger(__name__)

PLUGIN_REPOSITORY_FILENAME = "plugin-repository.json"


@dataclass(frozen=True)
class ExternalPluginDiagnosticEntry:
    bundle_id: str
    source_id: str
    installed_version: str
    folder_hash: str
    verified_signer_fingerprint: str | None
    last_verification_ok: bool
    last_verification_error: str | None
    source_display_name: str | None
    plugin_display_name: str | None
    provider: str | None


def collect_external_plugin_diagnostics(
    config_dir: Path | None = None,
) -> list[ExternalPluginDiagnosticEntry]:
    """Collect persisted metadata for installed external plugins."""
    resolved_config_dir = config_dir or _default_config_dir()
    installed_dir = resolved_config_dir / "plugins" / "installed"
    repository = _load_plugin_repository(resolved_config_dir)
    source_display_names = _load_source_display_names(repository)
    installed_plugins = _load_installed_plugins(repository)

    entries: list[ExternalPluginDiagnosticEntry] = []
    if not installed_plugins:
        return entries

    for bundle_id_key, metadata in sorted(installed_plugins.items()):
        bundle_id = _read_required_str(metadata, "bundle_id")
        source_id = _read_required_str(metadata, "source_id")
        installed_version = _read_required_str(metadata, "version")
        folder_hash = _read_required_str(metadata, "folder_hash")
        if bundle_id is None or source_id is None or installed_version is None or folder_hash is None:
            logger.warning("Skipping invalid installed plugin metadata for %s.", bundle_id_key)
            continue

        plugin_dir = installed_dir / bundle_id
        plugin_display_name, provider = _load_plugin_display_metadata(plugin_dir)
        entries.append(
            ExternalPluginDiagnosticEntry(
                bundle_id=bundle_id,
                source_id=source_id,
                installed_version=installed_version,
                folder_hash=folder_hash,
                verified_signer_fingerprint=_read_optional_str(metadata, "verified_signer_fingerprint"),
                last_verification_ok=_read_bool(metadata, "last_verification_ok", default=True),
                last_verification_error=_read_optional_str(metadata, "last_verification_error"),
                source_display_name=source_display_names.get(source_id),
                plugin_display_name=plugin_display_name,
                provider=provider,
            )
        )

    return sorted(entries, key=lambda entry: entry.bundle_id)


def format_external_plugin_diagnostics_as_text(config_dir: Path | None = None) -> str:
    """Render external plugin diagnostics as a human-readable text block."""
    try:
        entries = collect_external_plugin_diagnostics(config_dir=config_dir)
    except Exception:
        logger.exception("Could not collect external plugin diagnostics.")
        return "External Plugins:\n- unavailable"

    if not entries:
        return "External Plugins:\n- none installed"

    lines = ["External Plugins:"]
    for entry in entries:
        parts = [f"bundle_id={entry.bundle_id}"]
        if entry.plugin_display_name:
            parts.append(f"name={entry.plugin_display_name}")
        if entry.provider:
            parts.append(f"provider={entry.provider}")
        parts.append(f"version={entry.installed_version}")
        parts.append(f"folder_hash={entry.folder_hash}")
        parts.append(f"source_id={entry.source_id}")
        if entry.source_display_name:
            parts.append(f"source={entry.source_display_name}")
        parts.append(f"verified={'yes' if entry.last_verification_ok else 'no'}")
        if entry.verified_signer_fingerprint:
            parts.append(f"signer={entry.verified_signer_fingerprint}")
        if not entry.last_verification_ok and entry.last_verification_error:
            parts.append(f"verification_error={entry.last_verification_error}")
        lines.append(f"- {', '.join(parts)}")

    return "\n".join(lines)


def _default_config_dir() -> Path:
    """Return the default Bitcoin Safe user config directory."""
    return Path(appdirs.user_config_dir("bitcoin_safe"))


def _load_plugin_repository(config_dir: Path) -> dict[str, object]:
    """Load the persisted external plugin repository JSON from disk."""
    repository_path = config_dir / "plugins" / PLUGIN_REPOSITORY_FILENAME
    if not repository_path.exists():
        return {}
    try:
        data = json.loads(repository_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Skipping invalid plugin repository %s: %s", repository_path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Skipping invalid plugin repository %s.", repository_path)
        return {}
    return data


def _load_installed_plugins(repository: dict[str, object]) -> dict[str, dict[str, object]]:
    """Extract installed plugin metadata entries from the repository dump."""
    raw_installed_plugins = repository.get("installed_plugins")
    if not isinstance(raw_installed_plugins, dict):
        return {}
    installed_plugins: dict[str, dict[str, object]] = {}
    for bundle_id, metadata in raw_installed_plugins.items():
        if isinstance(metadata, dict):
            installed_plugins[str(bundle_id)] = metadata
    return installed_plugins


def _load_source_display_names(repository: dict[str, object]) -> dict[str, str]:
    """Build a map from source id to display name from repository data."""
    source_display_names: dict[str, str] = {}
    sources = repository.get("sources")
    if not isinstance(sources, dict):
        return source_display_names
    for source_key, data in sorted(sources.items()):
        if not isinstance(data, dict):
            logger.warning("Skipping invalid plugin source config for %s.", source_key)
            continue
        source_id = _read_required_str(data, "source_id")
        display_name = _read_required_str(data, "display_name")
        if source_id is None or display_name is None:
            logger.warning("Skipping invalid plugin source config for %s.", source_key)
            continue
        source_display_names[source_id] = display_name
    return source_display_names


def _load_plugin_display_metadata(plugin_dir: Path) -> tuple[str | None, str | None]:
    """Read display name and provider metadata from an installed plugin folder."""
    metadata_path = resolve_plugin_metadata_path(plugin_dir)
    if metadata_path is None:
        return None, None

    try:
        data = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        parsed = parse_plugin_pyproject(data, str(metadata_path))
    except Exception as exc:
        logger.warning("Skipping plugin display metadata %s: %s", metadata_path, exc)
        return None, None
    return parsed.display_name, parsed.provider


def _read_required_str(data: dict[str, object], key: str) -> str | None:
    """Return a non-empty string field or ``None`` if it is missing/invalid."""
    value = data.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _read_optional_str(data: dict[str, object], key: str) -> str | None:
    """Return a stripped string field when present and non-empty."""
    value = data.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _read_bool(data: dict[str, object], key: str, default: bool) -> bool:
    """Return a boolean field or a caller-provided default."""
    value = data.get(key)
    if isinstance(value, bool):
        return value
    return default
