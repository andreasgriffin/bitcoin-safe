#!/usr/bin/env bash

set -euo pipefail

export PYZBAR_LIBRARY="/app/lib/libzbar.so"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"

exec /app/bin/python3 -s -m bitcoin_safe "$@"
