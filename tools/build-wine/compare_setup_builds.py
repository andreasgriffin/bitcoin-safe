#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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
"""Compare Windows installer builds and report the differences.

This helper analyses two build outputs (typically the ``dist`` directory that
contains the ``*-setup.exe`` artefact produced by ``tools/build-wine``) and
highlights why they differ.  The script focuses on information that frequently
causes reproducibility problems:

* the PE/COFF metadata of the ``setup`` executable (section hashes, timestamps,
  overlay size, …),
* the complete file tree that gets bundled into the NSIS installer
  (``dist/bitcoin_safe``), including hashes and timestamps for every
  executable/DLL, and
* assorted contextual information such as the git commit and lock-file hashes
  when a repository is available.

Both inputs can either point directly to a ``*-setup.exe`` file or to the
directory that holds the ``dist`` artefacts.  When the ``dist`` directory is not
available, the script still reports high-level metadata for the installer.  The
output is text designed for humans, but a JSON export is also available when the
``--json`` option is supplied so the results can be archived in CI logs.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import import_module, util
from pathlib import Path
from typing import Any, TypedDict, cast


def _load_pefile_module() -> Any | None:
    """Load pefile module."""
    spec = util.find_spec("pefile")
    if spec is None:
        return None
    return import_module("pefile")


pefile: Any | None = _load_pefile_module()


class PESectionInfo(TypedDict):
    """Metadata describing a section inside a PE file."""

    name: str
    virtual_address: int
    virtual_size: int
    raw_size: int
    sha256: str
    entropy: float
    characteristics: int


class PEOverlayInfo(TypedDict):
    """Information about the overlay appended to a PE file."""

    offset: int
    size: int
    sha256: str


class PEMetadataBase(TypedDict):
    """Fields always present in :class:`PEMetadata`."""

    available: bool


class PEMetadata(PEMetadataBase, total=False):
    """Metadata returned by :func:`_pe_metadata`."""

    timestamp: int
    timestamp_iso: str
    image_checksum: int
    image_size: int
    characteristics: int
    sections: list[PESectionInfo]
    overlay: PEOverlayInfo | None


class DistFileEntryRequired(TypedDict):
    """Fields required for every file entry inside a dist manifest."""

    path: str
    size: int
    sha256: str
    mtime: str


class DistFileEntry(DistFileEntryRequired, total=False):
    """Optional PE-specific metadata for a dist manifest entry."""

    pe_timestamp: int
    pe_timestamp_iso: str


class DistManifest(TypedDict):
    """Describes the payload directory bundled by NSIS."""

    path: str
    file_count: int
    total_size: int
    tree_hash: str
    files: list[DistFileEntry]


class SetupInfo(TypedDict):
    """Information about the installer executable."""

    path: str
    size: int
    mtime: str
    sha256: str
    pe: PEMetadata


class BuildManifest(TypedDict):
    """High-level description of a build produced by :func:`_build_manifest`."""

    setup: SetupInfo
    context: dict[str, object]
    dist: DistManifest | None


@dataclass(frozen=True)
class BuildPaths:
    """Resolved artefact paths for one build."""

    base: Path
    setup: Path
    dist: Path | None


def _format_dt(timestamp: float) -> str:
    """Format dt."""
    return _dt.datetime.utcfromtimestamp(timestamp).isoformat(timespec="seconds") + "Z"


def _sha256_file(path: Path) -> str:
    """Sha256 file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_build_paths(raw: Path, override_dist: Path | None = None) -> BuildPaths:
    """Discover the installer and dist directory for a build."""

    raw = raw.resolve()
    if raw.is_file():
        setup_path = raw
        base_dir = setup_path.parent
    else:
        base_dir = raw
        setup_candidates = sorted(base_dir.glob("**/*-setup.exe"))
        if not setup_candidates:
            raise FileNotFoundError(f"Unable to find a *-setup.exe inside {raw}")
        setup_path = max(
            setup_candidates,
            key=lambda path: (path.stat().st_mtime, -len(path.parts), path.name),
        )

    dist_dir: Path | None
    if override_dist is not None:
        dist_dir = override_dist.resolve()
    else:
        # Try typical layouts produced by tools/build-wine/build_exe.sh
        default_candidates = [
            base_dir / "bitcoin_safe",
            base_dir / "dist" / "bitcoin_safe",
            setup_path.parent / "bitcoin_safe",
        ]
        dist_dir = next((candidate for candidate in default_candidates if candidate.is_dir()), None)

    return BuildPaths(base=base_dir, setup=setup_path, dist=dist_dir)


def _pe_metadata(path: Path) -> PEMetadata:
    """Pe metadata."""
    if pefile is None:
        return {"available": False}

    pe = pefile.PE(str(path), fast_load=False)
    metadata: PEMetadata = {
        "available": True,
        "timestamp": pe.FILE_HEADER.TimeDateStamp,
        "timestamp_iso": _format_dt(float(pe.FILE_HEADER.TimeDateStamp)),
        "image_checksum": int(pe.OPTIONAL_HEADER.CheckSum),
        "image_size": int(pe.OPTIONAL_HEADER.SizeOfImage),
        "characteristics": int(pe.FILE_HEADER.Characteristics),
    }

    sections: list[PESectionInfo] = []
    for section in pe.sections:
        name = section.Name.rstrip(b"\x00").decode(errors="ignore")
        data = section.get_data()
        sections.append(
            {
                "name": name,
                "virtual_address": int(section.VirtualAddress),
                "virtual_size": int(section.Misc_VirtualSize),
                "raw_size": int(section.SizeOfRawData),
                "sha256": hashlib.sha256(data).hexdigest(),
                "entropy": float(section.get_entropy()),
                "characteristics": int(section.Characteristics),
            }
        )
    metadata["sections"] = sections

    overlay_offset = pe.get_overlay_data_start_offset()
    if overlay_offset is not None:
        overlay_data = pe.__data__[overlay_offset:]
        metadata["overlay"] = {
            "offset": int(overlay_offset),
            "size": len(overlay_data),
            "sha256": hashlib.sha256(overlay_data).hexdigest(),
        }
    else:
        metadata["overlay"] = None

    pe.close()
    return metadata


def _gather_setup_info(path: Path) -> SetupInfo:
    """Gather setup info."""
    stat = path.stat()
    info: SetupInfo = {
        "path": str(path),
        "size": stat.st_size,
        "mtime": _format_dt(stat.st_mtime),
        "sha256": _sha256_file(path),
        "pe": _pe_metadata(path),
    }
    return info


def _is_probably_pe(path: Path) -> bool:
    """Is probably pe."""
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        signature = handle.read(2)
    return signature == b"MZ"


def _pe_timestamp(path: Path) -> int | None:
    """Pe timestamp."""
    if pefile is None:
        return None
    pe = pefile.PE(str(path), fast_load=True)
    timestamp = int(pe.FILE_HEADER.TimeDateStamp)
    pe.close()
    return timestamp


def _collect_dist_files(dist_dir: Path) -> DistManifest:
    """Collect dist files."""
    files: list[DistFileEntry] = []
    total_size = 0

    for file_path in sorted(dist_dir.rglob("*")):
        if not file_path.is_file():
            continue

        rel_path = file_path.relative_to(dist_dir).as_posix()
        stat = file_path.stat()
        entry: DistFileEntry = {
            "path": rel_path,
            "size": stat.st_size,
            "sha256": _sha256_file(file_path),
            "mtime": _format_dt(stat.st_mtime),
        }

        if _is_probably_pe(file_path):
            timestamp = _pe_timestamp(file_path)
            if timestamp is not None:
                entry["pe_timestamp"] = timestamp
                entry["pe_timestamp_iso"] = _format_dt(float(timestamp))

        files.append(entry)
        total_size += stat.st_size

    digest = hashlib.sha256()
    for entry in files:
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\0")

    manifest: DistManifest = {
        "path": str(dist_dir),
        "file_count": len(files),
        "total_size": total_size,
        "tree_hash": digest.hexdigest(),
        "files": files,
    }
    return manifest


def _find_repo_root(path: Path) -> Path | None:
    """Find repo root."""
    current = path
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_git_command(repo: Path, args: Sequence[str]) -> str | None:
    """Run git command."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _gather_context(build: BuildPaths) -> dict[str, object]:
    """Gather context."""
    repo_root = _find_repo_root(build.base)
    info: dict[str, object] = {
        "platform": platform.platform(),
        "python_version": sys.version,
        "repo_root": str(repo_root) if repo_root else None,
    }

    if repo_root is not None:
        head = _run_git_command(repo_root, ["rev-parse", "HEAD"])
        describe = _run_git_command(repo_root, ["describe", "--tags", "--dirty", "--always"])
        status = _run_git_command(repo_root, ["status", "--short"])
        info["git"] = {
            "head": head,
            "describe": describe,
            "status_short": status,
        }

        for filename in ("poetry.lock", "pyproject.toml"):
            file_path = repo_root / filename
            if file_path.exists():
                info[f"{filename}_sha256"] = _sha256_file(file_path)

    return info


def _build_manifest(paths: BuildPaths) -> BuildManifest:
    """Build manifest."""
    manifest: BuildManifest = {
        "setup": _gather_setup_info(paths.setup),
        "context": _gather_context(paths),
        "dist": None,
    }

    if paths.dist is not None and paths.dist.is_dir():
        manifest["dist"] = _collect_dist_files(paths.dist)

    return manifest


def _load_or_build(target: Path, override_dist: Path | None = None) -> BuildManifest:
    """Load or build."""
    if target.suffix.lower() == ".json" and target.is_file():
        with target.open("r", encoding="utf-8") as handle:
            return cast(BuildManifest, json.load(handle))

    paths = _resolve_build_paths(target, override_dist)
    return _build_manifest(paths)


def _print_header(title: str) -> None:
    """Print header."""
    print()
    print(title)
    print("=" * len(title))


def _summarise_setup(local: SetupInfo, cloud: SetupInfo) -> None:
    """Summarise setup."""
    _print_header("Setup executable")
    print(f"Local : {local['path']}")
    print(f"Cloud : {cloud['path']}")
    print(f"Local sha256: {local['sha256']}")
    print(f"Cloud sha256: {cloud['sha256']}")
    if local["sha256"] == cloud["sha256"]:
        print("✔ Identical setup executables")
    else:
        print("✘ Setup executables differ")
        print(f"Size     : {local['size']} vs {cloud['size']}")
        print(f"Modified : {local['mtime']} vs {cloud['mtime']}")

    local_pe = local["pe"]
    cloud_pe = cloud["pe"]
    if not (local_pe["available"] and cloud_pe["available"]):
        print("pefile is not available, PE comparison skipped")
        return

    def describe_overlay(pe_info: PEMetadata) -> str:
        """Describe overlay."""
        overlay = pe_info.get("overlay")
        if overlay is None:
            return "<none>"
        return f"size={overlay['size']} sha256={overlay['sha256']}"

    print("PE timestamp :", local_pe.get("timestamp_iso"), "|", cloud_pe.get("timestamp_iso"))
    print("PE checksum  :", local_pe.get("image_checksum"), "|", cloud_pe.get("image_checksum"))
    print("PE overlay   :", describe_overlay(local_pe), "|", describe_overlay(cloud_pe))

    local_sections_data = local_pe.get("sections")
    cloud_sections_data = cloud_pe.get("sections")
    local_sections = {entry["name"]: entry for entry in local_sections_data} if local_sections_data else {}
    cloud_sections = {entry["name"]: entry for entry in cloud_sections_data} if cloud_sections_data else {}
    section_names = sorted(set(local_sections) | set(cloud_sections))

    changed: list[str] = []
    missing_local: list[str] = []
    missing_cloud: list[str] = []
    for name in section_names:
        a = local_sections.get(name)
        b = cloud_sections.get(name)
        if a is None:
            missing_local.append(name)
            continue
        if b is None:
            missing_cloud.append(name)
            continue
        if a["sha256"] != b["sha256"] or a["raw_size"] != b["raw_size"]:
            changed.append(name)

    if not (changed or missing_local or missing_cloud):
        print("PE sections : identical")
        return

    print("PE section differences:")
    for name in changed:
        a = local_sections[name]
        b = cloud_sections[name]
        print(f"  {name}: sha256 {a['sha256']} vs {b['sha256']} | size {a['raw_size']} vs {b['raw_size']}")
    for name in missing_local:
        print(f"  {name}: missing in local build")
    for name in missing_cloud:
        print(f"  {name}: missing in cloud build")


def _summarise_dist(local: DistManifest | None, cloud: DistManifest | None, *, limit: int = 30) -> None:
    """Summarise dist."""
    _print_header("NSIS payload (dist/bitcoin_safe)")
    if local is None or cloud is None:
        print("dist directory missing for one of the builds; skipping file comparison")
        return

    print(f"Local tree hash: {local['tree_hash']}")
    print(f"Cloud tree hash: {cloud['tree_hash']}")
    if local["tree_hash"] == cloud["tree_hash"]:
        print("✔ The payload directory is identical")
        return

    local_files = {entry["path"]: entry for entry in local["files"]}
    cloud_files = {entry["path"]: entry for entry in cloud["files"]}

    only_local = sorted(set(local_files) - set(cloud_files))
    only_cloud = sorted(set(cloud_files) - set(local_files))
    changed: list[str] = []

    for path_key in sorted(set(local_files) & set(cloud_files)):
        a = local_files[path_key]
        b = cloud_files[path_key]
        if a["sha256"] != b["sha256"]:
            changed.append(path_key)

    def _print_sample(title: str, entries: Iterable[str]) -> None:
        """Print sample."""
        entries_list = list(entries)
        if not entries_list:
            return
        print(title)
        for path_key in entries_list[:limit]:
            print("  -", path_key)
        if len(entries_list) > limit:
            print(f"  … {len(entries_list) - limit} more")

    _print_sample("Files only present in local build:", only_local)
    _print_sample("Files only present in cloud build:", only_cloud)

    if changed:
        print("Files that differ:")
        for path_key in changed[:limit]:
            a = local_files[path_key]
            b = cloud_files[path_key]
            extra = ""
            if "pe_timestamp_iso" in a or "pe_timestamp_iso" in b:
                extra = f" (PE timestamp {a.get('pe_timestamp_iso')} vs {b.get('pe_timestamp_iso')})"
            print(
                f"  - {path_key}: size {a['size']} vs {b['size']}, sha256 {a['sha256']} vs {b['sha256']}{extra}"
            )
        if len(changed) > limit:
            print(f"  … {len(changed) - limit} more differing files")


def _dump_json(manifest: BuildManifest, destination: Path) -> None:
    """Dump json."""
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", required=True, type=Path, help="Local build directory or installer")
    parser.add_argument("--cloud", required=True, type=Path, help="Cloud build directory or installer")
    parser.add_argument("--local-dist", type=Path, help="Override dist directory for local build")
    parser.add_argument("--cloud-dist", type=Path, help="Override dist directory for cloud build")
    parser.add_argument("--local-json", type=Path, help="Write the local manifest to this path")
    parser.add_argument("--cloud-json", type=Path, help="Write the cloud manifest to this path")
    parser.add_argument(
        "--limit", type=int, default=30, help="Maximum number of differing files to list per category"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Main."""
    args = parse_args(argv)

    local_manifest = _load_or_build(args.local, args.local_dist)
    cloud_manifest = _load_or_build(args.cloud, args.cloud_dist)

    if args.local_json:
        _dump_json(local_manifest, args.local_json)
    if args.cloud_json:
        _dump_json(cloud_manifest, args.cloud_json)

    _summarise_setup(local_manifest["setup"], cloud_manifest["setup"])
    _summarise_dist(local_manifest["dist"], cloud_manifest["dist"], limit=args.limit)

    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation script
    raise SystemExit(main())
