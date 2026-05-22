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

normalize_tree_timestamps() {
    local path

    for path in "$@"; do
        [ -e "${path}" ] || continue
        find "${path}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
    done
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

    normalize_tree_timestamps \
        "${METADATA_PROBE_SOURCE_DIR}" \
        "${METADATA_PROBE_BIN_DIR}" \
        "${METADATA_PROBE_MANIFEST_PATH}"
}

run_metadata_compose_smoke_test() {
    local arch

    arch="$(flatpak --default-arch)"
    write_metadata_probe_files

    info "Running metadata compose smoke test."
    run_with_dbus_session flatpak-builder \
        --user \
        --arch="${arch}" \
        --disable-rofiles-fuse \
        --force-clean \
        --install-deps-from=flathub \
        --override-source-date-epoch="${SOURCE_DATE_EPOCH}" \
        --repo="${METADATA_PROBE_REPO_DIR}" \
        --state-dir="${METADATA_PROBE_STATE_DIR}" \
        "${METADATA_PROBE_BUILDER_DIR}" \
        "${METADATA_PROBE_MANIFEST_PATH}"

    desktop-file-validate "${METADATA_PROBE_BUILDER_DIR}/files/share/applications/${APP_ID}.desktop"
    test -f "${METADATA_PROBE_BUILDER_DIR}/files/share/icons/hicolor/scalable/apps/${APP_ID}.svg" \
        || fail "Metadata smoke test did not export the SVG icon for ${APP_ID}."
}

stage_source_tree() {
    info "Staging source tree for Flatpak build."
    rm -rf "${SOURCE_STAGING_DIR}"
    mkdir -p "${SOURCE_STAGING_DIR}"

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

    normalize_tree_timestamps "${SOURCE_STAGING_DIR}"
}

build_flatpak_bundle() {
    local arch bundle_name bundle_path project_version

    arch="$(flatpak --default-arch)"
    project_version="$(get_project_version)"
    bundle_name="Bitcoin-Safe-${project_version}-${arch}.flatpak"
    bundle_path="${DIST_DIR}/${bundle_name}"

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
        --repo="${REPO_DIR}" \
        --state-dir="${STATE_DIR}" \
        "${BUILDER_DIR}" \
        "${MANIFEST_PATH}"

    info "Validating exported desktop metadata."
    desktop-file-validate "${BUILDER_DIR}/files/share/applications/${APP_ID}.desktop"
    test -f "${BUILDER_DIR}/files/share/icons/hicolor/scalable/apps/${APP_ID}.svg" \
        || fail "Missing exported icon for ${APP_ID}."

    info "Creating Flatpak bundle at ${bundle_path}."
    rm -f "${bundle_path}"
    run_with_dbus_session flatpak build-bundle \
        "${REPO_DIR}" \
        "${bundle_path}" \
        "${APP_ID}" \
        "${FLATPAK_BRANCH}" \
        --arch="${arch}"

    test -f "${bundle_path}" || fail "Flatpak bundle was not created."
    printf '%s\n' "${bundle_path}" > "${WORK_DIR}/bundle-path.txt"
}

export TZ=UTC
export SOURCE_DATE_EPOCH="$(resolve_source_date_epoch)"

info "Using SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}."
install_flatpak_prerequisites
print_flatpak_toolchain_summary
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
