"""Stage 7 — libreldr bootloader installation (BIOS + UEFI).

Installs both backends so the same image boots on legacy BIOS and on
modern UEFI firmware. User sees the same libreldr menu either way.

Boot entries and the two config renderers come from libreldr itself
(libreldr_entries.py inside the cloned repo). This Stage knows nothing
about menu wording or kernel cmdlines — it just runs the renderers
shipped alongside libreldr.efi.
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

SYSLINUX_C32_DIRS = [
    "usr/share/syslinux",
    "usr/lib/syslinux/bios",
]
REQUIRED_C32 = ["menu.c32", "libcom32.c32", "libutil.c32", "ldlinux.c32"]


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

    for fn in ("render_libreldr_conf", "render_syslinux_cfg"):
        if not hasattr(mod, fn):
            err(f"{entries_path} is missing {fn}()")
            sys.exit(1)
    return mod


def _find_syslinux_dir(cfg: Config) -> Path:
    for d in SYSLINUX_C32_DIRS:
        p = cfg.mount / d
        if (p / "menu.c32").is_file():
            return p
    err("Syslinux modules not found in target.")
    err("Stage 6 should have installed sys-boot/syslinux.")
    sys.exit(1)


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
    step_banner("Stage 7 — Install libreldr (BIOS + UEFI)")

    boot = cfg.mount / "boot"
    kernel, initrd = _resolve_kernel_paths(cfg)

    libreldr_dir = _ensure_libreldr(cfg)
    libreldr_entries = _load_libreldr_entries(libreldr_dir)

    # 1. Canonical kernel/initrd names (both backends use these).
    info("Installing kernel and initramfs to /boot...")
    shutil.copy2(kernel, boot / "vmlinuz")
    if initrd:
        shutil.copy2(initrd, boot / "initramfs.img")

    # 2. UEFI backend.
    info("Installing UEFI backend (libreldr.efi)...")
    efi_dir = boot / "EFI"
    (efi_dir / "BOOT").mkdir(parents=True, exist_ok=True)
    (efi_dir / "libreldr").mkdir(parents=True, exist_ok=True)
    (efi_dir / "yetios").mkdir(parents=True, exist_ok=True)

    shutil.copy2(libreldr_dir / "libreldr.efi",
                 efi_dir / "BOOT" / "BOOTX64.EFI")
    (efi_dir / "libreldr" / "libreldr.conf").write_text(
        libreldr_entries.render_libreldr_conf())

    # Linux EFI stub: vmlinuz is itself a PE/COFF EFI app.
    shutil.copy2(boot / "vmlinuz", efi_dir / "yetios" / "vmlinuz.efi")
    if initrd:
        shutil.copy2(boot / "initramfs.img",
                     efi_dir / "yetios" / "initramfs.img")

    ok("UEFI backend installed")

    # 3. BIOS backend.
    info("Installing BIOS backend (syslinux, libreldr-themed)...")
    sys_dir = _find_syslinux_dir(cfg)
    for c32 in REQUIRED_C32:
        src = sys_dir / c32
        if not src.is_file():
            err(f"Missing syslinux module: {src}")
            sys.exit(1)
        shutil.copy2(src, boot / c32)

    (boot / "syslinux.cfg").write_text(
        libreldr_entries.render_syslinux_cfg())

    # syslinux --install writes ldlinux.sys onto the FAT ESP partition.
    esp_part = f"{loop}p2"
    run(["syslinux", "--install", esp_part])

    # MBR boot stub — prefer gptmbr.bin for GPT layouts.
    mbr_candidates = [
        cfg.mount / "usr/share/syslinux/gptmbr.bin",
        cfg.mount / "usr/share/syslinux/mbr.bin",
        cfg.mount / "usr/lib/syslinux/bios/gptmbr.bin",
        cfg.mount / "usr/lib/syslinux/bios/mbr.bin",
    ]
    mbr = next((p for p in mbr_candidates if p.is_file()), None)
    if mbr is None:
        err("No syslinux MBR stub (mbr.bin / gptmbr.bin) found in target.")
        sys.exit(1)
    info(f"Writing MBR stub: {mbr}")
    run(f"dd if={mbr} of={loop} bs=440 count=1 conv=notrunc")

    # Tell the MBR which GPT partition to chain to.
    run(["parted", "-s", loop, "set", "2", "legacy_boot", "on"])

    ok("BIOS backend installed")
    ok("libreldr installed for both BIOS and UEFI")