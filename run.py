#!/usr/bin/env python3
"""
run.py — YetiOS build orchestrator entry point.

YetiOS = Gentoo stage3 + custom user session.

Thin dispatcher: parses args, walks the resumable stage pipeline, and
delegates to modules under src/. Each stage writes a marker on success,
so re-running picks up where you left off after Ctrl-C or a failure.

Pipeline:
  1. host_check         — Verify Linux, root, tools, disk space, overlay
  2. image_create       — Create sparse .img and write partition table
  2. image_mount        — Loop-attach, format, mount root + /boot
  3. fetch              — Download Gentoo stage3 tarball (cached)
  4. extract            — Extract tarball into the mounted image
  5. portage_setup      — make.conf + binhost + sync portage tree
  6. install_packages   — emerge runtime packages (mostly binpkgs, ~30 min)
  7. bootloader         — extlinux + MBR + kernel symlinks
  8. unmount            — Clean detach, print QEMU boot command

Usage:
  sudo ./run.py                            # full build, defaults to nproc
  sudo ./run.py --restart                  # wipe stage markers
  sudo ./run.py --only 06_install_packages # re-run a single stage
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
    stage_05_portage_setup,
    stage_06_install_packages,
    stage_07_bootloader,
    stage_08_unmount,
)
from src.common import (
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
        description="YetiOS build orchestrator (Gentoo-based)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--build-dir", default=str(REPO_ROOT / "build"),
                   help="Output directory for image and stage3 cache")
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
    p.add_argument("--mirror", default="https://distfiles.gentoo.org/",
                   help="Gentoo distfiles mirror base URL")
    p.add_argument("--variant", default="amd64-openrc",
                   help="Stage3 variant (amd64-openrc, amd64-systemd, etc.)")
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

        # Image must be mounted for every later stage; re-attach if needed.
        loop = loop_for(cfg.img_path) or losetup_attach(cfg.img_path)
        if should_run("02_image_mount") or not os.path.ismount(cfg.mount):
            loop = stage_02_image.run_mount(cfg)
            state.mark("02_image_mount")

        if should_run("03_fetch"):
            stage_03_fetch.run_stage(cfg)
            state.mark("03_fetch")

        if should_run("04_extract"):
            stage_04_extract.run_stage(cfg)
            state.mark("04_extract")

        if should_run("05_portage_setup"):
            stage_05_portage_setup.run_stage(cfg)
            state.mark("05_portage_setup")

        if should_run("06_install_packages"):
            stage_06_install_packages.run_stage(cfg)
            state.mark("06_install_packages")

        if should_run("07_bootloader"):
            stage_07_bootloader.run_stage(cfg, loop)
            state.mark("07_bootloader")

        if should_run("08_unmount"):
            stage_08_unmount.run_stage(cfg, loop)
            state.mark("08_unmount")

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