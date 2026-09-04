"""Stage 4 - prepare a stock FreeBSD ESP for the first in-VM assemble boot."""

from __future__ import annotations

import shutil
from pathlib import Path

from .core import Config, ok, step_banner


def _replace_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False)


def _require_text(path: Path, needle: str) -> None:
    if needle not in path.read_text(errors="replace"):
        raise RuntimeError(f"{path} does not contain required text: {needle}")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 4 - Bootstrap FreeBSD ESP")

    loader_efi = cfg.rootfs_dir / "boot" / "loader.efi"
    if not loader_efi.is_file():
        raise FileNotFoundError(loader_efi)

    boot_dir = cfg.esp_dir / "EFI" / "BOOT"
    freebsd_dir = cfg.esp_dir / "EFI" / "freebsd"
    boot_dir.mkdir(parents=True, exist_ok=True)
    freebsd_dir.mkdir(parents=True, exist_ok=True)

    _replace_tree(cfg.rootfs_dir / "boot", cfg.esp_dir / "boot")
    _require_text(cfg.esp_dir / "boot" / "loader.conf", 'beastie_disable="YES"')
    _require_text(cfg.esp_dir / "boot" / "loader.conf", 'console="efi"')
    _require_text(cfg.esp_dir / "boot" / "loader.conf", 'vfs.root.mountfrom="ext2fs:/dev/gpt/yetios-root"')

    shutil.copy2(loader_efi, boot_dir / "BOOTX64.EFI")
    shutil.copy2(loader_efi, freebsd_dir / "loader.efi")
    shutil.copy2(loader_efi, cfg.esp_dir / "boot" / "loader.efi")

    ok("staged stock FreeBSD loader for the first in-VM assemble boot")
