#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

pip install --upgrade pip-tools
cd "$PROJECT_ROOT"

compile_requirements() {
    local input_file="$1"
    local output_file="$2"

    rm -f "$output_file"
    pip-compile "$input_file" --generate-hashes --allow-unsafe --output-file "$output_file"
}

compile_requirements "tools/deterministic-build/requirements-build.in" "tools/deterministic-build/requirements-build.txt"
compile_requirements \
    "tools/deterministic-build/requirements-build-mac-x86_64.in" \
    "tools/deterministic-build/requirements-build-mac-x86_64.txt"
