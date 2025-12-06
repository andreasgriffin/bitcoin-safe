#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="tools/deterministic-build"

# pip-tools is not yet compatible with pip>=25.1
python -m pip install 'pip<25.1'
python -m pip install pip-tools

pip-compile "${SCRIPT_DIR}/requirements-build.in" --generate-hashes --allow-unsafe
