#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../.. && pwd)}"
APP_ID="${2:-org.bitcoin_safe.BitcoinSafe}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${SCRIPT_DIR}/build/repro-check"
RUN1_DIR="${WORK_DIR}/run1"
RUN2_DIR="${WORK_DIR}/run2"
REPO1_DIR="${WORK_DIR}/repo1"
REPO2_DIR="${WORK_DIR}/repo2"
CHECKOUT1_DIR="${WORK_DIR}/checkout1"
CHECKOUT2_DIR="${WORK_DIR}/checkout2"
SOURCE_DATE_EPOCH="$(git -C "${PROJECT_ROOT}" show -s --format=%ct HEAD)"
VERSION="$(git -C "${PROJECT_ROOT}" describe --tags --always --abbrev=20)"

source "${SCRIPT_DIR}/flatpak_common.sh"

require_clean_checkout() {
    git -C "${PROJECT_ROOT}" diff --quiet --ignore-submodules HEAD -- \
        || fail "A clean checkout is required for reproducibility checks."
    git -C "${PROJECT_ROOT}" diff --cached --quiet --ignore-submodules -- \
        || fail "A clean checkout is required for reproducibility checks."
}

build_once() {
    local run_dir="$1"

    rm -rf "${run_dir}"
    mkdir -p "${run_dir}/dist"
    BITCOINSAFE_FLATPAK_SKIP_INSTALL_AND_TEST=1 \
    BITCOINSAFE_FLATPAK_VERSION="${VERSION}" \
    BITCOINSAFE_SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH}" \
        bash "${SCRIPT_DIR}/build_and_test.sh" "${PROJECT_ROOT}" "${run_dir}/dist" "${APP_ID}"
}

bundle_path_for() {
    find "$1/dist" -type f -name '*.flatpak' | sort | head -n 1
}

checkout_bundle_tree() {
    local bundle_path="$1"
    local repo_dir="$2"
    local checkout_dir="$3"
    local ref

    rm -rf "${repo_dir}" "${checkout_dir}"
    mkdir -p "${repo_dir}"
    # Compare imported OSTree payloads when bundle hashes differ. This tells us
    # whether the drift is inside the app files or only in outer bundle
    # metadata.
    flatpak build-import-bundle --no-update-summary "${repo_dir}" "${bundle_path}" >/dev/null
    ref="$(ostree refs --repo="${repo_dir}" | head -n 1)"
    [ -n "${ref}" ] || fail "No OSTree ref was imported from ${bundle_path}."
    ostree --repo="${repo_dir}" checkout "${ref}" "${checkout_dir}"
}

require_clean_checkout
install_flatpak_prerequisites
check_flatpak_sandbox_support
ensure_flathub_remote

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

info "Building first Flatpak bundle."
build_once "${RUN1_DIR}"
info "Building second Flatpak bundle."
build_once "${RUN2_DIR}"

BUNDLE1="$(bundle_path_for "${RUN1_DIR}")"
BUNDLE2="$(bundle_path_for "${RUN2_DIR}")"
[ -n "${BUNDLE1}" ] || fail "First Flatpak bundle was not produced."
[ -n "${BUNDLE2}" ] || fail "Second Flatpak bundle was not produced."

SHA1="$(sha256sum "${BUNDLE1}" | awk '{print $1}')"
SHA2="$(sha256sum "${BUNDLE2}" | awk '{print $1}')"
info "First bundle SHA256:  ${SHA1}"
info "Second bundle SHA256: ${SHA2}"

if [ "${SHA1}" = "${SHA2}" ]; then
    info "Reproducibility check passed: bundle hashes match exactly."
    exit 0
fi

info "Bundle hashes differ; comparing imported OSTree trees."
checkout_bundle_tree "${BUNDLE1}" "${REPO1_DIR}" "${CHECKOUT1_DIR}"
checkout_bundle_tree "${BUNDLE2}" "${REPO2_DIR}" "${CHECKOUT2_DIR}"

if diff -qr "${CHECKOUT1_DIR}" "${CHECKOUT2_DIR}" >/dev/null; then
    fail "Flatpak payload trees match, but the outer .flatpak bundles differ."
fi

diff -qr "${CHECKOUT1_DIR}" "${CHECKOUT2_DIR}" || true
fail "Flatpak payload trees differ between repeated builds."
