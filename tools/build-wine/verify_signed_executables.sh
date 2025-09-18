#!/usr/bin/env bash
#
# Compare signed Windows executables with their unsigned counterparts.
#
# Usage:
#   tools/build-wine/verify_signed_executables.sh <unsigned-dir> <signed-dir> <variant> [<variant> ...]
#
# When running locally, build the unsigned executables into the directory specified by
# <unsigned-dir> (for example `dist/`) and obtain the corresponding signed executables in
# <signed-dir> (for example `signpath-signed/`). Then execute the script from the repository
# root like so:
#
#   tools/build-wine/verify_signed_executables.sh dist signpath-signed portable setup
#
# The script requires `osslsigncode` to be available in PATH and will exit with a non-zero
# status code if any of the expected files is missing or if the hash comparison fails.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <unsigned-dir> <signed-dir> <variant> [<variant> ...]" >&2
  exit 1
fi

if ! command -v osslsigncode >/dev/null 2>&1; then
  echo "osslsigncode is required but was not found in PATH" >&2
  exit 1
fi

unsigned_dir=$1
signed_dir=$2
shift 2

for variant in "$@"; do
  unsigned_file=$(find "$unsigned_dir" -type f -iname "*${variant}.exe" -print -quit)
  signed_file=$(find "$signed_dir" -type f -iname "*${variant}.exe" -print -quit)

  if [[ -z "$unsigned_file" ]]; then
    echo "Unsigned ${variant} executable not found in ${unsigned_dir}/" >&2
    exit 1
  fi

  if [[ -z "$signed_file" ]]; then
    echo "Signed ${variant} executable not found in ${signed_dir}/" >&2
    exit 1
  fi

  stripped_file="${signed_file%.[eE][xX][eE]}-stripped.exe"
  osslsigncode remove-signature -in "$signed_file" -out "$stripped_file"

  unsigned_hash=$(sha256sum "$unsigned_file" | cut -d ' ' -f1)
  stripped_hash=$(sha256sum "$stripped_file" | cut -d ' ' -f1)

  if [[ "$unsigned_hash" != "$stripped_hash" ]]; then
    echo "SHA256 mismatch for ${variant} executable" >&2
    rm -f "$stripped_file"
    exit 1
  fi

  rm -f "$stripped_file"
done
