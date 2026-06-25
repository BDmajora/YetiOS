"""Stage 10 — CrystallineLattice compositor installation (chroot build).

CrystallineLattice (binary: `glacier`) is a from-scratch DRM/KMS
platform layer purpose-built for YetiOS. It talks to libdrm/GBM/EGL/GLES and
libinput directly and acquires devices through seatd (libseat) — there is NO
wlroots and NO upstream Wayland compositor underneath. It hosts native Linux
apps through its OWN minimal Wayland frontend (libwayland-server + a frozen
xdg-shell/xdg-decoration subset; Transport B), plus Xwayland for legacy X11 —
glacier's own code, not wlroots, not Weston.

Built inside the chroot (like the rest of the snow suite) so it links against
the target's libdrm/mesa/libseat rather than the host's, avoiding ABI drift.

Part of the YetiOS snow suite:
  snowcone (splash) → snowfall (login) → CrystallineLattice (DRM/KMS layer)
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

from .core import (
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
)


CRYSTALLINELATTICE_REPO   = "https://github.com/BDmajora/CrystallineLattice.git"
CRYSTALLINELATTICE_BRANCH = "main"

# Installed binary name (meson `executable('glacier', ...)`).
CL_BINARY = "glacier"

# pkg-config modules that must exist inside the chroot before building.
# These map 1:1 to the dependency() calls in CrystallineLattice's meson.build.
CHROOT_BUILD_PKGS = [
    "libdrm",
    "gbm",
    "egl",
    "glesv2",
    "libudev",
    "libseat",
    "wayland-server",      # Transport B: the Wayland compatibility frontend
    "wayland-protocols",   # xdg-shell + xdg-decoration XML (scanned at build time)
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _clone_source(cfg: Config) -> Path:
    """Clone CrystallineLattice source on the host (network access)."""
    src_dir = cfg.build_dir / "crystallinelattice"

    if src_dir.exists():
        info(f"Removing cached CrystallineLattice clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    if not have("git"):
        err("git not found on build host")
        sys.exit(1)

    info(f"Cloning CrystallineLattice from {CRYSTALLINELATTICE_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", CRYSTALLINELATTICE_BRANCH,
         CRYSTALLINELATTICE_REPO, str(src_dir)])

    return src_dir


def _build_in_chroot(cfg: Config, host_src: Path) -> None:
    """Copy source into chroot, meson-build there, install the binary."""
    chroot_src = cfg.mount / "tmp" / "crystallinelattice"

    # Clean any leftover from a previous attempt.
    if chroot_src.exists():
        shutil.rmtree(chroot_src)

    info("Copying CrystallineLattice source into chroot ...")
    shutil.copytree(host_src, chroot_src)

    chroot_mount(cfg)
    try:
        # Verify build deps exist inside the chroot.
        info("Checking chroot build dependencies ...")
        for pkg in CHROOT_BUILD_PKGS:
            cp = in_chroot(cfg, f"pkg-config --exists {pkg}", check=False)
            if cp.returncode != 0:
                err(f"Missing pkg-config module in chroot: {pkg}")
                err("Ensure the providing package is in packages.txt "
                    "(mesa, libglvnd, libdrm, seatd, udev, wayland, "
                    "wayland-protocols).")
                sys.exit(1)

        # The Wayland frontend's meson build scans xdg-shell/xdg-decoration XML
        # with wayland-scanner (a binary from the `wayland` package, not a .pc).
        cp = in_chroot(cfg, "command -v wayland-scanner", check=False)
        if cp.returncode != 0:
            err("wayland-scanner not found in chroot (provided by `wayland`).")
            sys.exit(1)

        # Configure + build + install via meson/ninja.
        info("Building CrystallineLattice inside chroot ...")
        in_chroot(
            cfg,
            "cd /tmp/crystallinelattice && "
            "rm -rf build && "
            "meson setup build --prefix=/usr --buildtype=release && "
            "ninja -C build && "
            "ninja -C build install",
        )

        # meson installs to /usr/bin/<CL_BINARY>; verify it landed.
        bin_dst = cfg.mount / "usr/bin" / CL_BINARY
        if not bin_dst.is_file():
            err(f"Build finished but {bin_dst} was not produced.")
            err("Check the CrystallineLattice build output for errors.")
            sys.exit(1)

        ok(f"CrystallineLattice built in chroot, installed as /usr/bin/{CL_BINARY}")

    finally:
        chroot_umount(cfg)
        # Clean up source from chroot /tmp.
        if chroot_src.exists():
            shutil.rmtree(chroot_src)


def run_stage(cfg: Config) -> None:
    step_banner("Stage 10 — Install CrystallineLattice compositor")

    repo_dir = _clone_source(cfg)
    _build_in_chroot(cfg, repo_dir)

    ok("CrystallineLattice installed")
