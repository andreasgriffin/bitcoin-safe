#!/usr/bin/env bash

set -euo pipefail

BUNDLE_PATH="${1:?usage: install_and_smoke_test_bundle.sh <bundle-path> [app-id]}"
APP_ID="${2:-org.bitcoin_safe.BitcoinSafe}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${SCRIPT_DIR}/build"
RUN_LOG="${WORK_DIR}/flatpak-run.log"
SCREENSHOT_PREFIX="${WORK_DIR}/flatpak-screenshot"
SMOKE_TEST_TIMEOUT_SECONDS=40
SCREENSHOT_INTERVAL_SECONDS=2
SCREENSHOT_COUNT=20
source "${SCRIPT_DIR}/flatpak_common.sh"

install_bundle() {
    info "Installing Flatpak bundle ${BUNDLE_PATH}."
    run_with_dbus_session flatpak install --user --noninteractive --reinstall "${BUNDLE_PATH}"
    run_with_dbus_session flatpak info --user "${APP_ID}" >/dev/null
}

smoke_test_bundle() {
    local capture_pid log_file run_status smoke_test_display

    log_file="${HOME}/.var/app/${APP_ID}/config/bitcoin_safe/bitcoin_safe.log"
    smoke_test_display="${DISPLAY:-desktop:0}"
    mkdir -p "${WORK_DIR}"
    rm -f "${log_file}" "${RUN_LOG}" "${SCREENSHOT_PREFIX}"-*.xwd "${SCREENSHOT_PREFIX}"-*.png

    if command -v xwd >/dev/null 2>&1; then
        (
            for i in $(seq 1 "${SCREENSHOT_COUNT}"); do
                xwd -root -silent -display "${smoke_test_display}" \
                    -out "${SCREENSHOT_PREFIX}-${i}.xwd" || true
                if command -v convert >/dev/null 2>&1; then
                    convert "${SCREENSHOT_PREFIX}-${i}.xwd" "${SCREENSHOT_PREFIX}-${i}.png" || true
                fi
                sleep "${SCREENSHOT_INTERVAL_SECONDS}"
            done
        ) &
        capture_pid=$!
    else
        info "Skipping Flatpak screenshots because xwd is not installed."
        capture_pid=""
    fi

    info "Launching Flatpak app for startup smoke test on DISPLAY=${smoke_test_display}."
    set +e
    run_with_dbus_session bash -lc \
        "DISPLAY='${smoke_test_display}' timeout ${SMOKE_TEST_TIMEOUT_SECONDS}s flatpak run ${APP_ID}" \
        >"${RUN_LOG}" 2>&1
    run_status=$?
    set -e

    if [ -n "${capture_pid}" ]; then
        wait "${capture_pid}" || true
    fi

    if [ "${run_status}" -ne 124 ]; then
        cat "${RUN_LOG}" >&2 || true
        fail "Flatpak startup smoke test exited with status ${run_status}; expected timeout 124."
    fi

    test -f "${log_file}" || fail "Expected Flatpak log file ${log_file} was not created."
    grep -q 'Starting Bitcoin-Safe' "${log_file}" || fail "Startup banner missing from Flatpak log."
    grep -q 'pyzbar could be loaded successfully' "${log_file}" \
        || fail "pyzbar did not load successfully inside Flatpak."

    if grep -Eq 'ModuleNotFoundError|ImportError|failed to load pyzbar|error while loading shared libraries' \
        "${log_file}" "${RUN_LOG}"; then
        cat "${RUN_LOG}" >&2 || true
        cat "${log_file}" >&2 || true
        fail "Detected missing module or shared-library error in Flatpak startup logs."
    fi
}

install_flatpak_prerequisites
check_flatpak_sandbox_support
ensure_flathub_remote
install_bundle
smoke_test_bundle
