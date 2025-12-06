#!/bin/bash

set -e

PROJECT_ROOT="$(dirname "$(readlink -e "$0")")/../../.."
CONTRIB="$PROJECT_ROOT/tools"
CONTRIB_APPIMAGE="$CONTRIB/build-linux/appimage"
DISTDIR="$CONTRIB_APPIMAGE/dist"
BUILDDIR="$CONTRIB_APPIMAGE/build/appimage"
APPDIR="$BUILDDIR/bitcoin_safe.AppDir"
BUILD_CACHEDIR="$CONTRIB_APPIMAGE/.cache/appimage"
export DLL_TARGET_DIR="$BUILD_CACHEDIR/dlls"
PIP_CACHE_DIR="$CONTRIB_APPIMAGE/.cache/pip_cache"
POETRY_WHEEL_DIR="$CONTRIB_APPIMAGE/.cache/poetry_wheel"
POETRY_CACHE_DIR="$CONTRIB_APPIMAGE/.cache/poetry_cache"

. "$CONTRIB"/build_tools_util.sh

git -C "$PROJECT_ROOT" rev-parse 2>/dev/null || fail "Building outside a git clone is not supported. PROJECT_ROOT contents:\n$(ls -la "$PROJECT_ROOT")"

export GCC_STRIP_BINARIES="1"

# pinned versions
PYTHON_VERSION=3.12.3
PY_VER_MAJOR="3.12"  # as it appears in fs paths
PKG2APPIMAGE_COMMIT="a9c85b7e61a3a883f4a35c41c5decb5af88b6b5d"

VERSION=$(git describe --tags --dirty --always --abbrev=20)
list_dirty_files
APPIMAGE="$DISTDIR/bitcoin_safe-$VERSION-x86_64.AppImage"

rm -rf "$BUILDDIR"
mkdir -p "$APPDIR" "$BUILD_CACHEDIR" "$PIP_CACHE_DIR" "$DISTDIR" "$DLL_TARGET_DIR"

# potential leftover from setuptools that might make pip put garbage in binary
rm -rf "$PROJECT_ROOT/build"


info "downloading some dependencies."
download_if_not_exist "$BUILD_CACHEDIR/functions.sh" "https://raw.githubusercontent.com/AppImage/pkg2appimage/$PKG2APPIMAGE_COMMIT/functions.sh"
verify_hash "$BUILD_CACHEDIR/functions.sh" "8f67711a28635b07ce539a9b083b8c12d5488c00003d6d726c7b134e553220ed"

download_if_not_exist "$BUILD_CACHEDIR/appimagetool" "https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage"
verify_hash "$BUILD_CACHEDIR/appimagetool" "46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"

download_if_not_exist "$BUILD_CACHEDIR/Python-$PYTHON_VERSION.tar.xz" "https://www.python.org/ftp/python/$PYTHON_VERSION/Python-$PYTHON_VERSION.tar.xz"
verify_hash "$BUILD_CACHEDIR/Python-$PYTHON_VERSION.tar.xz" "56bfef1fdfc1221ce6720e43a661e3eb41785dd914ce99698d8c7896af4bdaa1"



info "building python."
tar xf "$BUILD_CACHEDIR/Python-$PYTHON_VERSION.tar.xz" -C "$BUILD_CACHEDIR"
(
    if [ -f "$BUILD_CACHEDIR/Python-$PYTHON_VERSION/python" ]; then
        info "python already built, skipping"
        exit 0
    fi
    cd "$BUILD_CACHEDIR/Python-$PYTHON_VERSION"
    LC_ALL=C export BUILD_DATE=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%b %d %Y")
    LC_ALL=C export BUILD_TIME=$(date -u -d "@$SOURCE_DATE_EPOCH" "+%H:%M:%S")
    # Patch taken from Ubuntu http://archive.ubuntu.com/ubuntu/pool/main/p/python3.12/python3.12_3.12.3-1.debian.tar.xz
    patch -p1 < "$CONTRIB_APPIMAGE/patches/python-3.12-reproducible-buildinfo.diff"
    ./configure \
        --cache-file="$BUILD_CACHEDIR/python.config.cache" \
        --prefix="$APPDIR/usr" \
        --enable-ipv6 \
        --enable-shared \
        -q
    make "-j$CPU_COUNT" -s || fail "Could not build Python"
)
info "installing python."
(
    cd "$BUILD_CACHEDIR/Python-$PYTHON_VERSION"
    make -s install > /dev/null || fail "Could not install Python"
    # When building in docker on macOS, python builds with .exe extension because the
    # case insensitive file system of macOS leaks into docker. This causes the build
    # to result in a different output on macOS compared to Linux. We simply patch
    # sysconfigdata to remove the extension.
    # Some more info: https://bugs.python.org/issue27631
    sed -i -e 's/\.exe//g' "${APPDIR}/usr/lib/python${PY_VER_MAJOR}"/_sysconfigdata*
)
PYDIR="$APPDIR/usr/lib/python${PY_VER_MAJOR}"



appdir_python() {
    env \
        PYTHONNOUSERSITE=1 \
        LD_LIBRARY_PATH="$APPDIR/usr/lib:$APPDIR/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}" \
        "$APPDIR/usr/bin/python${PY_VER_MAJOR}" "$@"
}

info "installing pip."
appdir_python -m ensurepip

break_legacy_easy_install


info "Installing build dependencies"
function do_pip() {
    info "Installing pip $@"
    appdir_python -m pip install --no-build-isolation --no-dependencies --no-warn-script-location \
        --cache-dir "$PIP_CACHE_DIR" "$@" \
        || fail "Could not install the specified packages due to a failure in: $@"
}
do_pip -Ir $PROJECT_ROOT/tools/deterministic-build/requirements-build.txt


info "Installing build dependencies using poetry"

ln -s "$APPDIR/usr/bin/python${PY_VER_MAJOR}" "$APPDIR/usr/bin/python"
export PATH="$APPDIR/usr/bin:$PATH"
# for poetry to install into the system python environment 
# we have to also remove the .venv folder. Otherwise it will use it
export POETRY_VIRTUALENVS_CREATE=false
export POETRY_CACHE_DIR
mkdir -p "$PROJECT_ROOT/.venv"
mv "$PROJECT_ROOT/.venv" "$PROJECT_ROOT/.original.venv" # moving this out of the may so poetry doesnt detect it
appdir_python -m poetry install --only main --no-interaction

info "now install the root package"
rm -rf "$POETRY_WHEEL_DIR" # delete whl
appdir_python -m poetry build -f wheel --output="$POETRY_WHEEL_DIR"
do_pip "$POETRY_WHEEL_DIR"/*.whl


# # was only needed during build time, not runtime
appdir_python -m pip uninstall -y poetry pip 


mv "$PROJECT_ROOT/.original.venv" "$PROJECT_ROOT/.venv" # moving the .venv back


info "copying zbar"
mkdir -p "$APPDIR/usr/lib/"
cp /usr/lib/x86_64-linux-gnu/libzbar* "$APPDIR/usr/lib/"
cp /usr/lib/x86_64-linux-gnu/libzbar.so.0 "$APPDIR/usr/lib/libzbar.so"  # otherwise it is not detected


info "desktop integration."
cp "$CONTRIB/resources/linux-bitcoin-safe.desktop" "$APPDIR/bitcoin-safe.desktop"
cp "$CONTRIB/resources/icon.svg" "$APPDIR/bitcoin-safe.svg"


# add launcher
cp "$CONTRIB_APPIMAGE/apprun.sh" "$APPDIR/AppRun"




info "finalizing AppDir."
(
    export PKG2AICOMMIT="$PKG2APPIMAGE_COMMIT"
    . "$BUILD_CACHEDIR/functions.sh"

    cd "$APPDIR"
    # copy system dependencies
    copy_deps; copy_deps; copy_deps
    move_lib


    delete_blacklisted
) || fail "Could not finalize AppDir"

info "Copying additional libraries"
(
    # On some systems it can cause problems to use the system libusb (on AppImage excludelist)
    cp -f /usr/lib/x86_64-linux-gnu/libusb-* "$APPDIR/usr/lib/" || fail "Could not copy libusb"
    # some distros lack libxkbcommon-x11
    cp -f /usr/lib/x86_64-linux-gnu/libxkbcommon-x11* "$APPDIR"/usr/lib/x86_64-linux-gnu || fail "Could not copy libxkbcommon-x11"
    # some distros lack some libxcb libraries (see https://github.com/Electron-Cash/Electron-Cash/issues/2196)
    cp -f /usr/lib/x86_64-linux-gnu/libxcb-* "$APPDIR"/usr/lib/x86_64-linux-gnu || fail "Could not copy libxcb"
)

 

# --- the stripping below breaks numpy 
# info "stripping binaries from debug symbols."
# # "-R .note.gnu.build-id" also strips the build id
# # "-R .comment" also strips the GCC version information
# strip_binaries()
# {
#     chmod u+w -R "$APPDIR"
#     {
#         printf '%s\0' "$APPDIR/usr/bin/python${PY_VER_MAJOR}"
#         find "$APPDIR" -type f -regex '.*\.so\(\.[0-9.]+\)?$' -print0
#     } | xargs -0 --no-run-if-empty --verbose strip -R .note.gnu.build-id -R .comment
# }
# strip_binaries

remove_emptydirs()
{
    find "$APPDIR" -type d -empty -print0 | xargs -0 --no-run-if-empty rmdir -vp --ignore-fail-on-non-empty
}
remove_emptydirs


# info "removing some unneeded stuff to decrease binary size."
rm -rf "$APPDIR"/usr/{share,include}
rm -rf "$PYDIR"/{test,ensurepip,lib2to3,idlelib,turtledemo}
rm -rf "$PYDIR"/{ctypes,sqlite3,tkinter,unittest}/test
rm -rf "$PYDIR"/distutils/{command,tests}
rm -rf "$PYDIR"/config-3.*-x86_64-linux-gnu
rm -rf "$PYDIR"/site-packages/{opt,pip,setuptools,wheel}
rm -rf "$PYDIR"/site-packages/Cryptodome/SelfTest
rm -rf "$PYDIR"/site-packages/{psutil,qrcode,websocket}/tests
# rm lots of unused parts of Qt/PyQt. (assuming PyQt 6 layout)
# for component in connectivity declarative help location multimedia quickcontrols2 serialport webengine websockets xmlpatterns ; do
#     rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/translations/qt${component}_*
#     rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/resources/qt${component}_*
# done
rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/{qml,libexec}
rm -rf "$PYDIR"/site-packages/PyQt6/{pyrcc*.so,pylupdate*.so,uic}
rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/plugins/{bearer,gamepads,geometryloaders,geoservices,playlistformats,position,renderplugins,sceneparsers,sensors,sqldrivers,texttospeech,webview}
# for component in Bluetooth Concurrent Designer Help Location NetworkAuth Nfc Positioning PositioningQuick Qml Quick Sensors SerialPort Sql Test Web Xml Labs ShaderTools SpatialAudio ; do
#     rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/lib/libQt6${component}*
#     rm -rf "$PYDIR"/site-packages/PyQt6/Qt${component}*
#     rm -rf "$PYDIR"/site-packages/PyQt6/bindings/Qt${component}*
# done
for component in Qml Quick ; do
    rm -rf "$PYDIR"/site-packages/PyQt6/Qt6/lib/libQt6*${component}.so*
done
# rm -rf "$PYDIR"/site-packages/PyQt6/Qt.so


# Remove embedded VCS metadata which is not required at runtime and makes builds
# sensitive to git pack/index ordering.
find "$APPDIR" -name '.git' -type d -print0 | xargs -0 --no-run-if-empty rm -rf
find "$APPDIR" -type f \( -name '.gitmodules' -o -name '.gitignore' -o -name '.gitattributes' -o -name '.gitkeep' \) -delete

# these are deleted as they were not deterministic; and are not needed anyway
find "$APPDIR" -path '*/__pycache__*' -delete
# although note that *.dist-info might be needed by certain packages...
# e.g. importlib-metadata, see https://gitlab.com/python-devs/importlib_metadata/issues/71
rm -rf "$PYDIR"/site-packages/*.dist-info/
rm -rf "$PYDIR"/site-packages/*.egg-info/


export TZ=UTC
find -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +


info "creating the AppImage."
(
    cd "$BUILDDIR"
    cp "$BUILD_CACHEDIR/appimagetool" "$BUILD_CACHEDIR/appimagetool_copy"
    # zero out "appimage" magic bytes, as on some systems they confuse the linker
    sed -i 's|AI\x02|\x00\x00\x00|' "$BUILD_CACHEDIR/appimagetool_copy"
    chmod +x "$BUILD_CACHEDIR/appimagetool_copy"
    "$BUILD_CACHEDIR/appimagetool_copy" --appimage-extract
    # We build a small wrapper for mksquashfs that removes the -mkfs-time option
    # as it conflicts with SOURCE_DATE_EPOCH.
    mv "$BUILDDIR/squashfs-root/usr/bin/mksquashfs" "$BUILDDIR/squashfs-root/usr/bin/mksquashfs_orig"
    cat > "$BUILDDIR/squashfs-root/usr/bin/mksquashfs" << EOF
#!/bin/sh
args=\$(echo "\$@" | sed -e 's/-mkfs-time 0//')
"$BUILDDIR/squashfs-root/usr/bin/mksquashfs_orig" \$args
EOF
    chmod +x "$BUILDDIR/squashfs-root/usr/bin/mksquashfs"
    env VERSION="$VERSION" ARCH=x86_64 ./squashfs-root/AppRun --no-appstream --verbose "$APPDIR" "$APPIMAGE"
)


info "done."
ls -la "$DISTDIR"
sha256sum "$DISTDIR"/*
