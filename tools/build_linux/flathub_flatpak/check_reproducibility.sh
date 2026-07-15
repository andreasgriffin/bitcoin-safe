#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../.. && pwd)}"
APP_ID="${2:-org.bitcoin_safe.BitcoinSafe}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${SCRIPT_DIR}/build/repro-check"
RUN1_DIR="${WORK_DIR}/run1"
RUN2_DIR="${WORK_DIR}/run2"
IMPORT_REPO1_DIR="${WORK_DIR}/import-repo1"
IMPORT_REPO2_DIR="${WORK_DIR}/import-repo2"
IMPORT_CHECKOUT1_DIR="${WORK_DIR}/import-checkout1"
IMPORT_CHECKOUT2_DIR="${WORK_DIR}/import-checkout2"
SOURCE_DATE_EPOCH="$(git -C "${PROJECT_ROOT}" show -s --format=%ct HEAD)"

source "${SCRIPT_DIR}/flatpak_common.sh"

require_clean_checkout() {
    git -C "${PROJECT_ROOT}" diff --quiet --ignore-submodules HEAD -- \
        || fail "A clean checkout is required for reproducibility checks."
    git -C "${PROJECT_ROOT}" diff --cached --quiet --ignore-submodules -- \
        || fail "A clean checkout is required for reproducibility checks."
}

require_host_build_tools() {
    command -v docker >/dev/null 2>&1 || fail "docker is required for Flatpak reproducibility checks."
    command -v poetry >/dev/null 2>&1 || fail "poetry is required for Flatpak reproducibility checks."
}

prepare_run_dir() {
    local run_dir="$1"

    rm -rf "${run_dir}"
    mkdir -p "${run_dir}/dist"
}

copy_latest_repro_debug() {
    local run_dir="$1"
    local latest_debug_dir="${PROJECT_ROOT}/tools/build_linux/flathub_flatpak/build/repro-debug/latest"

    [ -d "${latest_debug_dir}" ] || fail "Missing reproducibility diagnostics at ${latest_debug_dir}."
    cp -a "${latest_debug_dir}" "${run_dir}/repro-debug"
}

copy_flatpak_bundle() {
    local run_dir="$1"
    local bundle_path

    bundle_path="$(find "${PROJECT_ROOT}/dist" -maxdepth 1 -type f -name '*.flatpak' | sort | head -n 1)"
    [ -n "${bundle_path}" ] || fail "No Flatpak bundle was produced in ${PROJECT_ROOT}/dist."
    cp -a "${bundle_path}" "${run_dir}/dist/"
}

build_once() {
    local run_dir="$1"

    prepare_run_dir "${run_dir}"
    find "${PROJECT_ROOT}/dist" -maxdepth 1 -type f -name '*.flatpak' -delete 2>/dev/null || true

    PATH="$(poetry -C "${PROJECT_ROOT}" env info -p)/bin:${PATH}" \
        poetry -C "${PROJECT_ROOT}" run python tools/build.py --targets flatpak --commit None

    copy_flatpak_bundle "${run_dir}"
    copy_latest_repro_debug "${run_dir}"
}

bundle_path_for() {
    find "$1/dist" -type f -name '*.flatpak' | sort | head -n 1
}

compare_text_file() {
    local description="$1"
    local first_path="$2"
    local second_path="$3"

    if cmp -s "${first_path}" "${second_path}"; then
        return 0
    fi

    info "${description}"
    diff -u "${first_path}" "${second_path}" | sed -n '1,200p' || true
    exit 1
}

compare_manifest_stage() {
    local description="$1"
    local manifest_name="$2"
    local run1_debug_dir="$3"
    local run2_debug_dir="$4"

    if cmp -s "${run1_debug_dir}/${manifest_name}.sha256" "${run2_debug_dir}/${manifest_name}.sha256"; then
        return 0
    fi

    info "${description}"
    info "run1 ${manifest_name} hash: $(cat "${run1_debug_dir}/${manifest_name}.sha256")"
    info "run2 ${manifest_name} hash: $(cat "${run2_debug_dir}/${manifest_name}.sha256")"
    diff -u "${run1_debug_dir}/${manifest_name}.manifest" "${run2_debug_dir}/${manifest_name}.manifest" \
        | sed -n '1,200p' || true
    exit 1
}

checkout_imported_bundle_tree() {
    local bundle_path="$1"
    local repo_dir="$2"
    local checkout_dir="$3"
    local ref

    rm -rf "${repo_dir}" "${checkout_dir}"
    mkdir -p "${repo_dir}"
    ostree init --repo="${repo_dir}" --mode=archive >/dev/null
    flatpak build-import-bundle --no-update-summary "${repo_dir}" "${bundle_path}" >/dev/null
    ref="$(ostree refs --repo="${repo_dir}" | head -n 1)"
    [ -n "${ref}" ] || fail "No OSTree ref was imported from ${bundle_path}."
    ostree --repo="${repo_dir}" checkout "${ref}" "${checkout_dir}"
}

compare_imported_bundle_trees() {
    local bundle1="$1"
    local bundle2="$2"

    checkout_imported_bundle_tree "${bundle1}" "${IMPORT_REPO1_DIR}" "${IMPORT_CHECKOUT1_DIR}"
    checkout_imported_bundle_tree "${bundle2}" "${IMPORT_REPO2_DIR}" "${IMPORT_CHECKOUT2_DIR}"

    if diff -qr "${IMPORT_CHECKOUT1_DIR}" "${IMPORT_CHECKOUT2_DIR}" >/dev/null; then
        fail "Outer Flatpak bundles differ, but the imported bundle trees match. This points to bundle-level metadata drift."
    fi

    diff -qr "${IMPORT_CHECKOUT1_DIR}" "${IMPORT_CHECKOUT2_DIR}" | sed -n '1,200p' || true
    fail "Imported bundle payload trees differ even though earlier checkpoints matched."
}

compare_run_diagnostics() {
    local run1_debug_dir="$1"
    local run2_debug_dir="$2"
    local bundle1="$3"
    local bundle2="$4"

    compare_text_file \
        "Build context differs between Flatpak runs." \
        "${run1_debug_dir}/context.txt" \
        "${run2_debug_dir}/context.txt"

    compare_manifest_stage \
        "Staged source tree differs between Docker Flatpak builds." \
        "source-tree" \
        "${run1_debug_dir}" \
        "${run2_debug_dir}"

    compare_manifest_stage \
        "Finalized /app tree differs between Docker Flatpak builds." \
        "builder-files" \
        "${run1_debug_dir}" \
        "${run2_debug_dir}"

    if ! cmp -s "${run1_debug_dir}/ostree-files.sha256" "${run2_debug_dir}/ostree-files.sha256"; then
        info "Exported OSTree file tree differs while finalized /app tree matches."
        info "run1 ostree-files hash: $(cat "${run1_debug_dir}/ostree-files.sha256")"
        info "run2 ostree-files hash: $(cat "${run2_debug_dir}/ostree-files.sha256")"
        diff -u "${run1_debug_dir}/ostree-files.manifest" "${run2_debug_dir}/ostree-files.manifest" \
            | sed -n '1,200p' || true
        exit 1
    fi

    if ! cmp -s "${run1_debug_dir}/ostree-commit.txt" "${run2_debug_dir}/ostree-commit.txt"; then
        info "Exported OSTree commit differs while finalized /app tree and exported file tree match."
        info "run1 ostree commit: $(cat "${run1_debug_dir}/ostree-commit.txt")"
        info "run2 ostree commit: $(cat "${run2_debug_dir}/ostree-commit.txt")"
        diff -u "${run1_debug_dir}/ostree-show.txt" "${run2_debug_dir}/ostree-show.txt" | sed -n '1,200p' || true
        exit 1
    fi

    if cmp -s "${run1_debug_dir}/bundle.sha256" "${run2_debug_dir}/bundle.sha256"; then
        info "Reproducibility check passed: bundle hashes match exactly."
        return
    fi

    info "run1 bundle hash: $(cat "${run1_debug_dir}/bundle.sha256")"
    info "run2 bundle hash: $(cat "${run2_debug_dir}/bundle.sha256")"

    if cmp -s "${run1_debug_dir}/bundle-imported-commit.txt" "${run2_debug_dir}/bundle-imported-commit.txt"; then
        fail "Outer Flatpak bundle differs while imported bundle commit matches."
    fi

    compare_imported_bundle_trees "${bundle1}" "${bundle2}"
}

require_clean_checkout
require_host_build_tools
install_flatpak_prerequisites

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

info "Building first Flatpak bundle through the Docker build path."
build_once "${RUN1_DIR}"
info "Building second Flatpak bundle through the Docker build path."
build_once "${RUN2_DIR}"

BUNDLE1="$(bundle_path_for "${RUN1_DIR}")"
BUNDLE2="$(bundle_path_for "${RUN2_DIR}")"
[ -n "${BUNDLE1}" ] || fail "First Flatpak bundle was not produced."
[ -n "${BUNDLE2}" ] || fail "Second Flatpak bundle was not produced."

compare_run_diagnostics "${RUN1_DIR}/repro-debug" "${RUN2_DIR}/repro-debug" "${BUNDLE1}" "${BUNDLE2}"
