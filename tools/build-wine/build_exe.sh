#!/bin/bash

NAME_ROOT=bitcoin_safe
WINE_ROOT_PACKAGE="$WINEPREFIX/drive_c/python3/Lib/site-packages/$NAME_ROOT/"
export PYTHONDONTWRITEBYTECODE=1  # don't create __pycache__/ folders with .pyc files


# Let's begin!
set -e

. "$CONTRIB"/build_tools_util.sh

pushd "$WINEPREFIX/drive_c/$NAME_ROOT"

VERSION=$(git describe --tags --dirty --always --abbrev=20)
list_dirty_files
info "Last commit: $VERSION"

export TZ=UTC
find -exec touch -h -d '2000-11-11T11:11:11+00:00' {} +
popd


# opt out of compiling C extensions
export AIOHTTP_NO_EXTENSIONS=1
export YARL_NO_EXTENSIONS=1
export MULTIDICT_NO_EXTENSIONS=1
export FROZENLIST_NO_EXTENSIONS=1
export ELECTRUM_ECC_DONT_COMPILE=1

POETRY_WHEEL_DIR="$BUILD_CACHEDIR/poetry_wheel"
WINE_POETRY_WHEEL_DIR=$(win_path "$POETRY_WHEEL_DIR")

APPDIR="$WINEPREFIX/drive_c/$NAME_ROOT"
WINE_APPDIR=$(win_path "$APPDIR")
PIP_CACHE_DIR="$BUILD_CACHEDIR/pip"
WINE_PIP_CACHE_DIR=$(win_path "$PIP_CACHE_DIR") 


mkdir -p "$POETRY_WHEEL_DIR" "$APPDIR"   "$PIP_CACHE_DIR"   "$L_POETRY_CACHE_DIR"

info "Installing requirements..."


info "Installing dependencies using poetry" 
# ln -s $WINE_PYHOME/python.exe "/usr/bin/python.exe"
# export PATH="$APPDIR/usr/bin:$PATH"
# for poetry to install into the system python environment 
# we have to also remove the .venv folder. Otherwise it will use it
export POETRY_CACHE_DIR="$WINE_POETRY_CACHE_DIR"
export POETRY_VIRTUALENVS_CREATE=false
$WINE_PYTHON -m poetry config virtualenvs.create false

move_and_overwrite $PROJECT_ROOT/.venv  $PROJECT_ROOT/.venv_org
# should have been installed already in prepare-wine
$WINE_PYTHON -m poetry install --only main --no-interaction  


info "now install the root package"
rm -Rf "$POETRY_WHEEL_DIR" || true 
$WINE_PYTHON -m poetry build -f wheel --output="$WINE_POETRY_WHEEL_DIR"
info "ls of output directory: {$POETRY_WHEEL_DIR}  $(ls $POETRY_WHEEL_DIR)"
for fullpath in "$POETRY_WHEEL_DIR"/*.whl; do
  # remove everything up to and including the last slash
  filename="${fullpath##*/}"
  do_wine_pip "$WINE_POETRY_WHEEL_DIR/$filename"
  break  # stop after the first one
done




# # was only needed during build time, not runtime
$WINE_PYTHON -m pip uninstall -y poetry pip 

move_and_overwrite $PROJECT_ROOT/.venv_org $PROJECT_ROOT/.venv


rm -rf dist/

# build standalone and portable versions
info "Running pyinstaller..."
bitcoin_safe_CMDLINE_NAME="$NAME_ROOT-$VERSION" wine "$WINE_PYHOME/scripts/pyinstaller.exe" --noconfirm --clean deterministic.spec

# set timestamps in dist, in order to make the installer reproducible
pushd dist
export TZ=UTC
find -exec touch -h -d '2000-11-11T11:11:11+00:00' {} +
popd

info "building NSIS installer"
# $VERSION could be passed to the bitcoin_safe.nsi script, but this would require some rewriting in the script itself.

makensis -DPRODUCT_VERSION=$VERSION bitcoin_safe.nsi

cd dist
mv bitcoin_safe-setup.exe $NAME_ROOT-$VERSION-setup.exe
cd ..

info "Padding binaries to 8-byte boundaries, and fixing COFF image checksum in PE header"
# note: 8-byte boundary padding is what osslsigncode uses:
#       https://github.com/mtrojnar/osslsigncode/blob/6c8ec4427a0f27c145973450def818e35d4436f6/osslsigncode.c#L3047
(
    cd dist
    for binary_file in ./*.exe; do
        info ">> fixing $binary_file..."
        # code based on https://github.com/erocarrera/pefile/blob/bbf28920a71248ed5c656c81e119779c131d9bd4/pefile.py#L5877
        python3 <<EOF
pe_file = "$binary_file"
with open(pe_file, "rb") as f:
    binary = bytearray(f.read())
pe_offset = int.from_bytes(binary[0x3c:0x3c+4], byteorder="little")
checksum_offset = pe_offset + 88
checksum = 0

# Pad data to 8-byte boundary.
remainder = len(binary) % 8
binary += bytes(8 - remainder)

for i in range(len(binary) // 4):
    if i == checksum_offset // 4:  # Skip the checksum field
        continue
    dword = int.from_bytes(binary[i*4:i*4+4], byteorder="little")
    checksum = (checksum & 0xffffffff) + dword + (checksum >> 32)
    if checksum > 2 ** 32:
        checksum = (checksum & 0xffffffff) + (checksum >> 32)

checksum = (checksum & 0xffff) + (checksum >> 16)
checksum = (checksum) + (checksum >> 16)
checksum = checksum & 0xffff
checksum += len(binary)

# Set the checksum
binary[checksum_offset : checksum_offset + 4] = int.to_bytes(checksum, byteorder="little", length=4)

with open(pe_file, "wb") as f:
    f.write(binary)
EOF
    done
)

sha256sum dist/bitcoin_safe*.exe
