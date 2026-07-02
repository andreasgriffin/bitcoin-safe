#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLATHUB_ASSET_DIR="tools/build-linux/flathub-flatpak"

export PYTHONDONTWRITEBYTECODE=1
export TZ=UTC
: "${SOURCE_DATE_EPOCH:?SOURCE_DATE_EPOCH must be set for reproducible Flatpak builds}"

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
BUILD_CACHE_ROOT="${PWD}/.cache"
TOOL_VENV_ROOT="${PWD}/.tool-venv"
APP_PYTHON="$(command -v python3)"
PIP_CACHE_DIR="${BUILD_CACHE_ROOT}/pip"
POETRY_CACHE_DIR="${BUILD_CACHE_ROOT}/poetry"
POETRY_WHEEL_DIR="${BUILD_CACHE_ROOT}/poetry-wheel"
APP_SITE_PACKAGES="/app/lib/python${PYVER}/site-packages"
VENDOR_ROOT="/app/share/bitcoin-safe/vendor"
BUILD_BACKENDS_DIR="${VENDOR_ROOT}/build-backends"
RUNTIME_VENDOR_DIR="${VENDOR_ROOT}/runtime"
GIT_VENDOR_DIR="${VENDOR_ROOT}/git-packages"

if [ -z "${APP_PYTHON}" ]; then
    echo "python3 is not available in the Flatpak build environment." >&2
    exit 1
fi

verify_runtime_import() {
    local module_name="$1"
    "${APP_PYTHON}" -c "import ${module_name}" \
        || { echo "Failed to import ${module_name} from the BaseApp Python runtime." >&2; exit 1; }
}

install_git_packages() {
    local metadata_path="${GIT_VENDOR_DIR}/git-packages-lock.json"
    mapfile -t git_archives < <(
        python3 - "${metadata_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    for package in json.load(handle):
        print(package["archive_filename"])
PY
    )

    for archive_name in "${git_archives[@]}"; do
        "${APP_PYTHON}" -m pip install \
            --ignore-installed \
            --no-dependencies \
            --no-warn-script-location \
            --prefix=/app \
            --cache-dir "${PIP_CACHE_DIR}" \
            "${GIT_VENDOR_DIR}/${archive_name}"
    done
}

python3 -m venv "${TOOL_VENV_ROOT}"
"${TOOL_VENV_ROOT}/bin/python" -m ensurepip --upgrade

# Build frontend and backend tooling only need to exist in the temporary tool
# venv; runtime packages are installed directly into /app below.
"${TOOL_VENV_ROOT}/bin/python" -m pip install \
    --no-build-isolation \
    --no-dependencies \
    --no-index \
    --find-links "${BUILD_BACKENDS_DIR}" \
    --no-warn-script-location \
    --cache-dir "${PIP_CACHE_DIR}" \
    -r "${BUILD_BACKENDS_DIR}/requirements-build-backends.txt"

rm -rf "${POETRY_WHEEL_DIR}"
mkdir -p "${POETRY_WHEEL_DIR}"
export POETRY_CACHE_DIR
export PIP_CONFIG_FILE=/dev/null
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INDEX=1
export PIP_FIND_LINKS="${BUILD_BACKENDS_DIR} ${RUNTIME_VENDOR_DIR} ${GIT_VENDOR_DIR}"

"${APP_PYTHON}" -m pip install \
    --ignore-installed \
    --no-dependencies \
    --no-warn-script-location \
    --no-compile \
    --prefix=/app \
    --cache-dir "${PIP_CACHE_DIR}" \
    -r "${RUNTIME_VENDOR_DIR}/requirements-runtime.txt"

install_git_packages

"${TOOL_VENV_ROOT}/bin/poetry" build -f wheel --output "${POETRY_WHEEL_DIR}"
"${APP_PYTHON}" -m pip install \
    --ignore-installed \
    --no-dependencies \
    --no-warn-script-location \
    --no-compile \
    --prefix=/app \
    --cache-dir "${PIP_CACHE_DIR}" \
    "${POETRY_WHEEL_DIR}"/*.whl

verify_runtime_import appdirs
verify_runtime_import bitcoin_safe

rm -rf "${APP_SITE_PACKAGES}/Cryptodome/SelfTest"
rm -rf "${APP_SITE_PACKAGES}/psutil/tests" \
    "${APP_SITE_PACKAGES}/qrcode/tests" \
    "${APP_SITE_PACKAGES}/websocket/tests"
find /app -name '.git' -type d -print0 | xargs -0 --no-run-if-empty rm -rf
find /app -type f \
    \( -name '.gitmodules' -o -name '.gitignore' -o -name '.gitattributes' -o -name '.gitkeep' \) \
    -delete
find /app -path '*/__pycache__*' -delete

install -Dm755 "${SCRIPT_DIR}/run-bitcoin-safe.sh" /app/bin/run-bitcoin-safe.sh
install -Dm644 "${FLATHUB_ASSET_DIR}/org.bitcoin_safe.BitcoinSafe.svg" /app/share/icons/hicolor/scalable/apps/org.bitcoin_safe.BitcoinSafe.svg
install -Dm644 tools/resources/icon-128.png /app/share/icons/hicolor/128x128/apps/org.bitcoin_safe.BitcoinSafe.png
install -Dm644 "${FLATHUB_ASSET_DIR}/org.bitcoin_safe.BitcoinSafe.metainfo.xml" /app/share/metainfo/org.bitcoin_safe.BitcoinSafe.metainfo.xml
sed \
    -e 's#^Exec=.*#Exec=run-bitcoin-safe.sh %F#' \
    -e 's#^Icon=.*#Icon=org.bitcoin_safe.BitcoinSafe#' \
    tools/resources/linux-bitcoin-safe.desktop \
    > org.bitcoin_safe.BitcoinSafe.desktop
install -Dm644 org.bitcoin_safe.BitcoinSafe.desktop /app/share/applications/org.bitcoin_safe.BitcoinSafe.desktop
mkdir -p /app/app
ln -sfn ../share /app/app/share

mkdir -p /app/lib/plugins
for runtime_plugin_dir in /usr/lib/plugins/*; do
    plugin_dir_name="$(basename "${runtime_plugin_dir}")"
    if [ ! -e "/app/lib/plugins/${plugin_dir_name}" ]; then
        ln -s "${runtime_plugin_dir}" "/app/lib/plugins/${plugin_dir_name}"
    fi
done

verify_runtime_import appdirs
verify_runtime_import bitcoin_safe

find /app -path '*/__pycache__*' -delete
rm -rf "${VENDOR_ROOT}" "${TOOL_VENV_ROOT}" "${BUILD_CACHE_ROOT}" dist org.bitcoin_safe.BitcoinSafe.desktop
find /app -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
