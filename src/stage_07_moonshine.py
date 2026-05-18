"""Stage 7 — Moonshine installation.

Clones the Moonshine repository (Wine fork), configures it for 64-bit execution
with Wayland support, builds it on the build host, and installs it into the 
target rootfs via DESTDIR.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .common import (
    Config,
    err,
    have,
    info,
    ok,
    run,
    step_banner,
    warn,
)


MOONSHINE_REPO   = "https://github.com/BDmajora/Moonshine.git"
MOONSHINE_BRANCH = "stable"


def _check_build_host() -> None:
    """Verify the build host has the basic tools and dev files needed to compile Moonshine."""
    missing_tools = [t for t in ("git", "make", "cc", "pkg-config") if not have(t)]
    if missing_tools:
        err(f"Missing build tools on host: {', '.join(missing_tools)}")
        sys.exit(1)

    # Wine 9+ / Moonshine requires xkbregistry along with wayland and xkbcommon libraries.
    pkgs = ["wayland-client", "wayland-egl", "xkbcommon", "xkbregistry"]
    missing_pkgs = []
    for pkg in pkgs:
        res = subprocess.run(["pkg-config", "--exists", pkg], capture_output=True)
        if res.returncode != 0:
            missing_pkgs.append(pkg)

    if missing_pkgs:
        err(f"Missing required 64-bit development files on host: {', '.join(missing_pkgs)}")
        warn("Please install the missing development libraries on your host machine.")
        warn("On Ubuntu/Debian, run: sudo apt install libwayland-dev libxkbcommon-dev libxkbregistry-dev")
        sys.exit(1)


def _ensure_moonshine(cfg: Config) -> Path:
    """Wipe cached clone, re-clone, configure, and build Moonshine."""
    src_dir = cfg.build_dir / "moonshine"

    if src_dir.exists():
        info(f"Removing cached Moonshine clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    info(f"Cloning Moonshine from {MOONSHINE_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", MOONSHINE_BRANCH,
         MOONSHINE_REPO, str(src_dir)])

    info("Configuring Moonshine ...")
    run(["./configure", "--enable-win64", "--with-wayland"], cwd=str(src_dir))

    # Added the -j flag here to ensure multi-threaded compilation
    info(f"Building Moonshine using {cfg.jobs} parallel jobs ...")
    run(["make", f"-j{cfg.jobs}", "-C", str(src_dir)])

    return src_dir


def _install_moonshine(cfg: Config, repo_dir: Path) -> None:
    """Install Moonshine into the target rootfs using DESTDIR."""
    info("Installing Moonshine into rootfs chroot ...")
    
    # DESTDIR must point to the absolute path of the rootfs mount point
    destdir = f"DESTDIR={cfg.mount.resolve()}"
    run(["make", "-C", str(repo_dir), destdir, "install"])


def run_stage(cfg: Config) -> None:
    step_banner("Stage 7 — Install Moonshine")

    _check_build_host()

    repo_dir = _ensure_moonshine(cfg)
    _install_moonshine(cfg, repo_dir)

    ok("Moonshine installed successfully into rootfs")