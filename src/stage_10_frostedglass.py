"""Stage 10 — frostedglass compositor installation.

Mirrors stage_09_snowfall.py's pattern: clone from GitHub, build on the
build host, copy binaries and configs into the rootfs, register the
Wayland session.

Frostedglass is a minimal wlroots-based compositor purpose-built for
YetiOS. It launches Wine explorer.exe as the desktop shell — Wine draws
the taskbar, start menu, and manages all windows through its own Win32
window manager. The compositor is invisible plumbing.

Part of the YetiOS snow suite:
  snowcone (splash) → snowfall (login) → frostedglass (desktop)

Build-host requirements:
  - make, pkg-config, gcc
  - wlroots 0.18+ development headers
  - wayland-server, wayland-protocols, xkbcommon, pixman-1
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from .common import (
    Config,
    chroot_mount,
    chroot_umount,
    err,
    have,
    in_chroot,
    info,
    ok,
    run,
    step_banner,
    warn,
)


FROSTEDGLASS_REPO   = "https://github.com/BDmajora/FrostedGlass.git"
FROSTEDGLASS_BRANCH = "main"

# pkg-config deps that must exist on the BUILD HOST.
REQUIRED_PKGCONFIG = [
    "wlroots-0.18",
    "wayland-server",
    "wayland-protocols",
    "xkbcommon",
    "pixman-1",
]

WLROOTS_FALLBACK = "wlroots"

APT_HINT = (
    "apt install build-essential pkg-config "
    "libwlroots-dev libwayland-dev wayland-protocols "
    "libxkbcommon-dev libpixman-1-dev libdrm-dev libinput-dev"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_build_host() -> None:
    """Verify build-host toolchain for frostedglass."""
    missing_tools = [t for t in ("git", "make", "cc", "pkg-config")
                     if not have(t)]
    if missing_tools:
        err(f"Missing build tools: {', '.join(missing_tools)}")
        err(f"Install with: {APT_HINT}")
        sys.exit(1)

    missing_pc = []
    for name in REQUIRED_PKGCONFIG:
        cp = run(["pkg-config", "--exists", name], check=False)
        if cp.returncode != 0:
            if name == "wlroots-0.18":
                cp2 = run(["pkg-config", "--exists", WLROOTS_FALLBACK],
                          check=False)
                if cp2.returncode == 0:
                    continue
            missing_pc.append(name)

    if missing_pc:
        err(f"Missing pkg-config modules: {', '.join(missing_pc)}")
        err(f"Install with: {APT_HINT}")
        sys.exit(1)


def _ensure_frostedglass(cfg: Config) -> Path:
    """Wipe cached clone, re-clone, build, return the repo dir.

    Same pattern as snowcone/snowfall: always build from a fresh clone
    so upstream changes never get masked by a stale binary.
    """
    src_dir  = cfg.build_dir / "frostedglass"
    bin_path = src_dir / "frostedglass"

    if src_dir.exists():
        info(f"Removing cached frostedglass clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    info(f"Cloning frostedglass from {FROSTEDGLASS_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", FROSTEDGLASS_BRANCH,
         FROSTEDGLASS_REPO, str(src_dir)])

    info("Building frostedglass ...")
    run(["make", "-C", str(src_dir)])

    if not bin_path.is_file():
        err(f"Build finished but {bin_path} was not produced.")
        err(f"Check dependencies: {APT_HINT}")
        sys.exit(1)

    return src_dir


def _install(cfg: Config, repo_dir: Path) -> None:
    """Install frostedglass binary, session file, and registry into rootfs."""
    bin_src = repo_dir / "frostedglass"

    # Binary → /usr/local/bin/frostedglass
    bin_dst = cfg.mount / "usr/local/bin/frostedglass"
    bin_dst.parent.mkdir(parents=True, exist_ok=True)
    if bin_dst.exists():
        bin_dst.unlink()
    shutil.copy2(bin_src, bin_dst)
    bin_dst.chmod(0o755)

    if _sha256(bin_src) != _sha256(bin_dst):
        err("frostedglass binary copy failed integrity check!")
        sys.exit(1)
    ok("frostedglass binary installed and verified")

    # Session desktop file → /usr/share/wayland-sessions/frostedglass.desktop
    desktop_src = repo_dir / "frostedglass.desktop"
    if desktop_src.is_file():
        desktop_dst = cfg.mount / "usr/share/wayland-sessions/frostedglass.desktop"
        desktop_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(desktop_src, desktop_dst)
        desktop_dst.chmod(0o644)
        ok("frostedglass.desktop session file installed")
    else:
        warn("frostedglass.desktop not found in repo; skipping session file.")

    # Wine registry prefs → /etc/skel/.frostedglass_prefs.reg
    reg_src = repo_dir / "frostedglass_prefs.reg"
    if reg_src.is_file():
        skel_dst = cfg.mount / "etc/skel/.frostedglass_prefs.reg"
        skel_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reg_src, skel_dst)
        skel_dst.chmod(0o644)

        # Also drop it into the yeti user's home if it exists.
        user_home = cfg.mount / "home" / cfg.yeti_user
        if user_home.is_dir():
            user_reg = user_home / ".frostedglass_prefs.reg"
            shutil.copy2(reg_src, user_reg)
            user_reg.chmod(0o644)
            ok(f"registry prefs installed for {cfg.yeti_user}")
    else:
        warn("frostedglass_prefs.reg not found in repo; skipping registry prefs.")


def _ensure_wine_in_chroot(cfg: Config) -> None:
    """Ensure Wine is installed in the target. Warn if missing."""
    chroot_mount(cfg)
    try:
        cp = in_chroot(cfg, "which wine", check=False)
        if cp.returncode != 0:
            warn("Wine not found in target rootfs!")
            warn("frostedglass requires Wine. Add app-emulation/wine-vanilla or")
            warn("app-emulation/wine-staging to YETI_PACKAGE_LIST.")
    finally:
        chroot_umount(cfg)


def run_stage(cfg: Config) -> None:
    step_banner("Stage 10 — Install frostedglass compositor")

    _check_build_host()

    repo_dir = _ensure_frostedglass(cfg)
    _install(cfg, repo_dir)
    _ensure_wine_in_chroot(cfg)

    ok("frostedglass installed")