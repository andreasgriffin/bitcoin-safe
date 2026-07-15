#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
LOCKED_CONSTRAINTS_FILE="tools/deterministic-build/.locked-build-constraints.txt"

cd "$PROJECT_ROOT"
trap 'rm -f "${LOCKED_CONSTRAINTS_FILE}"' EXIT

poetry sync --with dev --no-root

write_constraints() {
    poetry run pip freeze --all | grep -E '^[A-Za-z0-9_.-]+==' > "${LOCKED_CONSTRAINTS_FILE}"
    for excluded_package in "$@"; do
        local tmp_file="${LOCKED_CONSTRAINTS_FILE}.tmp"
        grep -Eiv "^${excluded_package}==" "${LOCKED_CONSTRAINTS_FILE}" > "${tmp_file}" || true
        mv "${tmp_file}" "${LOCKED_CONSTRAINTS_FILE}"
    done
}

compile_requirements() {
    local input_file="$1"
    local output_file="$2"
    shift 2

    write_constraints "$@"
    rm -f "$output_file"
    CUSTOM_COMPILE_COMMAND="bash tools/deterministic-build/compile.sh" \
        poetry run pip-compile \
            "$input_file" \
            --constraint "${LOCKED_CONSTRAINTS_FILE}" \
            --generate-hashes \
            --allow-unsafe \
            --no-strip-extras \
            --output-file "$output_file"
}

compile_requirements "tools/deterministic-build/requirements-build.in" "tools/deterministic-build/requirements-build.txt"
compile_requirements \
    "tools/deterministic-build/requirements-build_mac_x86_64.in" \
    "tools/deterministic-build/requirements-build_mac_x86_64.txt" \
    "cryptography"
