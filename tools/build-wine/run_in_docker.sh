#!/bin/bash

set -e

here="$(dirname "$(readlink -e "$0")")"
test -n "$here" -a -d "$here" || exit
# here = /opt/wine64/drive_c/bitcoin_safe/tools/build-wine 


if [ -z "$WIN_ARCH" ] ; then
    export WIN_ARCH="win64"  # default
fi
if [ "$WIN_ARCH" = "win32" ] ; then
    export GCC_TRIPLET_HOST="i686-w64-mingw32"
elif [ "$WIN_ARCH" = "win64" ] ; then
    export GCC_TRIPLET_HOST="x86_64-w64-mingw32"
else
    echo "unexpected WIN_ARCH: $WIN_ARCH"
    exit 1
fi


export CONTRIB="$here/.."
export PROJECT_ROOT="$CONTRIB/.."
 
export BUILD_TYPE="wine"
export GCC_TRIPLET_BUILD="x86_64-pc-linux-gnu"
export GCC_STRIP_BINARIES="1"


export BUILD_CACHEDIR="$here/.cache/$WIN_ARCH"
export PIP_CACHE_DIR="$here/.cache/$WIN_ARCH/pip"
export DLL_TARGET_DIR="$BUILD_CACHEDIR/dlls"

export WINEPREFIX="/opt/wine64"
export WINEDEBUG=-all
export WINE_PYHOME="c:/python3"
export WINE_PYTHON="wine $WINE_PYHOME/python.exe -B"

. "$CONTRIB"/build_tools_util.sh

export L_POETRY_CACHE_DIR="$BUILD_CACHEDIR/poetry" # needs the L_, because later I need to do  export POETRY_CACHE_DIR=WINE_POETRY_CACHE_DIR
export WINE_POETRY_CACHE_DIR=$(win_path "$L_POETRY_CACHE_DIR") 


git -C "$PROJECT_ROOT" rev-parse 2>/dev/null || fail "Building outside a git clone is not supported. PROJECT_ROOT contents:\n$(ls -la "$PROJECT_ROOT")"

info "Clearing $here/build and $here/dist..."
rm "$here"/build/* -rf
rm "$here"/dist/* -rf

mkdir -p "$BUILD_CACHEDIR" "$DLL_TARGET_DIR" "$PIP_CACHE_DIR"




#################
####  build libs
#################
if [ -f "$DLL_TARGET_DIR/libiconv.dll" ]; then
    info "libzbar already built, skipping"
else
    (
        # As debian bullseye doesn't provide win-iconv-mingw-w64-dev, we need to build it:
        WIN_ICONV_COMMIT="9f98392dfecadffd62572e73e9aba878e03496c4"
        # ^ tag "v0.0.8"
        info "Building win-iconv..."
        cd "$BUILD_CACHEDIR"
        if [ ! -d win-iconv ]; then
            git clone https://github.com/win-iconv/win-iconv.git
        fi
        cd win-iconv
        if ! $(git cat-file -e ${WIN_ICONV_COMMIT}) ; then
            info "Could not find requested version $WIN_ICONV_COMMIT in local clone; fetching..."
            git fetch --all
        fi
        git reset --hard
        git clean -dfxq
        git checkout "${WIN_ICONV_COMMIT}^{commit}"

        # note: "-j1" as parallel jobs lead to non-reproducibility seemingly due to ordering issues
        #       see https://github.com/win-iconv/win-iconv/issues/42
        CC="${GCC_TRIPLET_HOST}-gcc" make -j1 || fail "Could not build win-iconv"
        # FIXME avoid using sudo
        sudo make install prefix="/usr/${GCC_TRIPLET_HOST}"  || fail "Could not install win-iconv"
    )
    cp /usr/x86_64-w64-mingw32/bin/iconv.dll "$DLL_TARGET_DIR/libiconv.dll"
fi 

if [ -f "$DLL_TARGET_DIR/libzbar-0.dll" ]; then
    info "libzbar already built, skipping"
else
    "$CONTRIB"/make_zbar.sh || fail "Could not build zbar"
fi


if [ -f "$DLL_TARGET_DIR/libusb-1.0.dll" ]; then
    info "libusb already built, skipping"
else
    "$CONTRIB"/make_libusb.sh || fail "Could not build libusb"
fi

"$here/prepare-wine.sh" || fail "prepare-wine failed"

info "Resetting modification time in C:\Python..."
# (Because of some bugs in pyinstaller)
pushd /opt/wine64/drive_c/python*
export TZ=UTC
find -exec touch -h -d '2000-11-11T11:11:11+00:00' {} +
popd
ls -l /opt/wine64/drive_c/python*

"$here/build_exe.sh" || fail "build_exe failed"

info "Done."
