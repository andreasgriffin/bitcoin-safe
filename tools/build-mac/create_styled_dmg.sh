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
WINDOW_LEFT=140
WINDOW_TOP=120
WINDOW_WIDTH=640
WINDOW_HEIGHT=400
WINDOW_RIGHT=$((WINDOW_LEFT + WINDOW_WIDTH))
WINDOW_BOTTOM=$((WINDOW_TOP + WINDOW_HEIGHT))
ICON_SIZE=104
ICON_TEXT_SIZE=13
APP_ICON_X=138
APP_ICON_Y=228
APPLICATIONS_ICON_X=506
APPLICATIONS_ICON_Y=228

TEMP_ROOT="$(mktemp -d "/tmp/bitcoin_safe_dmg.XXXXXX")"
STAGING_DIR="${TEMP_ROOT}/staging"
RW_DMG_PATH="${TEMP_ROOT}/staged.dmg"
MOUNT_DIR="${TEMP_ROOT}/mount"
APP_NAME="$(basename "${APP_BUNDLE_PATH}")"
DEVICE_NAME=""
BACKGROUND_COPY_PATH="${STAGING_DIR}/.background/dmg-background.png"

detach_dmg() {
    if [ -n "${DEVICE_NAME}" ]; then
        hdiutil detach "${DEVICE_NAME}" -quiet || hdiutil detach "${DEVICE_NAME}" -force -quiet || true
        DEVICE_NAME=""
        return
    fi
    if [ -d "${MOUNT_DIR}" ] && mount | grep -Fq "on ${MOUNT_DIR} "; then
        hdiutil detach "${MOUNT_DIR}" -quiet || hdiutil detach "${MOUNT_DIR}" -force -quiet || true
    fi
}

create_plain_dmg() {
    local attempts=0

    mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
    rm -f "${OUTPUT_DMG_PATH}"
    until hdiutil create \
        -fs HFS+ \
        -volname "${VOLUME_NAME}" \
        -srcfolder "${STAGING_DIR}" \
        "${OUTPUT_DMG_PATH}" \
        >/dev/null; do
        if [ "${attempts}" -eq 10 ]; then
            echo "Could not create .DMG"
            return 1
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
}

cleanup() {
    detach_dmg
    rm -rf "${TEMP_ROOT}" || true
}
trap cleanup EXIT

mkdir -p "${STAGING_DIR}/.background"
cp -R "${APP_BUNDLE_PATH}" "${STAGING_DIR}/${APP_NAME}"
cp "${BACKGROUND_IMAGE_PATH}" "${BACKGROUND_COPY_PATH}"
sips -z "${WINDOW_HEIGHT}" "${WINDOW_WIDTH}" "${BACKGROUND_COPY_PATH}" >/dev/null
ln -s /Applications "${STAGING_DIR}/Applications"
touch -h -t "200101220000" "${BACKGROUND_COPY_PATH}"
touch -h -t "200101220000" "${STAGING_DIR}/Applications"

hdiutil create \
    -fs HFS+ \
    -format UDRW \
    -volname "${VOLUME_NAME}" \
    -srcfolder "${STAGING_DIR}" \
    "${RW_DMG_PATH}" \
    >/dev/null

mkdir -p "${MOUNT_DIR}"
DEVICE_NAME="$(
    hdiutil attach "${RW_DMG_PATH}" -readwrite -noverify -noautoopen -mountpoint "${MOUNT_DIR}" \
        | awk '/Apple_HFS/ {print $1; exit}'
)"

if [ -z "${DEVICE_NAME}" ]; then
    echo "Failed to mount temporary DMG."
    exit 1
fi

chflags hidden "${MOUNT_DIR}/.background"

if ! osascript <<EOF
set dmg_folder to POSIX file "${MOUNT_DIR}" as alias
set background_image to POSIX file "${MOUNT_DIR}/.background/dmg-background.png" as alias
tell application "Finder"
    open folder dmg_folder
    repeat 30 times
        try
            set dmg_window to container window of folder dmg_folder
            exit repeat
        on error
            delay 1
        end try
    end repeat
    set dmg_window to container window of folder dmg_folder
    set current view of dmg_window to icon view
    set toolbar visible of dmg_window to false
    set statusbar visible of dmg_window to false
    set the bounds of dmg_window to {${WINDOW_LEFT}, ${WINDOW_TOP}, ${WINDOW_RIGHT}, ${WINDOW_BOTTOM}}
    set view_options to the icon view options of dmg_window
    set arrangement of view_options to not arranged
    set icon size of view_options to ${ICON_SIZE}
    set text size of view_options to ${ICON_TEXT_SIZE}
    set background picture of view_options to background_image
    set position of item "${APP_NAME}" of dmg_window to {${APP_ICON_X}, ${APP_ICON_Y}}
    set position of item "Applications" of dmg_window to {${APPLICATIONS_ICON_X}, ${APPLICATIONS_ICON_Y}}
    update folder dmg_folder without registering applications
    delay 2
    close dmg_window
end tell
EOF
then
    detach_dmg
    create_plain_dmg
    exit 0
fi

sync
detach_dmg

mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
rm -f "${OUTPUT_DMG_PATH}"
hdiutil convert "${RW_DMG_PATH}" -format UDZO -imagekey zlib-level=9 -o "${OUTPUT_DMG_PATH}" >/dev/null
