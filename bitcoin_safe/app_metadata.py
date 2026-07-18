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

import datetime
import re
import subprocess
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from bitcoin_safe import __version__
from bitcoin_safe.constants import (
    APP_NAME,
    CONTACT_EMAIL,
    MACOS_BUNDLE_IDENTIFIER,
    MACOS_BUNDLE_NAME,
    WINDOWS_INSTALL_IDENTITY,
)

RELEASE_ENTRY_PATTERN = re.compile(r'(<release\b[^>]*\bversion=")([^"]+)(".*?\bdate=")([^"]+)(".*?/>)')
MANAGED_METAINFO_TAGS = frozenset(
    {
        "id",
        "metadata_license",
        "project_license",
        "name",
        "summary",
        "developer",
        "launchable",
        "description",
        "url",
        "content_rating",
        "branding",
        "categories",
        "keywords",
        "screenshots",
        "releases",
    }
)
PRESERVED_METAINFO_TAGS = frozenset({"releases"})


@dataclass(frozen=True)
class PackagingScreenshotPlaceholders:
    windows: tuple[str, ...]
    flatpak: tuple[str, ...]
    appimage: tuple[str, ...]
    deb: tuple[str, ...]
    mac: tuple[str, ...]


@dataclass(frozen=True)
class ApplicationMetadata:
    application_name: str
    windows_install_identity: str
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
    search_keywords: tuple[str, ...]
    flatpak_app_id: str
    copyright_year_range: str
    macos_camera_usage_description: str
    macos_bundle_name: str
    macos_bundle_identifier: str
    macos_executable_name: str
    source_repository: str
    brand_color_light: str
    brand_color_dark: str
    packaging_screenshot_placeholders: PackagingScreenshotPlaceholders

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
    def desktop_keywords_entry(self) -> str:
        return ";".join(self.search_keywords) + ";"

    @property
    def copyright_notice(self) -> str:
        return f"{self.copyright_year_range} {self.developer_name}"

    @property
    def macos_dmg_volume_name(self) -> str:
        return self.application_name

    @property
    def appstream_screenshot_urls(self) -> tuple[str, ...]:
        return self.packaging_screenshot_placeholders.flatpak

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
            f"Keywords={self.desktop_keywords_entry}",
            f"Comment={self.summary}",
            f"StartupWMClass={self.desktop_startup_wm_class}",
        ]
        return "\n".join(lines) + "\n"

    def render_metainfo(self, launchable_desktop_id: str, release_date: str) -> str:
        paragraphs = "\n".join(f"    <p>{escape(paragraph)}</p>" for paragraph in self.description_paragraphs)
        categories = "\n".join(
            f"    <category>{escape(category)}</category>" for category in self.desktop_categories
        )
        keywords = "\n".join(f"    <keyword>{escape(keyword)}</keyword>" for keyword in self.search_keywords)
        screenshots = self._render_metainfo_screenshots()
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
            "  <branding>\n"
            f'    <color type="primary" scheme_preference="light">{escape(self.brand_color_light)}</color>\n'
            f'    <color type="primary" scheme_preference="dark">{escape(self.brand_color_dark)}</color>\n'
            "  </branding>\n"
            "  <categories>\n"
            f"{categories}\n"
            "  </categories>\n"
            "  <keywords>\n"
            f"{keywords}\n"
            "  </keywords>\n"
            f"{screenshots}"
            "  <releases>\n"
            f'    <release version="{escape(self.version)}" date="{escape(release_date)}"/>\n'
            "  </releases>\n"
            "</component>\n"
        )

    def _render_metainfo_screenshots(self) -> str:
        if not self.appstream_screenshot_urls:
            return ""

        screenshot_entries: list[str] = []
        for index, image_url in enumerate(self.appstream_screenshot_urls):
            screenshot_type_attribute = ' type="default"' if index == 0 else ""
            screenshot_entries.extend(
                (
                    f"    <screenshot{screenshot_type_attribute}>",
                    f"      <image>{escape(image_url)}</image>",
                    "    </screenshot>",
                )
            )

        screenshots = "\n".join(screenshot_entries)
        return f"  <screenshots>\n{screenshots}\n  </screenshots>\n"

    def render_checked_in_metainfo(
        self,
        existing_content: str,
        launchable_desktop_id: str,
        release_date: str,
    ) -> str:
        generated_root = ET.fromstring(self.render_metainfo(launchable_desktop_id, release_date))
        existing_root = ET.fromstring(existing_content)

        preserved_children = [
            deepcopy(child)
            for child in existing_root
            if child.tag in PRESERVED_METAINFO_TAGS or child.tag not in MANAGED_METAINFO_TAGS
        ]

        generated_root[:] = [child for child in generated_root if child.tag not in PRESERVED_METAINFO_TAGS]
        generated_root.extend(preserved_children)

        ET.indent(generated_root, space="  ")
        rendered_xml = ET.tostring(generated_root, encoding="unicode")
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{rendered_xml}\n'

    def render_windows_nsi_defines(self) -> str:
        return (
            "; Generated by .update_version.py. Do not edit manually.\n"
            f'!define PRODUCT_NAME "{self.application_name}"\n'
            f'!define PRODUCT_INSTALL_IDENTITY "{self.windows_install_identity}"\n'
            f'!define PRODUCT_WEB_SITE "{self.homepage}"\n'
            f'!define PRODUCT_PUBLISHER "{self.developer_name}"\n'
            f'!define PRODUCT_SUMMARY "{self.summary}"\n'
            f'!define PRODUCT_INSTALLER_COMMENTS "The installer for {self.application_name}"\n'
            f'!define PRODUCT_COPYRIGHT "{self.copyright_notice}"\n'
            '!define PRODUCT_UNINST_KEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
            '${PRODUCT_INSTALL_IDENTITY}"\n'
        )

    def render_windows_version_info(
        self,
        original_filename: str,
        file_description: str,
        product_version: str | None = None,
        internal_name: str | None = None,
    ) -> str:
        version_text = product_version or self.version
        file_version = self._windows_version_tuple(version_text)
        escaped_company_name = self._python_unicode_literal(self.developer_name)
        escaped_file_description = self._python_unicode_literal(file_description)
        escaped_file_version = self._python_unicode_literal(version_text)
        escaped_homepage = self._python_unicode_literal(self.homepage)
        escaped_internal_name = self._python_unicode_literal(
            internal_name or original_filename.removesuffix(".exe")
        )
        escaped_copyright = self._python_unicode_literal(self.copyright_notice)
        escaped_original_filename = self._python_unicode_literal(original_filename)
        escaped_product_name = self._python_unicode_literal(self.application_name)
        escaped_product_version = self._python_unicode_literal(version_text)
        tuple_text = ", ".join(str(part) for part in file_version)

        return (
            "# UTF-8\n"
            "VSVersionInfo(\n"
            "  ffi=FixedFileInfo(\n"
            f"    filevers=({tuple_text}),\n"
            f"    prodvers=({tuple_text}),\n"
            "    mask=0x3F,\n"
            "    flags=0x0,\n"
            "    OS=0x4,\n"
            "    fileType=0x1,\n"
            "    subtype=0x0,\n"
            "    date=(0, 0)\n"
            "  ),\n"
            "  kids=[\n"
            "    StringFileInfo([\n"
            "      StringTable(\n"
            "        u'040904B0',\n"
            "        [\n"
            f"          StringStruct(u'CompanyName', u'{escaped_company_name}'),\n"
            f"          StringStruct(u'Comments', u'{escaped_homepage}'),\n"
            f"          StringStruct(u'FileDescription', u'{escaped_file_description}'),\n"
            f"          StringStruct(u'FileVersion', u'{escaped_file_version}'),\n"
            f"          StringStruct(u'InternalName', u'{escaped_internal_name}'),\n"
            f"          StringStruct(u'LegalCopyright', u'{escaped_copyright}'),\n"
            f"          StringStruct(u'OriginalFilename', u'{escaped_original_filename}'),\n"
            f"          StringStruct(u'ProductName', u'{escaped_product_name}'),\n"
            f"          StringStruct(u'ProductVersion', u'{escaped_product_version}')\n"
            "        ]\n"
            "      )\n"
            "    ]),\n"
            "    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])\n"
            "  ]\n"
            ")\n"
        )

    def _windows_version_tuple(self, version: str) -> tuple[int, int, int, int]:
        numbers = [int(match) for match in re.findall(r"\d+", version)]
        while len(numbers) < 4:
            numbers.append(0)
        return numbers[0], numbers[1], numbers[2], numbers[3]

    def _python_unicode_literal(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")


def resolve_metainfo_release_date(
    metainfo_path: Path,
    version: str,
    current_date: datetime.date | None = None,
    repository_root: Path | None = None,
) -> str:
    """Resolve the AppStream release date from git tags before falling back."""

    repo_root = repository_root or find_git_repository_root(metainfo_path)
    tagged_release_date = resolve_git_tag_date(repo_root, version) if repo_root else None
    if tagged_release_date:
        return tagged_release_date

    content = metainfo_path.read_text(encoding="utf-8")
    match = RELEASE_ENTRY_PATTERN.search(content)
    if not match:
        return resolve_latest_git_tag_date(repo_root) or (current_date or datetime.date.today()).isoformat()

    current_version = match.group(2)
    current_release_date = match.group(4)
    if current_version == version:
        return current_release_date
    return resolve_latest_git_tag_date(repo_root) or (current_date or datetime.date.today()).isoformat()


def find_git_repository_root(start_path: Path) -> Path | None:
    """Walk upward until a git repository root is found."""

    for candidate in (start_path.resolve(), *start_path.resolve().parents):
        git_path = candidate / ".git"
        if git_path.exists():
            return candidate
    return None


def resolve_git_tag_date(repository_root: Path, version: str) -> str | None:
    """Return the exact tag date for version if that tag exists."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "for-each-ref",
                "--format=%(creatordate:short)",
                f"refs/tags/{version}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    tag_date = result.stdout.strip()
    return tag_date or None


def resolve_latest_git_tag_date(repository_root: Path | None) -> str | None:
    """Return the most recent git tag date when available."""

    if not repository_root:
        return None

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "for-each-ref",
                "--sort=-creatordate",
                "--count=1",
                "--format=%(creatordate:short)",
                "refs/tags",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    tag_date = result.stdout.strip()
    return tag_date or None


APP_METADATA = ApplicationMetadata(
    application_name=APP_NAME,
    windows_install_identity=WINDOWS_INSTALL_IDENTITY,
    desktop_startup_wm_class=APP_NAME,
    summary="Manage your cold storage wallets",
    description_paragraphs=(
        "• Step-by-step Single and Multisig setup",
        "• Support for all major hardware signers (QR, USB, SD-card)",
        "• Private syncing via Compact Block Filters or Electrum servers",
        "• Encrypted multi-device syncing",
        "• Multisig signing collaboration via encrypted chat",
    ),
    developer_name="Andreas Griffin",
    developer_id="org.bitcoin_safe",
    developer_email=CONTACT_EMAIL,
    homepage="https://www.bitcoin-safe.org",
    project_license="GPL-3.0-only",
    metadata_license="CC0-1.0",
    desktop_categories=("Utility", "Finance"),
    search_keywords=(
        "bitcoin",
        "crypto",
        "multisig",
        "wallet",
        "btc",
        "cold wallet",
        "hardware wallet",
        "PSBT",
        "air-gapped",
        "self-custody",
    ),
    flatpak_app_id="org.bitcoin_safe.BitcoinSafe",
    copyright_year_range="2023-2026",
    macos_camera_usage_description=f"{APP_NAME} would like to access the camera to scan QR codes",
    macos_bundle_name=MACOS_BUNDLE_NAME,
    macos_bundle_identifier=MACOS_BUNDLE_IDENTIFIER,
    macos_executable_name="run_Bitcoin_Safe",
    source_repository="https://github.com/andreasgriffin/bitcoin-safe",
    brand_color_light="#f7931a",
    brand_color_dark="#f7931a",
    packaging_screenshot_placeholders=PackagingScreenshotPlaceholders(
        windows=(
            "https://bitcoin-safe.org/packaging_screenshots/win/screenshots%2001.png",
            "https://bitcoin-safe.org/packaging_screenshots/win/screenshots%2002.png",
            "https://bitcoin-safe.org/packaging_screenshots/win/screenshots%2003.png",
            "https://bitcoin-safe.org/packaging_screenshots/win/screenshots%2004.png",
        ),
        flatpak=(
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%201.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%202.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%203.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%204.png",
        ),
        appimage=(
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%201.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%202.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%203.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%204.png",
        ),
        deb=(
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%201.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%202.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%203.png",
            "https://bitcoin-safe.org/packaging_screenshots/flatpak/flatpak%204.png",
        ),
        mac=("https://bitcoin-safe.org/packaging_screenshots/mac/1.png",),
    ),
)
