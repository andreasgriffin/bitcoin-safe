#!/usr/bin/env bash

REQUIRED_TOOLS=(appstreamcli flatpak flatpak-builder dbus-run-session desktop-file-validate timeout tar)

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

info() {
    printf 'INFO: %s\n' "$*"
}

run_with_dbus_session() {
    dbus-run-session -- "$@"
}

ensure_appstream_cli_compose_support() {
    if ! command -v appstreamcli >/dev/null 2>&1; then
        fail "appstreamcli is not installed."
    fi

    if ! appstreamcli compose --help >/dev/null 2>&1; then
        fail "appstreamcli compose is not supported by the installed AppStream toolchain."
    fi
}

install_flatpak_prerequisites() {
    local missing_tools=0
    local tool
    for tool in "${REQUIRED_TOOLS[@]}"; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            missing_tools=1
            break
        fi
    done

    if [ "${missing_tools}" -eq 0 ]; then
        ensure_appstream_cli_compose_support
        return
    fi

    info "Installing Flatpak build prerequisites."
    sudo apt-get update
    sudo apt-get install -y \
        appstream \
        appstream-util \
        dbus-daemon \
        desktop-file-utils \
        flatpak \
        flatpak-builder
    ensure_appstream_cli_compose_support
}

print_flatpak_toolchain_summary() {
    info "Flatpak toolchain summary:"
    printf 'INFO:   %s\n' "$(flatpak --version | head -n 1)"
    printf 'INFO:   %s\n' "$(flatpak-builder --version | head -n 1)"
    printf 'INFO:   %s\n' "$(appstreamcli --version | head -n 1)"
    printf 'INFO:   appstreamcli path: %s\n' "$(command -v appstreamcli)"
}

check_flatpak_sandbox_support() {
    if ! command -v bwrap >/dev/null 2>&1; then
        fail "bubblewrap is not installed. Ensure Flatpak smoke-test prerequisites were installed before probing sandbox support."
    fi

    if bwrap --ro-bind / / --proc /proc true >/dev/null 2>&1; then
        return
    fi

    if sysctl kernel.apparmor_restrict_unprivileged_userns >/dev/null 2>&1; then
        fail "bubblewrap sandboxing is unavailable. On Ubuntu 24.04 this is often caused by AppArmor blocking unprivileged user namespaces; current kernel.apparmor_restrict_unprivileged_userns=$(sysctl -n kernel.apparmor_restrict_unprivileged_userns)."
    fi

    fail "bubblewrap sandboxing is unavailable. Flatpak builds and flatpak run require user namespaces in the current environment."
}

ensure_flathub_remote() {
    if run_with_dbus_session flatpak remotes --columns=name | grep -qx 'flathub'; then
        return
    fi

    info "Adding Flathub remote."
    run_with_dbus_session flatpak remote-add --user --if-not-exists \
        flathub https://flathub.org/repo/flathub.flatpakrepo
}
