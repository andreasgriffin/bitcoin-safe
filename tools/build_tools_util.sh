#!/usr/bin/env bash

# Set a fixed umask as this leaks into docker containers
umask 0022

RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color
function info() {
    # Combine all arguments into one string for printf
    local message="$*"
    # Use printf to print the combined message
    printf "\r💬 ${BLUE}INFO:${NC} %s\n" "$message"
}
function fail() {
    local message="$*"
    printf "\r🗯 ${RED}ERROR:${NC} %s\n" "$message"
    exit 1
}
function warn() {
    local message="$*"
    printf "\r⚠️  ${YELLOW}WARNING:${NC} %s\n" "$message"
}


# based on https://superuser.com/questions/497940/script-to-verify-a-signature-with-gpg
function verify_signature() {
    local file=$1 keyring=$2 out=
    if out=$(gpg --no-default-keyring --keyring "$keyring" --status-fd 1 --verify "$file" 2>/dev/null) &&
        echo "$out" | grep -qs "^\[GNUPG:\] VALIDSIG "; then
        return 0
    else
        echo "$out" >&2
        exit 1
    fi
}

function verify_hash() {
    local file=$1 expected_hash=$2
    actual_hash=$(sha256sum $file | awk '{print $1}')
    if [ "$actual_hash" == "$expected_hash" ]; then
        return 0
    else
        echo "$file $actual_hash (unexpected hash)" >&2
        rm "$file"
        exit 1
    fi
}

function download_if_not_exist() {
    local file_name=$1 url=$2
    if [ ! -e $file_name ] ; then
        wget -O $file_name "$url"
    fi
}

# https://github.com/travis-ci/travis-build/blob/master/lib/travis/build/templates/header.sh
function retry() {
    local result=0
    local count=1
    while [ $count -le 3 ]; do
        [ $result -ne 0 ] && {
            echo -e "\nThe command \"$@\" failed. Retrying, $count of 3.\n" >&2
        }
        ! { "$@"; result=$?; }
        [ $result -eq 0 ] && break
        count=$(($count + 1))
        sleep 1
    done

    [ $count -gt 3 ] && {
        echo -e "\nThe command \"$@\" failed 3 times.\n" >&2
    }

    return $result
}

function gcc_with_triplet()
{
    TRIPLET="$1"
    CMD="$2"
    shift 2
    if [ -n "$TRIPLET" ] ; then
        "$TRIPLET-$CMD" "$@"
    else
        "$CMD" "$@"
    fi
}

function gcc_host()
{
    gcc_with_triplet "$GCC_TRIPLET_HOST" "$@"
}

function gcc_build()
{
    gcc_with_triplet "$GCC_TRIPLET_BUILD" "$@"
}

function host_strip()
{
    if [ "$GCC_STRIP_BINARIES" -ne "0" ] ; then
        case "$BUILD_TYPE" in
            linux|wine)
                gcc_host strip "$@"
                ;;
            darwin)
                # TODO: Strip on macOS?
                ;;
        esac
    fi
}

# on MacOS, there is no realpath by default
if ! [ -x "$(command -v realpath)" ]; then
    function realpath() {
        [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"
    }
fi


# Use a reproducible build timestamp derived from the source tree when available.
# Fall back to a constant epoch if the repository metadata is unavailable (e.g. tarball release).
if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
    # When the caller has not set SOURCE_DATE_EPOCH explicitly we try to infer a
    # deterministic value: locate the repository root (relative to this script),
    # read the commit timestamp of HEAD, and reuse that as our canonical build
    # time.  This makes repeated builds with the same source revision resolve to
    # the same clock value while still allowing upstream environments to supply
    # their own timestamp when required.
    _tools_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if command -v git >/dev/null 2>&1 && git -C "${_tools_dir}/.." rev-parse >/dev/null 2>&1; then
        SOURCE_DATE_EPOCH="$(git -C "${_tools_dir}/.." log -1 --format=%ct 2>/dev/null || true)"
    fi
    if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
        # The hard-coded epoch gives us a stable fallback for source archives
        # (which ship without the .git metadata needed for the logic above).
        SOURCE_DATE_EPOCH=1530212462
    fi
    unset _tools_dir
fi
export SOURCE_DATE_EPOCH
export ZERO_AR_DATE=1 # for macOS
export PYTHONHASHSEED=22
# Set the build type, overridden by wine build
export BUILD_TYPE="${BUILD_TYPE:-$(uname | tr '[:upper:]' '[:lower:]')}"
# Add host / build flags if the triplets are set
if [ -n "$GCC_TRIPLET_HOST" ] ; then
    export AUTOCONF_FLAGS="$AUTOCONF_FLAGS --host=$GCC_TRIPLET_HOST"
fi
if [ -n "$GCC_TRIPLET_BUILD" ] ; then
    export AUTOCONF_FLAGS="$AUTOCONF_FLAGS --build=$GCC_TRIPLET_BUILD"
fi

export GCC_STRIP_BINARIES="${GCC_STRIP_BINARIES:-0}"

if [ -n "$CIRRUS_CPU" ] ; then
    # special-case for CI. see https://github.com/cirruslabs/cirrus-ci-docs/issues/1115
    export CPU_COUNT="$CIRRUS_CPU"
else
    export CPU_COUNT="$(nproc 2> /dev/null || sysctl -n hw.ncpu)"
fi
info "Found $CPU_COUNT CPUs, which we might use for building."


function break_legacy_easy_install() {
    # We don't want setuptools sneakily installing dependencies, invisible to pip.
    # This ensures that if setuptools calls distutils which then calls easy_install,
    # easy_install will not download packages over the network.
    # see https://pip.pypa.io/en/stable/reference/pip_install/#controlling-setup-requires
    # see https://github.com/pypa/setuptools/issues/1916#issuecomment-743350566
    info "Intentionally breaking legacy easy_install."
    DISTUTILS_CFG="${HOME}/.pydistutils.cfg"
    DISTUTILS_CFG_BAK="${HOME}/.pydistutils.cfg.orig"
    # If we are not inside docker, we might be overwriting a config file on the user's system...
    if [ -e "$DISTUTILS_CFG" ] && [ ! -e "$DISTUTILS_CFG_BAK" ]; then
        warn "Overwriting python distutils config file at '$DISTUTILS_CFG'. A copy will be saved at '$DISTUTILS_CFG_BAK'."
        mv "$DISTUTILS_CFG" "$DISTUTILS_CFG_BAK"
    fi
    cat <<EOF > "$DISTUTILS_CFG"
[easy_install]
index_url = ''
find_links = ''
EOF
}





function replace_once() {
  local text="$1"
  local search_str="$2"
  local replace_str="$3"

  # Check if the search string is at the beginning of the text
  if [[ "$text" == "$search_str"* ]]; then
    # Remove the search string and check the remainder
    local prefix=${text#$search_str}
    
    # If the prefix still starts with the search string or is the same as before removing,
    # it means 'search_str' appears more than once at the start or not at all after the first
    if [[ "$prefix" == "$text" ]] || [[ "$prefix" == "$search_str"* ]]; then
      echo "Error: '$search_str' does not appear exactly once at the left side of '$text'" >&2
      exit 1
    else
      # Replace the first occurrence of search_str with replace_str
      local new_text="${text/#$search_str/$replace_str}"
      echo "$new_text"
    fi
  else
    echo "Error: '$search_str' is not at the left side of '$text'" >&2
    exit 1
  fi
}

# replaces  /opt/wine64/drive_c/   -->  c:/
function win_path() {
    local text="$1"



    here="$(dirname "$(readlink -e "$0")")"
    test -n "$here" -a -d "$here" || exit
    # here = /opt/wine64/drive_c/bitcoin_safe/tools/build-wine 
    CONTRIB="$here/.."
    PROJECT_ROOT="$CONTRIB/.."

    # Correctly capturing the output of realpath into a variable
    local search_path=$(realpath "$PROJECT_ROOT/..")

    # Assuming replace_once function exists and is used to replace the first occurrence
    # This will echo the result after replacing the first occurrence of search_path in text with "c:"
    echo $(replace_once "$text" "$search_path" "c:")
}






function do_wine_pip() {
    info "Installing pip $@"
    WINE_PIP_CACHE_DIR=$(win_path "$PIP_CACHE_DIR")
    $WINE_PYTHON -m pip install --no-build-isolation --no-dependencies --no-warn-script-location \
        --cache-dir "$WINE_PIP_CACHE_DIR" "$@" \
        || fail "Could not install the specified packages due to a failure in: $@"
}



move_and_overwrite() {
    local source_dir="$1"
    local dest_dir="$2"

    # Check if source directory is not provided or does not exist
    if [[ -z "$source_dir" || ! -d "$source_dir" ]]; then
        echo "Notice: Source directory '$source_dir' does not exist or is not provided. Skipping."
        return 0  # Consider using 'return 0' to indicate skipping as non-critical.
    fi

    # Check if destination directory is provided
    if [[ -z "$dest_dir" ]]; then
        echo "Error: Destination directory is not provided."
        return 1
    fi

    # Remove the destination directory if it exists
    if [[ -d "$dest_dir" ]]; then
        echo "Removing existing destination directory '$dest_dir'."
        rm -rf "$dest_dir"
    fi

    # Move the source directory to the destination
    mv "$source_dir" "$dest_dir" && echo "Successfully moved '$source_dir' to '$dest_dir'." || {
        echo "Error: Failed to move '$source_dir' to '$dest_dir'."
        return 1
    }
}



list_dirty_files() {
    # Retrieve the current git version including tags and state
    local temp_version=$(git describe --tags --dirty --always --abbrev=20)

    # Check if the string 'dirty' is in the version
    if [[ "$temp_version" == *dirty* ]]; then
        warn "Repository is dirty. Listing modified files:"
        # List files that are modified but not yet staged for commit
        git diff --name-only
        # List files that are staged but not yet committed
        git diff --name-only --cached
    else
        info "Repository is clean version: $temp_version"
    fi
}



breakpoint() {
  local src="${BASH_SOURCE[1]}"
  local line="${BASH_LINENO[0]}"

  # 1️⃣ grab every variable (and function) definition
  local allvars
  allvars="$(declare -p)"

  # 2️⃣ grab every exported var too (so that declare -p covers only shell variables,
  #    and export -p covers already‐exported ones)
  local exports
  exports="$(export -p)"

  echo "⏸ Pausing at ${src}:${line}"

  # 3️⃣ spawn an interactive bash with a custom rcfile
  /bin/bash --rcfile <(
    # re-inject all shell vars as exported
    printf '%s\n' "$allvars" 2>/dev/null
    printf '%s\n' "$exports" 2>/dev/null
    # your friendly welcome…
    printf 'echo "🛠  Welcome to debug shell (paused at %s:%s). Type exit to resume."\n' \
           "${src}" "${line}"
    # and a distinctive prompt
    printf 'PS1="(DEBUG) $ "\n'
    # then load your normal profile so aliases/functions still work:
    cat ~/.bashrc 2>/dev/null
  ) -i
}
