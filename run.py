#!/usr/bin/env python3
"""
run.py — YetiOS build orchestrator entry point.

YetiOS = Artix (OpenRC) base + custom user session.

Thin dispatcher: parses args, walks the resumable stage pipeline, and
delegates to modules under src/. Each stage writes a marker on success,
so re-running picks up where you left off after Ctrl-C or a failure.

Pipeline:
  1. host_check         — Verify Linux, root, tools, disk space, overlay
  2. image_create       — Create sparse .img and write partition table
  2. image_mount        — Loop-attach, format, mount root + /boot
  3. fetch              — Download artix-bootstrap.sh (cached)
  4. extract            — Bootstrap a minimal Artix base into the image
  5. pacman_setup       — pacman.conf + mirror lists + keyrings + sync
  6. install_packages   — pacman -S the YetiOS userland (packages.txt)
  7. moonshine          — Build and install Moonshine (Wine fork) in chroot
  8. bootloader         — libreldr UEFI install + kernel/initramfs to ESP
  9. splash             — Build and install snowcone boot splash
 10. snowfall           — Build and install snowfall login manager
 11. crystallinelattice — Build and install CrystallineLattice compositor
 12. unmount            — Clean detach, print QEMU boot command

Boot chain on the resulting image:
  libreldr  -> snowcone (boot splash, grabs DRM master)
            -> snowfall (login manager, takes DRM master,
                        which causes snowcone to detect master loss
                        and exit cleanly)
            -> CrystallineLattice (from-scratch DRM/KMS platform layer,
                                  takes DRM master from snowfall; no
                                  wlroots, no Wayland)

Usage:
  sudo ./run.py                                  # full build, defaults to nproc
  sudo ./run.py --restart                        # wipe stage markers
  sudo ./run.py --only 10_crystallinelattice     # re-run a single stage
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from src import (
    stage_01_host_check,
    stage_02_image,
    stage_03_fetch,
    stage_04_extract,
    stage_05_pacman_setup,
    stage_06_install_packages,
    stage_07_moonshine,
    stage_08_bootloader,
    stage_09_snowfall,
    stage_10_crystallinelattice,
    stage_11_splash,
    stage_12_unmount,
)
from src.core import (
    BuildState,
    Config,
    STAGES,
    emergency_unmount,
    err,
    loop_for,
    losetup_attach,
    ok,
    warn,
)


REPO_ROOT = Path(__file__).resolve().parent
OVERLAY_DIR = REPO_ROOT / "yeti-overlay"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="YetiOS build orchestrator (Artix-based, OpenRC)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--build-dir", default=str(REPO_ROOT / "build"),
                   help="Output directory for image and bootstrap cache")
    p.add_argument("--size", type=int, default=20,
                   help="Image size in GB")
    p.add_argument("--mount", default="/mnt/yetios",
                   help="Mountpoint for the target root during build")
    p.add_argument("--yeti-user", default="yeti",
                   help="Default user inside YetiOS")
    p.add_argument("--hostname", default="yetios", help="System hostname")
    p.add_argument("--tz", default="UTC", help="Timezone")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 2,
                   help="Parallel jobs (default: $(nproc))")
    p.add_argument("--artix-mirror", default="https://mirror1.artixlinux.org/repos",
                   help="Artix repo mirror base ($repo/os/$arch is appended)")
    p.add_argument("--arch-mirror", default="https://geo.mirror.pkgbuild.com",
                   help="Arch repo mirror base ($repo/os/$arch is appended)")
    p.add_argument("--init", default="openrc",
                   choices=["openrc", "runit", "s6", "dinit"],
                   help="Artix init system to bootstrap")
    p.add_argument("--restart", action="store_true",
                   help="Wipe stage markers and start over (preserves image)")
    p.add_argument("--only", choices=STAGES, default=None,
                   help="Run a single stage and exit (for debugging)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.from_args(args, OVERLAY_DIR)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    state = BuildState(cfg.build_dir)
    if args.restart:
        warn("--restart: wiping stage markers")
        state.clear()
    state.load()

    loop: "str | None" = None

    def should_run(stage: str) -> bool:
        if args.only:
            return stage == args.only
        return not state.done(stage)

    try:
        if should_run("01_host_check"):
            stage_01_host_check.run_stage(cfg)
            state.mark("01_host_check")

        if should_run("02_image_create"):
            stage_02_image.run_create(cfg)
            state.mark("02_image_create")

        # Mounting is ephemeral runtime state, NOT a resumable build artifact,
        # so (re)mount on EVERY run rather than gating on a marker. This is
        # what guarantees the FAT ESP is mounted at <mount>/boot before any
        # stage writes the kernel or EFI files there. (Previously, if the root
        # was already mounted from a prior run the mount step was skipped and
        # the ESP was never mounted — the bootloader + kernel then landed on
        # the ext4 root's /boot and the real ESP booted empty → UEFI shell.)
        loop = stage_02_image.run_mount(cfg)
        state.mark("02_image_mount")

        if should_run("03_fetch"):
            stage_03_fetch.run_stage(cfg)
            state.mark("03_fetch")

        if should_run("04_extract"):
            stage_04_extract.run_stage(cfg)
            state.mark("04_extract")

        if should_run("05_pacman_setup"):
            stage_05_pacman_setup.run_stage(cfg)
            state.mark("05_pacman_setup")

        if should_run("06_install_packages"):
            stage_06_install_packages.run_stage(cfg)
            state.mark("06_install_packages")

        if should_run("07_moonshine"):
            stage_07_moonshine.run_stage(cfg)
            state.mark("07_moonshine")

        if should_run("07_bootloader"):
            stage_08_bootloader.run_stage(cfg, loop)
            state.mark("07_bootloader")

        if should_run("08_splash"):
            stage_11_splash.run_stage(cfg)
            state.mark("08_splash")

        if should_run("09_snowfall"):
            stage_09_snowfall.run_stage(cfg)
            state.mark("09_snowfall")

        if should_run("10_crystallinelattice"):
            stage_10_crystallinelattice.run_stage(cfg)
            state.mark("10_crystallinelattice")

        if should_run("11_unmount"):
            stage_12_unmount.run_stage(cfg, loop)
            state.mark("11_unmount")

    except subprocess.CalledProcessError as e:
        err(f"Command failed: {e}")
        warn("Re-run to retry — completed stages are skipped.")
        warn("Or use --only <stage> to retry just one.")
        emergency_unmount(cfg)
        return 1
    except KeyboardInterrupt:
        warn("Interrupted. Detaching cleanly.")
        emergency_unmount(cfg)
        return 130

    ok("YetiOS build complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())