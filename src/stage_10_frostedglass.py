"""Stage 10 — frostedglass compositor installation.

Frostedglass is a minimal wlroots-based compositor purpose-built for
YetiOS. It launches Wine explorer.exe as the desktop shell — Wine draws
the taskbar, start menu, and manages all windows through its own Win32
window manager. The compositor is invisible plumbing.

IMPORTANT: frostedglass links against libwlroots, which has an unstable
ABI that changes every minor release. The host may have wlroots-0.18
while the target rootfs has wlroots-0.20 (or vice versa). Building on
the host produces a binary that segfaults or fails to load in the guest.

Solution: clone on the host (for network access), copy the source tree
into the chroot, build inside the chroot against the target's wlroots,
then install the resulting binary.

Part of the YetiOS snow suite:
  snowcone (splash) → snowfall (login) → frostedglass (desktop)
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

# Build deps that must be present inside the chroot.
CHROOT_BUILD_PKGS = [
    "wayland-server",
    "wayland-protocols",
    "xkbcommon",
    "pixman-1",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _clone_source(cfg: Config) -> Path:
    """Clone frostedglass source on the host (network access)."""
    src_dir = cfg.build_dir / "frostedglass"

    if src_dir.exists():
        info(f"Removing cached frostedglass clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    if not have("git"):
        err("git not found on build host")
        sys.exit(1)

    info(f"Cloning frostedglass from {FROSTEDGLASS_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", FROSTEDGLASS_BRANCH,
         FROSTEDGLASS_REPO, str(src_dir)])

    return src_dir


def _build_in_chroot(cfg: Config, host_src: Path) -> None:
    """Copy source into chroot, build there, install the binary."""
    chroot_src = cfg.mount / "tmp" / "frostedglass"

    # Clean any leftover from a previous attempt
    if chroot_src.exists():
        shutil.rmtree(chroot_src)

    # Copy source tree into the chroot's /tmp
    info("Copying frostedglass source into chroot ...")
    shutil.copytree(host_src, chroot_src)

    chroot_mount(cfg)
    try:
        # Verify build deps exist inside the chroot
        info("Checking chroot build dependencies ...")
        for pkg in CHROOT_BUILD_PKGS:
            cp = in_chroot(cfg, f"pkg-config --exists {pkg}", check=False)
            if cp.returncode != 0:
                err(f"Missing pkg-config module in chroot: {pkg}")
                err("Ensure dev headers are installed in the rootfs.")
                sys.exit(1)

        # wlroots can be any version — the Makefile auto-detects
        cp = in_chroot(cfg, "pkg-config --exists wlroots-0.18 2>/dev/null || "
                            "pkg-config --exists wlroots-0.20 2>/dev/null || "
                            "pkg-config --exists wlroots 2>/dev/null",
                       check=False)
        if cp.returncode != 0:
            err("No wlroots found in chroot (tried wlroots-0.18, wlroots-0.20, wlroots)")
            sys.exit(1)

        # Build
        info("Building frostedglass inside chroot ...")
        in_chroot(cfg, "make -C /tmp/frostedglass clean && make -C /tmp/frostedglass")

        # Verify binary was produced
        bin_chroot = chroot_src / "frostedglass"
        if not bin_chroot.is_file():
            err("Build completed but frostedglass binary was not produced.")
            sys.exit(1)

        # Install binary → /usr/local/bin/frostedglass
        bin_dst = cfg.mount / "usr/local/bin/frostedglass"
        bin_dst.parent.mkdir(parents=True, exist_ok=True)
        if bin_dst.exists():
            bin_dst.unlink()
        shutil.copy2(bin_chroot, bin_dst)
        bin_dst.chmod(0o755)

        if _sha256(bin_chroot) != _sha256(bin_dst):
            err("frostedglass binary copy failed integrity check!")
            sys.exit(1)
        ok("frostedglass binary built in chroot, installed and verified")

    finally:
        chroot_umount(cfg)
        # Clean up source from chroot /tmp
        if chroot_src.exists():
            shutil.rmtree(chroot_src)


def _install_configs(cfg: Config, repo_dir: Path) -> None:
    """Install session file and registry prefs (no compilation needed)."""

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

    repo_dir = _clone_source(cfg)
    _build_in_chroot(cfg, repo_dir)
    _install_configs(cfg, repo_dir)
    _ensure_wine_in_chroot(cfg)

    ok("frostedglass installed")