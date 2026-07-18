#!/usr/bin/env bash

set -euo pipefail

if [ "$(uname)" != "Darwin" ]; then
    echo "This script needs to be run on macOS."
    exit 1
fi

APP_BUNDLE_PATH="${1:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
OUTPUT_DMG_PATH="${2:?Usage: $0 <app-bundle-path> <output-dmg-path> [volume-name] [background-image-path]}"
VOLUME_NAME="${3:-Bitcoin-Safe}"
BACKGROUND_IMAGE_PATH="${4:-$(dirname "$0")/../resources/dmg-background.png}"
WINDOW_LEFT=140
WINDOW_TOP=120
WINDOW_WIDTH=640
WINDOW_HEIGHT=400
WINDOW_RIGHT=$((WINDOW_LEFT + WINDOW_WIDTH))
WINDOW_BOTTOM=$((WINDOW_TOP + WINDOW_HEIGHT))
ICON_SIZE=104
ICON_TEXT_SIZE=13
APP_ICON_X=132
APP_ICON_Y=170
APPLICATIONS_ICON_X=506
APPLICATIONS_ICON_Y=170

TEMP_ROOT="$(mktemp -d "/tmp/bitcoin_safe_dmg.XXXXXX")"
TEMP_ROOT="$(cd "${TEMP_ROOT}" && pwd -P)"
STAGING_DIR="${TEMP_ROOT}/staging"
RW_DMG_PATH="${TEMP_ROOT}/staged.dmg"
MOUNT_DIR="${TEMP_ROOT}/mount"
APP_NAME="$(basename "${APP_BUNDLE_PATH}")"
DEVICE_NAME=""
BACKGROUND_COPY_PATH="${STAGING_DIR}/.background/dmg-background.png"
DMG_RETRY_ATTEMPTS=5
DMG_RETRY_DELAY_SECONDS=10
DMG_RELEASE_ATTEMPTS=30

wait_before_dmg_retry() {
    local failed_attempts="${1}"
    local delay=$((DMG_RETRY_DELAY_SECONDS * (2 ** (failed_attempts - 1))))
    local next_attempt=$((failed_attempts + 1))

    echo "Retrying DMG operation in ${delay} seconds (attempt ${next_attempt} of ${DMG_RETRY_ATTEMPTS})."
    sleep "${delay}"
}

staged_dmg_is_attached() {
    local image_info

    if ! image_info="$(hdiutil info)"; then
        echo "Could not query attached disk images; treating the staged DMG as attached." >&2
        return 0
    fi
    grep -Fq "${RW_DMG_PATH}" <<<"${image_info}"
}

print_dmg_diagnostics() {
    echo "Disk image diagnostics:"
    hdiutil info || true
    df -h "${TEMP_ROOT}" "$(dirname "${OUTPUT_DMG_PATH}")" || true
    lsof "${RW_DMG_PATH}" || true
}

wait_for_dmg_release() {
    local attempts=0

    while { [ -d "${MOUNT_DIR}" ] && mount | grep -Fq "on ${MOUNT_DIR} "; } || staged_dmg_is_attached; do
        if [ "${attempts}" -ge "${DMG_RELEASE_ATTEMPTS}" ]; then
            echo "Timed out waiting for staged DMG to detach completely."
            print_dmg_diagnostics
            return 1
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
}

detach_dmg() {
    if [ -n "${DEVICE_NAME}" ]; then
        if ! hdiutil detach "${DEVICE_NAME}" -quiet; then
            echo "Normal detach failed for ${DEVICE_NAME}; trying a forced detach."
            hdiutil detach "${DEVICE_NAME}" -force -quiet || true
        fi
        wait_for_dmg_release || return 1
        DEVICE_NAME=""
        return
    fi
    if [ -d "${MOUNT_DIR}" ] && mount | grep -Fq "on ${MOUNT_DIR} "; then
        if ! hdiutil detach "${MOUNT_DIR}" -quiet; then
            echo "Normal detach failed for ${MOUNT_DIR}; trying a forced detach."
            hdiutil detach "${MOUNT_DIR}" -force -quiet || true
        fi
        wait_for_dmg_release
    fi
}

create_plain_dmg() {
    local attempts=1

    mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
    rm -f "${OUTPUT_DMG_PATH}"
    until hdiutil create \
        -fs HFS+ \
        -volname "${VOLUME_NAME}" \
        -srcfolder "${STAGING_DIR}" \
        "${OUTPUT_DMG_PATH}" \
        >/dev/null; do
        if [ "${attempts}" -ge "${DMG_RETRY_ATTEMPTS}" ]; then
            echo "Could not create .DMG"
            print_dmg_diagnostics
            return 1
        fi
        wait_before_dmg_retry "${attempts}"
        attempts=$((attempts + 1))
    done
}

convert_compressed_dmg() {
    local attempts=1

    mkdir -p "$(dirname "${OUTPUT_DMG_PATH}")"
    rm -f "${OUTPUT_DMG_PATH}"
    until hdiutil convert \
        "${RW_DMG_PATH}" \
        -format UDZO \
        -imagekey zlib-level=9 \
        -o "${OUTPUT_DMG_PATH}" \
        >/dev/null; do
        if [ "${attempts}" -ge "${DMG_RETRY_ATTEMPTS}" ]; then
            echo "Could not convert staged DMG."
            print_dmg_diagnostics
            return 1
        fi
        rm -f "${OUTPUT_DMG_PATH}"
        wait_before_dmg_retry "${attempts}"
        attempts=$((attempts + 1))
    done
}

cleanup() {
    detach_dmg || true
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
ATTACH_OUTPUT="$(
    hdiutil attach "${RW_DMG_PATH}" -readwrite -noverify -noautoopen -mountpoint "${MOUNT_DIR}"
)"
VOLUME_DEVICE="$(printf '%s\n' "${ATTACH_OUTPUT}" | awk '/Apple_HFS/ {print $1; exit}')"
DEVICE_NAME="$(printf '%s\n' "${VOLUME_DEVICE}" | sed -E 's/s[0-9]+$//')"

if [ -z "${VOLUME_DEVICE}" ] || [ -z "${DEVICE_NAME}" ]; then
    echo "Failed to mount temporary DMG."
    printf '%s\n' "${ATTACH_OUTPUT}"
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

convert_compressed_dmg
