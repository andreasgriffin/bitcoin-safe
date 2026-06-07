#!/usr/bin/env bash

set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "This script needs to be run on macOS."
    exit 1
fi

APP_BUNDLE_PATH="${1:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
OUTPUT_DMG_PATH="${2:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
VOLUME_NAME="${3:-Bitcoin Safe}"

TEMP_ROOT="$(mktemp -d "/tmp/bitcoin_safe_dmg.XXXXXX")"
STAGING_DIR="${TEMP_ROOT}/staging"
APP_NAME="$(basename "${APP_BUNDLE_PATH}")"

cleanup() {
    rm -rf "${TEMP_ROOT}" || true
}
trap cleanup EXIT

mkdir -p "${STAGING_DIR}"
cp -R "${APP_BUNDLE_PATH}" "${STAGING_DIR}/${APP_NAME}"
ln -s /Applications "${STAGING_DIR}/Applications"
touch -h -t "200101220000" "${STAGING_DIR}/Applications"

mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
rm -f "${OUTPUT_DMG_PATH}"

attempts=0
until hdiutil create \
    -fs HFS+ \
    -volname "${VOLUME_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    "${OUTPUT_DMG_PATH}" \
    >/dev/null; do
    if [ "${attempts}" -eq 10 ]; then
        echo "Could not create .DMG"
        exit 1
    fi
    attempts=$((attempts + 1))
    sleep 1
done
