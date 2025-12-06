#!/bin/bash

PYINSTALLER_REPO="https://github.com/pyinstaller/pyinstaller.git"
PYINSTALLER_COMMIT="3f596f66feebe3a7d247248f95f76c071d08b832" # ~ v6.17.0

PYTHON_VERSION=3.12.3


# Let's begin!
set -e

here="$(dirname "$(readlink -e "$0")")"

. "$CONTRIB"/build_tools_util.sh



info "Booting wine."
wine 'wineboot'



cd "$BUILD_CACHEDIR"
mkdir -p $WINEPREFIX/drive_c/tmp

info "Installing Python."
# note: you might need "sudo apt-get install dirmngr" for the following
# keys from https://www.python.org/downloads/#pubkeys
KEYRING_PYTHON_DEV="keyring-bitcoin_safe-build-python-dev.gpg"
gpg --no-default-keyring --keyring $KEYRING_PYTHON_DEV --import "$here"/gpg_keys/7ED10B6531D7C8E1BC296021FC624643487034E5.asc
if [ "$WIN_ARCH" = "win32" ] ; then
    PYARCH="win32"
elif [ "$WIN_ARCH" = "win64" ] ; then
    PYARCH="amd64"
else
    fail "unexpected WIN_ARCH: $WIN_ARCH"
fi
PYTHON_DOWNLOADS="$BUILD_CACHEDIR/python$PYTHON_VERSION"
mkdir -p "$PYTHON_DOWNLOADS"
for msifile in core dev exe lib pip; do
    echo "Installing $msifile..."
    download_if_not_exist "$PYTHON_DOWNLOADS/${msifile}.msi" "https://www.python.org/ftp/python/$PYTHON_VERSION/$PYARCH/${msifile}.msi"
    download_if_not_exist "$PYTHON_DOWNLOADS/${msifile}.msi.asc" "https://www.python.org/ftp/python/$PYTHON_VERSION/$PYARCH/${msifile}.msi.asc"
    verify_signature "$PYTHON_DOWNLOADS/${msifile}.msi.asc" $KEYRING_PYTHON_DEV || fail "invalid sig for ${msifile}.msi"
    wine msiexec /i "$PYTHON_DOWNLOADS/${msifile}.msi" /qb TARGETDIR=$WINE_PYHOME || fail "wine msiexec failed for ${msifile}.msi"
done

break_legacy_easy_install

info "Installing build dependencies"
do_wine_pip -Ir "$PROJECT_ROOT/tools/deterministic-build/requirements-build.txt"


info "Installing build dependencies using poetry"
# Installing via poetry directly would be better, but it seems not possible to 
# overwrite the poetry.toml config to prevent local venv
export POETRY_CACHE_DIR="$WINE_POETRY_CACHE_DIR"
export POETRY_VIRTUALENVS_CREATE=false
$WINE_PYTHON -m poetry config virtualenvs.create false
move_and_overwrite $PROJECT_ROOT/.venv  $PROJECT_ROOT/.venv_org
$WINE_PYTHON -m poetry install --with main,build_wine --no-interaction \
  || $WINE_PYTHON -m poetry install --with main,build_wine --no-interaction \
  || { echo "poetry install failed twice"; exit 1; }
move_and_overwrite   $PROJECT_ROOT/.venv_org $PROJECT_ROOT/.venv



# copy already built DLLs
cp "$DLL_TARGET_DIR/libiconv.dll" $WINEPREFIX/drive_c/bitcoin_safe/bitcoin_safe/ || fail "Could not copy libiconv to its destination"
cp "$DLL_TARGET_DIR/libzbar-0.dll" $WINEPREFIX/drive_c/bitcoin_safe/bitcoin_safe/libzbar-64.dll || fail "Could not copy libzbar to its destination"
cp "$DLL_TARGET_DIR/libusb-1.0.dll" $WINEPREFIX/drive_c/bitcoin_safe/bitcoin_safe/ || fail "Could not copy libusb to its destination"


info "Building PyInstaller."
# we build our own PyInstaller boot loader as the default one has high
# anti-virus false positives
(
    if [ "$WIN_ARCH" = "win32" ] ; then
        PYINST_ARCH="32bit"
    elif [ "$WIN_ARCH" = "win64" ] ; then
        PYINST_ARCH="64bit"
    else
        fail "unexpected WIN_ARCH: $WIN_ARCH"
    fi
    if [ -f "$BUILD_CACHEDIR/pyinstaller/PyInstaller/bootloader/Windows-$PYINST_ARCH-intel/runw.exe" ]; then
        info "pyinstaller already built, skipping"
        exit 0
    fi
    cd "$WINEPREFIX/drive_c/bitcoin_safe"
    BITCOIN_SAFE_COMMIT_HASH=$(git rev-parse HEAD)
    cd "$BUILD_CACHEDIR"
    rm -rf pyinstaller
    mkdir pyinstaller
    cd pyinstaller
    # Shallow clone
    git init
    git remote add origin $PYINSTALLER_REPO
    git fetch --depth 1 origin $PYINSTALLER_COMMIT
    git checkout -b pinned "${PYINSTALLER_COMMIT}^{commit}"
    rm -fv PyInstaller/bootloader/Windows-*/run*.exe || true
    # add reproducible randomness. this ensures we build a different bootloader for each commit.
    # if we built the same one for all releases, that might also get anti-virus false positives
    echo "const char *bitcoin_safe_tag = \"tagged by Bitcoin_Safe@$BITCOIN_SAFE_COMMIT_HASH\";" >> ./bootloader/src/pyi_main.c
    pushd bootloader
    # cross-compile to Windows using host python
    python3 ./waf all CC="${GCC_TRIPLET_HOST}-gcc" \
                      CFLAGS="-static"
    popd
    # sanity check bootloader is there:
    [[ -e "PyInstaller/bootloader/Windows-$PYINST_ARCH-intel/runw.exe" ]] || fail "Could not find runw.exe in target dir!"
) || fail "PyInstaller build failed"
info "Installing PyInstaller."
do_wine_pip ./pyinstaller

info "Wine is configured."
