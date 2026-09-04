"""Stage 1 - host sanity check for the FreeBSD image pipeline."""

from __future__ import annotations

import os
import sys

from .core import Config, err, have, ok, parse_size_to_bytes, step_banner


REQUIRED_TOOLS = (
    "qemu-img",
    "parted",
    "losetup",
    "mount",
    "umount",
    "mkfs.ext2",
    "e2fsck",
    "tune2fs",
    "mkfs.vfat",
    "tar",
    "xz",
)


def run_stage(cfg: Config) -> None:
    step_banner("Stage 1 - Host sanity check")

    if sys.version_info < (3, 11):
        err("Python 3.11 or newer is required.")
        sys.exit(1)

    if os.geteuid() != 0:
        err("Run as root or with sudo. The Linux image tools need loop devices and mounts.")
        sys.exit(1)

    missing = [tool for tool in REQUIRED_TOOLS if not have(tool)]
    if missing:
        err("Missing required host tools: " + ", ".join(missing))
        err("Install the original Artix-era Linux image tools.")
        sys.exit(1)

    source_checks = {
        "libreldr": (cfg.libreldr_dir, ("Makefile", "src/libreldr.c")),
        "SnowCone": (
            cfg.snowcone_dir,
            (
                "Makefile",
                "LICENSE",
                "main_freebsd.c",
                "snowcone.freebsd.rc",
                "snowcone.freebsd-handoff.rc",
                "src/sc_fb_freebsd.c",
                "src/sc_theme.c",
                "src/sc_font.c",
                "src/sc_raster.c",
                "include/sc_kms.h",
                "include/sc_scene.h",
                "include/sc_raster.h",
                "include/sc_font.h",
                "include/sc_log.h",
            ),
        ),
        "Moonshine": (
            cfg.moonshine_dir,
            (
                "configure",
                "configure.ac",
                "dlls/winewayland.drv/Makefile.in",
                "programs/explorer/desktop.c",
            ),
        ),
        "SnowFall": (
            cfg.snowfall_dir,
            ("Makefile", "main.c", "src/drm.c", "src/input.c", "src/session.c"),
        ),
        "FrostedWeb": (
            cfg.frostedweb_dir,
            ("meson.build", "main.c", "src/fw_moonshine.c", "include/fw_moonshine.h"),
        ),
    }
    for label, (root, files) in source_checks.items():
        if not root.is_dir():
            err(f"{label} source tree not found: {root}")
            sys.exit(1)
        for name in files:
            if not (root / name).is_file():
                err(f"{label} source file not found: {root / name}")
                sys.exit(1)

    if not cfg.desktop_packages_file.is_file():
        err(f"desktop package list not found: {cfg.desktop_packages_file}")
        sys.exit(1)

    parent = cfg.build_dir.parent if not cfg.build_dir.exists() else cfg.build_dir
    try:
        statvfs = os.statvfs(parent)
        free_gb = statvfs.f_bavail * statvfs.f_frsize / (1024 ** 3)
    except FileNotFoundError:
        err(f"Build directory path {parent} is invalid.")
        sys.exit(1)

    needed_gb = max(10, (cfg.total_image_bytes * 2) / (1024 ** 3))
    if free_gb < needed_gb:
        err(f"Need at least {needed_gb:.1f} GB free in {parent}, have {free_gb:.1f} GB.")
        sys.exit(1)

    for size in (cfg.root_size, cfg.local_size, cfg.esp_size, cfg.swap_size):
        parse_size_to_bytes(size)

    ok(f"host ready, {free_gb:.1f} GB free")
