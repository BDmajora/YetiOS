"""Stage 7 — libreldr bootloader installation (UEFI only).

Always wipes the cached libreldr clone and rebuilds from scratch so that
upstream changes to libreldr never get masked by a stale binary. Then
verifies that the .efi placed on the ESP is the freshly built one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path

from .core import (
    Config,
    err,
    info,
    ok,
    run,
    step_banner,
    warn,
)


LIBRELDR_REPO   = "https://github.com/BDmajora/libreldr.git"
LIBRELDR_BRANCH = "main"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_libreldr(cfg: Config) -> Path:
    """Wipe any cached clone, re-clone, build, return the repo dir.

    Why wipe every time: the previous behavior of `git pull --ff-only`
    on a cached clone could silently skip rebuilds when permissions or
    object cache got into a bad state, leaving a stale libreldr.efi.
    Building from scratch is cheap (~2s) and guarantees correctness.
    """
    src_dir  = cfg.build_dir / "libreldr"
    efi_path = src_dir / "libreldr.efi"

    if src_dir.exists():
        info(f"Removing cached libreldr clone at {src_dir} ...")
        shutil.rmtree(src_dir)
        if src_dir.exists():
            err(f"Failed to remove {src_dir}. Check permissions.")
            sys.exit(1)

    info(f"Cloning libreldr from {LIBRELDR_REPO} ...")
    run(["git", "clone", "--depth", "1", "-b", LIBRELDR_BRANCH,
         LIBRELDR_REPO, str(src_dir)])

    info("Building libreldr.efi ...")
    run(["make", "-C", str(src_dir)])

    if not efi_path.is_file():
        err(f"Build finished but {efi_path} was not produced.")
        err("Check that gnu-efi is installed on the host:")
        err("  apt install gnu-efi build-essential binutils")
        sys.exit(1)

    return src_dir


def _load_libreldr_entries(repo_dir: Path):
    """Import libreldr_entries.py from the cloned libreldr repo."""
    candidates = [
        repo_dir / "libreldr_entries.py",
        repo_dir / "integration" / "libreldr_entries.py",
    ]
    entries_path = next((p for p in candidates if p.is_file()), None)
    if entries_path is None:
        err("libreldr_entries.py not found in cloned libreldr repo.")
        err(f"Looked under: {repo_dir}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location(
        "libreldr_entries", entries_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "render_libreldr_conf"):
        err(f"{entries_path} is missing render_libreldr_conf()")
        sys.exit(1)
    return mod


def _resolve_kernel_paths(cfg: Config) -> tuple[Path, Path | None]:
    boot = cfg.mount / "boot"
    kernels = sorted(boot.glob("vmlinuz-*"))
    initrds = sorted(boot.glob("initramfs-*.img"))
    if not kernels:
        err("No vmlinuz-* found in /boot.")
        sys.exit(1)
    kernel = kernels[-1]
    initrd = initrds[-1] if initrds else None
    if not initrd:
        warn("No initramfs-*.img found. Boot may fail at root mount.")
    return kernel, initrd


def _verify_esp_matches_build(src_efi: Path, esp_paths: list[Path]) -> None:
    """Hard-fail if the .efi on the ESP doesn't match the freshly built one."""
    src_hash = _sha256(src_efi)
    info(f"freshly built libreldr.efi sha256: {src_hash[:16]}...")
    for p in esp_paths:
        if not p.is_file():
            err(f"Expected file missing on ESP: {p}")
            sys.exit(1)
        if _sha256(p) != src_hash:
            err(f"ESP copy {p} does not match freshly built binary!")
            err("Something corrupted the copy between build and install.")
            sys.exit(1)
    ok("ESP copies verified against freshly built binary")


def run_stage(cfg: Config, loop: str) -> None:
    step_banner("Stage 7 — Install libreldr (UEFI)")

    boot = cfg.mount / "boot"
    kernel, initrd = _resolve_kernel_paths(cfg)

    libreldr_dir = _ensure_libreldr(cfg)
    libreldr_entries = _load_libreldr_entries(libreldr_dir)
    src_efi = libreldr_dir / "libreldr.efi"

    # Canonical kernel/initramfs names on the ESP.
    info("Installing kernel and initramfs to ESP...")
    efi_dir = boot / "EFI"
    (efi_dir / "BOOT").mkdir(parents=True, exist_ok=True)
    (efi_dir / "libreldr").mkdir(parents=True, exist_ok=True)
    (efi_dir / "yetios").mkdir(parents=True, exist_ok=True)

    shutil.copy2(kernel, efi_dir / "yetios" / "vmlinuz.efi")
    if initrd:
        shutil.copy2(initrd, efi_dir / "yetios" / "initramfs.img")

    # Two copies of libreldr.efi (fallback + canonical paths).
    info("Installing libreldr.efi to fallback and canonical paths...")
    bootx64 = efi_dir / "BOOT" / "BOOTX64.EFI"
    canonical = efi_dir / "libreldr" / "libreldr.efi"

    # Remove first so we can't accidentally end up reading a stale copy
    # from any kind of caching layer.
    for p in (bootx64, canonical):
        if p.exists():
            p.unlink()

    shutil.copy2(src_efi, bootx64)
    shutil.copy2(src_efi, canonical)

    (efi_dir / "libreldr" / "libreldr.conf").write_text(
        libreldr_entries.render_libreldr_conf())

    _verify_esp_matches_build(src_efi, [bootx64, canonical])
    ok("libreldr installed (UEFI fallback path + canonical path)")