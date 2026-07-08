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

import hashlib
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import datetime
import json
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from bitcoin_safe.app_metadata import APP_METADATA, resolve_git_tag_date
from tools.build_linux.flathub_flatpak.repo_builder import (
    BUILD_BACKEND_REQUIREMENTS_FILENAME,
    DEFAULT_SOURCE_REPO_URL,
    FLATHUB_FLATPAK_DIR,
    METAINFO_FILENAME,
    NATIVE_GIT_DEPENDENCIES_FILE,
    NORMALIZE_SVG_SCRIPT,
    RUNTIME_REQUIREMENTS_FILENAME,
    SVG_FILENAME,
    ReleaseInfo,
    SourceContext,
    build_requirements_for_tree,
    evaluate_packages,
    is_prerelease_version,
    load_toml,
    log_step,
    read_local_app_version,
    render_requirements,
    resolve_dependency_modules,
    run_command,
)
from tools.release_notes import iter_release_notes, required_release_notes

APP_ID = APP_METADATA.flatpak_app_id
REQUIREMENTS_INPUT_HASH_PREFIX = "# dependency-input-sha256: "


def file_contents_match(first_path: Path, second_path: Path) -> bool:
    return (
        first_path.exists() and second_path.exists() and first_path.read_bytes() == second_path.read_bytes()
    )


def _validate_generated_file(generated_path: Path, tracked_path: Path, description: str) -> None:
    if file_contents_match(generated_path, tracked_path):
        return

    if not tracked_path.exists():
        raise RuntimeError(
            f"Missing tracked {description} at {tracked_path}. "
            "Refresh the tracked Flathub files before generating the manifest repo."
        )

    raise RuntimeError(
        f"Tracked {description} at {tracked_path} is out of date. "
        "Refresh the tracked Flathub files before generating the manifest repo."
    )


def _append_release_notes_description(parent: ET.Element, body: str) -> None:
    body = body.replace("\r\n", "\n").strip()
    if not body:
        return

    trimmed_lines: list[str] = []
    for raw_line in body.splitlines():
        normalized_heading = raw_line.strip().lstrip("#").strip().rstrip(":").casefold()
        if normalized_heading == "check out":
            break
        trimmed_lines.append(raw_line)
    body = "\n".join(trimmed_lines).strip()
    if not body:
        return

    def normalize_inline(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = text.replace("`", "")
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r"(?<!\w)[*_](?!\w)|(?<!\w)[*_](?=\w)|(?<=\w)[*_](?!\w)", "", text)
        return re.sub(r"\s+", " ", text).strip()

    description = ET.SubElement(parent, "description")
    lines = body.splitlines()
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    in_code_block = False

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            text = normalize_inline(" ".join(paragraph_lines))
            if text:
                ET.SubElement(description, "p").text = text
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            unordered_list = ET.SubElement(description, "ul")
            for item in list_items:
                ET.SubElement(unordered_list, "li").text = normalize_inline(item)
            list_items = []

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line.startswith(("- ", "* ")):
            flush_paragraph()
            list_items.append(line[2:].strip())
            continue
        if re.match(r"^\d+\.\s+", line):
            flush_paragraph()
            list_items.append(re.sub(r"^\d+\.\s+", "", line))
            continue
        if line.startswith("#"):
            flush_paragraph()
            flush_list()
            heading = line.lstrip("#").strip()
            if heading:
                ET.SubElement(description, "p").text = normalize_inline(heading)
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()

    if len(description) == 0:
        parent.remove(description)


def _indent_xml(element: ET.Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in element:
            _indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


def _release_sort_key(version: str, date: str) -> tuple[Version, str]:
    try:
        parsed_version = Version(version)
    except InvalidVersion:
        parsed_version = Version("0")
    return parsed_version, date


def _is_release_version(version: str) -> bool:
    try:
        Version(version)
    except InvalidVersion:
        return False
    return True


def tracked_metainfo_path() -> Path:
    return FLATHUB_FLATPAK_DIR / METAINFO_FILENAME


def tracked_svg_path() -> Path:
    return FLATHUB_FLATPAK_DIR / SVG_FILENAME


def tracked_normalizer_path() -> Path:
    return FLATHUB_FLATPAK_DIR / NORMALIZE_SVG_SCRIPT


def tracked_build_backend_requirements_path() -> Path:
    return FLATHUB_FLATPAK_DIR / BUILD_BACKEND_REQUIREMENTS_FILENAME


def tracked_runtime_requirements_path() -> Path:
    return FLATHUB_FLATPAK_DIR / RUNTIME_REQUIREMENTS_FILENAME


def requirements_input_hash(tree_root: Path) -> str:
    digest = hashlib.sha256()
    for name, path in (
        ("poetry.lock", tree_root / "poetry.lock"),
        ("tools/native_git_dependencies.sh", NATIVE_GIT_DEPENDENCIES_FILE),
        ("tools/build_linux/flathub_flatpak/repo_builder.py", Path(__file__).with_name("repo_builder.py")),
        ("tools/build_linux/flathub_flatpak/tracked_repo_files.py", Path(__file__)),
    ):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(
        json.dumps(
            {"build-system-requires": build_requirements_for_tree(tree_root)},
            sort_keys=True,
        ).encode("utf-8")
    )
    return digest.hexdigest()


def requirements_input_hash_comment(tree_root: Path) -> str:
    return f"{REQUIREMENTS_INPUT_HASH_PREFIX}{requirements_input_hash(tree_root)}"


def tracked_requirements_match_current_inputs(tree_root: Path) -> bool:
    expected_comment = requirements_input_hash_comment(tree_root)
    for path in (tracked_build_backend_requirements_path(), tracked_runtime_requirements_path()):
        if not path.exists():
            return False
        first_line = path.read_text(encoding="utf-8").splitlines()[:1]
        if not first_line or first_line[0] != expected_comment:
            return False
    return True


def tracked_release_date_for_version(version: str) -> str | None:
    metainfo_path = tracked_metainfo_path()
    if not metainfo_path.exists():
        return None

    root = ET.fromstring(metainfo_path.read_text(encoding="utf-8"))
    releases_node = root.find("releases")
    if releases_node is None:
        return None

    for release_node in releases_node.findall("release"):
        if release_node.get("version") == version:
            return release_node.get("date")
    return None


def resolve_local_release_date(tree_root: Path, version: str) -> str:
    tagged_release_date = resolve_git_tag_date(tree_root, version)
    if tagged_release_date:
        return tagged_release_date

    existing_release_date = tracked_release_date_for_version(version)
    if existing_release_date:
        return existing_release_date

    return datetime.date.today().isoformat()


def build_local_refresh_context(repo_url: str, tree_root: Path) -> SourceContext:
    app_version = read_local_app_version(tree_root)
    required_release_notes(tree_root, app_version)
    release_date = resolve_local_release_date(tree_root, app_version)
    log_step(f"Using local release metadata for version {app_version} dated {release_date}")
    return SourceContext(
        repo_url=repo_url,
        release=ReleaseInfo(
            source_repo_url=repo_url,
            tag_name=app_version,
            published_at=f"{release_date}T00:00:00Z",
            prerelease=is_prerelease_version(app_version),
            tarball_url="",
            html_url=repo_url,
            body="",
        ),
        tree_root=tree_root,
        app_version=app_version,
    )


def write_metainfo(template_path: Path, output_path: Path, context: SourceContext) -> None:
    shared_metainfo = APP_METADATA.render_checked_in_metainfo(
        existing_content=template_path.read_text(encoding="utf-8"),
        launchable_desktop_id=f"{APP_METADATA.flatpak_app_id}.desktop",
        release_date=context.release.date,
    )
    root = ET.fromstring(shared_metainfo)
    releases_node = root.find("releases")
    if releases_node is None:
        releases_node = ET.SubElement(root, "releases")
        existing_release_nodes: list[ET.Element] = []
    else:
        existing_release_nodes = [
            release
            for release in releases_node.findall("release")
            if release.get("version") and not is_prerelease_version(release.get("version", ""))
        ]
        releases_node.clear()

    existing_release_dates: dict[str, str] = {}
    current_version = context.app_version
    for release_node in existing_release_nodes:
        version = release_node.get("version")
        date = release_node.get("date")
        if version and date:
            existing_release_dates[version] = date

    release_nodes_by_version: dict[str, ET.Element] = {}
    for release_notes in iter_release_notes(context.tree_root):
        if is_prerelease_version(release_notes.version):
            continue
        if release_notes.version == current_version:
            release_date = context.release.date
        else:
            stored_release_date = existing_release_dates.get(release_notes.version)
            if not stored_release_date:
                raise RuntimeError(
                    f"Missing release date for {release_notes.version} in tracked Flathub metainfo."
                )
            release_date = stored_release_date
        release_element = ET.Element(
            "release",
            {
                "version": release_notes.version,
                "date": release_date,
            },
        )
        _append_release_notes_description(release_element, release_notes.body)
        release_nodes_by_version[release_notes.version] = release_element

    if (
        _is_release_version(current_version)
        and not context.release.prerelease
        and not is_prerelease_version(current_version)
        and current_version not in release_nodes_by_version
    ):
        release_nodes_by_version[current_version] = ET.Element(
            "release",
            {
                "version": current_version,
                "date": context.release.date,
            },
        )

    sorted_release_nodes = sorted(
        release_nodes_by_version.values(),
        key=lambda release: _release_sort_key(
            release.get("version", "0"),
            release.get("date", ""),
        ),
        reverse=True,
    )
    for release_node in sorted_release_nodes:
        releases_node.append(release_node)

    _indent_xml(root)
    output_path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n{ET.tostring(root, encoding="unicode")}\n',
        encoding="utf-8",
    )


def refresh_normalized_svg(tree_root: Path, output_svg: Path) -> None:
    source_svg = tree_root / "tools/resources/icon.svg"
    normalizer = tracked_normalizer_path()
    log_step(f"Refreshing normalized SVG {output_svg}")
    run_command(
        [sys.executable, str(normalizer), str(source_svg), str(output_svg)],
        tree_root,
        description="Normalizing app SVG canvas to a square upstream build artifact",
    )


def validate_tracked_generated_assets(context: SourceContext) -> None:
    tracked_svg = tracked_svg_path()
    tracked_metainfo = tracked_metainfo_path()
    tracked_svg.parent.mkdir(parents=True, exist_ok=True)
    tracked_metainfo.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bitcoin-safe-flathub-assets-") as tempdir_name:
        tempdir = Path(tempdir_name)
        generated_svg = tempdir / SVG_FILENAME
        generated_metainfo = tempdir / METAINFO_FILENAME

        refresh_normalized_svg(context.tree_root, generated_svg)
        write_metainfo(tracked_metainfo, generated_metainfo, context)
        _validate_generated_file(generated_svg, tracked_svg, "Flathub SVG asset")
        _validate_generated_file(generated_metainfo, tracked_metainfo, "Flathub metainfo asset")


def refresh_tracked_generated_assets(context: SourceContext) -> None:
    tracked_svg = tracked_svg_path()
    tracked_metainfo = tracked_metainfo_path()
    tracked_svg.parent.mkdir(parents=True, exist_ok=True)
    tracked_metainfo.parent.mkdir(parents=True, exist_ok=True)
    refresh_normalized_svg(context.tree_root, tracked_svg)
    log_step(f"Refreshed tracked Flathub SVG asset at {tracked_svg}")
    write_metainfo(tracked_metainfo, tracked_metainfo, context)
    log_step(f"Refreshed tracked Flathub metainfo asset at {tracked_metainfo}")


def validate_tracked_dependency_requirements(
    backend_packages: list[dict[str, Any]],
    runtime_packages: list[dict[str, Any]],
    requirements_header_comment: str | None = None,
) -> None:
    tracked_paths = [
        (
            tracked_build_backend_requirements_path(),
            backend_packages,
            "Flathub build backend requirements",
        ),
        (
            tracked_runtime_requirements_path(),
            runtime_packages,
            "Flathub runtime requirements",
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="bitcoin-safe-flathub-requirements-") as tempdir_name:
        tempdir = Path(tempdir_name)
        for tracked_path, packages, description in tracked_paths:
            tracked_path.parent.mkdir(parents=True, exist_ok=True)
            generated_path = tempdir / tracked_path.name
            render_requirements(generated_path, packages, header_comment=requirements_header_comment)
            _validate_generated_file(generated_path, tracked_path, description)


def refresh_tracked_dependency_requirements(
    backend_packages: list[dict[str, Any]],
    runtime_packages: list[dict[str, Any]],
    requirements_header_comment: str | None = None,
) -> None:
    tracked_paths = [
        (
            tracked_build_backend_requirements_path(),
            backend_packages,
            "Flathub build backend requirements",
        ),
        (
            tracked_runtime_requirements_path(),
            runtime_packages,
            "Flathub runtime requirements",
        ),
    ]
    for tracked_path, packages, description in tracked_paths:
        tracked_path.parent.mkdir(parents=True, exist_ok=True)
        render_requirements(tracked_path, packages, header_comment=requirements_header_comment)
        log_step(f"Refreshed tracked {description} at {tracked_path}")


def validate_tracked_dependency_requirements_for_context(context: SourceContext) -> None:
    lock_payload = load_toml(context.tree_root / "poetry.lock")
    main_packages, all_packages = evaluate_packages(lock_payload)
    dependencies = resolve_dependency_modules(context, main_packages, all_packages)
    header_comment = requirements_input_hash_comment(context.tree_root)
    validate_tracked_dependency_requirements(
        dependencies.backend_packages,
        dependencies.runtime_packages,
        requirements_header_comment=header_comment,
    )


def validate_tracked_dependency_requirements_for_tree(
    tree_root: Path,
    repo_url: str = DEFAULT_SOURCE_REPO_URL,
) -> None:
    validate_tracked_dependency_requirements_for_context(
        build_local_refresh_context(repo_url, tree_root.resolve())
    )


def refresh_tracked_files(
    tree_root: Path,
    repo_url: str = DEFAULT_SOURCE_REPO_URL,
) -> None:
    resolved_tree_root = tree_root.resolve()
    context = build_local_refresh_context(repo_url, resolved_tree_root)
    refresh_tracked_files_for_context(context)


def refresh_tracked_files_for_context(context: SourceContext) -> None:
    resolved_tree_root = context.tree_root.resolve()
    log_step(f"Refreshing tracked Flathub files for {context.app_version}")
    refresh_tracked_generated_assets(context)
    if tracked_requirements_match_current_inputs(resolved_tree_root):
        log_step("Skipping tracked dependency requirement refresh because dependency inputs are unchanged")
        return
    lock_payload = load_toml(resolved_tree_root / "poetry.lock")
    main_packages, all_packages = evaluate_packages(lock_payload)
    dependencies = resolve_dependency_modules(context, main_packages, all_packages)
    refresh_tracked_dependency_requirements(
        dependencies.backend_packages,
        dependencies.runtime_packages,
        requirements_header_comment=requirements_input_hash_comment(resolved_tree_root),
    )
