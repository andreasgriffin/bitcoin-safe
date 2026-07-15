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
from pathlib import Path

from packaging.version import InvalidVersion, Version


RELEASE_NOTES_DIRNAME = "release-notes"


@dataclass(frozen=True)
class ReleaseNotesEntry:
    version: str
    body: str


def release_notes_path(repository_root: Path, version: str) -> Path:
    """Return the checked-in markdown file for a version's release notes."""

    return repository_root / RELEASE_NOTES_DIRNAME / f"{version}.md"


def load_release_notes(repository_root: Path, version: str) -> str | None:
    """Load checked-in release notes if they exist."""

    path = release_notes_path(repository_root, version)
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8").strip()
    return content or None


def required_release_notes(repository_root: Path, version: str) -> str:
    """Load release notes or raise a helpful error."""

    path = release_notes_path(repository_root, version)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing release notes for version {version}. Create {path} before publishing the release."
        )

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(
            f"Release notes file {path} is empty. Add release notes before publishing the release."
        )

    return content


def iter_release_notes(repository_root: Path) -> list[ReleaseNotesEntry]:
    """Return all checked-in release notes sorted from newest to oldest."""

    notes_dir = repository_root / RELEASE_NOTES_DIRNAME
    if not notes_dir.exists():
        return []

    def version_key(path: Path) -> Version:
        try:
            return Version(path.stem)
        except InvalidVersion:
            return Version("0")

    entries: list[ReleaseNotesEntry] = []
    for path in sorted(notes_dir.glob("*.md"), key=version_key, reverse=True):
        body = path.read_text(encoding="utf-8").strip()
        if body:
            entries.append(ReleaseNotesEntry(version=path.stem, body=body))
    return entries
