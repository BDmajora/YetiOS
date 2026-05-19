"""Stage 7 — Moonshine installation (chroot build).

Clones the Moonshine repository (Wine fork) on the build host (for
network access), copies the source tree into the chroot, configures and
builds it inside the chroot against the target's libraries, then installs
it in-place.

WHY CHROOT BUILD: Moonshine/Wine links against dozens of shared libraries
(wayland-client, vulkan, freetype, gnutls, …). Building on the host
produces binaries linked against the host's library versions, which may
differ from the target rootfs.  This causes anything from subtle ABI
mismatches to outright "symbol not found" crashes at runtime.  Building
inside the chroot guarantees the binary matches the target, just like
frostedglass (stage 10).

The trade-off is that the chroot needs a C toolchain and dev headers
installed — stage 06 handles this via YETI_PACKAGE_LIST.
"""

from __future__ import annotations

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


MOONSHINE_REPO   = "https://github.com/BDmajora/Moonshine.git"
MOONSHINE_BRANCH = "stable"

# pkg-config modules that must exist inside the chroot before configure.
# These are the Wayland/Vulkan deps that Moonshine needs at link time.
CHROOT_BUILD_PKGS = [
    "wayland-client",
    "wayland-egl",
    "xkbcommon",
    "xkbregistry",
    "freetype2",
    "vulkan",
]


def _clone_source(cfg: Config) -> Path:
    """Clone Moonshine source on the host (network access)."""
    src_dir = cfg.build_dir / "moonshine"

    if src_dir.exists():
        info(f"Removing cached Moonshine clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    if not have("git"):
        err("git not found on build host")
        sys.exit(1)

    info(f"Cloning Moonshine from {MOONSHINE_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", MOONSHINE_BRANCH,
         MOONSHINE_REPO, str(src_dir)])

    return src_dir


def _build_in_chroot(cfg: Config, host_src: Path) -> None:
    """Copy source into chroot, configure + build + install there."""
    chroot_src = cfg.mount / "tmp" / "moonshine"

    # Clean any leftover from a previous attempt
    if chroot_src.exists():
        shutil.rmtree(chroot_src)

    info("Copying Moonshine source into chroot ...")
    shutil.copytree(host_src, chroot_src)

    chroot_mount(cfg)
    try:
        # Verify build toolchain exists inside the chroot
        info("Checking chroot build toolchain ...")
        for tool in ("gcc", "make", "pkg-config"):
            cp = in_chroot(cfg, f"command -v {tool}", check=False)
            if cp.returncode != 0:
                err(f"Missing build tool in chroot: {tool}")
                err("Ensure build toolchain packages are in YETI_PACKAGE_LIST.")
                sys.exit(1)

        # Verify key dev libraries are present
        info("Checking chroot build dependencies ...")
        missing_pc = []
        for pkg in CHROOT_BUILD_PKGS:
            cp = in_chroot(cfg, f"pkg-config --exists {pkg}", check=False)
            if cp.returncode != 0:
                missing_pc.append(pkg)
        if missing_pc:
            warn(f"Missing pkg-config modules in chroot: {', '.join(missing_pc)}")
            warn("Moonshine may configure without some optional features.")
            warn("Add the providing packages to YETI_PACKAGE_LIST if needed.")

        # Configure — enable 64-bit Wine with Wayland support
        info("Configuring Moonshine inside chroot ...")
        in_chroot(cfg, "cd /tmp/moonshine && ./configure --enable-win64 --with-wayland")

        # Build with parallel jobs
        info(f"Building Moonshine inside chroot using {cfg.jobs} parallel jobs ...")
        info("(This will take a while — Wine is a large codebase)")
        in_chroot(cfg, f"make -j{cfg.jobs} -C /tmp/moonshine")

        # Install in-place (no DESTDIR needed — we're already in the target)
        info("Installing Moonshine inside chroot ...")
        in_chroot(cfg, "make -C /tmp/moonshine install")

        # Verify the binary landed
        cp = in_chroot(cfg, "command -v wine64 || command -v wine", check=False)
        if cp.returncode != 0:
            err("Moonshine installed but neither wine64 nor wine found in PATH.")
            err("Check the Moonshine build output for errors.")
            sys.exit(1)

        ok("Moonshine built and installed inside chroot")

    finally:
        chroot_umount(cfg)
        # Clean up source from chroot /tmp
        if chroot_src.exists():
            shutil.rmtree(chroot_src)


def run_stage(cfg: Config) -> None:
    step_banner("Stage 7 — Install Moonshine (chroot build)")

    repo_dir = _clone_source(cfg)
    _build_in_chroot(cfg, repo_dir)

    ok("Moonshine installed successfully into rootfs")