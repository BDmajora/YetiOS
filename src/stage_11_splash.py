"""Stage 8 — snowcone boot splash installation (chroot build).

Clone the snowcone repo on the build host (for network access), copy the
source tree into the chroot, build inside the chroot against the target's
DRM headers, install the binary + OpenRC service, and register it.

WHY CHROOT BUILD: snowcone links against libdrm and uses Linux DRM
headers.  Building on the host risks linking against the wrong libdrm
version or kernel headers.  Building inside the chroot ensures the
binary matches the target environment exactly.

The integration is consciously identical to libreldr:
  - wipe any cached clone every time, so upstream changes always land
  - build from scratch (cheap; one .c file)
  - hash-verify the binary copy lands intact

We also check that the cmdline tokens recommended by snowcone_integration.py
are present in the libreldr config.  Without `quiet`, kernel messages will
scroll over the splash.
"""

from __future__ import annotations

import hashlib
import importlib.util
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


SNOWCONE_REPO   = "https://github.com/BDmajora/snowcone.git"
SNOWCONE_BRANCH = "main"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _clone_source(cfg: Config) -> Path:
    """Clone snowcone source on the host (network access)."""
    src_dir = cfg.build_dir / "snowcone"

    if src_dir.exists():
        info(f"Removing cached snowcone clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    if not have("git"):
        err("git not found on build host")
        sys.exit(1)

    info(f"Cloning snowcone from {SNOWCONE_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", SNOWCONE_BRANCH,
         SNOWCONE_REPO, str(src_dir)])

    return src_dir


def _load_integration(repo_dir: Path):
    """Import snowcone_integration.py from the cloned repo."""
    p = repo_dir / "snowcone_integration.py"
    if not p.is_file():
        err(f"{p} not found in cloned snowcone repo.")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("snowcone_integration", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for required in ("FILES", "RUNLEVEL", "cmdline_addition"):
        if not hasattr(mod, required):
            err(f"{p} is missing {required}")
            sys.exit(1)
    return mod


def _check_cmdline_tokens(cfg: Config, integration) -> None:
    """Warn (don't fail) if libreldr_entries.py lacks the recommended tokens.

    libreldr_entries lives in the libreldr repo; we don't edit it. This
    is purely informational — without `quiet`, kernel messages will scroll
    over the splash.
    """
    libreldr_repo = cfg.build_dir / "libreldr"
    entries_path = libreldr_repo / "libreldr_entries.py"
    if not entries_path.is_file():
        return

    needed = integration.cmdline_addition().split()
    text = entries_path.read_text()
    missing = [t for t in needed if t not in text]
    if missing:
        warn("libreldr_entries.py is missing recommended cmdline tokens "
             "for the splash:")
        for m in missing:
            warn(f"  {m}")
        warn("Add them to the 'options' field in your Entry list inside "
             f"{entries_path} for a fully silent boot.")


def _build_and_install_in_chroot(cfg: Config, host_src: Path, integration) -> None:
    """Copy source into chroot, build there, install binary + service."""
    chroot_src = cfg.mount / "tmp" / "snowcone"

    # Clean any leftover from a previous attempt
    if chroot_src.exists():
        shutil.rmtree(chroot_src)

    info("Copying snowcone source into chroot ...")
    shutil.copytree(host_src, chroot_src)

    chroot_mount(cfg)
    try:
        # Verify build toolchain
        info("Checking chroot build toolchain ...")
        for tool in ("gcc", "make"):
            cp = in_chroot(cfg, f"command -v {tool}", check=False)
            if cp.returncode != 0:
                err(f"Missing build tool in chroot: {tool}")
                err("Ensure build toolchain packages are in packages.txt.")
                sys.exit(1)

        # Verify DRM headers exist (snowcone's only real build dep)
        cp = in_chroot(
            cfg,
            "test -f /usr/include/libdrm/drm.h || "
            "test -f /usr/include/drm/drm.h || "
            "pkg-config --exists libdrm",
            check=False,
        )
        if cp.returncode != 0:
            warn("DRM headers not detected via standard paths in chroot.")
            warn("Build may still succeed if headers are in a non-standard location.")

        # Build
        info("Building snowcone inside chroot ...")
        in_chroot(cfg, "make -C /tmp/snowcone clean 2>/dev/null; make -C /tmp/snowcone")

        # Verify binary was produced
        bin_chroot = chroot_src / "snowcone"
        if not bin_chroot.is_file():
            err("Build completed but snowcone binary was not produced.")
            err("Check that the chroot has a C toolchain and Linux DRM headers:")
            err("  sys-devel/gcc, sys-devel/make, sys-kernel/linux-headers")
            sys.exit(1)

        # Install files using integration metadata
        files = integration.FILES

        # Binary
        bin_dst = cfg.mount / files.binary_dst.lstrip("/")
        bin_dst.parent.mkdir(parents=True, exist_ok=True)
        if bin_dst.exists():
            bin_dst.unlink()
        shutil.copy2(bin_chroot, bin_dst)
        bin_dst.chmod(0o755)

        # Verify copy integrity
        if _sha256(bin_chroot) != _sha256(bin_dst):
            err("snowcone binary in rootfs does not match freshly built copy!")
            sys.exit(1)
        ok("snowcone binary built in chroot, installed and verified")

        # OpenRC init script
        openrc_src = chroot_src / files.openrc_src
        openrc_dst = cfg.mount / files.openrc_dst.lstrip("/")
        openrc_dst.parent.mkdir(parents=True, exist_ok=True)
        if openrc_dst.exists():
            openrc_dst.unlink()
        shutil.copy2(openrc_src, openrc_dst)
        openrc_dst.chmod(0o755)

        # Register the OpenRC service
        in_chroot(cfg, f"rc-update add snowcone {integration.RUNLEVEL}")
        ok(f"snowcone registered in '{integration.RUNLEVEL}' runlevel")

    finally:
        chroot_umount(cfg)
        # Clean up source from chroot /tmp
        if chroot_src.exists():
            shutil.rmtree(chroot_src)


def run_stage(cfg: Config) -> None:
    step_banner("Stage 8 — Install snowcone (chroot build)")

    repo_dir = _clone_source(cfg)
    integration = _load_integration(repo_dir)

    _build_and_install_in_chroot(cfg, repo_dir, integration)
    _check_cmdline_tokens(cfg, integration)

    ok("snowcone installed")