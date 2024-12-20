#!/usr/bin/env bash

set -e

# Parameterize
PYTHON_VERSION=3.10.11
PY_VER_MAJOR="3.10"  # as it appears in fs paths
PACKAGE=Bitcoin_Safe
GIT_REPO=https://github.com/spesmilo/bitcoin_safe

export GCC_STRIP_BINARIES="1"
export PYTHONDONTWRITEBYTECODE=1  # don't create __pycache__/ folders with .pyc files


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


python_path="/Library/Frameworks/Python.framework/Versions/$PY_VER_MAJOR"
python3="$python_path/bin/python$PY_VER_MAJOR"

info "Removing old Python installation:  $python_path "
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

break_legacy_easy_install

# create a fresh virtualenv
# This helps to avoid older versions of pip-installed dependencies interfering with the build.
VENV_DIR="$CONTRIB_OSX/build-venv"
rm -rf "$VENV_DIR"
$python3 -m venv $VENV_DIR
source $VENV_DIR/bin/activate

# don't add debug info to compiled C files (e.g. when pip calls setuptools/wheel calls gcc)
# see https://github.com/pypa/pip/issues/6505#issuecomment-526613584
# note: this does not seem sufficient when cython is involved (although it is on linux, just not on mac... weird.)
#       see additional "strip" pass on built files later in the file.
export CFLAGS="-g0"

# Do not build universal binaries. The default on macos 11+ and xcode 12+ is "-arch arm64 -arch x86_64"
# but with that e.g. "hid.cpython-310-darwin.so" is not reproducible as built by clang.
export ARCHFLAGS="-arch x86_64"

info "Installing build dependencies"
# note: re pip installing from PyPI,
#       we prefer compiling C extensions ourselves, instead of using binary wheels,
#       hence "--no-binary :all:" flags. However, we specifically allow
#       - PyQt6, as it's harder to build from source
#       - cryptography, as it's harder to build from source
#       - the whole of "requirements-build-base.txt", which includes pip and friends, as it also includes "wheel",
#         and I am not quite sure how to break the circular dependence there (I guess we could introduce
#         "requirements-build-base-base.txt" with just wheel in it...)
$python3 -m pip install --no-build-isolation --no-dependencies --no-warn-script-location \
    -Ir ./tools/deterministic-build/requirements-build-base.txt \
    || fail "Could not install build dependencies (base)"
$python3 -m pip install --no-build-isolation --no-dependencies --no-binary :all: --no-warn-script-location \
    -Ir ./tools/deterministic-build/requirements-build-mac.txt \
    || fail "Could not install build dependencies (mac)"

info "Installing some build-time deps for compilation..."
brew install autoconf automake libtool gettext coreutils pkgconfig

info "Building PyInstaller."
PYINSTALLER_REPO="https://github.com/pyinstaller/pyinstaller.git"
PYINSTALLER_COMMIT="5d7a0449ecea400eccbbb30d5fcef27d72f8f75d"
# ^ tag "v6.6.0"
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
    # Shallow clone
    git init
    git remote add origin $PYINSTALLER_REPO
    git fetch --depth 1 origin $PYINSTALLER_COMMIT
    git checkout -b pinned "${PYINSTALLER_COMMIT}^{commit}"
    rm -fv PyInstaller/bootloader/Darwin-*/run* || true
    # add reproducible randomness. this ensures we build a different bootloader for each commit.
    # if we built the same one for all releases, that might also get anti-virus false positives
    echo "const char *bitcoin_safe_tag = \"tagged by Bitcoin_Safe@$BITCOIN_SAFE_COMMIT_HASH\";" >> ./bootloader/src/pyi_main.c
    pushd bootloader
    # compile bootloader
    $python3 ./waf all CFLAGS="-static"
    popd
    # sanity check bootloader is there:
    [[ -e "PyInstaller/bootloader/Darwin-64bit/runw" ]] || fail "Could not find runw in target dir!"
) || fail "PyInstaller build failed"
info "Installing PyInstaller."
$python3 -m pip install --no-build-isolation --no-dependencies --no-warn-script-location "$CACHEDIR/pyinstaller"

info "Using these versions for building $PACKAGE:"
sw_vers
$python3 --version
echo -n "Pyinstaller "
pyinstaller="/Library/Frameworks/Python.framework/Versions/$PY_VER_MAJOR/bin/pyinstaller"
$pyinstaller --version

rm -rf ./dist

git submodule update --init


if [ ! -f "$DLL_TARGET_DIR/libsecp256k1.2.dylib" ]; then
    info "Building libsecp256k1 dylib..."
    "$CONTRIB"/make_libsecp256k1.sh || fail "Could not build libsecp"
else
    info "Skipping libsecp256k1 build: reusing already built dylib."
fi
#cp -f "$DLL_TARGET_DIR"/libsecp256k1.*.dylib "$PROJECT_ROOT/bitcoin_safe" || fail "Could not copy libsecp256k1 dylib"

if [ ! -f "$DLL_TARGET_DIR/libzbar.0.dylib" ]; then
    info "Building ZBar dylib..."
    "$CONTRIB"/make_zbar.sh || fail "Could not build ZBar dylib"
else
    info "Skipping ZBar build: reusing already built dylib."
fi
cp -f "$DLL_TARGET_DIR/libzbar.0.dylib" "$PROJECT_ROOT/bitcoin_safe/" || fail "Could not copy ZBar dylib"

if [ ! -f "$DLL_TARGET_DIR/libusb-1.0.dylib" ]; then
    info "Building libusb dylib..."
    "$CONTRIB"/make_libusb.sh || fail "Could not build libusb dylib"
else
    info "Skipping libusb build: reusing already built dylib."
fi
cp -f "$DLL_TARGET_DIR/libusb-1.0.dylib" "$PROJECT_ROOT/bitcoin_safe/" || fail "Could not copy libusb dylib"




info "Installing poetry"
$python3 -m pip install --no-build-isolation --no-warn-script-location \
    --cache-dir "$PIP_CACHE_DIR" poetry==1.8.5


info "Installing build dependencies using poetry"

export PATH="$APPDIR/usr/bin:$PATH"
export POETRY_CACHE_DIR
$python3 -m poetry install --no-interaction
$python3 -m poetry export --output requirements.txt  
$python3 -m pip install -r requirements.txt

info "now install the root package"
$python3 -m poetry build -f wheel --output="$POETRY_WHEEL_DIR"
$python3 -m pip install --no-dependencies --no-warn-script-location \
    --cache-dir "$PIP_CACHE_DIR" "$POETRY_WHEEL_DIR"/*.whl



# # was only needed during build time, not runtime
$python3 -m pip uninstall -y pip 


info "Faking timestamps..."
find . -exec touch -t '200101220000' {} + || true

VERSION=$(git describe --tags --dirty --always)

info "Building binary"
BITCOIN_SAFE_VERSION=$VERSION $pyinstaller    --noconfirm --clean tools/build-mac/osx.spec || fail "Could not build binary"

info "Finished building unsigned dist/${PACKAGE}.app. This hash should be reproducible:"
find "dist/${PACKAGE}.app" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256

info "Creating unsigned .DMG"
hdiutil create -fs HFS+ -volname $PACKAGE -srcfolder dist/$PACKAGE.app dist/bitcoin_safe-$VERSION-unsigned.dmg || fail "Could not create .DMG"

info "App was built successfully but was not code signed. Users may get security warnings from macOS."
info "Now you also need to run sign_osx.sh to codesign/notarize the binary."
