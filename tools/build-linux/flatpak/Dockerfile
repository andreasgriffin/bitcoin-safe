FROM ubuntu:24.04@sha256:c4a8d5503dfb2a3eb8ab5f807da5bc69a85730fb49b5cfca2330194ebcc41c7b

ENV LC_ALL=C.UTF-8 LANG=C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive

# need ca-certificates before using snapshot packages
RUN apt update -qq > /dev/null && apt install -qq --yes --no-install-recommends \
    ca-certificates

# Use only the pinned snapshot for package installs so apt never mixes live
# archive metadata with the frozen snapshot metadata in CI.
RUN mkdir -p /etc/apt/disabled-sources && \
    if [ -f /etc/apt/sources.list ]; then mv /etc/apt/sources.list /etc/apt/disabled-sources/sources.list; fi && \
    if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then mv /etc/apt/sources.list.d/ubuntu.sources /etc/apt/disabled-sources/ubuntu.sources; fi && \
    printf '' > /etc/apt/sources.list
COPY apt.sources.list /etc/apt/sources.list.d/ubuntu-snapshot.list
COPY apt.preferences /etc/apt/preferences.d/snapshot
COPY apt.conf /etc/apt/apt.conf.d/99-bitcoin-safe-network-resilience

RUN apt-get update -q && \
    apt-get install -qy --allow-downgrades --no-install-recommends \
        appstream \
        appstream-util \
        bubblewrap \
        dbus-daemon \
        desktop-file-utils \
        elfutils \
        flatpak \
        flatpak-builder \
        git \
        librsvg2-common \
        python3 \
        sudo \
        tar && \
    flatpak --version && \
    flatpak-builder --version && \
    appstreamcli --version && \
    command -v appstreamcli >/dev/null 2>&1 && \
    appstreamcli compose --help >/dev/null 2>&1 && \
    rm -rf /var/lib/apt/lists/*

ARG UID=1000
ENV USER="user"
ENV HOME_BASE="/home"
ENV HOME_DIR="${HOME_BASE}/${USER}"
ENV WORK_DIR="${HOME_DIR}/wspace" \
    PATH="${HOME_DIR}/.local/bin:${PATH}"
RUN existing_user="$(getent passwd "${UID}" | cut -d: -f1 || true)" && \
    if [ -n "${existing_user}" ]; then \
        userdel --remove "${existing_user}" || true; \
    fi && \
    useradd --uid "${UID}" --create-home --shell /bin/bash "${USER}"
RUN usermod --append --groups sudo "${USER}"
RUN echo "%sudo ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
WORKDIR ${WORK_DIR}
RUN chown --recursive "${USER}" "${WORK_DIR}"
USER ${USER}
