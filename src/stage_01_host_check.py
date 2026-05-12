"""Stage 1 — host sanity check."""

from __future__ import annotations

import os
import sys

from .common import Config, err, have, ok, step_banner, warn


REQUIRED_HOST_TOOLS = [
    # Image + partition + mount
    "qemu-img", "parted",
    "mkfs.ext4", "mkfs.vfat",
    "losetup", "mount", "umount",
    # Download + extract stage3
    "wget", "tar", "xz",
    # Chroot
    "chroot",
    # Fetch + build libreldr from its own repo
    "git", "make",
]


def run_stage(cfg: Config) -> None:
    step_banner("Stage 1 — Host sanity check")

    if sys.platform != "linux":
        err("yeti-build must run on a Linux host (uses chroot + loop devices).")
        sys.exit(1)

    if os.geteuid() != 0:
        err("Run as root (or via sudo). Loop mounts and chroot require it.")
        sys.exit(1)

    missing = [t for t in REQUIRED_HOST_TOOLS if not have(t)]
    if missing:
        err("Missing host tools: " + ", ".join(missing))
        err("On Debian/Ubuntu/Mint:")
        err("  apt install parted util-linux dosfstools qemu-utils \\")
        err("              wget tar xz-utils git build-essential gnu-efi")
        sys.exit(1)

    needed_gb = cfg.img_size_gb + 5
    parent = cfg.build_dir.parent if not cfg.build_dir.exists() else cfg.build_dir
    try:
        statvfs = os.statvfs(parent)
        free_gb = statvfs.f_bavail * statvfs.f_frsize / (1024 ** 3)
        if free_gb < needed_gb:
            err(f"Need ~{needed_gb} GB free in {parent}, have {free_gb:.1f} GB.")
            sys.exit(1)
    except FileNotFoundError:
        err(f"Build directory path {parent} is invalid.")
        sys.exit(1)

    if cfg.overlay_dir.is_dir():
        ok("yeti-overlay/ found (optional files will be used if present).")
    else:
        warn(f"yeti-overlay/ not found at {cfg.overlay_dir}; using internal defaults.")

    ok(f"Linux host, root, all tools present, {free_gb:.1f} GB free.")