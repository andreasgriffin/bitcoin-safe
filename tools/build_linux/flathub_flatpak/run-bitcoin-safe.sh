#!/usr/bin/env bash

set -euo pipefail

exec env \
    PYZBAR_LIBRARY="/app/lib/libzbar.so" \
    python3 -s -m bitcoin_safe "$@"
