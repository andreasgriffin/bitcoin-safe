#!/usr/bin/env bash

set -ex

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../.."
CONTRIB="$PROJECT_ROOT/tools"
CONTRIB_OSX="$PROJECT_ROOT/tools/build-mac"
. "$CONTRIB"/build_tools_util.sh
. "$CONTRIB_OSX"/app_metadata.sh
. "$CONTRIB_OSX"/ensure_reproducible_dmg_tools.sh

PACKAGE_NAME="$(bitcoin_safe_macos_bundle_name "$PROJECT_ROOT")"
DMG_VOLUME_NAME="$(bitcoin_safe_macos_dmg_volume_name "$PROJECT_ROOT")"

if [ -z "$1" ]; then
    echo "Usage: $0 ${PACKAGE_NAME}"
    exit -127
fi

ensure_reproducible_dmg_tools

plist=$1/Contents/Info.plist
test -f "$plist" || fail "Info.plist not found"
VERSION=$(grep -1 ShortVersionString "$plist" | tail -1 | gawk 'match($0, /<string>(.*)<\/string>/, a) {print a[1]}')
echo "$VERSION"

staging_root=/tmp/bitcoin_safe-macos
staging_dir="${staging_root}/image"
uncompressed_dmg="${staging_root}/bitcoin_safe_uncompressed.dmg"

rm -rf "$staging_root" > /dev/null 2>&1
mkdir -p "$staging_dir"
cp -r "$1" "$staging_dir/"

build_dir=$(dirname "$1")
test -n "$build_dir" -a -d "$build_dir" || exit
cd "$build_dir"

rm -f "$uncompressed_dmg" "bitcoin_safe-$VERSION.dmg"
"$BITCOIN_SAFE_GENISOIMAGE" \
    -no-cache-inodes \
    -D \
    -l \
    -probe \
    -V "$DMG_VOLUME_NAME" \
    -no-pad \
    -r \
    -dir-mode 0755 \
    -apple \
    -o "$uncompressed_dmg" \
    "$staging_dir" || fail "Unable to create uncompressed dmg"

"$BITCOIN_SAFE_DMG_COMPRESSOR" dmg "$uncompressed_dmg" "bitcoin_safe-$VERSION.dmg" \
    || fail "Unable to create compressed dmg"
rm -f "$uncompressed_dmg"

echo "Done."
sha256sum "bitcoin_safe-$VERSION.dmg"
