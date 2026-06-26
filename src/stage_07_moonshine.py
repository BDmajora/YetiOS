"""Stage 7 — Moonshine installation (chroot build).

Clones the Moonshine repository (Wine fork) on the build host (for
network access), copies the source tree into the chroot, configures and
builds it inside the chroot against the target's libraries, then installs
it in-place.

WHY CHROOT BUILD: Moonshine/Wine links against dozens of shared libraries
(vulkan, freetype, gnutls, …). Building on the host
produces binaries linked against the host's library versions, which may
differ from the target rootfs.  This causes anything from subtle ABI
mismatches to outright "symbol not found" crashes at runtime.  Building
inside the chroot guarantees the binary matches the target, just like
CrystallineLattice (stage 10).

The trade-off is that the chroot needs a C toolchain and dev headers
installed — stage 06 handles this via packages.txt.
"""

from __future__ import annotations

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
    warn,
)


MOONSHINE_REPO   = "https://github.com/BDmajora/Moonshine.git"
MOONSHINE_BRANCH = "stable"

# pkg-config modules Moonshine needs inside the chroot before configure.
#
# YetiOS builds Wine with the CrystallineLattice driver (winedrm.drv, Path β),
# NOT the Wayland driver. winedrm links only libwin32u + pthread, so it needs
# NO wayland-client/wayland-egl/xkbcommon/xkbregistry dev libs — those belonged
# to winewayland.drv, which we no longer build. glacier (stage 10) owns the
# Wayland *frontend* for native Linux apps; Wine itself never speaks Wayland.
# What's left here are the Wine-core link deps worth verifying up front.
CHROOT_BUILD_PKGS = [
    "freetype2",
    "vulkan",
]


# Wine Mono MSI — Moonshine (a Wine fork) looks for the Mono installer in
# /usr/share/wine/mono/ before trying to download it. Staging it here lets the
# Wine prefix initialize offline (no "Install Mono" dialog blocking the first
# session). Moved here from the old frostedglass stage since it's a Wine/
# Moonshine concern, not a compositor one.
WINE_MONO_VERSION = "9.4.0"
WINE_MONO_URL = (
    f"https://dl.winehq.org/wine/wine-mono/{WINE_MONO_VERSION}/"
    f"wine-mono-{WINE_MONO_VERSION}-x86.msi"
)


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
                err("Ensure build toolchain packages are in packages.txt.")
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
            warn("Add the providing packages to packages.txt if needed.")

        # Configure — 64-bit Wine with the CrystallineLattice driver (winedrm).
        # --with-drm is the meaningful switch: it selects winedrm.drv as the Wine
        # display path AND disables the Wayland driver (they're alternative
        # backends), so winewayland.drv and its wayland-client/xkb deps stay out
        # of the build. winedrm registers as a graphics driver, so configure does
        # NOT fall back to demanding X11 dev files (this rootfs ships no Xorg).
        info("Configuring Moonshine inside chroot (--with-drm: winedrm driver) ...")
        in_chroot(cfg, "cd /tmp/moonshine && ./configure --enable-win64 --with-drm")

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


def _install_wine_mono(cfg: Config) -> None:
    """Pre-stage the Wine Mono MSI into the shared Wine cache.

    Moonshine looks for Mono MSIs in /usr/share/wine/mono/ before trying to
    download them. Pre-installing avoids the "Install Mono" dialog and the
    need for network access when the Wine prefix is first initialized.
    Non-fatal: if the download fails, Mono is fetched on first boot instead.
    """
    mono_cache = cfg.mount / "usr/share/wine/mono"
    mono_msi = mono_cache / f"wine-mono-{WINE_MONO_VERSION}-x86.msi"

    if mono_msi.exists():
        info("Wine Mono MSI already staged, skipping download")
        return

    mono_cache.mkdir(parents=True, exist_ok=True)

    info(f"Downloading Wine Mono {WINE_MONO_VERSION} ...")
    dl_path = cfg.build_dir / f"wine-mono-{WINE_MONO_VERSION}-x86.msi"

    if not dl_path.exists():
        cp = run(["wget", "-q", "--show-progress", "-O", str(dl_path),
                  WINE_MONO_URL], check=False)
        if cp.returncode != 0:
            warn(f"Failed to download Wine Mono from {WINE_MONO_URL}")
            warn("Wine will download Mono on first boot instead (needs network).")
            dl_path.unlink(missing_ok=True)
            return

    shutil.copy2(dl_path, mono_msi)
    mono_msi.chmod(0o644)
    ok(f"Wine Mono {WINE_MONO_VERSION} staged to /usr/share/wine/mono/")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 7 — Install Moonshine (chroot build)")

    repo_dir = _clone_source(cfg)
    _build_in_chroot(cfg, repo_dir)
    _install_wine_mono(cfg)

    ok("Moonshine installed successfully into rootfs")