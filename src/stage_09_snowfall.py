"""Stage 9 — snowfall login manager installation (chroot build).

Clone the snowfall repo on the build host (for network access), copy the
source tree into the chroot, build inside the chroot against the target's
libraries, install the binary + configs, and register the OpenRC service.

WHY CHROOT BUILD: snowfall links against libdrm, libinput, cairo, libpam,
libxkbcommon, and libudev.  Building on the host produces a binary linked
against host library versions that may differ from the rootfs.  Building
inside the chroot guarantees ABI compatibility at runtime.

The DRM master handoff chain is:
  libreldr -> snowcone (boot splash, grabs DRM master)
           -> snowfall (login manager, takes DRM master,
                       which causes snowcone to detect the loss and exit)
           -> user's Wayland compositor (sway, frostedglass, etc.)

The OpenRC service file in the snowfall repo declares `after snowcone`,
so the runlevel-order side of the handoff is handled without extra work.
"""

from __future__ import annotations

import hashlib
import importlib.util
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


SNOWFALL_REPO   = "https://github.com/BDmajora/snowfall.git"
SNOWFALL_BRANCH = "main"

# pkg-config names that must be present inside the chroot for building.
CHROOT_BUILD_PKGS = [
    "libdrm",
    "libinput",
    "cairo",
    "xkbcommon",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _clone_source(cfg: Config) -> Path:
    """Clone snowfall source on the host (network access)."""
    src_dir = cfg.build_dir / "snowfall"

    if src_dir.exists():
        info(f"Removing cached snowfall clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    if not have("git"):
        err("git not found on build host")
        sys.exit(1)

    info(f"Cloning snowfall from {SNOWFALL_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", SNOWFALL_BRANCH,
         SNOWFALL_REPO, str(src_dir)])

    return src_dir


def _load_integration(repo_dir: Path):
    """Import snowfall_integration.py from the cloned repo."""
    p = repo_dir / "snowfall_integration.py"
    if not p.is_file():
        err(f"{p} not found in cloned snowfall repo.")
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("snowfall_integration", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for required in ("FILES", "RUNLEVEL"):
        if not hasattr(mod, required):
            err(f"{p} is missing {required}")
            sys.exit(1)
    return mod


def _build_and_install_in_chroot(cfg: Config, host_src: Path, integration) -> None:
    """Copy source into chroot, build there, install binary + configs."""
    chroot_src = cfg.mount / "tmp" / "snowfall"

    # Clean any leftover from a previous attempt
    if chroot_src.exists():
        shutil.rmtree(chroot_src)

    info("Copying snowfall source into chroot ...")
    shutil.copytree(host_src, chroot_src)

    chroot_mount(cfg)
    try:
        # Verify build toolchain
        info("Checking chroot build toolchain ...")
        for tool in ("gcc", "make", "pkg-config"):
            cp = in_chroot(cfg, f"command -v {tool}", check=False)
            if cp.returncode != 0:
                err(f"Missing build tool in chroot: {tool}")
                err("Ensure build toolchain packages are in YETI_PACKAGE_LIST.")
                sys.exit(1)

        # Verify build deps
        info("Checking chroot build dependencies ...")
        missing_pc = []
        for pkg in CHROOT_BUILD_PKGS:
            cp = in_chroot(cfg, f"pkg-config --exists {pkg}", check=False)
            if cp.returncode != 0:
                missing_pc.append(pkg)
        if missing_pc:
            err(f"Missing pkg-config modules in chroot: {', '.join(missing_pc)}")
            err("Ensure dev headers are installed in the rootfs.")
            sys.exit(1)

        # PAM doesn't ship a .pc file — check the header inside the chroot
        cp = in_chroot(
            cfg,
            "test -f /usr/include/security/pam_appl.h || "
            "test -f /usr/include/pam/pam_appl.h",
            check=False,
        )
        if cp.returncode != 0:
            err("PAM development headers not found in chroot.")
            err("Ensure sys-libs/pam is in YETI_PACKAGE_LIST.")
            sys.exit(1)

        # Build
        info("Building snowfall inside chroot ...")
        in_chroot(cfg, "make -C /tmp/snowfall clean 2>/dev/null; make -C /tmp/snowfall")

        # Verify binary was produced
        bin_chroot = chroot_src / "snowfall"
        if not bin_chroot.is_file():
            err("Build completed but snowfall binary was not produced.")
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
            err("snowfall binary copy failed integrity check!")
            sys.exit(1)
        ok("snowfall binary built in chroot, installed and verified")

        # OpenRC init script
        openrc_src = chroot_src / files.openrc_src
        openrc_dst = cfg.mount / files.openrc_dst.lstrip("/")
        openrc_dst.parent.mkdir(parents=True, exist_ok=True)
        if openrc_dst.exists():
            openrc_dst.unlink()
        shutil.copy2(openrc_src, openrc_dst)
        openrc_dst.chmod(0o755)

        # PAM config
        pam_src = chroot_src / files.pam_src
        pam_dst = cfg.mount / files.pam_dst.lstrip("/")
        pam_dst.parent.mkdir(parents=True, exist_ok=True)
        if pam_dst.exists():
            pam_dst.unlink()
        shutil.copy2(pam_src, pam_dst)
        pam_dst.chmod(0o644)

        # Register OpenRC service
        in_chroot(cfg, f"rc-update add snowfall {integration.RUNLEVEL}")
        ok(f"snowfall registered in '{integration.RUNLEVEL}' runlevel")

    finally:
        chroot_umount(cfg)
        # Clean up source from chroot /tmp
        if chroot_src.exists():
            shutil.rmtree(chroot_src)


def _ensure_sessions_dir(cfg: Config) -> None:
    """Make sure /usr/share/wayland-sessions/ exists.

    Compositors installed via emerge (sway, labwc, etc.) will drop their
    .desktop files here. Snowfall reads from this directory to populate
    the session picker, so the directory must exist even if empty.
    """
    sessions_dir = cfg.mount / "usr/share/wayland-sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ok(f"ensured {sessions_dir.relative_to(cfg.mount)} exists")


def _runtime_deps_present(cfg: Config) -> None:
    """Warn (don't fail) if runtime shared libraries aren't in the rootfs.

    Since we now build inside the chroot, the binary is guaranteed to
    link against whatever's present — but if a library is missing entirely,
    the build would have failed already. This check is a safety net for
    libraries that might be dlopened at runtime rather than linked.
    """
    expected = [
        "lib64/libdrm.so.2",
        "usr/lib64/libdrm.so.2",
        "lib64/libcairo.so.2",
        "usr/lib64/libcairo.so.2",
        "lib64/libpam.so.0",
        "usr/lib64/libpam.so.0",
        "lib64/libxkbcommon.so.0",
        "usr/lib64/libxkbcommon.so.0",
        "lib64/libinput.so.10",
        "usr/lib64/libinput.so.10",
        "lib64/libudev.so.1",
        "usr/lib64/libudev.so.1",
    ]
    # Group by library; satisfied if any candidate path exists.
    groups: dict[str, list[Path]] = {}
    for rel in expected:
        soname = Path(rel).name
        groups.setdefault(soname, []).append(cfg.mount / rel)

    missing = [name for name, paths in groups.items()
               if not any(p.exists() for p in paths)]
    if missing:
        warn("snowfall runtime libraries not yet present in rootfs:")
        for m in missing:
            warn(f"  {m}")
        warn("Add the providing packages to YETI_PACKAGE_LIST in "
             "src/templates.py and re-run stage 06.")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 9 — Install snowfall (chroot build)")

    repo_dir = _clone_source(cfg)
    integration = _load_integration(repo_dir)

    _build_and_install_in_chroot(cfg, repo_dir, integration)
    _ensure_sessions_dir(cfg)
    _runtime_deps_present(cfg)

    ok("snowfall installed")