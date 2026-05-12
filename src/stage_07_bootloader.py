"""Stage 7 — libreldr bootloader installation (UEFI only).

Lays the bootloader onto the ESP. There are two locations:

  1. `\\EFI\\BOOT\\BOOTX64.EFI` — the UEFI "removable media" fallback path.
     Every UEFI firmware will try this when no NVRAM entry matches, which
     is exactly the situation in a freshly-defined VM: the VM's NVRAM is
     blank, so falling back to this path is what lets the very first boot
     succeed without any host-side efibootmgr trickery.

  2. `\\EFI\\libreldr\\libreldr.efi` — the canonical install location. The
     `libreldr-register` OpenRC service (installed in stage 6) runs once
     inside the guest on first boot and points an NVRAM entry called
     "LibreLoader (YetiOS)" at this path. After that, libreldr appears in
     the firmware boot menu next to any other installed OS.

Boot entries and the config renderer come from libreldr itself
(libreldr_entries.py inside the cloned repo).
"""

from __future__ import annotations

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


LIBRELDR_REPO   = "https://github.com/BDmajora/libreldr.git"
LIBRELDR_BRANCH = "main"


def _ensure_libreldr(cfg: Config) -> Path:
    """Clone libreldr if missing, build libreldr.efi, return the repo dir."""
    src_dir  = cfg.build_dir / "libreldr"
    efi_path = src_dir / "libreldr.efi"

    if not src_dir.is_dir():
        info(f"Cloning libreldr from {LIBRELDR_REPO} ...")
        run(["git", "clone", "--depth", "1", "-b", LIBRELDR_BRANCH,
             LIBRELDR_REPO, str(src_dir)])
    else:
        info("libreldr clone present; pulling latest ...")
        run(["git", "-C", str(src_dir), "pull", "--ff-only"], check=False)

    if not efi_path.is_file():
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


def run_stage(cfg: Config, loop: str) -> None:
    step_banner("Stage 7 — Install libreldr (UEFI)")

    boot = cfg.mount / "boot"
    kernel, initrd = _resolve_kernel_paths(cfg)

    libreldr_dir = _ensure_libreldr(cfg)
    libreldr_entries = _load_libreldr_entries(libreldr_dir)

    # Canonical kernel/initramfs names on the ESP. We copy under \EFI\yetios\
    # so the config in libreldr.conf can point at stable, predictable paths
    # regardless of which kernel version Gentoo installed.
    info("Installing kernel and initramfs to ESP...")
    efi_dir = boot / "EFI"
    (efi_dir / "BOOT").mkdir(parents=True, exist_ok=True)
    (efi_dir / "libreldr").mkdir(parents=True, exist_ok=True)
    (efi_dir / "yetios").mkdir(parents=True, exist_ok=True)

    # The Linux EFI stub means vmlinuz is itself a PE/COFF EFI app, and
    # libreldr loads it via BS->LoadImage / StartImage. No separate stub
    # or shim needed.
    shutil.copy2(kernel, efi_dir / "yetios" / "vmlinuz.efi")
    if initrd:
        shutil.copy2(initrd, efi_dir / "yetios" / "initramfs.img")

    # libreldr.efi in two places:
    #   1. \EFI\BOOT\BOOTX64.EFI — fallback / removable-media path; lets the
    #      VM boot on first power-on before NVRAM has an entry.
    #   2. \EFI\libreldr\libreldr.efi — canonical path; the first-boot
    #      service registers this with efibootmgr as "LibreLoader (YetiOS)".
    info("Installing libreldr.efi to fallback and canonical paths...")
    shutil.copy2(libreldr_dir / "libreldr.efi",
                 efi_dir / "BOOT" / "BOOTX64.EFI")
    shutil.copy2(libreldr_dir / "libreldr.efi",
                 efi_dir / "libreldr" / "libreldr.efi")

    # libreldr config
    (efi_dir / "libreldr" / "libreldr.conf").write_text(
        libreldr_entries.render_libreldr_conf())

    ok("libreldr installed (UEFI fallback path + canonical path)")