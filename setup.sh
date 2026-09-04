#!/usr/bin/env bash
set -euo pipefail

# Host setup for an Artix Linux machine building/running YetiOS.
#
# This is based on the original Artix-base YetiOS host requirements:
# qemu-img, parted, mkfs.ext2, e2fsck, tune2fs, mkfs.ext4, mkfs.vfat, losetup,
# mount, umount, wget, curl, tar, xz, zstd, gzip, gawk, sed, and git.
#
# YetiOS components are compiled by /assemble inside the FreeBSD VM, not by the
# Artix host.
#
# No AUR is used here. Everything is installed from enabled pacman repos only.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PACMAN_FLAGS=(--needed)
if [[ "${ASSUME_YES:-0}" == "1" ]]; then
    PACMAN_FLAGS+=(--noconfirm)
fi

if (( EUID == 0 )); then
    SUDO=()
    TARGET_USER="${SUDO_USER:-}"
else
    SUDO=(sudo)
    TARGET_USER="${USER:-}"
fi

say() {
    printf '[*] %s\n' "$*"
}

warn() {
    printf '[!] %s\n' "$*" >&2
}

die() {
    printf '[x] %s\n' "$*" >&2
    exit 1
}

have() {
    command -v "$1" >/dev/null 2>&1
}

repo_has() {
    pacman -Si "$1" >/dev/null 2>&1 || pacman -Sg "$1" >/dev/null 2>&1
}

install_repo_package() {
    local pkg="$1"
    if repo_has "$pkg"; then
        say "Installing $pkg"
        "${SUDO[@]}" pacman -S "${PACMAN_FLAGS[@]}" "$pkg"
        return 0
    fi

    warn "Package not found in enabled pacman repos: $pkg"
    return 1
}

install_repo_candidates() {
    local pkg
    for pkg in "$@"; do
        install_repo_package "$pkg" || true
    done
}

install_first_available() {
    local label="$1"
    shift

    local pkg
    for pkg in "$@"; do
        if repo_has "$pkg"; then
            say "Installing $label via $pkg"
            "${SUDO[@]}" pacman -S "${PACMAN_FLAGS[@]}" "$pkg"
            return 0
        fi
    done

    warn "No enabled pacman repo package found for $label; tried: $*"
    return 1
}

add_user_to_group_if_present() {
    local user="$1"
    local group="$2"

    [[ -n "$user" ]] || return 0
    getent group "$group" >/dev/null 2>&1 || return 0
    "${SUDO[@]}" usermod -aG "$group" "$user" || true
}

enable_openrc_service_if_present() {
    local service="$1"
    if have rc-update && [[ -e "/etc/init.d/$service" ]]; then
        "${SUDO[@]}" rc-update add "$service" default || true
        "${SUDO[@]}" rc-service "$service" start || true
    fi
}

if ! have pacman; then
    die "This setup script is for Artix/Arch-style hosts with pacman."
fi

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}:${ID_LIKE:-}" in
        artix:*|arch:*|*:arch*) ;;
        *) warn "This does not look like Artix/Arch from /etc/os-release; continuing because pacman exists." ;;
    esac
fi

say "Repository root: $ROOT_DIR"
say "Syncing system and package databases"
"${SUDO[@]}" pacman -Syu

say "Installing original Artix-base YetiOS build host packages"
install_repo_candidates \
    base-devel \
    python \
    git \
    make \
    gcc \
    binutils \
    parted \
    util-linux \
    e2fsprogs \
    dosfstools \
    wget \
    curl \
    tar \
    xz \
    zstd \
    gzip \
    gawk \
    sed \
    coreutils

say "Installing QEMU and libvirt packages from enabled repos"
install_first_available "QEMU image tools" qemu-img qemu-base qemu-full || true
install_first_available "QEMU x86 system emulator" qemu-system-x86 qemu-desktop qemu-full || true
install_repo_candidates \
    edk2-ovmf \
    libvirt \
    virt-manager \
    dnsmasq \
    bridge-utils \
    openbsd-netcat \
    swtpm \
    acl

if have rc-service; then
    say "Installing OpenRC libvirt service packages from enabled repos"
    install_repo_candidates \
        libvirt-openrc \
        virtlogd-openrc \
        virtlockd-openrc \
        dnsmasq-openrc
fi

say "Adding user to virtualization groups when present"
add_user_to_group_if_present "$TARGET_USER" libvirt
add_user_to_group_if_present "$TARGET_USER" kvm

say "Starting libvirt services when this host exposes them"
enable_openrc_service_if_present virtlogd
enable_openrc_service_if_present virtlockd
enable_openrc_service_if_present libvirtd
enable_openrc_service_if_present dnsmasq

missing_original=()
for tool in qemu-img parted mkfs.ext2 e2fsck tune2fs mkfs.ext4 mkfs.vfat losetup mount umount wget curl tar xz zstd gzip gawk sed git; do
    have "$tool" || missing_original+=("$tool")
done

missing_current=()
for tool in qemu-system-x86_64 virsh; do
    have "$tool" || missing_current+=("$tool")
done

if (( ${#missing_original[@]} > 0 )); then
    warn "Still missing original Artix-base build tools: ${missing_original[*]}"
    exit 1
fi

if (( ${#missing_current[@]} > 0 )); then
    warn "Original Artix-base host tools are installed, but these VM commands are still missing: ${missing_current[*]}"
    exit 1
fi

say "Host packages/tools look ready."
say "If your user was added to libvirt/kvm, log out and back in before using virt-manager."
say "VM start command: virsh -c qemu:///system start yetios"
