#!/usr/bin/env bash

set -euo pipefail

# Qt 6.11 can crash when the runtime reads incompatible host fontconfig caches.
exec env \
    FONTCONFIG_FILE="${FONTCONFIG_FILE:-/app/etc/bitcoin-safe-fontconfig/fonts.conf}" \
    PYZBAR_LIBRARY="/app/lib/libzbar.so" \
    python3 -s -m bitcoin_safe "$@"
