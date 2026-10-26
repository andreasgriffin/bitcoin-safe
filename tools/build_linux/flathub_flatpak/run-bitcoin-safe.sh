#!/usr/bin/env bash

set -euo pipefail


exec env \
    FONTCONFIG_FILE="${FONTCONFIG_FILE:-/app/etc/bitcoin-safe-fontconfig/fonts.conf}" \
    PYZBAR_LIBRARY="/app/lib/libzbar.so" \
    python3 -s -m bitcoin_safe "$@"
