#!/usr/bin/env python3
"""
run.py - YetiOS FreeBSD base-image preparer.

The Artix/Linux host prepares a bootable FreeBSD VM image, creates the default
YetiOS account, stages YetiOS source trees, and copies in `/assemble`.
The actual YetiOS-owned components are built later from inside FreeBSD by
running `./assemble` in the VM.

Pipeline:
  1. host_check        - Verify local tooling and workspace state
  2. fetch_release     - Fetch FreeBSD MANIFEST, base.txz, and kernel.txz
  3. stage_root        - Verify/extract sets, create identity, stage assemble
  4. bootstrap_esp     - Install stock FreeBSD loader for first VM boot
  5. assemble_image    - Create the GPT image with Linux host image tools
  6. libvirt_access    - Grant system libvirt access to build/yetios.img
  7. manifest          - Write image/source notes

Usage:
  sudo ./run.py
  sudo ./run.py --restart
  sudo ./run.py --only 04_bootstrap_esp
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from src import (
    stage_01_host_check,
    stage_02_fetch_release,
    stage_03_stage_root,
    stage_04_bootstrap_esp,
    stage_05_assemble_image,
    stage_06_libvirt_access,
    stage_07_manifest,
)
from src.core import BuildState, Config, STAGES, err, ok, warn


REPO_ROOT = Path(__file__).resolve().parent
PIPELINE_STATE_VERSION = "freebsd-base-plus-assemble-v1"

_STAGE_FILES = {
    "01_host_check": ("src/core.py", "src/stage_01_host_check.py"),
    "02_fetch_release": ("src/core.py", "src/stage_02_fetch_release.py"),
    "03_stage_root": ("src/core.py", "src/rootfs.py", "src/snowcone_loader.py", "src/stage_03_stage_root.py", "desktop-packages.txt"),
    "04_bootstrap_esp": ("src/core.py", "src/rootfs.py", "src/stage_04_bootstrap_esp.py"),
    "05_assemble_image": ("src/core.py", "src/stage_05_assemble_image.py"),
    "06_libvirt_access": ("src/core.py", "src/stage_06_libvirt_access.py"),
    "07_manifest": ("src/core.py", "src/stage_07_manifest.py"),
}


def _label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _stage_source_paths(stage: str, cfg: Config) -> list[Path]:
    paths = [REPO_ROOT / "run.py"]
    paths.extend(REPO_ROOT / rel for rel in _STAGE_FILES[stage])
    if stage == "03_stage_root":
        paths.extend([
            cfg.libreldr_dir / "Makefile",
            cfg.libreldr_dir / "src" / "libreldr.c",
            cfg.libreldr_dir / "libreldr_entries.py",
            cfg.snowcone_dir / "Makefile",
            cfg.snowcone_dir / "main_freebsd.c",
            cfg.snowcone_dir / "snowcone.freebsd.rc",
            cfg.snowcone_dir / "snowcone.freebsd-handoff.rc",
            cfg.snowcone_dir / "src" / "sc_fb_freebsd.c",
            cfg.snowcone_dir / "src" / "sc_theme.c",
            cfg.snowcone_dir / "src" / "sc_font.c",
            cfg.snowcone_dir / "src" / "sc_raster.c",
            cfg.snowcone_dir / "include" / "sc_kms.h",
            cfg.snowcone_dir / "include" / "sc_scene.h",
            cfg.snowcone_dir / "include" / "sc_raster.h",
            cfg.snowcone_dir / "include" / "sc_font.h",
            cfg.snowcone_dir / "include" / "sc_log.h",
            cfg.snowcone_dir / "LICENSE",
            cfg.moonshine_dir / "configure",
            cfg.moonshine_dir / "configure.ac",
            cfg.moonshine_dir / "dlls" / "winewayland.drv" / "Makefile.in",
            cfg.moonshine_dir / "programs" / "explorer" / "desktop.c",
            cfg.snowfall_dir / "Makefile",
            cfg.snowfall_dir / "main.c",
            cfg.snowfall_dir / "snowfall_integration.py",
            cfg.snowfall_dir / "src" / "drm.c",
            cfg.snowfall_dir / "src" / "input.c",
            cfg.snowfall_dir / "src" / "auth.c",
            cfg.snowfall_dir / "src" / "session.c",
            cfg.snowfall_dir / "src" / "drm_freebsd.c",
            cfg.snowfall_dir / "src" / "input_freebsd.c",
            cfg.snowfall_dir / "include" / "sf_session.h",
            cfg.snowfall_dir / "snowfall.freebsd.rc",
            cfg.frostedweb_dir / "meson.build",
            cfg.frostedweb_dir / "main.c",
            cfg.frostedweb_dir / "include" / "fw_moonshine.h",
            cfg.frostedweb_dir / "src" / "fw_moonshine.c",
            cfg.frostedweb_dir / "frostedweb.desktop",
            cfg.frostedweb_dir / "moonshine-wayland.reg",
        ])
    return paths


def _stage_signature(stage: str, cfg: Config) -> str:
    h = hashlib.sha256()
    h.update(PIPELINE_STATE_VERSION.encode())
    h.update(stage.encode())
    stage_config = {
        "release": cfg.release,
        "arch": cfg.arch,
        "mirror": cfg.mirror,
        "hostname": cfg.hostname,
        "yeti_user": cfg.yeti_user,
        "yeti_password": cfg.yeti_password,
        "timezone": cfg.timezone,
        "root_size": cfg.root_size,
        "local_size": cfg.local_size,
        "esp_size": cfg.esp_size,
        "swap_size": cfg.swap_size,
        "jobs": cfg.jobs,
        "libreldr_dir": str(cfg.libreldr_dir),
        "snowcone_dir": str(cfg.snowcone_dir),
        "moonshine_dir": str(cfg.moonshine_dir),
        "snowfall_dir": str(cfg.snowfall_dir),
        "frostedweb_dir": str(cfg.frostedweb_dir),
        "desktop_packages_file": str(cfg.desktop_packages_file),
    }
    h.update(
        json.dumps(stage_config, sort_keys=True).encode()
    )
    for path in _stage_source_paths(stage, cfg):
        h.update(_label(path).encode())
        h.update(b"\0")
        h.update(path.read_bytes() if path.exists() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="YetiOS FreeBSD image orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--build-dir", default=str(REPO_ROOT / "build"),
                   help="Output directory for image work and FreeBSD cache")
    p.add_argument("--release", default="15.1-RELEASE",
                   help="FreeBSD release to install into the YetiOS image")
    p.add_argument("--arch", default="amd64",
                   help="FreeBSD release architecture")
    p.add_argument("--mirror",
                   default="https://download.freebsd.org/releases",
                   help="FreeBSD release mirror base URL")
    p.add_argument("--hostname", default="yetios",
                   help="Target hostname")
    p.add_argument("--yeti-user", default="yetios",
                   help="Default YetiOS login account")
    p.add_argument("--yeti-password", default="yetios",
                   help="Default alpha password for the YetiOS login account")
    p.add_argument("--tz", default="UTC",
                   help="Target timezone")
    p.add_argument("--root-size", default="6g",
                   help="Root ext2 partition size for the Linux-tool alpha path")
    p.add_argument("--local-size", default="24g",
                   help="Persistent FreeBSD UFS /usr/local partition size for in-VM builds")
    p.add_argument("--esp-size", default="260m",
                   help="EFI system partition image size")
    p.add_argument("--swap-size", default="512m",
                   help="Swap partition image size")
    p.add_argument("--jobs", type=int, default=24,
                   help="Default parallel jobs for the in-VM assemble script")
    p.add_argument("--libreldr-dir", default=str(REPO_ROOT.parent / "libreldr"),
                   help="Path to the libreldr source tree")
    p.add_argument("--snowcone-dir", default=str(REPO_ROOT.parent / "SnowCone"),
                   help="Path to the SnowCone source tree")
    p.add_argument("--moonshine-dir", default=str(REPO_ROOT.parent / "Moonshine"),
                   help="Path to the Moonshine source tree")
    p.add_argument("--snowfall-dir", default=str(REPO_ROOT.parent / "snowfall"),
                   help="Path to the SnowFall source tree")
    p.add_argument("--frostedweb-dir", default=str(REPO_ROOT.parent / "FrostedWeb"),
                   help="Path to the FrostedWeb source tree")
    p.add_argument("--desktop-packages-file", default=str(REPO_ROOT / "desktop-packages.txt"),
                   help="FreeBSD pkg list copied into the image for /assemble")
    p.add_argument("--restart", action="store_true",
                   help="Wipe stage markers and run the image pipeline again")
    p.add_argument("--only", choices=STAGES, default=None,
                   help="Run a single stage and exit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.from_args(args)
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    state = BuildState(cfg.build_dir)
    if args.restart:
        warn("--restart: wiping stage markers")
        state.clear()
    state.load()
    signatures = {stage: _stage_signature(stage, cfg) for stage in STAGES}
    rerun_rest = False

    def should_run(stage: str) -> bool:
        if args.only:
            return stage == args.only
        return rerun_rest or not state.done(stage, signatures[stage])

    def mark_done(stage: str) -> None:
        nonlocal rerun_rest
        state.mark(stage, signatures[stage])
        if not args.only:
            rerun_rest = True

    def run_one(stage: str, runner) -> None:
        if should_run(stage):
            runner.run_stage(cfg)
            mark_done(stage)

    try:
        run_one("01_host_check", stage_01_host_check)
        run_one("02_fetch_release", stage_02_fetch_release)
        run_one("03_stage_root", stage_03_stage_root)
        run_one("04_bootstrap_esp", stage_04_bootstrap_esp)
        run_one("05_assemble_image", stage_05_assemble_image)
        run_one("06_libvirt_access", stage_06_libvirt_access)
        run_one("07_manifest", stage_07_manifest)

    except subprocess.CalledProcessError as e:
        err(f"Command failed: {e}")
        warn("Re-run to retry; completed and up-to-date stages are skipped.")
        warn("Or use --only <stage> to retry just one.")
        return 1
    except KeyboardInterrupt:
        warn("Interrupted.")
        return 130
    except Exception as e:
        err(str(e))
        return 1

    ok("YetiOS FreeBSD image prepared.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
