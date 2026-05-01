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
from pathlib import Path, PurePosixPath

from btcpay_tools.config import BTCPayConfig
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

PLUGIN_PYPROJECT_FILENAME = "pyproject.toml"
SCHEMA_VERSION = "1"


class PluginSourceModelError(Exception):
    pass


class _ModelBase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_schema_version(value: str) -> str:
    if value != SCHEMA_VERSION:
        raise ValueError("unsupported schema_version")
    return value


def _validate_path_component(value: str) -> str:
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("must be a single safe path component")
    return value


def _validate_relative_posix_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("must be a safe relative path")
    return value


class PluginMetadataModel(_ModelBase):
    schema_version: str
    bundle_id: str
    version: str
    display_name: str
    description: str
    provider: str
    plugin_api_version: str
    entrypoint: str
    app_version_specifier: str
    btcpay_config: BTCPayConfig | None = None

    @field_validator(
        "schema_version",
        "bundle_id",
        "version",
        "display_name",
        "description",
        "provider",
        "plugin_api_version",
        "entrypoint",
    )
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("bundle_id")
    @classmethod
    def _validate_bundle_id(cls, value: str) -> str:
        return _validate_path_component(value)

    @field_validator("entrypoint")
    @classmethod
    def _validate_entrypoint(cls, value: str) -> str:
        return _validate_relative_posix_path(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        return _validate_schema_version(value)

    @field_validator("app_version_specifier")
    @classmethod
    def _strip_optional_strings(cls, value: str) -> str:
        return _strip_required(value)


class PoetryModel(_ModelBase):
    name: str
    version: str
    description: str
    authors: list[str] = []

    @field_validator("name", "version", "description")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("authors")
    @classmethod
    def _strip_authors(cls, value: list[str]) -> list[str]:
        stripped_values = [entry.strip() for entry in value if entry.strip()]
        return stripped_values


class ToolPluginModel(_ModelBase):
    schema_version: str
    display_name: str
    plugin_api_version: str
    entrypoint: str
    bitcoin_safe_version: str
    provider: str | None = None
    btcpay: BTCPayConfig | None = None

    @field_validator(
        "schema_version", "display_name", "plugin_api_version", "entrypoint", "bitcoin_safe_version"
    )
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("provider")
    @classmethod
    def _strip_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        return _validate_schema_version(value)


class ToolBitcoinSafeModel(_ModelBase):
    plugin: ToolPluginModel


class ToolModel(_ModelBase):
    poetry: PoetryModel
    bitcoin_safe: ToolBitcoinSafeModel


class PluginPyprojectModel(_ModelBase):
    tool: ToolModel


class SourceManifestPluginModel(_ModelBase):
    bundle_id: str
    folder_hash: str
    release_ref: str

    @field_validator("bundle_id", "folder_hash", "release_ref")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("bundle_id")
    @classmethod
    def _validate_bundle_id(cls, value: str) -> str:
        return _validate_path_component(value)

    @field_validator("release_ref")
    @classmethod
    def _validate_release_ref(cls, value: str) -> str:
        return _validate_relative_posix_path(value)


class SourceManifestModel(_ModelBase):
    schema_version: str
    source_id: str
    display_name: str
    publisher_fingerprint: str | None = None
    source_serial: int
    plugins: list[SourceManifestPluginModel]
    min_app_version: str | None = None
    max_app_version: str | None = None

    @field_validator("schema_version", "source_id", "display_name")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str) -> str:
        return _validate_path_component(value)

    @field_validator("publisher_fingerprint", "min_app_version", "max_app_version")
    @classmethod
    def _strip_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        return _validate_schema_version(value)

    @model_validator(mode="after")
    def _validate_unique_bundle_ids(self) -> SourceManifestModel:
        bundle_ids = [plugin.bundle_id for plugin in self.plugins]
        if len(bundle_ids) != len(set(bundle_ids)):
            raise ValueError("plugins contain duplicate bundle_id values")
        return self

    def to_toml(self) -> str:
        lines: list[str] = [
            f"schema_version = {json.dumps(self.schema_version)}",
            f"source_id = {json.dumps(self.source_id)}",
            f"display_name = {json.dumps(self.display_name)}",
        ]
        if self.publisher_fingerprint is not None:
            lines.append(f"publisher_fingerprint = {json.dumps(self.publisher_fingerprint)}")
        lines.append(f"source_serial = {self.source_serial}")
        if self.min_app_version is not None:
            lines.append(f"min_app_version = {json.dumps(self.min_app_version)}")
        if self.max_app_version is not None:
            lines.append(f"max_app_version = {json.dumps(self.max_app_version)}")

        for plugin in self.plugins:
            lines.append("")
            lines.append("[[plugins]]")
            lines.append(f"bundle_id = {json.dumps(plugin.bundle_id)}")
            lines.append(f"folder_hash = {json.dumps(plugin.folder_hash)}")
            lines.append(f"release_ref = {json.dumps(plugin.release_ref)}")
        return "\n".join(lines) + "\n"

    def write_to_file(self, path: Path) -> Path:
        path.write_text(self.to_toml(), encoding="utf-8")
        return path


def parse_source_manifest(data: object, file_name: str) -> SourceManifestModel:
    try:
        return SourceManifestModel.model_validate(data)
    except ValidationError as exc:
        raise PluginSourceModelError(f"Invalid {file_name}: {exc}") from exc


def parse_plugin_pyproject(data: object, file_name: str) -> PluginMetadataModel:
    try:
        pyproject = PluginPyprojectModel.model_validate(data)
        return PluginMetadataModel(
            schema_version=pyproject.tool.bitcoin_safe.plugin.schema_version,
            bundle_id=pyproject.tool.poetry.name,
            version=pyproject.tool.poetry.version,
            display_name=pyproject.tool.bitcoin_safe.plugin.display_name,
            description=pyproject.tool.poetry.description,
            provider=_plugin_provider(pyproject),
            plugin_api_version=pyproject.tool.bitcoin_safe.plugin.plugin_api_version,
            entrypoint=pyproject.tool.bitcoin_safe.plugin.entrypoint,
            app_version_specifier=pyproject.tool.bitcoin_safe.plugin.bitcoin_safe_version,
            btcpay_config=pyproject.tool.bitcoin_safe.plugin.btcpay,
        )
    except ValidationError as exc:
        raise PluginSourceModelError(f"Invalid {file_name}: {exc}") from exc


def resolve_plugin_metadata_path(plugin_dir: Path) -> Path | None:
    pyproject_path = plugin_dir / PLUGIN_PYPROJECT_FILENAME
    if pyproject_path.exists():
        return pyproject_path
    return None


def _plugin_provider(pyproject: PluginPyprojectModel) -> str:
    if pyproject.tool.bitcoin_safe.plugin.provider:
        return pyproject.tool.bitcoin_safe.plugin.provider
    if pyproject.tool.poetry.authors:
        return pyproject.tool.poetry.authors[0].split("<", 1)[0].strip()
    return pyproject.tool.poetry.name
