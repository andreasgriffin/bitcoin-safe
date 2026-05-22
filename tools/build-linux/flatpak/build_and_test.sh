#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="${1:?usage: build_and_test.sh <project-root> <dist-dir> [app-id]}"
DIST_DIR="${2:?usage: build_and_test.sh <project-root> <dist-dir> [app-id]}"
APP_ID="${3:-org.bitcoin_safe.BitcoinSafe}"
FLATPAK_BRANCH="stable"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_PATH="${SCRIPT_DIR}/${APP_ID}.yml"
INSTALL_AND_TEST_SCRIPT="${SCRIPT_DIR}/install_and_smoke_test_bundle.sh"
WORK_DIR="${SCRIPT_DIR}/build"
REPRO_DEBUG_ROOT_DIR="${WORK_DIR}/repro-debug"
REPRO_DEBUG_DIR="${BITCOINSAFE_FLATPAK_REPRO_DEBUG_DIR:-${REPRO_DEBUG_ROOT_DIR}/latest}"
METADATA_PROBE_DEBUG_DIR="${REPRO_DEBUG_DIR}/metadata-probe"
SOURCE_STAGING_DIR="${WORK_DIR}/source-tree"
BUILDER_DIR="${WORK_DIR}/builder"
REPO_DIR="${WORK_DIR}/repo"
STATE_DIR="${WORK_DIR}/state"
METADATA_PROBE_SOURCE_DIR="${WORK_DIR}/metadata-probe-src"
METADATA_PROBE_BIN_DIR="${WORK_DIR}/metadata-probe-bin"
METADATA_PROBE_MANIFEST_PATH="${WORK_DIR}/metadata-probe.yml"
METADATA_PROBE_BUILDER_DIR="${WORK_DIR}/metadata-probe-builder"
METADATA_PROBE_REPO_DIR="${WORK_DIR}/metadata-probe-repo"
METADATA_PROBE_STATE_DIR="${WORK_DIR}/metadata-probe-state"
source "${SCRIPT_DIR}/flatpak_common.sh"

resolve_source_date_epoch() {
    if [ -n "${BITCOINSAFE_SOURCE_DATE_EPOCH:-}" ]; then
        printf '%s\n' "${BITCOINSAFE_SOURCE_DATE_EPOCH}"
        return
    fi

    if git -C "${PROJECT_ROOT}" rev-parse --show-toplevel >/dev/null 2>&1; then
        git -C "${PROJECT_ROOT}" show -s --format=%ct HEAD
        return
    fi

    fail "SOURCE_DATE_EPOCH is required for reproducible Flatpak builds."
}

setup_repro_debug_dir() {
    rm -rf "${REPRO_DEBUG_DIR}"
    mkdir -p "${REPRO_DEBUG_DIR}" "${METADATA_PROBE_DEBUG_DIR}"
}

sha256_file() {
    python3 - <<'PY' "$1"
from pathlib import Path
import hashlib
import sys

digest = hashlib.sha256()
with Path(sys.argv[1]).open("rb") as handle:
    for chunk in iter(lambda: handle.read(1 << 20), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
}

emit_hash_file() {
    local input_path="$1"
    local output_path="$2"
    local digest

    digest="$(sha256_file "${input_path}")"
    printf '%s\n' "${digest}" > "${output_path}"
    printf '%s\n' "${digest}"
}

normalize_tree_timestamps() {
    local path

    # Keep staged files at the commit timestamp instead of the local checkout
    # time. Example: the copied source tree should not differ just because it
    # was staged at 09:00 in one build and 09:05 in the next.
    for path in "$@"; do
        [ -e "${path}" ] || continue
        find "${path}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    done
}

format_source_date_timestamp() {
    # flatpak build-export expects an RFC3339 timestamp, e.g.
    # "2026-05-22T07:30:00Z", not a raw unix epoch.
    date -u -d "@${SOURCE_DATE_EPOCH}" "+%Y-%m-%dT%H:%M:%SZ"
}

normalize_flatpak_bundle_timestamp() {
    local bundle_path="$1"
    local commit_checksum="$2"
    local diagnostics_path="$3"

    python3 - <<'PY' "${bundle_path}" "${commit_checksum}" "${SOURCE_DATE_EPOCH}" "${diagnostics_path}"
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys

bundle_path = Path(sys.argv[1])
commit_checksum = sys.argv[2]
source_date_epoch = int(sys.argv[3])
diagnostics_path = Path(sys.argv[4])
commit_bytes = bytes.fromhex(commit_checksum)
data = bundle_path.read_bytes()
match_count = data.count(commit_bytes)

if match_count != 1:
    raise SystemExit(
        f"Expected exactly one commit anchor in {bundle_path}, found {match_count} for commit {commit_checksum}."
    )

commit_offset = data.find(commit_bytes)
if commit_offset < 8:
    raise SystemExit(f"Commit anchor offset {commit_offset} is too small to contain the preceding timestamp.")

timestamp_offset = commit_offset - 8
timestamp_before = int.from_bytes(data[timestamp_offset:commit_offset], "big")
patched = bytearray(data)
patched[timestamp_offset:commit_offset] = source_date_epoch.to_bytes(8, "big")
bundle_path.write_bytes(patched)

diagnostics_path.write_text(
    "\n".join(
        [
            f"commit={commit_checksum}",
            f"commit_offset={commit_offset}",
            f"timestamp_offset={timestamp_offset}",
            f"timestamp_before={timestamp_before}",
            f"timestamp_before_iso={datetime.fromtimestamp(timestamp_before, UTC).isoformat()}",
            f"timestamp_after={source_date_epoch}",
            f"timestamp_after_iso={datetime.fromtimestamp(source_date_epoch, UTC).isoformat()}",
        ]
    )
    + "\n",
    encoding="utf-8",
)
PY
}

run_flatpak_build_bundle() {
    local repo_dir="$1"
    local bundle_path="$2"
    local arch="$3"
    local commit_checksum="$4"
    local diagnostics_path="$5"

    info "Creating Flatpak bundle at ${bundle_path}."
    run_with_dbus_session flatpak build-bundle \
        "${repo_dir}" \
        "${bundle_path}" \
        "${APP_ID}" \
        "${FLATPAK_BRANCH}" \
        --arch="${arch}"
    normalize_flatpak_bundle_timestamp "${bundle_path}" "${commit_checksum}" "${diagnostics_path}"
}

emit_tree_manifest() {
    local root_path="$1"
    local output_dir="$2"
    local label="$3"
    local mtime_mode="${4:-filesystem}"
    local manifest_path="${output_dir}/${label}.manifest"
    local hash_path="${output_dir}/${label}.sha256"
    local digest

    python3 - <<'PY' "${root_path}" "${manifest_path}" "${mtime_mode}"
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import stat
import sys

root = Path(sys.argv[1]).resolve()
manifest_path = Path(sys.argv[2])
mtime_mode = sys.argv[3]


def iter_paths(path: Path):
    yield path
    if not path.is_dir():
        return

    def walk_dir(directory: Path):
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            entry_path = Path(entry.path)
            yield entry_path
            if entry.is_dir(follow_symlinks=False):
                yield from walk_dir(entry_path)

    yield from walk_dir(path)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


manifest_path.parent.mkdir(parents=True, exist_ok=True)
with manifest_path.open("w", encoding="utf-8") as handle:
    handle.write("path\ttype\tmode\tsize\tmtime\ttarget\tsha256\n")
    for path in iter_paths(root):
        relative_path = "." if path == root else path.relative_to(root).as_posix()
        stat_result = os.lstat(path)
        file_type = "other"
        size = "-"
        target = "-"
        sha256 = "-"
        if stat.S_ISREG(stat_result.st_mode):
            file_type = "file"
            size = str(stat_result.st_size)
            sha256 = file_digest(path)
        elif stat.S_ISDIR(stat_result.st_mode):
            file_type = "dir"
        elif stat.S_ISLNK(stat_result.st_mode):
            file_type = "symlink"
            size = str(stat_result.st_size)
            target = os.readlink(path)
        else:
            size = str(stat_result.st_size)
        mtime = "-" if mtime_mode == "ignore" else str(int(stat_result.st_mtime))
        # Directory st_size reflects host filesystem allocation details, e.g.
        # the same children may occupy 16384 bytes in one build dir and 20480
        # in another. Excluding it keeps the manifest focused on semantic tree
        # content instead of ext4 bookkeeping noise.
        handle.write(
            f"{relative_path}\t{file_type}\t{stat.S_IMODE(stat_result.st_mode):04o}\t"
            f"{size}\t{mtime}\t{target}\t{sha256}\n"
        )
PY

    digest="$(emit_hash_file "${manifest_path}" "${hash_path}")"
    info "${label} manifest hash: ${digest}"
}

emit_build_context() {
    local output_dir="$1"
    local context_path="${output_dir}/context.txt"
    local context_hash_path="${output_dir}/context.sha256"
    local git_commit git_describe arch digest

    git_commit="$(git -C "${PROJECT_ROOT}" rev-parse HEAD)"
    git_describe="$(git -C "${PROJECT_ROOT}" describe --tags --dirty --always --abbrev=20)"
    arch="$(flatpak --default-arch)"

    cat > "${context_path}" <<EOF
git_commit=${git_commit}
git_describe=${git_describe}
source_date_epoch=${SOURCE_DATE_EPOCH}
source_date_timestamp=${SOURCE_DATE_TIMESTAMP}
flatpak_version=$(flatpak --version | head -n 1)
flatpak_builder_version=$(flatpak-builder --version | head -n 1)
appstreamcli_version=$(appstreamcli --version | head -n 1)
python_version=$(python3 --version)
arch=${arch}
docker_image=${BITCOINSAFE_DOCKER_IMAGE:-unknown}
docker_image_id=${BITCOINSAFE_DOCKER_IMAGE_ID:-unknown}
EOF

    digest="$(emit_hash_file "${context_path}" "${context_hash_path}")"
    info "build context hash: ${digest}"
}

get_app_ref() {
    local arch="$1"

    printf 'app/%s/%s/%s\n' "${APP_ID}" "${arch}" "${FLATPAK_BRANCH}"
}

emit_ostree_ref_manifest() {
    local repo_dir="$1"
    local ref_name="$2"
    local output_dir="$3"
    local commit
    local checkout_dir

    commit="$(ostree rev-parse --repo="${repo_dir}" "${ref_name}")"
    printf '%s\n' "${ref_name}" > "${output_dir}/ostree-ref.txt"
    printf '%s\n' "${commit}" > "${output_dir}/ostree-commit.txt"
    ostree show --repo="${repo_dir}" "${commit}" > "${output_dir}/ostree-show.txt"
    ostree show --repo="${repo_dir}" --raw "${commit}" > "${output_dir}/ostree-show.raw"
    ostree show --repo="${repo_dir}" --list-metadata-keys "${commit}" > "${output_dir}/ostree-metadata-keys.txt"
    ostree ls --repo="${repo_dir}" -R -C "${commit}" > "${output_dir}/ostree-ls.txt"

    checkout_dir="$(mktemp -d "${WORK_DIR}/ostree-checkout.XXXXXX")"
    rm -rf "${checkout_dir}"
    ostree --repo="${repo_dir}" checkout "${commit}" "${checkout_dir}"
    emit_tree_manifest "${checkout_dir}" "${output_dir}" "ostree-files" "ignore"
    rm -rf "${checkout_dir}"
}

emit_bundle_manifest() {
    local bundle_path="$1"
    local output_dir="$2"
    local digest
    local import_repo_dir
    local imported_ref
    local imported_commit

    digest="$(emit_hash_file "${bundle_path}" "${output_dir}/bundle.sha256")"
    info "bundle hash: ${digest}"

    import_repo_dir="$(mktemp -d "${WORK_DIR}/bundle-import.XXXXXX")"
    ostree init --repo="${import_repo_dir}" --mode=archive >/dev/null
    flatpak build-import-bundle --no-update-summary "${import_repo_dir}" "${bundle_path}" >/dev/null
    imported_ref="$(ostree refs --repo="${import_repo_dir}" | head -n 1)"
    imported_commit="$(ostree rev-parse --repo="${import_repo_dir}" "${imported_ref}")"
    printf '%s\n' "${imported_ref}" > "${output_dir}/bundle-imported-ref.txt"
    printf '%s\n' "${imported_commit}" > "${output_dir}/bundle-imported-commit.txt"
    rm -rf "${import_repo_dir}"
}

get_project_version() {
    if [ -n "${BITCOINSAFE_FLATPAK_VERSION:-}" ]; then
        printf '%s\n' "${BITCOINSAFE_FLATPAK_VERSION}"
        return
    fi

    python3 - <<'PY' "${PROJECT_ROOT}/bitcoin_safe/__init__.py"
from pathlib import Path
import sys

namespace: dict[str, str] = {}
exec(Path(sys.argv[1]).read_text(encoding="utf-8"), namespace)
print(namespace["__version__"])
PY
}

get_manifest_field() {
    python3 - <<'PY' "${MANIFEST_PATH}" "$1"
from pathlib import Path
import re
import sys

manifest_text = Path(sys.argv[1]).read_text(encoding="utf-8")
field_name = sys.argv[2]
match = re.search(rf"^{re.escape(field_name)}:\s*\"?([^\n\"]+)\"?\s*$", manifest_text, re.MULTILINE)
if not match:
    raise SystemExit(f"Missing required manifest field: {field_name}")
print(match.group(1).strip())
PY
}

write_metadata_probe_files() {
    local runtime runtime_version sdk

    runtime="$(get_manifest_field "runtime")"
    runtime_version="$(get_manifest_field "runtime-version")"
    sdk="$(get_manifest_field "sdk")"

    rm -rf \
        "${METADATA_PROBE_SOURCE_DIR}" \
        "${METADATA_PROBE_BIN_DIR}" \
        "${METADATA_PROBE_MANIFEST_PATH}" \
        "${METADATA_PROBE_BUILDER_DIR}" \
        "${METADATA_PROBE_REPO_DIR}" \
        "${METADATA_PROBE_STATE_DIR}"
    mkdir -p "${METADATA_PROBE_SOURCE_DIR}" "${METADATA_PROBE_BIN_DIR}"

    cp "${PROJECT_ROOT}/tools/resources/icon.svg" "${METADATA_PROBE_SOURCE_DIR}/icon.svg"
    cp "${PROJECT_ROOT}/tools/resources/icon-128.png" "${METADATA_PROBE_SOURCE_DIR}/icon-128.png"
    cp "${PROJECT_ROOT}/tools/resources/linux-bitcoin-safe.desktop" \
        "${METADATA_PROBE_SOURCE_DIR}/linux-bitcoin-safe.desktop"
    cp "${SCRIPT_DIR}/${APP_ID}.metainfo.xml" "${METADATA_PROBE_SOURCE_DIR}/${APP_ID}.metainfo.xml"

    cat > "${METADATA_PROBE_BIN_DIR}/run-bitcoin-safe.sh" <<'EOF'
#!/bin/sh
printf 'Bitcoin Safe metadata probe\n'
EOF
    chmod 755 "${METADATA_PROBE_BIN_DIR}/run-bitcoin-safe.sh"

    cat > "${METADATA_PROBE_MANIFEST_PATH}" <<EOF
app-id: ${APP_ID}
branch: ${FLATPAK_BRANCH}
runtime: ${runtime}
runtime-version: "${runtime_version}"
sdk: ${sdk}
command: run-bitcoin-safe.sh
separate-locales: false
modules:
  - name: metadata-probe
    buildsystem: simple
    build-commands:
      - install -Dm755 run-bitcoin-safe.sh /app/bin/run-bitcoin-safe.sh
      - install -Dm644 icon.svg /app/share/icons/hicolor/scalable/apps/${APP_ID}.svg
      - install -Dm644 icon-128.png /app/share/icons/hicolor/128x128/apps/${APP_ID}.png
      - install -Dm644 ${APP_ID}.metainfo.xml /app/share/metainfo/${APP_ID}.metainfo.xml
      - |
        sed \\
            -e 's#^Exec=.*#Exec=run-bitcoin-safe.sh %F#' \\
            -e 's#^Icon=.*#Icon=${APP_ID}#' \\
            linux-bitcoin-safe.desktop \\
            > ${APP_ID}.desktop
      - install -Dm644 ${APP_ID}.desktop /app/share/applications/${APP_ID}.desktop
      - mkdir -p /app/app
      - ln -sfn ../share /app/app/share
    sources:
      - type: dir
        path: metadata-probe-src
      - type: dir
        path: metadata-probe-bin
EOF

    # The probe uses generated files, so normalize those too before we ask
    # Flatpak to export metadata from them.
    normalize_tree_timestamps \
        "${METADATA_PROBE_SOURCE_DIR}" \
        "${METADATA_PROBE_BIN_DIR}" \
        "${METADATA_PROBE_MANIFEST_PATH}"
}

run_metadata_compose_smoke_test() {
    local arch
    local probe_ref

    arch="$(flatpak --default-arch)"
    probe_ref="$(get_app_ref "${arch}")"
    write_metadata_probe_files

    info "Running metadata compose smoke test."
    run_with_dbus_session flatpak-builder \
        --user \
        --arch="${arch}" \
        --disable-rofiles-fuse \
        --force-clean \
        --install-deps-from=flathub \
        --override-source-date-epoch="${SOURCE_DATE_EPOCH}" \
        --state-dir="${METADATA_PROBE_STATE_DIR}" \
        "${METADATA_PROBE_BUILDER_DIR}" \
        "${METADATA_PROBE_MANIFEST_PATH}"

    # Export in a second explicit step so the OSTree commit timestamp is pinned
    # as well. Example: the same finished app dir should not export to
    # different commits at 10:00 and 10:01.
    run_with_dbus_session flatpak build-export \
        --arch="${arch}" \
        --disable-sandbox \
        --no-update-summary \
        --timestamp="${SOURCE_DATE_TIMESTAMP}" \
        "${METADATA_PROBE_REPO_DIR}" \
        "${METADATA_PROBE_BUILDER_DIR}" \
        "${FLATPAK_BRANCH}"

    emit_tree_manifest "${METADATA_PROBE_BUILDER_DIR}/files" "${METADATA_PROBE_DEBUG_DIR}" "builder-files"
    emit_ostree_ref_manifest "${METADATA_PROBE_REPO_DIR}" "${probe_ref}" "${METADATA_PROBE_DEBUG_DIR}"

    desktop-file-validate "${METADATA_PROBE_BUILDER_DIR}/files/share/applications/${APP_ID}.desktop"
    test -f "${METADATA_PROBE_BUILDER_DIR}/files/share/icons/hicolor/scalable/apps/${APP_ID}.svg" \
        || fail "Metadata smoke test did not export the SVG icon for ${APP_ID}."
}

stage_source_tree() {
    info "Staging source tree for Flatpak build."
    rm -rf "${SOURCE_STAGING_DIR}"
    mkdir -p "${SOURCE_STAGING_DIR}"

    # Stage only committed files so ignored local runtime state, such as
    # tests/bitcoin_data/regtest/debug.log, cannot affect reproducibility.
    if git -C "${PROJECT_ROOT}" rev-parse --show-toplevel >/dev/null 2>&1; then
        git -C "${PROJECT_ROOT}" archive --format=tar HEAD | tar -C "${SOURCE_STAGING_DIR}" -xf -
    else
        tar -C "${PROJECT_ROOT}" \
            --exclude='.git' \
            --exclude='.venv' \
            --exclude='build' \
            --exclude='dist' \
            --exclude='.flatpak-builder' \
            --exclude='.mypy_cache' \
            --exclude='.pytest_cache' \
            --exclude='.ruff_cache' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='tools/build-linux/flatpak/build' \
            -cf - . | tar -C "${SOURCE_STAGING_DIR}" -xf -
    fi

    # The copied tree inherits fresh filesystem mtimes from tar/extract, so
    # reset them to the commit timestamp before flatpak-builder sees them.
    normalize_tree_timestamps "${SOURCE_STAGING_DIR}"
    emit_tree_manifest "${SOURCE_STAGING_DIR}" "${REPRO_DEBUG_DIR}" "source-tree"
}

build_flatpak_bundle() {
    local arch bundle_name bundle_path project_version ref_name commit_checksum

    arch="$(flatpak --default-arch)"
    project_version="$(get_project_version)"
    bundle_name="Bitcoin-Safe-${project_version}-${arch}.flatpak"
    bundle_path="${DIST_DIR}/${bundle_name}"
    ref_name="$(get_app_ref "${arch}")"

    rm -rf "${BUILDER_DIR}" "${REPO_DIR}" "${STATE_DIR}"
    mkdir -p "${BUILDER_DIR}" "${REPO_DIR}" "${STATE_DIR}" "${DIST_DIR}" "${WORK_DIR}"

    info "Building Flatpak manifest."
    run_with_dbus_session flatpak-builder \
        --user \
        --arch="${arch}" \
        --disable-rofiles-fuse \
        --force-clean \
        --install-deps-from=flathub \
        --override-source-date-epoch="${SOURCE_DATE_EPOCH}" \
        --state-dir="${STATE_DIR}" \
        "${BUILDER_DIR}" \
        "${MANIFEST_PATH}"

    emit_tree_manifest "${BUILDER_DIR}/files" "${REPRO_DEBUG_DIR}" "builder-files"

    # AppImage already controls its final packaging timestamp explicitly. Do
    # the same for Flatpak export so equal app dirs produce equal OSTree
    # commits and bundles.
    run_with_dbus_session flatpak build-export \
        --arch="${arch}" \
        --disable-sandbox \
        --no-update-summary \
        --timestamp="${SOURCE_DATE_TIMESTAMP}" \
        "${REPO_DIR}" \
        "${BUILDER_DIR}" \
        "${FLATPAK_BRANCH}"

    emit_ostree_ref_manifest "${REPO_DIR}" "${ref_name}" "${REPRO_DEBUG_DIR}"
    commit_checksum="$(cat "${REPRO_DEBUG_DIR}/ostree-commit.txt")"

    info "Validating exported desktop metadata."
    desktop-file-validate "${BUILDER_DIR}/files/share/applications/${APP_ID}.desktop"
    test -f "${BUILDER_DIR}/files/share/icons/hicolor/scalable/apps/${APP_ID}.svg" \
        || fail "Missing exported icon for ${APP_ID}."

    rm -f "${bundle_path}"
    run_flatpak_build_bundle \
        "${REPO_DIR}" \
        "${bundle_path}" \
        "${arch}" \
        "${commit_checksum}" \
        "${REPRO_DEBUG_DIR}/bundle-normalized.txt"

    test -f "${bundle_path}" || fail "Flatpak bundle was not created."
    emit_bundle_manifest "${bundle_path}" "${REPRO_DEBUG_DIR}"
    printf '%s\n' "${bundle_path}" > "${WORK_DIR}/bundle-path.txt"
}

export TZ=UTC
export SOURCE_DATE_EPOCH="$(resolve_source_date_epoch)"
export SOURCE_DATE_TIMESTAMP="$(format_source_date_timestamp)"

setup_repro_debug_dir
# Use the git commit time as the single reproducibility clock for staging,
# flatpak-builder, and flatpak build-export.
info "Using SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}."
info "Using Flatpak export timestamp ${SOURCE_DATE_TIMESTAMP}."
install_flatpak_prerequisites
print_flatpak_toolchain_summary
emit_build_context "${REPRO_DEBUG_DIR}"
check_flatpak_sandbox_support
ensure_flathub_remote
run_metadata_compose_smoke_test
stage_source_tree
build_flatpak_bundle

if [ "${BITCOINSAFE_FLATPAK_SKIP_INSTALL_AND_TEST:-0}" = "1" ]; then
    info "Skipping Flatpak install and smoke test."
    exit 0
fi

"${INSTALL_AND_TEST_SCRIPT}" "$(cat "${WORK_DIR}/bundle-path.txt")" "${APP_ID}"

info "Flatpak build and smoke test completed successfully."
