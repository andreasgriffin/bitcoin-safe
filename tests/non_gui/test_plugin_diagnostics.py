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
from pathlib import Path

from bitcoin_safe.plugin_framework.plugin_diagnostics import (
    format_external_plugin_diagnostics_as_text,
)


def test_format_external_plugin_diagnostics_as_text_with_no_plugins(tmp_path: Path) -> None:
    assert (
        format_external_plugin_diagnostics_as_text(config_dir=tmp_path)
        == "External Plugins:\n- none installed"
    )


def test_format_external_plugin_diagnostics_as_text_enriches_installed_plugins(tmp_path: Path) -> None:
    _write_installed_plugin_metadata(
        config_dir=tmp_path,
        bundle_id="scheduled_payments",
        source_id="acme-source",
        version="1.2.3",
        folder_hash="abc123",
        signer="FINGERPRINT",
    )
    _write_source_config(config_dir=tmp_path, source_id="acme-source", display_name="Acme Plugins")
    _write_plugin_pyproject(
        plugin_dir=tmp_path / "plugins" / "installed" / "scheduled_payments",
        bundle_id="scheduled_payments",
        version="1.2.3",
        display_name="Scheduled Payments",
        provider="Acme",
    )

    text = format_external_plugin_diagnostics_as_text(config_dir=tmp_path)

    assert text == (
        "External Plugins:\n"
        "- bundle_id=scheduled_payments, name=Scheduled Payments, provider=Acme, version=1.2.3, "
        "folder_hash=abc123, source_id=acme-source, source=Acme Plugins, verified=yes, signer=FINGERPRINT"
    )


def test_format_external_plugin_diagnostics_as_text_falls_back_without_enrichment(tmp_path: Path) -> None:
    _write_installed_plugin_metadata(
        config_dir=tmp_path,
        bundle_id="foo_tools",
        source_id="foo-source",
        version="0.4.1",
        folder_hash="def456",
        signer=None,
    )

    text = format_external_plugin_diagnostics_as_text(config_dir=tmp_path)

    assert text == (
        "External Plugins:\n"
        "- bundle_id=foo_tools, version=0.4.1, folder_hash=def456, source_id=foo-source, verified=yes"
    )


def test_format_external_plugin_diagnostics_as_text_reports_failed_verification(tmp_path: Path) -> None:
    _write_installed_plugin_metadata(
        config_dir=tmp_path,
        bundle_id="foo_tools",
        source_id="foo-source",
        version="0.4.1",
        folder_hash="def456",
        signer=None,
        last_verification_ok=False,
        last_verification_error="Installed plugin files no longer match the verified manifest.",
    )

    text = format_external_plugin_diagnostics_as_text(config_dir=tmp_path)

    assert "verified=no" in text
    assert "verification_error=Installed plugin files no longer match the verified manifest." in text


def test_format_external_plugin_diagnostics_as_text_skips_invalid_metadata_and_keeps_valid_plugins(
    tmp_path: Path,
) -> None:
    _write_installed_plugin_metadata(
        config_dir=tmp_path,
        bundle_id="scheduled_payments",
        source_id="acme-source",
        version="1.2.3",
        folder_hash="abc123",
        signer="FINGERPRINT",
    )
    repository = _load_plugin_repository(tmp_path)
    installed_plugins = repository.setdefault("installed_plugins", {})
    assert isinstance(installed_plugins, dict)
    installed_plugins["broken-plugin"] = {"bundle_id": "broken-plugin"}
    _write_plugin_repository(tmp_path, repository)

    text = format_external_plugin_diagnostics_as_text(config_dir=tmp_path)

    assert "bundle_id=scheduled_payments" in text
    assert "broken-plugin" not in text


def _write_installed_plugin_metadata(
    config_dir: Path,
    bundle_id: str,
    source_id: str,
    version: str,
    folder_hash: str,
    signer: str | None,
    last_verification_ok: bool = True,
    last_verification_error: str | None = None,
) -> None:
    plugin_dir = config_dir / "plugins" / "installed" / bundle_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    repository = _load_plugin_repository(config_dir)
    installed_plugins = repository.setdefault("installed_plugins", {})
    assert isinstance(installed_plugins, dict)
    installed_plugins[bundle_id] = {
        "__class__": "InstalledSourcePluginMetadata",
        "VERSION": "0.0.1",
        "bundle_id": bundle_id,
        "source_id": source_id,
        "version": version,
        "folder_hash": folder_hash,
        "installed_at": "2026-04-21T00:00:00+00:00",
        "trusted_auto_allow_signer": False,
        "verified_signer_fingerprint": signer,
        "last_verification_ok": last_verification_ok,
        "last_verification_error": last_verification_error,
    }
    _write_plugin_repository(config_dir, repository)


def _write_source_config(config_dir: Path, source_id: str, display_name: str) -> None:
    repository = _load_plugin_repository(config_dir)
    sources = repository.setdefault("sources", {})
    assert isinstance(sources, dict)
    sources[source_id] = {
        "__class__": "PluginSource",
        "VERSION": "0.0.1",
        "source_id": source_id,
        "display_name": display_name,
        "manifest_url": "https://example.invalid/source.toml",
        "pinned_source_public_key": "key",
        "auth_config": {"__class__": "PluginSourceAuthConfig", "VERSION": "0.0.1"},
        "enabled": True,
        "last_seen_source_serial": 1,
        "last_checked_at": None,
        "last_error": None,
    }
    _write_plugin_repository(config_dir, repository)


def _load_plugin_repository(config_dir: Path) -> dict[str, object]:
    repository_path = config_dir / "plugins" / "plugin-repository.json"
    if not repository_path.exists():
        return {
            "__class__": "ExternalPluginRegistry",
            "VERSION": "0.0.1",
            "sources": {},
            "source_catalogs": {},
            "installed_plugins": {},
        }
    data = json.loads(repository_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write_plugin_repository(config_dir: Path, repository: dict[str, object]) -> None:
    repository_path = config_dir / "plugins" / "plugin-repository.json"
    repository_path.parent.mkdir(parents=True, exist_ok=True)
    repository_path.write_text(json.dumps(repository), encoding="utf-8")


def _write_plugin_pyproject(
    plugin_dir: Path,
    bundle_id: str,
    version: str,
    display_name: str,
    provider: str,
) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.poetry]",
                f'name = "{bundle_id}"',
                f'version = "{version}"',
                'description = "Test plugin"',
                'authors = ["Tests <tests@example.com>"]',
                "",
                "[tool.bitcoin_safe.plugin]",
                'schema_version = "1"',
                f'display_name = "{display_name}"',
                f'provider = "{provider}"',
                'plugin_api_version = "1"',
                'entrypoint = "test_plugin/plugin_bundle.py"',
                'bitcoin_safe_version = ">=0.0.0"',
                "",
            ]
        ),
        encoding="utf-8",
    )
