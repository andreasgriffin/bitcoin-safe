#!/usr/bin/env bash

set -euo pipefail

PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
export PATH="/app/bin:${PATH}"
export PYTHONPATH="/app/lib/python${PYVER}/site-packages${PYTHONPATH+:${PYTHONPATH}}"
export LD_LIBRARY_PATH="/app/lib${LD_LIBRARY_PATH+:${LD_LIBRARY_PATH}}"
export PYZBAR_LIBRARY="/app/lib/libzbar.so"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

exec python3 -s -m bitcoin_safe "$@"
