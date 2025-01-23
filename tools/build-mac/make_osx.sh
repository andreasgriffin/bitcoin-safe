#!/usr/bin/env bash

set -e

# ======================
# Parameters
# ======================
PYTHON_VERSION=3.10.11
PY_VER_MAJOR="3.10"  # as it appears in fs paths
PACKAGE=Bitcoin_Safe
GIT_REPO=https://github.com/andreasgriffin/bitcoin_safe

export GCC_STRIP_BINARIES="1"
export PYTHONDONTWRITEBYTECODE=1  # don't create __pycache__/ with .pyc

# Helper/utility functions
. "$(dirname "$0")/../build_tools_util.sh"

CONTRIB_OSX="$(dirname "$(realpath "$0")")"
CONTRIB="$CONTRIB_OSX/.."
PROJECT_ROOT="$CONTRIB/.."
CACHEDIR="$CONTRIB_OSX/.cache"
export DLL_TARGET_DIR="$CACHEDIR/dlls"
PIP_CACHE_DIR="$CACHEDIR/pip_cache"
POETRY_WHEEL_DIR="$CACHEDIR/poetry_wheel"
POETRY_CACHE_DIR="$CACHEDIR/poetry_cache"

mkdir -p "$CACHEDIR" "$DLL_TARGET_DIR"

cd "$PROJECT_ROOT"

git -C "$PROJECT_ROOT" rev-parse 2>/dev/null || fail "Building outside a git clone is not supported."

which brew > /dev/null 2>&1 || fail "Please install brew from https://brew.sh/ to continue"
which xcodebuild > /dev/null 2>&1 || fail "Please install xcode command line tools to continue"


# ======================
# Install System Python
# ======================
python_path="/Library/Frameworks/Python.framework/Versions/$PY_VER_MAJOR"
python3="$python_path/bin/python$PY_VER_MAJOR"

info "Removing old Python installation:  $python_path"
# repeating this script without removal of the python installation leads to python not bein able to find pip
sudo rm -rf "$python_path"

info "Installing Python $PYTHON_VERSION"
PKG_FILE="python-${PYTHON_VERSION}-macos11.pkg"
if [ ! -f "$CACHEDIR/$PKG_FILE" ]; then
    curl -o "$CACHEDIR/$PKG_FILE" "https://www.python.org/ftp/python/${PYTHON_VERSION}/$PKG_FILE"
fi
echo "767ed35ad688d28ea4494081ae96408a0318d0d5bb9ca0139d74d6247b231cfc  $CACHEDIR/$PKG_FILE" | shasum -a 256 -c \
    || fail "python pkg checksum mismatched"
sudo installer -pkg "$CACHEDIR/$PKG_FILE" -target / \
    || fail "failed to install python"

# sanity check "python3" has the version we just installed.
FOUND_PY_VERSION=$($python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
if [[ "$FOUND_PY_VERSION" != "$PYTHON_VERSION" ]]; then
    fail "python version mismatch: $FOUND_PY_VERSION != $PYTHON_VERSION"
fi

# Update certificates for python.org Pythons
/Applications/Python\ $PY_VER_MAJOR/Install\ Certificates.command

break_legacy_easy_install


# ======================
# Create and Use venv
# ======================
info "Creating fresh Python virtual environment"
VENV_DIR="$CONTRIB_OSX/venv-mac"
rm -rf "$VENV_DIR"
$python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Double-check we are using the correct Python in the venv:
which python
python --version


# ======================
# Install build-time dependencies
# ======================
info "Installing build dependencies"
function do_pip() {
    info "Installing pip $@"
    pip install --no-build-isolation --no-dependencies --no-warn-script-location \
        --cache-dir "$PIP_CACHE_DIR" "$@" \
        || fail "Could not install the specified packages due to a failure in: $@"
}

info "Installing required pip packages for building..."
do_pip -Ir ./tools/deterministic-build/requirements-build-base.txt  
do_pip -Ir ./tools/deterministic-build/requirements-poetry.txt 

info "Installing some Brew tools for compilation"
brew install autoconf automake libtool gettext coreutils pkgconfig


# ======================
# Install Dependencies via Poetry in the same venv
# ======================
info "Using Poetry to install local project dependencies"
# Optionally ensure Poetry does not create its own .venv:
poetry config virtualenvs.create false --local
# ...But we are already inside a venv, so Poetry *should* install into this environment:
poetry install --with main,build_mac

# or, if you prefer an in-project .venv:
# poetry config virtualenvs.in-project true
# poetry env use python
# poetry install --with main,build_mac


# ======================
# Build PyInstaller from a pinned commit
# ======================

# don't add debug info to compiled C files (e.g. when pip calls setuptools/wheel calls gcc)
# see https://github.com/pypa/pip/issues/6505#issuecomment-526613584
# note: this does not seem sufficient when cython is involved (although it is on linux, just not on mac... weird.)
#       see additional "strip" pass on built files later in the file.
export CFLAGS="-g0"

# Do not build universal binaries. The default on macos 11+ and xcode 12+ is "-arch arm64 -arch x86_64"
# but with that e.g. "hid.cpython-310-darwin.so" is not reproducible as built by clang.
arch=$(uname -m)
export ARCHFLAGS="-arch $arch"


info "Building PyInstaller"
PYINSTALLER_REPO="https://github.com/pyinstaller/pyinstaller.git"
PYINSTALLER_COMMIT="1318b8bc26d348147c4e99c0a7b60052a27eb1cc" # ~ v6.11.1

(
    if [ -f "$CACHEDIR/pyinstaller/PyInstaller/bootloader/Darwin-64bit/runw" ]; then
        info "pyinstaller already built, skipping"
        exit 0
    fi
    cd "$PROJECT_ROOT"
    BITCOIN_SAFE_COMMIT_HASH=$(git rev-parse HEAD)
    cd "$CACHEDIR"
    rm -rf pyinstaller
    mkdir pyinstaller
    cd pyinstaller
    git init
    git remote add origin $PYINSTALLER_REPO
    git fetch --depth 1 origin $PYINSTALLER_COMMIT
    git checkout -b pinned "${PYINSTALLER_COMMIT}^{commit}"
    # add reproducible randomness. this ensures we build a different bootloader for each commit.
    # if we built the same one for all releases, that might also get anti-virus false positives
    echo "const char *bitcoin_safe_tag = \"tagged by Bitcoin_Safe@$BITCOIN_SAFE_COMMIT_HASH\";" >> ./bootloader/src/pyi_main.c
    pushd bootloader
    # compile bootloader
    python ./waf all CFLAGS="-static"
    popd
    [[ -e "PyInstaller/bootloader/Darwin-64bit/runw" ]] || fail "Could not find runw in target dir!"
)

info "Installing local build of PyInstaller"
pip install "$CACHEDIR/pyinstaller"


info "Using these versions for building $PACKAGE:"
sw_vers
python --version
echo -n "PyInstaller "
pyinstaller --version


# ======================
# Build .dylibs (libsecp256k1, zbar, libusb)
# ======================
git submodule update --init

if [ ! -f "$DLL_TARGET_DIR/libsecp256k1.2.dylib" ]; then
    info "Building libsecp256k1 dylib..."
    "$CONTRIB"/make_libsecp256k1.sh || fail "Could not build libsecp"
else
    info "Skipping libsecp256k1 build: reusing already built dylib."
fi
cp -f "$DLL_TARGET_DIR"/libsecp256k1.*.dylib "$PROJECT_ROOT/bitcoin_safe" || fail "copying libsecp256k1 failed"

if [ ! -f "$DLL_TARGET_DIR/libzbar.0.dylib" ]; then
    info "Building ZBar dylib..."
    "$CONTRIB"/make_zbar.sh || fail "Could not build ZBar dylib"
else
    info "Skipping ZBar build: reusing already built dylib."
fi
cp -f "$DLL_TARGET_DIR/libzbar.0.dylib" "$PROJECT_ROOT/bitcoin_safe/" || fail "copying zbar failed"

if [ ! -f "$DLL_TARGET_DIR/libusb-1.0.dylib" ]; then
    info "Building libusb dylib..."
    "$CONTRIB"/make_libusb.sh || fail "Could not build libusb dylib"
else
    info "Skipping libusb build: reusing already built dylib."
fi
cp -f "$DLL_TARGET_DIR/libusb-1.0.dylib" "$PROJECT_ROOT/bitcoin_safe/" || fail "copying libusb failed"


# ======================
# Install the root package (Wheel)
# ======================
sudo rm -Rf "$POETRY_WHEEL_DIR" || true
poetry build -f wheel --output="$POETRY_WHEEL_DIR"
pip install "$POETRY_WHEEL_DIR"/*.whl


# ======================
# Build the final binary
# ======================
rm ./dist/*   || true
info "Faking timestamps..."
find . -exec sudo touch -t '200101220000' {} + || true

VERSION=$(git describe --tags --dirty --always)

info "Running PyInstaller to create macOS .app"
BITCOIN_SAFE_VERSION=$VERSION \
  pyinstaller --noconfirm --clean tools/build-mac/osx.spec || fail "PyInstaller failed."

info "Finished building unsigned dist/${PACKAGE}.app. This hash should be reproducible:"
find "dist/${PACKAGE}.app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256

info "Creating unsigned .DMG"
hdiutil create \
        -fs HFS+ \
        -volname "$PACKAGE" \
        -srcfolder "dist/$PACKAGE.app" \
        "dist/bitcoin_safe-$VERSION-unsigned.dmg" \
  || fail "Could not create .DMG"

info "Done. The .app and .dmg are *unsigned* and will trigger macOS Gatekeeper warnings."
info "To ship, you’ll need to sign and notarize. See: sign_osx.sh"
