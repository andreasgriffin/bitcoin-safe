#!/usr/bin/env bash

set -e

security -v unlock-keychain login.keychain

PACKAGE=Bitcoin_Safe

. "$(dirname "$0")/../build_tools_util.sh"

CONTRIB_OSX="$(dirname "$(realpath "$0")")"
CONTRIB="$CONTRIB_OSX/.."
PROJECT_ROOT="$CONTRIB/.."
CACHEDIR="$CONTRIB_OSX/.cache"
CODESIGN_CERT="andreas"

cd "$PROJECT_ROOT"

# Code Signing: Using a self-signed certificate
if [ -n "$CODESIGN_CERT" ]; then
    # Test that the identity is valid by trying a dry run sign
    cp -f /bin/ls ./CODESIGN_TEST
    set +e
    codesign -s "$CODESIGN_CERT" --dryrun -f ./CODESIGN_TEST > /dev/null 2>&1
    res=$?
    set -e
    rm -f ./CODESIGN_TEST
    if ((res)); then
        fail "Code signing identity \"$CODESIGN_CERT\" appears to be invalid."
    fi
    info "Code signing enabled using identity \"$CODESIGN_CERT\""
else
    fail "Code signing disabled. Specify a valid certificate identity in 'CODESIGN_CERT' to enable signing."
fi

function DoCodeSignMaybe { # ARGS: infoName fileOrDirName
    infoName="$1"
    file="$2"
    deep=""
    if [ -z "$CODESIGN_CERT" ]; then
        # no cert -> we won't codesign
        return
    fi
    if [ -d "$file" ]; then
        deep="--deep"
    fi
    if [ -z "$infoName" ] || [ -z "$file" ] || [ ! -e "$file" ]; then
        fail "Argument error to internal function DoCodeSignMaybe()"
    fi

    # For a self-signed certificate, we typically won't set hardened runtime or entitlements.
    # If you have entitlements you wish to apply, you can add them here.
    # Example (uncomment if you have entitlements):
    # hardened_arg="--entitlements=${CONTRIB_OSX}/entitlements.plist -o runtime"
    # Otherwise, keep it empty:
    hardened_arg=""

    info "Code signing ${infoName}..."
    codesign -f -v $deep -s "$CODESIGN_CERT" $hardened_arg "$file" || fail "Could not code sign ${infoName}"
}

VERSION=$(git describe --tags --dirty --always --abbrev=20)
list_dirty_files

DoCodeSignMaybe "app bundle" "dist/${PACKAGE}.app"

# Removed notarization since we are using a self-signed certificate and do not have Apple Developer credentials.
# if [ ! -z "$CODESIGN_CERT" ]; then
#     if [ ! -z "$APPLE_ID_USER" ]; then
#         info "Notarizing .app with Apple's central server..."
#         "${CONTRIB_OSX}/notarize_app.sh" "dist/${PACKAGE}.app" || fail "Could not notarize binary."
#     else
#         warn "AppleID details not set! Skipping Apple notarization."
#     fi
# fi

info "Creating .DMG"
hdiutil create -fs HFS+ -volname $PACKAGE -srcfolder dist/$PACKAGE.app dist/bitcoin_safe-$VERSION.dmg || fail "Could not create .DMG"

DoCodeSignMaybe ".DMG" "dist/bitcoin_safe-${VERSION}.dmg"
