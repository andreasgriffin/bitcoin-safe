#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="tools/deterministic-build"

python -m pip install "pip-tools>=7.5.0"

rm "${SCRIPT_DIR}/requirements-build.txt"
pip-compile "${SCRIPT_DIR}/requirements-build.in" --generate-hashes --allow-unsafe
