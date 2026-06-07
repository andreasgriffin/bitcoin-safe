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

from dataclasses import dataclass
from xml.sax.saxutils import escape

from bitcoin_safe import __version__
from bitcoin_safe.constants import CONTACT_EMAIL


@dataclass(frozen=True)
class ApplicationMetadata:
    application_name: str
    desktop_startup_wm_class: str
    summary: str
    description_paragraphs: tuple[str, ...]
    developer_name: str
    developer_id: str
    developer_email: str
    homepage: str
    project_license: str
    metadata_license: str
    desktop_categories: tuple[str, ...]
    flatpak_app_id: str
    release_date: str
    copyright_year_range: str
    macos_camera_usage_description: str
    macos_executable_name: str
    source_repository: str

    @property
    def version(self) -> str:
        return __version__

    @property
    def maintainer(self) -> str:
        return f"{self.developer_name} <{self.developer_email}>"

    @property
    def desktop_categories_entry(self) -> str:
        return ";".join(self.desktop_categories) + ";"

    @property
    def copyright_notice(self) -> str:
        return f"{self.copyright_year_range} {self.developer_name}"

    @property
    def macos_bundle_name(self) -> str:
        return f"{self.application_name}.app"

    @property
    def macos_dmg_volume_name(self) -> str:
        return self.application_name

    def render_debian_copyright(self, package_name: str) -> str:
        return (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            f"Upstream-Name: {self.application_name}\n"
            f"Upstream-Contact: {self.maintainer}\n"
            f"Source: {self.source_repository}\n"
            f"License: {self.project_license}\n"
            "\n"
            "Files: *\n"
            f"Copyright: {self.copyright_notice}\n"
            f"License: {self.project_license}\n"
            f"Comment: Debian package metadata for {package_name}.\n"
            "\n"
            f"License: {self.project_license}\n"
            " This package is distributed under the GNU General Public License, version 3 only.\n"
            " On Debian systems, the full license text can be found in\n"
            " /usr/share/common-licenses/GPL-3.\n"
        )

    def render_desktop_entry(self, exec_command: str, icon_name: str) -> str:
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={self.application_name}",
            f"Exec={exec_command}",
            f"Icon={icon_name}",
            "Terminal=false",
            f"Categories={self.desktop_categories_entry}",
            f"Comment={self.summary}",
            f"StartupWMClass={self.desktop_startup_wm_class}",
        ]
        return "\n".join(lines) + "\n"

    def render_metainfo(self, launchable_desktop_id: str) -> str:
        paragraphs = "\n".join(f"    <p>{escape(paragraph)}</p>" for paragraph in self.description_paragraphs)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<component type="desktop-application">\n'
            f"  <id>{escape(self.flatpak_app_id)}</id>\n"
            f"  <metadata_license>{escape(self.metadata_license)}</metadata_license>\n"
            f"  <project_license>{escape(self.project_license)}</project_license>\n"
            f"  <name>{escape(self.application_name)}</name>\n"
            f"  <summary>{escape(self.summary)}</summary>\n"
            f'  <developer id="{escape(self.developer_id)}">\n'
            f"    <name>{escape(self.developer_name)}</name>\n"
            "  </developer>\n"
            f'  <launchable type="desktop-id">{escape(launchable_desktop_id)}</launchable>\n'
            "  <description>\n"
            f"{paragraphs}\n"
            "  </description>\n"
            f'  <url type="homepage">{escape(self.homepage)}</url>\n'
            '  <content_rating type="oars-1.1"/>\n'
            "  <categories>\n"
            "    <category>Utility</category>\n"
            "    <category>Finance</category>\n"
            "  </categories>\n"
            "  <releases>\n"
            f'    <release version="{escape(self.version)}" date="{escape(self.release_date)}"/>\n'
            "  </releases>\n"
            "</component>\n"
        )

    def render_legacy_appdata(self, launchable_desktop_id: str) -> str:
        paragraphs = "\n".join(f"    <p>{escape(paragraph)}</p>" for paragraph in self.description_paragraphs)
        desktop_id = launchable_desktop_id.removesuffix(".desktop")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<component type="desktop">\n'
            f"  <id>{escape(desktop_id)}</id>\n"
            f"  <metadata_license>{escape(self.metadata_license)}</metadata_license>\n"
            f"  <project_license>{escape(self.project_license)}</project_license>\n"
            f"  <name>{escape(self.application_name)}</name>\n"
            f"  <summary>{escape(self.summary)}</summary>\n"
            f"  <developer_name>{escape(self.developer_name)}</developer_name>\n"
            f'  <developer id="{escape(self.developer_id)}">\n'
            f"    <name>{escape(self.developer_name)}</name>\n"
            "  </developer>\n"
            f'  <launchable type="desktop-id">{escape(launchable_desktop_id)}</launchable>\n'
            "  <description>\n"
            f"{paragraphs}\n"
            "  </description>\n"
            f'  <url type="homepage">{escape(self.homepage)}</url>\n'
            '  <content_rating type="oars-1.1"/>\n'
            "  <categories>\n"
            "    <category>Utility</category>\n"
            "    <category>Finance</category>\n"
            "  </categories>\n"
            "  <releases>\n"
            f'    <release version="{escape(self.version)}" date="{escape(self.release_date)}"/>\n'
            "  </releases>\n"
            "</component>\n"
        )

    def render_windows_nsi_defines(self) -> str:
        return (
            "; Generated by tools/generate_packaging_metadata.py. Do not edit manually.\n"
            f'!define PRODUCT_NAME "{self.application_name}"\n'
            f'!define PRODUCT_WEB_SITE "{self.homepage}"\n'
            f'!define PRODUCT_PUBLISHER "{self.developer_name}"\n'
            f'!define PRODUCT_SUMMARY "{self.summary}"\n'
            f'!define PRODUCT_INSTALLER_COMMENTS "The installer for {self.application_name}"\n'
            f'!define PRODUCT_COPYRIGHT "{self.copyright_notice}"\n'
            '!define PRODUCT_UNINST_KEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${PRODUCT_NAME}"\n'
        )


APP_METADATA = ApplicationMetadata(
    application_name="Bitcoin Safe",
    desktop_startup_wm_class="Bitcoin Safe",
    summary="A desktop software for managing your cold storage wallets",
    description_paragraphs=(
        "Bitcoin Safe is a bitcoin savings wallet focused on family-friendly multisig setup, hardware signers, and long-term self-custody.",
        "It supports USB, QR, and SD-card hardware wallet workflows, guided setup, PDF backups, transaction visualization, and synchronized labels across devices.",
    ),
    developer_name="Andreas Griffin",
    developer_id="org.bitcoin_safe",
    developer_email=CONTACT_EMAIL,
    homepage="https://www.bitcoin-safe.org",
    project_license="GPL-3.0-only",
    metadata_license="CC0-1.0",
    desktop_categories=("Utility", "Finance"),
    flatpak_app_id="org.bitcoin_safe.BitcoinSafe",
    release_date="2026-06-06",
    copyright_year_range="2023-2026",
    macos_camera_usage_description="Bitcoin Safe would like to access the camera to scan QR codes",
    macos_executable_name="run_Bitcoin_Safe",
    source_repository="https://github.com/andreasgriffin/bitcoin-safe",
)
