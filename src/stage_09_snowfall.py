"""Stage 9 — snowfall login manager installation.

Mirrors stage_08_splash.py's pattern: clone the sister project, build it
on the build host, copy binaries and configs into the rootfs, register
the OpenRC service.

Snowfall differs from snowcone in two ways:
  - it has a PAM config file in addition to the binary + openrc init
  - it has real build dependencies (libdrm, libinput, cairo, libpam,
    libxkbcommon, libudev) that must be present on the BUILD HOST.

The DRM master handoff chain is:
  libreldr -> snowcone (boot splash, grabs DRM master)
           -> snowfall (login manager, takes DRM master,
                       which causes snowcone to detect the loss and exit)
           -> user's Wayland compositor (sway, etc.)

The OpenRC service file in the snowfall repo already declares
`after snowcone`, so the runlevel-order side of the handoff is handled
without any extra work here.
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

# pkg-config names we expect to find on the BUILD HOST. If any are
# missing we fail early with a helpful apt-line, the same way
# stage_08_splash hints at linux-libc-dev.
REQUIRED_PKGCONFIG = [
    "libdrm",
    "libinput",
    "cairo",
    "xkbcommon",
]

# apt-line for Debian/Ubuntu build hosts. Adjusted for the actual
# package names (libpam doesn't have a .pc file — we check it via
# pam_appl.h existence further down).
APT_HINT = (
    "apt install build-essential pkg-config "
    "libdrm-dev libinput-dev libcairo2-dev libpam0g-dev "
    "libxkbcommon-dev libudev-dev"
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_build_host() -> None:
    """Verify the build host has everything needed to compile snowfall."""
    missing_tools = [t for t in ("git", "make", "cc", "pkg-config") if not have(t)]
    if missing_tools:
        err(f"Missing build tools on host: {', '.join(missing_tools)}")
        err(f"Install with: {APT_HINT}")
        sys.exit(1)

    missing_pc = []
    for name in REQUIRED_PKGCONFIG:
        cp = run(["pkg-config", "--exists", name], check=False)
        if cp.returncode != 0:
            missing_pc.append(name)
    if missing_pc:
        err(f"Missing pkg-config modules on host: {', '.join(missing_pc)}")
        err(f"Install with: {APT_HINT}")
        sys.exit(1)

    # PAM doesn't ship a .pc file on most distros — check the header.
    pam_header_candidates = [
        Path("/usr/include/security/pam_appl.h"),
        Path("/usr/include/pam/pam_appl.h"),
    ]
    if not any(p.is_file() for p in pam_header_candidates):
        err("PAM development headers not found "
            "(/usr/include/security/pam_appl.h).")
        err(f"Install with: {APT_HINT}")
        sys.exit(1)


def _ensure_snowfall(cfg: Config) -> Path:
    """Wipe cached clone, re-clone, build, return the repo dir."""
    src_dir = cfg.build_dir / "snowfall"
    bin_path = src_dir / "snowfall"

    if src_dir.exists():
        info(f"Removing cached snowfall clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    info(f"Cloning snowfall from {SNOWFALL_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", SNOWFALL_BRANCH,
         SNOWFALL_REPO, str(src_dir)])

    info("Building snowfall ...")
    run(["make", "-C", str(src_dir)])

    if not bin_path.is_file():
        err(f"Build finished but {bin_path} was not produced.")
        err("Check that you have all required development headers:")
        err(f"  {APT_HINT}")
        sys.exit(1)

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


def _install_files(cfg: Config, repo_dir: Path, integration) -> None:
    files = integration.FILES

    bin_src    = repo_dir / files.binary_src
    openrc_src = repo_dir / files.openrc_src
    pam_src    = repo_dir / files.pam_src

    # Destinations inside the target rootfs.
    bin_dst    = cfg.mount / files.binary_dst.lstrip("/")
    openrc_dst = cfg.mount / files.openrc_dst.lstrip("/")
    pam_dst    = cfg.mount / files.pam_dst.lstrip("/")

    for dst in (bin_dst, openrc_dst, pam_dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()

    shutil.copy2(bin_src,    bin_dst)
    shutil.copy2(openrc_src, openrc_dst)
    shutil.copy2(pam_src,    pam_dst)

    bin_dst.chmod(0o755)
    openrc_dst.chmod(0o755)
    pam_dst.chmod(0o644)

    if _sha256(bin_src) != _sha256(bin_dst):
        err("snowfall binary in rootfs does not match freshly built copy!")
        sys.exit(1)
    ok("snowfall binary verified in rootfs")


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

    Snowfall links against libdrm/libinput/cairo/libpam/libxkbcommon/libudev.
    On Gentoo these come from media-libs/mesa indirectly plus the explicit
    package list. Missing libs would cause snowfall to fail at startup;
    we flag it now so the user can adjust YETI_PACKAGE_LIST.
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
    step_banner("Stage 9 — Install snowfall")

    _check_build_host()

    repo_dir = _ensure_snowfall(cfg)
    integration = _load_integration(repo_dir)

    _install_files(cfg, repo_dir, integration)
    _ensure_sessions_dir(cfg)

    # Register the OpenRC service inside the chroot. The snowfall.openrc
    # file declares `after snowcone`, so the runlevel order handles the
    # handoff at boot.
    chroot_mount(cfg)
    try:
        in_chroot(cfg, f"rc-update add snowfall {integration.RUNLEVEL}")
        ok(f"snowfall registered in '{integration.RUNLEVEL}' runlevel")
    finally:
        chroot_umount(cfg)

    _runtime_deps_present(cfg)

    ok("snowfall installed")