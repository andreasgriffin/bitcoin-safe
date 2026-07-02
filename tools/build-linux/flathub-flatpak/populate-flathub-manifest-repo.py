#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import copy
import errno
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.client import RemoteDisconnected
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError

import tomllib
import yaml
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version


DEFAULT_SOURCE_REPO_URL = "https://github.com/andreasgriffin/bitcoin-safe/"
APP_ID = "org.bitcoin_safe.BitcoinSafe"
APP_NAME = "Bitcoin Safe"
BUNDLE_FILENAME = f"{APP_ID}.flatpak"
FLATPAK_BRANCH = "master"
FLATHUB_KDE_RUNTIME_VERSION = "6.10"
PYQT_BASEAPP_ID = "com.riverbankcomputing.PyQt.BaseApp"
FLATPAK_PYTHON_FULL_VERSION = "3.13.0"
FLATPAK_PYTHON_VERSION = "3.13"
FLATPAK_PYTHON_TAG = "cp313"
PIP_INSTALL_ARGS = "--ignore-installed --no-build-isolation --prefix=${FLATPAK_DEST}"
PIP_OFFLINE_INSTALL_ARGS = (
    '--ignore-installed --no-build-isolation --no-index --find-links="file://${PWD}" --prefix=${FLATPAK_DEST}'
)
RUNTIME_ENV = {
    "implementation_name": "cpython",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_python_implementation": "CPython",
    "platform_release": "",
    "platform_system": "Linux",
    "platform_version": "",
    "python_full_version": FLATPAK_PYTHON_FULL_VERSION,
    "python_version": FLATPAK_PYTHON_VERSION,
    "sys_platform": "linux",
    "extra": "",
}
NAMESPACE = {"": "http://www.freedesktop.org/standards/appstream/1.0"}
MANIFEST_FILENAME = f"{APP_ID}.yml"
VENDOR_ROOT = "/app/share/bitcoin-safe/vendor"
BUILD_BACKEND_VENDOR_DIR = f"{VENDOR_ROOT}/build-backends"
RUNTIME_VENDOR_DIR = f"{VENDOR_ROOT}/runtime"
GIT_VENDOR_DIR = f"{VENDOR_ROOT}/git-packages"
FORCE_SDIST_PACKAGES: set[str] = set()
GIT_RUNTIME_DEPENDENCY_OVERRIDES: dict[str, list[str]] = {
    # bitcoin-safe-lib imports packaging.version.Version at runtime but does not
    # currently declare packaging in its pyproject dependencies.
    "bitcoin-safe-lib": ["packaging"],
}
BASEAPP_OWNED_RUNTIME_PACKAGES = {
    "pyqt-builder",
    "pyqt6",
    "pyqt6-charts-qt6",
    "pyqt6-qt6",
    "pyqt6-sip",
}
RUNTIME_PACKAGE_VERSION_OVERRIDES = {
    # The PyQt BaseApp is currently built on Qt 6.10, so PyQt6-Charts must
    # stay on the matching 6.10 line instead of the lockfile's newer 6.11
    # wheel, which requires Qt_6.11 symbols at runtime.
    "pyqt6-charts": "6.10.0",
}
INTERNAL_GENERATED_DEPENDENCY_MODULES = {
    "build/generated/python3-build-backends.json",
    "build/generated/python3-runtime.json",
    "build/generated/python3-git-packages.json",
}
AppSourceMode = Literal["archive", "local-dir"]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "build" / "generated-repo"
DEFAULT_OUTPUT_DIR_DOC = "tools/build-linux/flathub-flatpak/build/generated-repo"
NORMALIZE_SVG_SCRIPT = "normalize-svg-icon.py"
METAINFO_FILENAME = f"{APP_ID}.metainfo.xml"
SVG_FILENAME = f"{APP_ID}.svg"
HELPER_FILENAMES = [
    "build-flatpak-app.sh",
    "run-bitcoin-safe.sh",
]
NATIVE_GIT_DEPENDENCIES_FILE = Path(__file__).resolve().parents[2] / "native_git_dependencies.sh"
BASE_MANIFEST: dict[str, Any] = {
    "app-id": APP_ID,
    "runtime": "org.kde.Platform",
    "runtime-version": FLATHUB_KDE_RUNTIME_VERSION,
    "sdk": "org.kde.Sdk",
    "base": PYQT_BASEAPP_ID,
    "base-version": FLATHUB_KDE_RUNTIME_VERSION,
    "command": "run-bitcoin-safe.sh",
    "separate-locales": False,
    "build-options": {
        "env": [
            "BASEAPP_REMOVE_WEBENGINE=1",
        ]
    },
    "cleanup-commands": [
        "/app/cleanup-BaseApp.sh",
    ],
    "finish-args": [
        "--share=network",
        "--share=ipc",
        "--socket=wayland",
        "--socket=fallback-x11",
        "--device=all",
        "--filesystem=home",
    ],
}


@dataclass
class ReleaseInfo:
    source_repo_url: str
    tag_name: str
    published_at: str
    prerelease: bool
    tarball_url: str
    html_url: str
    body: str

    @property
    def date(self) -> str:
        return self.published_at[:10]

    @property
    def branch(self) -> str:
        return "beta" if self.prerelease or "rc" in self.tag_name.lower() else "stable"


@dataclass
class SourceContext:
    repo_url: str
    release: ReleaseInfo
    tree_root: Path


@dataclass
class GitHubReleaseNotes:
    tag_name: str
    published_at: str
    prerelease: bool
    body: str

    @property
    def date(self) -> str:
        return self.published_at[:10]

    @property
    def version(self) -> str:
        return self.tag_name.removeprefix("v")


@dataclass(frozen=True)
class NativeGitDependency:
    name: str
    url: str
    commit: str
    tag: str


def github_repo_slug(repo_url: str) -> str:
    parsed = urllib.parse.urlparse(repo_url)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    slug = path.strip("/")
    if slug.count("/") != 1:
        raise ValueError(f"Unsupported repository URL: {repo_url}")
    return slug


def json_request(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "bitcoin-safe-flathub-generator",
        },
    )
    with urlopen_with_retries(request) as response:
        return json.loads(response.read().decode("utf-8"))


def text_request(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "bitcoin-safe-flathub-generator"})
    with urlopen_with_retries(request) as response:
        return response.read().decode("utf-8")


def binary_request(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "bitcoin-safe-flathub-generator"})
    with urlopen_with_retries(request) as response:
        return response.read()


def log_step(message: str) -> None:
    print(f"[populate] {message}", file=sys.stderr)


def urlopen_with_retries(request: urllib.request.Request, *, attempts: int = 4) -> Any:
    delay = 1.0
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return urllib.request.urlopen(request)
        except HTTPError:
            raise
        except (RemoteDisconnected, TimeoutError, URLError, OSError) as error:
            last_error = error
            if attempt == attempts:
                break
            time.sleep(delay)
            delay *= 2
    assert last_error is not None
    raise last_error


def fetch_release(repo_url: str, tag_name: str | None) -> ReleaseInfo:
    if tag_name:
        log_step(f"Fetching release metadata for ref '{tag_name}' from {repo_url}")
    else:
        log_step(f"Fetching latest GitHub release metadata from {repo_url}")
    slug = github_repo_slug(repo_url)
    if tag_name:
        try:
            payload = json_request(f"https://api.github.com/repos/{slug}/releases/tags/{tag_name}")
        except HTTPError as error:
            if error.code != 404:
                raise
            log_step(f"Ref '{tag_name}' is not a GitHub release tag, falling back to commit lookup")
            commit_payload = json_request(f"https://api.github.com/repos/{slug}/commits/{tag_name}")
            commit_sha = commit_payload["sha"]
            commit_date = commit_payload.get("commit", {}).get("committer", {}).get(
                "date"
            ) or commit_payload.get("commit", {}).get("author", {}).get("date")
            if not commit_date:
                raise RuntimeError(f"Unable to determine commit date for {tag_name}")
            return ReleaseInfo(
                source_repo_url=repo_url,
                tag_name=commit_sha,
                published_at=commit_date,
                prerelease=False,
                tarball_url=github_archive_url(repo_url, commit_sha),
                html_url=commit_payload["html_url"],
                body=commit_payload.get("commit", {}).get("message", ""),
            )
    else:
        releases = json_request(f"https://api.github.com/repos/{slug}/releases?per_page=1")
        if not releases:
            raise RuntimeError(f"No releases found for {repo_url}")
        payload = releases[0]
    return ReleaseInfo(
        source_repo_url=repo_url,
        tag_name=payload["tag_name"],
        published_at=payload["published_at"],
        prerelease=bool(payload["prerelease"]),
        tarball_url=github_release_archive_url(repo_url, payload["tag_name"]),
        html_url=payload["html_url"],
        body=payload.get("body", ""),
    )


def fetch_release_notes(repo_url: str) -> list[GitHubReleaseNotes]:
    slug = github_repo_slug(repo_url)
    releases: list[GitHubReleaseNotes] = []
    page = 1
    while True:
        payload = json_request(f"https://api.github.com/repos/{slug}/releases?per_page=100&page={page}")
        if not payload:
            return releases
        for item in payload:
            if item.get("draft", False):
                continue
            releases.append(
                GitHubReleaseNotes(
                    tag_name=item["tag_name"],
                    published_at=item["published_at"],
                    prerelease=bool(item.get("prerelease", False)),
                    body=item.get("body", ""),
                )
            )
        page += 1


def extract_release_tree(release: ReleaseInfo, workdir: Path) -> Path:
    log_step(f"Downloading and extracting source archive for {release.tag_name}")
    archive_path = workdir / f"{release.tag_name}.tar.gz"
    archive_path.write_bytes(binary_request(release.tarball_url))
    with tarfile.open(archive_path) as tar:
        tar.extractall(workdir, filter="data")
    roots = [path for path in workdir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"Expected exactly one extracted root in {workdir}, found {len(roots)}")
    return roots[0]


def build_source_context(
    repo_url: str,
    local_source_checkout: str | None,
    release_tag: str | None,
) -> SourceContext:
    release = fetch_release(repo_url, release_tag)
    if local_source_checkout:
        tree_root = Path(local_source_checkout).resolve()
        log_step(f"Using local source checkout at {tree_root}")
    else:
        tempdir = Path(tempfile.mkdtemp(prefix="bitcoin-safe-flathub-"))
        tree_root = extract_release_tree(release, tempdir)
        log_step(f"Using extracted release tree at {tree_root}")
    log_step(
        "Selected source: "
        f"{release.tag_name} ({'prerelease' if release.prerelease else 'stable'}), "
        f"published {release.date}"
    )
    return SourceContext(repo_url=repo_url, release=release, tree_root=tree_root)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(read_text(path))


def load_toml(path: Path) -> Any:
    return tomllib.loads(read_text(path))


def parse_shell_assignments(path: Path) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line_number, raw_line in enumerate(read_text(path).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z0-9_]+)=(.+)", line)
        if not match:
            raise RuntimeError(f"Unsupported assignment in {path}:{line_number}: {raw_line}")
        key, raw_value = match.groups()
        try:
            value = ast.literal_eval(raw_value)
        except (SyntaxError, ValueError) as error:
            raise RuntimeError(f"Unable to parse {path}:{line_number}: {raw_line}") from error
        if not isinstance(value, str):
            raise RuntimeError(f"Expected string value in {path}:{line_number}: {raw_line}")
        assignments[key] = value
    return assignments


def load_native_git_dependencies(path: Path = NATIVE_GIT_DEPENDENCIES_FILE) -> dict[str, NativeGitDependency]:
    assignments = parse_shell_assignments(path)
    dependencies: dict[str, NativeGitDependency] = {}
    for name in ("hidapi", "zbar"):
        prefix = name.upper()
        dependencies[name] = NativeGitDependency(
            name=name,
            url=assignments[f"{prefix}_URL"],
            commit=assignments[f"{prefix}_COMMIT"],
            tag=assignments[f"{prefix}_TAG"],
        )
    return dependencies


def marker_matches(marker_text: str | dict[str, str] | None) -> bool:
    if isinstance(marker_text, dict):
        marker_text = marker_text.get("main")
    if not marker_text:
        return True
    return Marker(marker_text).evaluate(RUNTIME_ENV)


def normalize_project_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def safe_module_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def choose_artifact(name: str, version: str, file_entries: list[dict[str, str]]) -> dict[str, str]:
    normalized_name = normalize_project_name(name)

    def wheel_score(filename: str) -> tuple[int, str] | None:
        lower = filename.lower()
        if not lower.endswith(".whl"):
            return None
        if "py3-none-any" in lower or "py2.py3-none-any" in lower:
            return (0, lower)
        if f"-{FLATPAK_PYTHON_TAG}-{FLATPAK_PYTHON_TAG}-" in lower and "x86_64" in lower:
            if "manylinux" in lower:
                return (1, lower)
            if "linux" in lower:
                return (2, lower)
        if "abi3" in lower and "x86_64" in lower:
            if "manylinux" in lower:
                return (3, lower)
            if "linux" in lower:
                return (4, lower)
        if "py3-none" in lower and "x86_64" in lower:
            if "manylinux" in lower:
                return (5, lower)
            if "linux" in lower:
                return (6, lower)
        return None

    sdists = sorted(
        (entry for entry in file_entries if entry["file"].lower().endswith((".tar.gz", ".zip", ".tar.bz2"))),
        key=lambda entry: entry["file"].lower(),
    )
    compatible_wheels: list[tuple[tuple[int, str], dict[str, str]]] = []
    for entry in file_entries:
        score = wheel_score(entry["file"])
        if score is None:
            continue
        compatible_wheels.append((score, entry))
    compatible_wheels.sort(key=lambda item: item[0])

    if normalized_name in FORCE_SDIST_PACKAGES and sdists:
        return sdists[0]
    if compatible_wheels:
        return compatible_wheels[0][1]
    if sdists:
        return sdists[0]
    raise RuntimeError(
        f"No compatible artifact found for {name}=={version} with target Python tag {FLATPAK_PYTHON_TAG}"
    )


class PypiIndex:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def release_json(self, name: str, version: str) -> dict[str, Any]:
        key = (normalize_project_name(name), version)
        if key not in self._cache:
            url = f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{urllib.parse.quote(version)}/json"
            self._cache[key] = json.loads(text_request(url))
        return self._cache[key]

    def file_url(self, name: str, version: str, filename: str) -> str:
        payload = self.release_json(name, version)
        for entry in payload["urls"]:
            if entry["filename"] == filename:
                return entry["url"]
        raise RuntimeError(f"Unable to find {filename} in PyPI release {name}=={version}")

    def resolve_version(self, name: str, specifier: str) -> str:
        payload = json.loads(text_request(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json"))
        spec = SpecifierSet(specifier)
        candidates = sorted((Version(item) for item in payload["releases"].keys()), reverse=True)
        for candidate in candidates:
            if spec.contains(candidate, prereleases=True):
                return str(candidate)
        raise RuntimeError(f"No PyPI release of {name} satisfies {specifier}")

    def dependency_specs(self, name: str, version: str) -> set[str]:
        payload = self.release_json(name, version)
        requires_dist = payload.get("info", {}).get("requires_dist") or []
        specs: set[str] = set()
        for raw_requirement in requires_dist:
            requirement = Requirement(raw_requirement)
            if requirement.marker and not requirement.marker.evaluate(RUNTIME_ENV):
                continue
            specs.add(f"{requirement.name}{requirement.specifier}")
        return specs


def artifact_source_entry(
    name: str, version: str, file_entry: dict[str, str], pypi: PypiIndex
) -> dict[str, str]:
    return {
        "type": "file",
        "url": pypi.file_url(name, version, file_entry["file"]),
        "sha256": file_entry["hash"].split(":", 1)[1],
    }


def runtime_package_from_pypi(name: str, version: str, pypi: PypiIndex) -> dict[str, Any]:
    payload = pypi.release_json(name, version)
    files = [
        {"file": entry["filename"], "hash": f"sha256:{entry['digests']['sha256']}"}
        for entry in payload["urls"]
    ]
    chosen_artifact = choose_artifact(name, version, files)
    return {
        "name": name,
        "version": version,
        "chosen_artifact": chosen_artifact,
        "artifact_url": pypi.file_url(name, version, chosen_artifact["file"]),
    }


def dependency_names(package: dict[str, Any]) -> list[str]:
    deps = package.get("dependencies", {})
    if isinstance(deps, dict):
        return list(deps.keys())
    return []


def closure_from_lock(
    lock_packages: dict[str, dict[str, Any]],
    seed_names: set[str],
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        normalized = normalize_project_name(name)
        if normalized in seen or normalized not in lock_packages:
            return
        seen.add(normalized)
        package = lock_packages[normalized]
        if not marker_matches(package.get("markers")):
            return
        for dependency in dependency_names(package):
            visit(dependency)
        ordered.append(package)

    for name in sorted(seed_names):
        visit(name)
    return ordered


def download_sha256(url: str) -> str:
    digest = hashlib.sha256()
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "bitcoin-safe-flathub-generator"})
    ) as response:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def github_archive_url(git_url: str, resolved_reference: str) -> str:
    if git_url.endswith(".git"):
        git_url = git_url[:-4]
    parsed = urllib.parse.urlparse(git_url)
    path = parsed.path.rstrip("/")
    if parsed.netloc != "github.com":
        raise RuntimeError(f"Only GitHub git sources are currently supported, got {git_url}")
    quoted_reference = urllib.parse.quote(resolved_reference, safe="")
    return f"https://github.com{path}/archive/{quoted_reference}.tar.gz"


def github_release_archive_url(repo_url: str, tag_name: str) -> str:
    if repo_url.endswith(".git"):
        repo_url = repo_url[:-4]
    parsed = urllib.parse.urlparse(repo_url)
    path = parsed.path.rstrip("/")
    if parsed.netloc != "github.com":
        raise RuntimeError(f"Only GitHub release sources are currently supported, got {repo_url}")
    quoted_tag = urllib.parse.quote(tag_name, safe="")
    return f"https://github.com{path}/archive/refs/tags/{quoted_tag}.tar.gz"


def extract_archive_to_temp(url: str) -> Path:
    data = binary_request(url)
    tempdir = Path(tempfile.mkdtemp(prefix="bitcoin-safe-src-"))
    archive_path = tempdir / "archive.tar.gz"
    archive_path.write_bytes(data)
    with tarfile.open(archive_path) as tar:
        tar.extractall(tempdir, filter="data")
    roots = [path for path in tempdir.iterdir() if path.is_dir()]
    for root in roots:
        if root.name != archive_path.stem:
            return root
    if roots:
        return roots[0]
    raise RuntimeError(f"Unable to extract archive from {url}")


def build_requirements_for_tree(tree_root: Path) -> list[str]:
    pyproject_path = tree_root / "pyproject.toml"
    if pyproject_path.exists():
        payload = load_toml(pyproject_path)
        build_system = payload.get("build-system", {})
        if build_system:
            return list(build_system.get("requires", []))
    if (tree_root / "setup.py").exists():
        return ["setuptools", "wheel"]
    return []


def backend_name(spec: str) -> str:
    match = re.match(r"([A-Za-z0-9_.-]+)", spec)
    if not match:
        raise RuntimeError(f"Unable to parse backend requirement {spec}")
    return match.group(1)


def resolve_backend_packages(
    lock_packages: dict[str, dict[str, Any]],
    requirement_specs: set[str],
    pypi: PypiIndex,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    seed_names = {backend_name(spec) for spec in requirement_specs}
    for package in closure_from_lock(lock_packages, seed_names):
        file_entry = choose_artifact(package["name"], package["version"], package["files"])
        resolved.append(
            {
                "name": package["name"],
                "version": package["version"],
                "file_entry": file_entry,
                "source": artifact_source_entry(package["name"], package["version"], file_entry, pypi),
            }
        )

    seen: set[str] = {normalize_project_name(item["name"]) for item in resolved}
    pending_specs = sorted(requirement_specs)
    while pending_specs:
        spec = pending_specs.pop(0)
        name = backend_name(spec)
        normalized = normalize_project_name(name)
        if normalized in seen:
            continue
        seen.add(normalized)
        if normalized in lock_packages:
            package = lock_packages[normalized]
            version = package["version"]
            file_entry = choose_artifact(package["name"], version, package["files"])
            resolved.append(
                {
                    "name": package["name"],
                    "version": version,
                    "file_entry": file_entry,
                    "source": artifact_source_entry(package["name"], version, file_entry, pypi),
                }
            )
            continue

        specifier = spec[len(name) :]
        version = pypi.resolve_version(name, specifier or "")
        payload = pypi.release_json(name, version)
        files = [
            {"file": entry["filename"], "hash": f"sha256:{entry['digests']['sha256']}"}
            for entry in payload["urls"]
        ]
        file_entry = choose_artifact(name, version, files)
        resolved.append(
            {
                "name": name,
                "version": version,
                "file_entry": file_entry,
                "source": {
                    "type": "file",
                    "url": pypi.file_url(name, version, file_entry["file"]),
                    "sha256": file_entry["hash"].split(":", 1)[1],
                },
            }
        )
        for dependency_spec in sorted(pypi.dependency_specs(name, version)):
            dependency_name = normalize_project_name(backend_name(dependency_spec))
            if dependency_name in seen:
                continue
            if dependency_spec not in pending_specs:
                pending_specs.append(dependency_spec)
        pending_specs.sort()
    return resolved


def resolve_unique_backend_packages(
    lock_packages: dict[str, dict[str, Any]],
    requirement_specs: set[str],
    pypi: PypiIndex,
) -> list[dict[str, Any]]:
    resolved = resolve_backend_packages(lock_packages, requirement_specs, pypi)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for package in resolved:
        normalized = normalize_project_name(package["name"])
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(package)
    return unique


def collect_backend_specs_from_sdists(
    packages: list[dict[str, Any]],
) -> set[str]:
    specs: set[str] = set()
    for package in packages:
        file_entry = package["file_entry"]
        filename = file_entry["file"].lower()
        if filename.endswith(".whl"):
            continue
        tree_root = extract_archive_to_temp(package["source"]["url"])
        specs.update(build_requirements_for_tree(tree_root))
    return {spec for spec in specs if spec}


def evaluate_packages(lock_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    main_packages: list[dict[str, Any]] = []
    all_packages: dict[str, dict[str, Any]] = {}
    for package in lock_payload["package"]:
        normalized = normalize_project_name(package["name"])
        all_packages[normalized] = package
        if "main" not in package.get("groups", []):
            continue
        if not marker_matches(package.get("markers")):
            continue
        if normalized == normalize_project_name("bitcoin-safe"):
            continue
        main_packages.append(package)
    return main_packages, all_packages


def topological_git_packages(git_packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {normalize_project_name(pkg["name"]): pkg for pkg in git_packages}
    indegree = {name: 0 for name in by_name}
    graph: dict[str, set[str]] = {name: set() for name in by_name}
    for name, package in by_name.items():
        for dependency in dependency_names(package):
            dep_name = normalize_project_name(dependency)
            if dep_name in by_name and dep_name not in graph[name]:
                graph[dep_name].add(name)
                indegree[name] += 1
    ordered: list[dict[str, Any]] = []
    ready = sorted([name for name, degree in indegree.items() if degree == 0])
    while ready:
        current = ready.pop(0)
        ordered.append(by_name[current])
        for child in sorted(graph[current]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort()
    if len(ordered) != len(git_packages):
        raise RuntimeError("Git package dependency cycle detected")
    return ordered


def render_requirements(path: Path, packages: list[dict[str, Any]]) -> None:
    lines = []
    for package in packages:
        requirement = f"{package['name']}=={package['version']}"
        artifact_hash = package.get("source", {}).get("sha256")
        if not artifact_hash:
            artifact_hash = (package.get("chosen_artifact", {}).get("hash") or "").removeprefix("sha256:")
        if not artifact_hash:
            artifact_hash = (package.get("file_entry", {}).get("hash") or "").removeprefix("sha256:")
        if not artifact_hash:
            raise RuntimeError(
                f"Unable to determine artifact hash for requirement {package['name']}=={package['version']}"
            )
        lines.append(f"{requirement} --hash=sha256:{artifact_hash}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def serialize_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def write_flathub_json(path: Path) -> None:
    serialize_json(
        path,
        {
            "only-arches": ["x86_64"],
            # , "aarch64"  https://pypi.org/project/bdkpython/#files  is not available for linux arm64
        },
    )


def write_readme(path: Path, release: ReleaseInfo) -> None:
    text = f"""# {APP_ID}

Flathub-style Flatpak packaging for [Bitcoin Safe]({DEFAULT_SOURCE_REPO_URL}).

## Maintainer Workflow
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

Run:

```sh
./populate-flathub-manifest-repo.py
```

By default the script writes the generated manifest repo to:

```sh
{DEFAULT_OUTPUT_DIR_DOC}
```

and then runs local validation:

- `flatpak-builder --show-manifest`
- `flatpak-builder-lint manifest` when `org.flatpak.Builder` is installed
- `flatpak-builder --user --install-deps-from=flathub --repo=repo build-dir {MANIFEST_FILENAME}`

Use these flags to skip parts of that default flow:

- `--skip-validate`
- `--skip-lint`
- `--skip-build`

Use this flag to launch the built app after a successful local build:

- `--run-flatpak`

To run the local checks on Ubuntu, install the builder tools and lint helper first:

```sh
sudo apt update
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.kde.Platform//{FLATHUB_KDE_RUNTIME_VERSION} org.kde.Sdk//{FLATHUB_KDE_RUNTIME_VERSION} {PYQT_BASEAPP_ID}//{FLATHUB_KDE_RUNTIME_VERSION} org.flatpak.Builder
```

By default the generator reads from `{DEFAULT_SOURCE_REPO_URL}` and uses the most recently published GitHub release, including prereleases.

Source selection works like this:

- if you pass `--local-source-checkout`, that local checkout is used for manifests, lockfile, and assets
- otherwise, if you pass `--source-repo-url`, that upstream repo is used
- otherwise, the generator falls back to `{DEFAULT_SOURCE_REPO_URL}`

You can override the defaults with:

- `--release-tag <tag>`
- `--source-repo-url <url>`
- `--local-source-checkout <path>`
- `--app-source-mode local-dir` to make the generated manifest point at that local checkout instead of a release archive
- `--refresh` to explicitly update the checked-in generated SVG and metainfo files first

The generator is the only Flatpak manifest source of truth:

- it defines the Flatpak manifest in Python instead of reading a checked-in YAML manifest
- by default replaces local staged sources with pinned release archives
- replaces build-time dependency resolution with generated, pinned dependency manifests
- relies on `{PYQT_BASEAPP_ID}//{FLATHUB_KDE_RUNTIME_VERSION}` for the core PyQt runtime instead of vendoring PyQt into the app
- keeps normal runs side-effect-free by checking tracked generated assets instead of rewriting them

Flathub builds from the checked-in files in this repo, not from Docker.
"""
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def append_release_notes_description(parent: ET.Element, body: str) -> None:
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
            ul = ET.SubElement(description, "ul")
            for item in list_items:
                ET.SubElement(ul, "li").text = normalize_inline(item)
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


def indent_xml(element: ET.Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in element:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


def release_sort_key(version: str, date: str) -> tuple[Version, str]:
    try:
        parsed_version = Version(version)
    except InvalidVersion:
        parsed_version = Version("0")
    return parsed_version, date


def is_prerelease_version(version: str) -> bool:
    try:
        return Version(version).is_prerelease or Version(version).is_devrelease
    except InvalidVersion:
        lowered = version.lower()
        return any(marker in lowered for marker in ("a", "b", "rc", "dev"))


def flathub_flatpak_dir() -> Path:
    return SCRIPT_DIR


def tracked_metainfo_path() -> Path:
    return flathub_flatpak_dir() / METAINFO_FILENAME


def tracked_svg_path() -> Path:
    return flathub_flatpak_dir() / SVG_FILENAME


def tracked_normalizer_path() -> Path:
    return flathub_flatpak_dir() / NORMALIZE_SVG_SCRIPT


def read_xml_template(path: Path) -> ET.Element:
    return ET.fromstring(path.read_text(encoding="utf-8"))


def write_metainfo(template_path: Path, output_path: Path, context: SourceContext) -> None:
    root = read_xml_template(template_path)
    releases_node = root.find("releases")
    if releases_node is None:
        releases_node = ET.SubElement(root, "releases")
        existing_release_nodes: list[ET.Element] = []
    else:
        existing_release_nodes = [
            copy.deepcopy(release)
            for release in releases_node.findall("release")
            if release.get("version") and not is_prerelease_version(release.get("version", ""))
        ]
        releases_node.clear()

    release_nodes_by_version: dict[str, ET.Element] = {}
    for release_node in existing_release_nodes:
        version = release_node.get("version")
        if version:
            release_nodes_by_version[version] = release_node

    for release in fetch_release_notes(context.repo_url):
        if release.prerelease or is_prerelease_version(release.version):
            continue
        release_element = ET.Element(
            "release",
            {
                "version": release.version,
                "date": release.date,
            },
        )
        append_release_notes_description(release_element, release.body)
        release_nodes_by_version[release.version] = release_element

    sorted_release_nodes = sorted(
        release_nodes_by_version.values(),
        key=lambda release: release_sort_key(
            release.get("version", "0"),
            release.get("date", ""),
        ),
        reverse=True,
    )
    for release_node in sorted_release_nodes:
        releases_node.append(release_node)

    indent_xml(root)
    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def copy_manifest_support_files(output_dir: Path) -> None:
    script_dir = Path(__file__).resolve().parent
    for filename in HELPER_FILENAMES:
        source = script_dir / filename
        destination = output_dir / filename
        if source.resolve() == destination.resolve():
            continue
        shutil.copyfile(source, destination)


def refresh_normalized_svg(tree_root: Path, output_svg: Path) -> None:
    source_svg = tree_root / "tools/resources/icon.svg"
    normalizer = tracked_normalizer_path()
    log_step(f"Refreshing normalized SVG {output_svg}")
    run_command(
        [sys.executable, str(normalizer), str(source_svg), str(output_svg)],
        tree_root,
        description="Normalizing app SVG canvas to a square upstream build artifact",
    )


def file_contents_match(first_path: Path, second_path: Path) -> bool:
    return (
        first_path.exists() and second_path.exists() and first_path.read_bytes() == second_path.read_bytes()
    )


def refresh_or_validate_generated_file(
    generated_path: Path,
    tracked_path: Path,
    *,
    refresh: bool,
    description: str,
) -> None:
    if refresh:
        shutil.copyfile(generated_path, tracked_path)
        log_step(f"Refreshed tracked {description} at {tracked_path}")
        return

    if file_contents_match(generated_path, tracked_path):
        return

    if not tracked_path.exists():
        raise RuntimeError(
            f"Missing tracked {description} at {tracked_path}. Run the generator with --refresh to create it."
        )

    raise RuntimeError(
        f"Tracked {description} at {tracked_path} is out of date. "
        "Run the generator with --refresh to update the checked-in file."
    )


def ensure_tracked_generated_assets(context: SourceContext, *, refresh: bool) -> None:
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

        refresh_or_validate_generated_file(
            generated_svg,
            tracked_svg,
            refresh=refresh,
            description="Flathub SVG asset",
        )
        refresh_or_validate_generated_file(
            generated_metainfo,
            tracked_metainfo,
            refresh=refresh,
            description="Flathub metainfo asset",
        )


def path_for_manifest(source_path: Path, manifest_dir: Path) -> str:
    try:
        return os.path.relpath(source_path, manifest_dir)
    except ValueError:
        return str(source_path)


def build_app_source_entry(
    context: SourceContext, output_dir: Path, app_source_mode: AppSourceMode
) -> dict[str, str]:
    if app_source_mode == "archive":
        log_step(f"Computing pinned checksum for app release tarball {context.release.tag_name}")
        return {
            "type": "archive",
            "url": context.release.tarball_url,
            "sha256": download_sha256(context.release.tarball_url),
        }

    if app_source_mode == "local-dir":
        return {
            "type": "dir",
            "path": path_for_manifest(context.tree_root, output_dir),
        }

    raise AssertionError(f"Unsupported app source mode: {app_source_mode}")


def native_git_source_entry(dependency: NativeGitDependency) -> dict[str, str]:
    return {
        "type": "git",
        "url": dependency.url,
        "tag": dependency.tag,
        "commit": dependency.commit,
    }


def build_native_modules(
    dependencies: dict[str, NativeGitDependency],
) -> list[dict[str, Any]]:
    return [
        {
            "name": "hidapi",
            "buildsystem": "cmake-ninja",
            "config-opts": [
                "-DBUILD_SHARED_LIBS=ON",
                "-DHIDAPI_WITH_HIDRAW=ON",
                "-DHIDAPI_WITH_LIBUSB=ON",
                "-DHIDAPI_BUILD_HIDTEST=OFF",
                "-DHIDAPI_BUILD_TESTGUI=OFF",
            ],
            "cleanup": [
                "/include",
                "/lib/pkgconfig",
                "/share/doc",
                "/share/man",
            ],
            "sources": [
                native_git_source_entry(dependencies["hidapi"]),
            ],
        },
        {
            "name": "zbar",
            "buildsystem": "autotools",
            "config-opts": [
                "--enable-pthread=no",
                "--enable-doc=no",
                "--with-python=no",
                "--with-gtk=no",
                "--with-qt=no",
                "--with-java=no",
                "--with-imagemagick=no",
                "--with-dbus=no",
                "--with-x=no",
                "--enable-video=no",
                "--with-jpeg=no",
                "--enable-codes=qrcode",
                "--disable-static",
                "--enable-shared",
            ],
            "cleanup": [
                "/bin",
                "/include",
                "/lib/pkgconfig",
                "/share/doc",
                "/share/man",
            ],
            "sources": [
                native_git_source_entry(dependencies["zbar"]),
                {
                    "type": "script",
                    "dest-filename": "autogen.sh",
                    "commands": [
                        "exec autoreconf -vfi",
                    ],
                },
            ],
        },
    ]


def build_manifest(app_source_entry: dict[str, str]) -> dict[str, Any]:
    manifest: dict[str, Any] = copy.deepcopy(BASE_MANIFEST)
    manifest["finish-args"] = normalize_finish_args(copy.deepcopy(BASE_MANIFEST["finish-args"]))
    manifest["modules"] = build_native_modules(load_native_git_dependencies())
    manifest["modules"].extend(
        [
            "python3-build-backends.json",
            "python3-runtime.json",
            "python3-git-packages.json",
            {
                "name": "bitcoin-safe",
                "buildsystem": "simple",
                "build-commands": [
                    "bash build-flatpak-app.sh",
                ],
                "sources": [
                    app_source_entry,
                    {"type": "file", "path": "build-flatpak-app.sh"},
                    {"type": "file", "path": "run-bitcoin-safe.sh"},
                ],
            },
        ]
    )
    return manifest


def is_internal_generated_dependency_module(module: Any) -> bool:
    if not isinstance(module, str):
        return False
    return module.replace("\\", "/") in INTERNAL_GENERATED_DEPENDENCY_MODULES


def normalize_finish_args(finish_args: list[str]) -> list[str]:
    normalized: list[str] = []
    saw_wayland = False
    saw_x11 = False
    require_version = "1.16.0"
    require_version_index: int | None = None

    for arg in finish_args:
        if arg.startswith("--require-version="):
            current_version = arg.split("=", 1)[1]
            if current_version < require_version:
                arg = f"--require-version={require_version}"
            require_version_index = len(normalized)
            normalized.append(arg)
            continue
        if arg == "--filesystem=home":
            continue
        if arg == "--socket=wayland":
            saw_wayland = True
            normalized.append(arg)
            continue
        if arg == "--socket=x11":
            saw_x11 = True
            continue
        normalized.append(arg)

    if saw_wayland and saw_x11:
        normalized.append("--socket=fallback-x11")
    elif saw_x11:
        normalized.append("--socket=x11")

    return normalized


def collect_backend_specs(
    context: SourceContext,
    runtime_packages: list[dict[str, Any]],
    git_packages: list[dict[str, Any]],
    pypi: PypiIndex,
) -> set[str]:
    specs: set[str] = set()
    specs.update(["poetry-core", "setuptools", "wheel"])

    chosen_runtime_sdists: list[tuple[str, str, str]] = []
    for package in runtime_packages:
        chosen = package["chosen_artifact"]
        if chosen["file"].lower().endswith(".whl"):
            continue
        chosen_runtime_sdists.append((package["name"], package["version"], package["artifact_url"]))

    for _, _, url in chosen_runtime_sdists:
        tree_root = extract_archive_to_temp(url)
        specs.update(build_requirements_for_tree(tree_root))

    for package in git_packages:
        source = package["source"]
        archive_url = github_archive_url(source["url"], source["resolved_reference"])
        tree_root = extract_archive_to_temp(archive_url)
        specs.update(build_requirements_for_tree(tree_root))

    specs.update(build_requirements_for_tree(context.tree_root))
    return {spec for spec in specs if spec}


def prepare_runtime_packages(
    main_packages: list[dict[str, Any]],
    all_packages: dict[str, dict[str, Any]],
    pypi: PypiIndex,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    runtime_packages: list[dict[str, Any]] = []
    git_packages: list[dict[str, Any]] = []
    runtime_names: set[str] = set()
    for package in main_packages:
        package = copy.deepcopy(package)
        normalized_name = normalize_project_name(package["name"])
        if normalized_name in BASEAPP_OWNED_RUNTIME_PACKAGES:
            continue
        if normalized_name in RUNTIME_PACKAGE_VERSION_OVERRIDES:
            overridden_version = RUNTIME_PACKAGE_VERSION_OVERRIDES[normalized_name]
            package = runtime_package_from_pypi(package["name"], overridden_version, pypi)
            runtime_packages.append(package)
            runtime_names.add(normalized_name)
            continue
        if package.get("source", {}).get("type") == "git":
            git_packages.append(package)
            continue
        chosen_artifact = choose_artifact(package["name"], package["version"], package["files"])
        package["chosen_artifact"] = chosen_artifact
        package["artifact_url"] = pypi.file_url(package["name"], package["version"], chosen_artifact["file"])
        runtime_packages.append(package)
        runtime_names.add(normalized_name)

    for git_package in git_packages:
        for override_name in GIT_RUNTIME_DEPENDENCY_OVERRIDES.get(git_package["name"], []):
            normalized_override = normalize_project_name(override_name)
            if normalized_override in runtime_names:
                continue
            if normalized_override not in all_packages:
                raise RuntimeError(
                    f"Runtime dependency override {override_name!r} for git package "
                    f"{git_package['name']!r} was not found in poetry.lock"
                )
            package = copy.deepcopy(all_packages[normalized_override])
            chosen_artifact = choose_artifact(package["name"], package["version"], package["files"])
            package["chosen_artifact"] = chosen_artifact
            package["artifact_url"] = pypi.file_url(
                package["name"], package["version"], chosen_artifact["file"]
            )
            runtime_packages.append(package)
            runtime_names.add(normalized_override)
    return runtime_packages, git_packages


def write_dependency_modules(
    output_dir: Path,
    release: ReleaseInfo,
    context: SourceContext,
    main_packages: list[dict[str, Any]],
    all_packages: dict[str, dict[str, Any]],
) -> None:
    log_step("Resolving Python dependencies from poetry.lock")
    pypi = PypiIndex()
    runtime_packages, git_packages = prepare_runtime_packages(main_packages, all_packages, pypi)
    git_packages = topological_git_packages(git_packages)
    log_step(
        f"Preparing dependency manifests: {len(runtime_packages)} PyPI packages, "
        f"{len(git_packages)} git packages"
    )

    backend_specs = collect_backend_specs(context, runtime_packages, git_packages, pypi)
    backend_packages = resolve_unique_backend_packages(all_packages, backend_specs, pypi)
    while True:
        known_backend_names = {normalize_project_name(package["name"]) for package in backend_packages}
        discovered_specs = collect_backend_specs_from_sdists(backend_packages)
        discovered_specs = {
            spec
            for spec in discovered_specs
            if normalize_project_name(backend_name(spec)) not in known_backend_names
        }
        if not discovered_specs:
            break
        new_bootstrap_packages = resolve_unique_backend_packages(all_packages, discovered_specs, pypi)
        for package in new_bootstrap_packages:
            if normalize_project_name(package["name"]) not in known_backend_names:
                backend_packages.append(package)
                known_backend_names.add(normalize_project_name(package["name"]))
    log_step(f"Resolved {len(backend_packages)} build backend packages")
    render_requirements(output_dir / "requirements-build-backends.txt", backend_packages)
    render_requirements(output_dir / "requirements-runtime.txt", runtime_packages)

    git_sources = []
    git_lock = []
    for package in git_packages:
        archive_url = github_archive_url(package["source"]["url"], package["source"]["resolved_reference"])
        archive_filename = (
            f"{safe_module_name(package['name'])}-{package['source']['resolved_reference']}.tar.gz"
        )
        git_sources.append(
            {
                "type": "file",
                "url": archive_url,
                "dest-filename": archive_filename,
                "sha256": download_sha256(archive_url),
            }
        )
        git_lock.append(
            {
                "name": package["name"],
                "archive_filename": archive_filename,
                "url": archive_url,
            }
        )

    serialize_json(output_dir / "git-packages-lock.json", git_lock)

    serialize_json(
        output_dir / "python3-build-backends.json",
        {
            "name": "python3-build-backends",
            "buildsystem": "simple",
            "build-commands": [
                f"install -d {BUILD_BACKEND_VENDOR_DIR}",
                f"cp -t {BUILD_BACKEND_VENDOR_DIR} ./*",
            ],
            "sources": [{"type": "file", "path": "requirements-build-backends.txt"}]
            + [package["source"] for package in backend_packages],
        },
    )

    serialize_json(
        output_dir / "python3-runtime.json",
        {
            "name": "python3-runtime",
            "buildsystem": "simple",
            "build-commands": [
                f"install -d {RUNTIME_VENDOR_DIR}",
                f"cp -t {RUNTIME_VENDOR_DIR} ./*",
            ],
            "sources": [{"type": "file", "path": "requirements-runtime.txt"}]
            + [
                artifact_source_entry(package["name"], package["version"], package["chosen_artifact"], pypi)
                for package in runtime_packages
            ],
        },
    )

    serialize_json(
        output_dir / "python3-git-packages.json",
        {
            "name": "python3-git-packages",
            "buildsystem": "simple",
            "build-commands": [
                f"install -d {GIT_VENDOR_DIR}",
                f"cp -t {GIT_VENDOR_DIR} ./*",
            ],
            "sources": [{"type": "file", "path": "git-packages-lock.json"}] + git_sources,
        },
    )


def generate_dependency_modules(output_dir: Path, tree_root: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_step(f"Generating dependency modules in {output_dir} from {tree_root}")
    lock_payload = load_toml(tree_root / "poetry.lock")
    main_packages, all_packages = evaluate_packages(lock_payload)
    dummy_release = ReleaseInfo(
        source_repo_url=DEFAULT_SOURCE_REPO_URL,
        tag_name="local-build",
        published_at="1970-01-01T00:00:00Z",
        prerelease=False,
        tarball_url="",
        html_url=DEFAULT_SOURCE_REPO_URL,
        body="",
    )
    context = SourceContext(
        repo_url=DEFAULT_SOURCE_REPO_URL,
        release=dummy_release,
        tree_root=tree_root,
    )
    write_dependency_modules(output_dir, dummy_release, context, main_packages, all_packages)


def generate_repo(
    output_dir: Path,
    context: SourceContext,
    *,
    app_source_mode: AppSourceMode,
    refresh: bool,
) -> None:
    log_step(f"Generating Flathub manifest repo in {output_dir}")
    log_step("Loading tracked Flathub assets and Poetry lockfile")
    output_dir.mkdir(parents=True, exist_ok=True)
    obsolete_metainfo = output_dir / f"{APP_ID}.metainfo.xml"
    if obsolete_metainfo.exists():
        obsolete_metainfo.unlink()
        log_step(f"Removed obsolete generated file {obsolete_metainfo}")
    obsolete_svg = output_dir / f"{APP_ID}.svg"
    if obsolete_svg.exists():
        obsolete_svg.unlink()
        log_step(f"Removed obsolete generated file {obsolete_svg}")
    obsolete_normalizer = output_dir / "normalize-svg-icon.py"
    if obsolete_normalizer.exists():
        obsolete_normalizer.unlink()
        log_step(f"Removed obsolete generated file {obsolete_normalizer}")

    ensure_tracked_generated_assets(context, refresh=refresh)
    lock_payload = load_toml(context.tree_root / "poetry.lock")
    main_packages, all_packages = evaluate_packages(lock_payload)
    app_source_entry = build_app_source_entry(context, output_dir, app_source_mode)

    log_step("Writing flathub.json and README")
    write_flathub_json(output_dir / "flathub.json")
    write_readme(output_dir / "README.md", context.release)
    copy_manifest_support_files(output_dir)
    write_dependency_modules(output_dir, context.release, context, main_packages, all_packages)

    log_step(f"Writing main manifest {MANIFEST_FILENAME}")
    manifest = build_manifest(app_source_entry)
    (output_dir / MANIFEST_FILENAME).write_text(
        yaml.safe_dump(manifest, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    log_step("Generation complete")


def clean_transient_artifacts(output_dir: Path) -> None:
    transient_paths = [
        output_dir / "build-dir",
        output_dir / "repo",
        output_dir / BUNDLE_FILENAME,
        output_dir / ".flatpak-builder",
        output_dir / "__pycache__",
    ]

    removed_any = False
    for path in transient_paths:
        if not path.exists():
            continue
        removed_any = True
        if path.is_dir():
            detach_rofiles_mounts(path)
            shutil.rmtree(path, onexc=retry_remove_busy_path)
        else:
            path.unlink()
        log_step(f"Removed transient path {path}")

    if not removed_any:
        log_step("No previous transient build artifacts found to clean")


def retry_remove_busy_path(function: Any, path: str, excinfo: BaseException) -> None:
    if not isinstance(excinfo, OSError) or excinfo.errno != errno.EBUSY:
        raise excinfo

    error = excinfo
    if error.errno != errno.EBUSY:
        raise error

    busy_path = Path(path)
    if not detach_mount(busy_path):
        raise error

    function(path)


def detach_rofiles_mounts(root: Path) -> None:
    candidates = [root, *root.rglob("*")]
    for candidate in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        if candidate.is_dir() and candidate.name.startswith("rofiles-"):
            detach_mount(candidate)


def detach_mount(path: Path) -> bool:
    if not path.exists() or not os.path.ismount(path):
        return False

    for args in (
        ["fusermount3", "-uz", str(path)],
        ["fusermount3", "-u", str(path)],
        ["umount", "-l", str(path)],
    ):
        result = subprocess.run(args, text=True, capture_output=True)
        if result.returncode == 0:
            log_step(f"Detached mounted rofiles path {path}")
            return True
    return False


def run_command(
    args: list[str],
    cwd: Path,
    *,
    allow_failure: bool = False,
    description: str | None = None,
    quiet_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    if description:
        log_step(description)
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr and not (quiet_failure and result.returncode != 0):
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0 and not allow_failure:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}")
    return result


def validate_repo(
    output_dir: Path,
    *,
    skip_validate: bool,
    skip_lint: bool,
    skip_build: bool,
    run_flatpak: bool,
) -> None:
    if skip_validate:
        log_step("Skipping validation because --skip-validate was requested")
        return

    log_step("Starting local validation")
    manifest_path = output_dir / MANIFEST_FILENAME
    run_command(
        ["flatpak-builder", "--show-manifest", MANIFEST_FILENAME],
        output_dir,
        description="Checking manifest syntax with flatpak-builder --show-manifest",
    )

    if not skip_lint:
        lint_check = run_command(
            ["flatpak", "info", "org.flatpak.Builder"],
            output_dir,
            allow_failure=True,
            quiet_failure=True,
        )
        if lint_check.returncode == 0:
            lint_result = run_command(
                [
                    "flatpak",
                    "run",
                    "--command=flatpak-builder-lint",
                    "org.flatpak.Builder",
                    "manifest",
                    str(manifest_path),
                ],
                output_dir,
                description="Running flatpak-builder-lint manifest",
                allow_failure=True,
            )
            if lint_result.returncode != 0:
                lint_payload = parse_lint_output(lint_result.stdout)
                if lint_payload.get("errors"):
                    raise RuntimeError(f"flatpak-builder-lint reported errors: {lint_payload['errors']}")
                log_step("flatpak-builder-lint reported only warnings/info; continuing")
        else:
            print(
                "[populate] Skipping flatpak-builder-lint: org.flatpak.Builder is not installed. "
                "On Ubuntu install prerequisites with: "
                "'sudo apt install flatpak flatpak-builder' and then "
                "'flatpak install flathub org.flatpak.Builder'.",
                file=sys.stderr,
            )

    if skip_build:
        log_step("Skipping local build because --skip-build was requested")
        return

    remote_check = run_command(
        ["flatpak", "remotes", "--columns=name"],
        output_dir,
        allow_failure=True,
    )
    if remote_check.returncode != 0 or "flathub" not in remote_check.stdout.split():
        print(
            "[populate] Skipping local build: flatpak remote 'flathub' is not configured.",
            file=sys.stderr,
        )
        return

    build_dir = output_dir / "build-dir"
    repo_dir = output_dir / "repo"
    run_command(
        [
            "flatpak-builder",
            "--user",
            "--assumeyes",
            "--force-clean",
            "--disable-rofiles-fuse",
            "--install-deps-from=flathub",
            f"--repo={repo_dir}",
            str(build_dir),
            MANIFEST_FILENAME,
        ],
        output_dir,
        description="Building the Flatpak locally with flatpak-builder",
    )
    bundle_path = output_dir / BUNDLE_FILENAME
    run_command(
        [
            "flatpak",
            "build-bundle",
            str(repo_dir),
            str(bundle_path),
            APP_ID,
            FLATPAK_BRANCH,
        ],
        output_dir,
        description="Building standalone Flatpak bundle for local testing",
    )
    log_step(f"Local Flatpak repo written to {repo_dir} (OSTree repo, not a .flatpak bundle)")
    log_step(f"Standalone Flatpak bundle written to {bundle_path}")
    if run_flatpak:
        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        run_command_args = [upstream_command(output_dir / MANIFEST_FILENAME)]
        if wayland_display:
            run_command_args = ["env", f"WAYLAND_DISPLAY={wayland_display}", *run_command_args]
        run_result = run_command(
            [
                "flatpak-builder",
                "--run",
                str(build_dir),
                MANIFEST_FILENAME,
                *run_command_args,
            ],
            output_dir,
            description="Running the built Flatpak locally with flatpak-builder --run",
            allow_failure=True,
        )
        if run_result.returncode == 0:
            return

        rofiles_failure_text = f"{run_result.stdout}\n{run_result.stderr}"
        if "rofiles-fuse" not in rofiles_failure_text:
            raise RuntimeError(
                "Command failed "
                f"({run_result.returncode}): flatpak-builder --run {build_dir} {MANIFEST_FILENAME}"
            )

        log_step(
            "flatpak-builder --run could not start rofiles-fuse; falling back to bundle install + flatpak run"
        )
        run_command(
            [
                "dbus-run-session",
                "--",
                "flatpak",
                "install",
                "--user",
                "--noninteractive",
                "--reinstall",
                str(bundle_path),
            ],
            output_dir,
            description="Installing the built Flatpak bundle for local run fallback",
        )
        run_command(
            [
                "dbus-run-session",
                "--",
                "flatpak",
                "run",
                *([f"--env=WAYLAND_DISPLAY={wayland_display}"] if wayland_display else []),
                APP_ID,
            ],
            output_dir,
            description="Running the installed Flatpak bundle fallback with flatpak run",
        )


def parse_lint_output(output: str) -> dict[str, Any]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def upstream_command(manifest_path: Path) -> str:
    manifest = load_yaml(manifest_path)
    command = manifest.get("command")
    if not isinstance(command, str) or not command.strip():
        raise RuntimeError(f"Manifest {manifest_path} does not define a runnable command")
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Populate the Bitcoin Safe Flathub manifest repo.")
    parser.add_argument(
        "--source-repo-url",
        help=(
            "Upstream repository URL to read release metadata from. "
            f"Defaults to {DEFAULT_SOURCE_REPO_URL} when no source override is provided."
        ),
    )
    parser.add_argument(
        "--local-source-checkout",
        help=(
            "Local bitcoin-safe checkout to use for manifests, lockfile, and assets. "
            "When provided, this takes precedence over downloading the release tarball."
        ),
    )
    parser.add_argument(
        "--release-tag",
        help="GitHub release tag or arbitrary commit hash to build from.",
    )
    parser.add_argument("--use-latest-release", action="store_true")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh the checked-in generated SVG and metainfo assets before generating the manifest repo.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--run-flatpak", action="store_true")
    parser.add_argument("--only-write-dependency-modules", action="store_true")
    parser.add_argument(
        "--app-source-mode",
        choices=["archive", "local-dir"],
        default="archive",
        help=(
            "How the generated manifest should reference the bitcoin-safe app source. "
            "'archive' keeps the Flathub default, while 'local-dir' points at --local-source-checkout."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tag_name = args.release_tag
    repo_url = args.source_repo_url or DEFAULT_SOURCE_REPO_URL
    output_dir = Path(args.output_dir).resolve()
    log_step(f"Source repository: {repo_url}")
    if args.local_source_checkout:
        log_step(f"Local source override: {Path(args.local_source_checkout).resolve()}")
    log_step(f"Output directory: {output_dir}")
    if tag_name:
        log_step(f"Requested source ref: {tag_name}")
    else:
        log_step("Requested source ref: latest published release")
    if args.only_write_dependency_modules:
        if not args.local_source_checkout:
            raise RuntimeError("--only-write-dependency-modules requires --local-source-checkout")
        generate_dependency_modules(output_dir, Path(args.local_source_checkout).resolve())
        log_step("Dependency module generation completed successfully")
        return
    if args.refresh and not args.local_source_checkout:
        raise RuntimeError(
            "--refresh requires --local-source-checkout so tracked files can be updated safely"
        )
    if args.app_source_mode == "local-dir" and not args.local_source_checkout:
        raise RuntimeError("--app-source-mode local-dir requires --local-source-checkout")
    if args.run_flatpak and args.skip_validate:
        raise RuntimeError("--run-flatpak cannot be used together with --skip-validate")
    if args.run_flatpak and args.skip_build:
        raise RuntimeError("--run-flatpak cannot be used together with --skip-build")
    clean_transient_artifacts(output_dir)
    context = build_source_context(
        repo_url=repo_url,
        local_source_checkout=args.local_source_checkout,
        release_tag=tag_name,
    )
    generate_repo(output_dir, context, app_source_mode=args.app_source_mode, refresh=args.refresh)
    validate_repo(
        output_dir,
        skip_validate=args.skip_validate,
        skip_lint=args.skip_lint,
        skip_build=args.skip_build,
        run_flatpak=args.run_flatpak,
    )
    log_step("Populate completed successfully")


if __name__ == "__main__":
    main()
