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
from typing import Any

import tomllib  # pyright: ignore[reportMissingImports]
import yaml
from btcpay_tools.config import BTCPayConfig
from PyQt6.QtCore import QTranslator
from PyQt6.QtWidgets import QApplication

from bitcoin_safe.config import UserConfig

BYTECODE_DIRECTORY_NAME = "_bytecode"


def resolve_external_plugin_package_root(module_file: str, package_name: str) -> Path:
    module_path = Path(module_file).resolve()
    for parent in module_path.parents:
        if parent.name != BYTECODE_DIRECTORY_NAME:
            continue
        package_root = parent.parent
        if package_root.name != package_name:
            raise ValueError(
                f"Expected package root {package_name!r} above {BYTECODE_DIRECTORY_NAME!r}, got {package_root}"
            )
        return package_root

    package_root = module_path.parent
    if package_root.name != package_name:
        raise ValueError(f"Could not resolve package root {package_name!r} from {module_path}")
    return package_root


def _load_btcpay_config_from_mapping(data: Any, source_path: Path) -> BTCPayConfig:
    if not isinstance(data, dict):
        raise RuntimeError(f"{source_path} must contain a mapping")

    btcpay_data = data.get("btcpay")
    if not isinstance(btcpay_data, dict):
        raise RuntimeError(f"{source_path} must define a 'btcpay' mapping")

    try:
        return BTCPayConfig.model_validate(btcpay_data)
    except Exception as exc:
        raise RuntimeError(f"{source_path} has invalid 'btcpay' config: {exc}") from exc


def load_external_plugin_btcpay_config(package_root: Path) -> BTCPayConfig:
    plugin_manifest_path = package_root / "plugin.yaml"
    if plugin_manifest_path.is_file():
        manifest_data = yaml.safe_load(plugin_manifest_path.read_text(encoding="utf-8"))
        return _load_btcpay_config_from_mapping(manifest_data, plugin_manifest_path)

    pyproject_path = package_root.parent / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        plugin_data = (
            pyproject_data.get("tool", {}).get("bitcoin_safe", {}).get("plugin")
            if isinstance(pyproject_data, dict)
            else None
        )
        return _load_btcpay_config_from_mapping(plugin_data, pyproject_path)

    raise RuntimeError(
        f"Could not locate BTCPay config for {package_root}. "
        f"Expected {plugin_manifest_path} or {pyproject_path}."
    )


class ExternalPluginResources:
    def __init__(
        self,
        module_file: str,
        package_name: str,
        config: UserConfig,
        locale_prefix: str | None = None,
    ) -> None:
        self.config = config
        self.package_name = package_name
        self.locale_prefix = locale_prefix or "app"
        self.package_root = resolve_external_plugin_package_root(
            module_file=module_file,
            package_name=package_name,
        )
        self.btcpay_config = load_external_plugin_btcpay_config(self.package_root)
        self.icons_dir = self.package_root / "icons"
        self.locales_dir = self.package_root / "locales"
        self._translator: QTranslator | None = None

        self.reload_translator()

    def reload_translator(self) -> None:
        self._remove_translator()
        app = QApplication.instance()
        if app is None:
            return

        for prefix in self._translation_prefixes():
            translator = QTranslator()
            if translator.load(f"{prefix}_{self.config.language_code}", str(self.locales_dir)):
                app.installTranslator(translator)
                self._translator = translator
                return

    def close(self) -> None:
        self._remove_translator()

    def _translation_prefixes(self) -> tuple[str, ...]:
        prefixes = [self.locale_prefix]
        if self.package_name not in prefixes:
            prefixes.append(self.package_name)
        return tuple(prefixes)

    def _remove_translator(self) -> None:
        if self._translator is None:
            return
        if app := QApplication.instance():
            app.removeTranslator(self._translator)
        self._translator = None
