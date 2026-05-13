"""Stage 8 — snowcone boot splash installation.

Mirrors stage_07_bootloader.py's pattern of cloning a sister project,
building it on the build host (not inside the chroot), copying the
binary into the rootfs, and registering an OpenRC service.

The integration is consciously identical to libreldr:
  - wipe any cached clone every time, so upstream changes always land
  - build from scratch (cheap; one .c file)
  - hash-verify the binary copy lands intact

We also patch the cmdline tokens recommended by snowcone_integration.py
into the libreldr config indirectly: by ensuring the kernel options used
by libreldr include `quiet loglevel=3 vt.global_cursor_default=0`. Since
libreldr_entries.py is the source of truth for those, this stage emits
a small warning if it notices the tokens are missing — it does NOT
modify libreldr_entries.py itself (that lives in the libreldr repo).
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

from .common import (
    Config,
    err,
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


def _ensure_snowcone(cfg: Config) -> Path:
    """Wipe cached clone, re-clone, build, return the repo dir."""
    src_dir = cfg.build_dir / "snowcone"
    bin_path = src_dir / "snowcone"

    if src_dir.exists():
        info(f"Removing cached snowcone clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    info(f"Cloning snowcone from {SNOWCONE_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", SNOWCONE_BRANCH,
         SNOWCONE_REPO, str(src_dir)])

    info("Building snowcone ...")
    run(["make", "-C", str(src_dir)])

    if not bin_path.is_file():
        err(f"Build finished but {bin_path} was not produced.")
        err("Check that you have a working C toolchain and Linux DRM headers:")
        err("  apt install build-essential linux-libc-dev")
        sys.exit(1)

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
        # Stage 7 hasn't run yet (or was run with a different layout).
        # Nothing to check.
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


def _install_files(cfg: Config, repo_dir: Path, integration) -> None:
    files = integration.FILES

    bin_src = repo_dir / files.binary_src
    openrc_src = repo_dir / files.openrc_src

    # Destination paths inside the target rootfs.
    bin_dst    = cfg.mount / files.binary_dst.lstrip("/")
    openrc_dst = cfg.mount / files.openrc_dst.lstrip("/")

    bin_dst.parent.mkdir(parents=True, exist_ok=True)
    openrc_dst.parent.mkdir(parents=True, exist_ok=True)

    # Remove first so any cached/stale binary can't survive.
    for p in (bin_dst, openrc_dst):
        if p.exists():
            p.unlink()

    shutil.copy2(bin_src, bin_dst)
    shutil.copy2(openrc_src, openrc_dst)
    bin_dst.chmod(0o755)
    openrc_dst.chmod(0o755)

    # Verify the in-rootfs binary matches what we just built.
    if _sha256(bin_src) != _sha256(bin_dst):
        err("snowcone binary in rootfs does not match freshly built copy!")
        sys.exit(1)
    ok("snowcone binary verified in rootfs")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 8 — Install snowcone")

    repo_dir = _ensure_snowcone(cfg)
    integration = _load_integration(repo_dir)

    _install_files(cfg, repo_dir, integration)

    # Register the OpenRC service inside the chroot.
    from .common import chroot_mount, chroot_umount, in_chroot
    chroot_mount(cfg)
    try:
        in_chroot(cfg, f"rc-update add snowcone {integration.RUNLEVEL}")
        ok(f"snowcone registered in '{integration.RUNLEVEL}' runlevel")
    finally:
        chroot_umount(cfg)

    _check_cmdline_tokens(cfg, integration)

    ok("snowcone installed")