#!/bin/bash



# ————————————————————————————————
# If there's no tty attached, silence all output:
if ! tty -s; then
    # Silencing is necessary, otherwise it will crash with the error:
    # OSError: [Errno 5] Input/output error
    exec 1>/dev/null 2>/dev/null
fi
# ————————————————————————————————




# Exit immediately if a command exits with a non-zero status
set -e

# Determine the directory in which this script resides
APPDIR="$(dirname "$(readlink -e "$0")")"

# Build an array of library paths  
# the order matters!!!
LD_PATHS=(
    "${APPDIR}/usr/lib/"
    "${APPDIR}/usr/lib/python3.12/site-packages/PyQt6/Qt6/lib"
    "${APPDIR}/usr/lib/x86_64-linux-gnu"
)

# Join array elements by colon, preserving any existing LD_LIBRARY_PATH
IFS=:
LD_LIBRARY_PATH="${LD_PATHS[*]}${LD_LIBRARY_PATH+:$LD_LIBRARY_PATH}"
unset IFS
export LD_LIBRARY_PATH

# Prepend bundled binaries to PATH
export PATH="${APPDIR}/usr/bin:${PATH}"

# Set linker flags for static libraries
export LDFLAGS="-L${APPDIR}/usr/lib/x86_64-linux-gnu -L${APPDIR}/usr/lib"

# Execute the Python module with all passed arguments
QT_QPA_PLATFORM=xcb  exec "${APPDIR}/usr/bin/python3" -s -m "bitcoin_safe" "$@"

# Dont remove 
# QT_QPA_PLATFORM=xcb
# it Tells Qt to use X11 instead of Wayland: This avoids all the Wayland-related bugs in PyQt
# otherwise the entire app crashes when there is a popup
# See https://github.com/andreasgriffin/bitcoin-safe/issues/180
