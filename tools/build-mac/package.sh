#!/usr/bin/env bash

set -ex

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../.."
CONTRIB="$PROJECT_ROOT/tools"
. "$CONTRIB"/build_tools_util.sh

METADATA_SCRIPT="$PROJECT_ROOT/tools/generate_packaging_metadata.py"
PACKAGE_NAME="$(python3 "$METADATA_SCRIPT" get macos-bundle-name)"
DMG_VOLUME_NAME="$(python3 "$METADATA_SCRIPT" get macos-dmg-volume-name)"
DMG_BACKGROUND_PATH="$PROJECT_ROOT/tools/resources/dmg-background.png"


if [ -z "$1" ]; then
    echo "Usage: $0 ${PACKAGE_NAME}"
    exit -127
fi

plist=$1/Contents/Info.plist
test -f "$plist" || fail "Info.plist not found"
VERSION=$(grep -1 ShortVersionString $plist | tail -1 | gawk 'match($0, /<string>(.*)<\/string>/, a) {print a[1]}')
echo $VERSION

build_dir=$(dirname "$1")
test -n "$build_dir" -a -d "$build_dir" || exit
cd "$build_dir"

"$PROJECT_ROOT/tools/build-mac/create_styled_dmg.sh" \
    "$1" \
    "$build_dir/bitcoin_safe-$VERSION.dmg" \
    "$DMG_VOLUME_NAME" \
    "$DMG_BACKGROUND_PATH" || fail "Unable to create styled dmg"

echo "Done."
sha256sum bitcoin_safe-$VERSION.dmg
