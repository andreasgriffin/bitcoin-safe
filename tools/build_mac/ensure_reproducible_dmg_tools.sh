#!/usr/bin/env bash

CONTRIB_OSX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DMG_TOOLS_CACHE_DIR="${CONTRIB_OSX}/.cache/reproducible-dmg-tools"
DMG_TOOLS_BIN_DIR="${DMG_TOOLS_CACHE_DIR}/bin"
CDRKIT_VERSION="1.1.11"
CDRKIT_DOWNLOAD_URL="http://distro.ibiblio.org/fatdog/source/600/c/cdrkit-${CDRKIT_VERSION}.tar.bz2"
CDRKIT_ARCHIVE_SHA256="b50d64c214a65b1a79afe3a964c691931a4233e2ba605d793eb85d0ac3652564"
CDRKIT_PATCH_PATH="${CONTRIB_OSX}/cdrkit-deterministic.patch"
GENISOIMAGE_PATH="${DMG_TOOLS_BIN_DIR}/genisoimage-${CDRKIT_VERSION}"
LIBDMG_REPO_URL="https://github.com/theuni/libdmg-hfsplus"
DMG_COMPRESSOR_PATH="${DMG_TOOLS_BIN_DIR}/dmg"

ensure_reproducible_dmg_tools() {
    mkdir -p "${DMG_TOOLS_CACHE_DIR}" "${DMG_TOOLS_BIN_DIR}"

    if [ ! -x "${GENISOIMAGE_PATH}" ]; then
        build_deterministic_genisoimage
    fi

    if [ ! -x "${DMG_COMPRESSOR_PATH}" ]; then
        build_libdmg_compressor
    fi

    export PATH="${DMG_TOOLS_BIN_DIR}:$PATH"
    export BITCOIN_SAFE_GENISOIMAGE="${GENISOIMAGE_PATH}"
    export BITCOIN_SAFE_DMG_COMPRESSOR="${DMG_COMPRESSOR_PATH}"
}

build_deterministic_genisoimage() {
    local archive_path="${DMG_TOOLS_CACHE_DIR}/cdrkit-${CDRKIT_VERSION}.tar.bz2"
    local build_root="${DMG_TOOLS_CACHE_DIR}/cdrkit-build"
    local source_dir="${build_root}/cdrkit-${CDRKIT_VERSION}"

    rm -rf "${build_root}"
    mkdir -p "${build_root}"

    if [ ! -f "${archive_path}" ]; then
        curl -L "${CDRKIT_DOWNLOAD_URL}" -o "${archive_path}"
    fi

    echo "${CDRKIT_ARCHIVE_SHA256}  ${archive_path}" | shasum -a 256 -c

    tar -xjf "${archive_path}" -C "${build_root}"
    (
        cd "${source_dir}"
        patch -p1 < "${CDRKIT_PATCH_PATH}"
        cmake . -Wno-dev
        make genisoimage
        cp genisoimage/genisoimage "${GENISOIMAGE_PATH}"
    )
}

build_libdmg_compressor() {
    local build_root="${DMG_TOOLS_CACHE_DIR}/libdmg-build"
    local source_dir="${build_root}/libdmg-hfsplus"

    rm -rf "${build_root}"
    mkdir -p "${build_root}"

    git clone "${LIBDMG_REPO_URL}" "${source_dir}"
    (
        cd "${source_dir}"
        cmake .
        make
        cp dmg/dmg "${DMG_COMPRESSOR_PATH}"
    )
}
