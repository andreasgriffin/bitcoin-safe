#!/usr/bin/env bash

set -eo pipefail

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/tools"
CONTRIB_FLATPAK="$PROJECT_ROOT/tools/build-linux/flatpak"
DISTDIR="$CONTRIB_FLATPAK/dist"

# The container may run as root while the bind-mounted checkout is owned by the
# host user. Mark it as safe before any sourced helpers invoke git.
git config --global --add safe.directory '*'
git config --global --add safe.directory "$PROJECT_ROOT"

. "$CONTRIB"/build_tools_util.sh

git_probe_output="$(git -C "$PROJECT_ROOT" rev-parse 2>&1)" || fail "Git could not access the mounted checkout at ${PROJECT_ROOT}: ${git_probe_output}\nPROJECT_ROOT contents:\n$(ls -la "$PROJECT_ROOT")"

VERSION=$(git -C "$PROJECT_ROOT" describe --tags --dirty --always --abbrev=20)
SOURCE_DATE_EPOCH=$(git -C "$PROJECT_ROOT" show -s --format=%ct HEAD)
list_dirty_files

mkdir -p "${DISTDIR}"
export BITCOINSAFE_FLATPAK_SKIP_INSTALL_AND_TEST=1
export BITCOINSAFE_FLATPAK_VERSION="${VERSION}"
export BITCOINSAFE_SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH}"

bash "${CONTRIB_FLATPAK}/build_and_test.sh" "${PROJECT_ROOT}" "${DISTDIR}" "org.bitcoin_safe.BitcoinSafe"

if [ "$(id -u)" = "0" ] && [ -n "${BITCOINSAFE_BUILD_UID:-}" ] && [ -n "${BITCOINSAFE_BUILD_GID:-}" ]; then
    chown -R "${BITCOINSAFE_BUILD_UID}:${BITCOINSAFE_BUILD_GID}" "${CONTRIB_FLATPAK}"
fi
