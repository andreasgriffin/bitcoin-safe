#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="tools/deterministic-build"

rm "${SCRIPT_DIR}/requirements-build.txt" || true
pip-compile "${SCRIPT_DIR}/requirements-build.in" --generate-hashes --allow-unsafe
