#!/usr/bin/env bash

set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "This script needs to be run on macOS."
    exit 1
fi

APP_BUNDLE_PATH="${1:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
OUTPUT_DMG_PATH="${2:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
VOLUME_NAME="${3:-Bitcoin Safe}"
BACKGROUND_IMAGE_PATH="${4:-$(dirname "$0")/../resources/dmg-background.png}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMP_ROOT="$(mktemp -d "/tmp/bitcoin_safe_dmg.XXXXXX")"
STAGING_DIR="${TEMP_ROOT}/staging"
RW_DMG_PATH="${TEMP_ROOT}/staged.dmg"
APP_NAME="$(basename "${APP_BUNDLE_PATH}")"

cleanup() {
    local mount_dir

    mount_dir="${TEMP_ROOT}/mount"
    if [ -d "${mount_dir}" ] && mount | grep -Fq "on ${mount_dir} "; then
        hdiutil detach "${mount_dir}" -quiet || true
    fi
    rm -rf "${TEMP_ROOT}"
}
trap cleanup EXIT

mkdir -p "${STAGING_DIR}/.background"
cp -R "${APP_BUNDLE_PATH}" "${STAGING_DIR}/${APP_NAME}"
cp "${BACKGROUND_IMAGE_PATH}" "${STAGING_DIR}/.background/dmg-background.png"
ln -s /Applications "${STAGING_DIR}/Applications"
touch -h -t '200101220000' "${STAGING_DIR}/.background/dmg-background.png"
touch -h -t '200101220000' "${STAGING_DIR}/Applications"

hdiutil create \
    -fs HFS+ \
    -format UDRW \
    -volname "${VOLUME_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    "${RW_DMG_PATH}" \
    >/dev/null

mkdir -p "${TEMP_ROOT}/mount"
DEVICE_NAME="$(
    hdiutil attach "${RW_DMG_PATH}" -readwrite -noverify -noautoopen -mountpoint "${TEMP_ROOT}/mount" \
        | awk '/Apple_HFS/ {print $1; exit}'
)"

if [ -z "${DEVICE_NAME}" ]; then
    echo "Failed to mount temporary DMG."
    exit 1
fi

chflags hidden "${TEMP_ROOT}/mount/.background"

osascript <<EOF
set volume_name to "${VOLUME_NAME}"
tell application "Finder"
    repeat 30 times
        if exists disk volume_name then
            exit repeat
        end if
        delay 1
    end repeat
    if not (exists disk volume_name) then
        error "Finder could not see mounted disk " & quote & volume_name & quote
    end if
    tell disk volume_name
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {140, 120, 780, 520}
        set view_options to the icon view options of container window
        set arrangement of view_options to not arranged
        set icon size of view_options to 128
        set text size of view_options to 14
        set background picture of view_options to file ".background:dmg-background.png"
        set position of item "${APP_NAME}" of container window to {170, 215}
        set position of item "Applications" of container window to {470, 215}
        close
        open
        update without registering applications
        delay 2
    end tell
end tell
EOF

sync
hdiutil detach "${DEVICE_NAME}" -quiet

mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
rm -f "${OUTPUT_DMG_PATH}"
hdiutil convert "${RW_DMG_PATH}" -format UDZO -imagekey zlib-level=9 -o "${OUTPUT_DMG_PATH}" >/dev/null
