#!/usr/bin/env bash

function bitcoin_safe_read_app_metadata_field() {
    local project_root="$1"
    local field_name="$2"
    local pythonpath="$project_root"

    if [ -n "${PYTHONPATH:-}" ]; then
        pythonpath="${project_root}:${PYTHONPATH}"
    fi

    PYTHONPATH="${pythonpath}" python3 - "${field_name}" <<'PY'
import sys

from bitcoin_safe.app_metadata import APP_METADATA

field_name = sys.argv[1]

if field_name == "application_name":
    print(APP_METADATA.application_name)
elif field_name == "macos_bundle_name":
    print(APP_METADATA.macos_bundle_name)
elif field_name == "macos_dmg_volume_name":
    print(APP_METADATA.macos_dmg_volume_name)
else:
    raise SystemExit(f"Unknown metadata field: {field_name}")
PY
}


function bitcoin_safe_application_name() {
    bitcoin_safe_read_app_metadata_field "$1" "application_name"
}


function bitcoin_safe_macos_bundle_name() {
    bitcoin_safe_read_app_metadata_field "$1" "macos_bundle_name"
}


function bitcoin_safe_macos_dmg_volume_name() {
    bitcoin_safe_read_app_metadata_field "$1" "macos_dmg_volume_name"
}
