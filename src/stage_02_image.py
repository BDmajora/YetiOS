"""Stages 2 — disk image creation, partitioning, formatting, mounting.

UEFI-only GPT layout:
  p1   512 MiB   ESP (FAT32)          (libreldr.efi + kernel/initramfs)
  p2   rest      ext4                 (yetios-root)

The ESP is mounted at /boot inside the guest so kernel/initramfs files
produced by `installkernel` land where libreldr expects them.
"""

from __future__ import annotations

import os

from .common import (
    Config,
    losetup_attach,
    loop_for,
    ok,
    run,
    step_banner,
    warn,
    info,
)


def run_create(cfg: Config) -> None:
    step_banner("Stage 2 — Create disk image (GPT, UEFI-only)")
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    if cfg.img_path.exists():
        warn(f"{cfg.img_path} exists; reusing. Pass --restart to wipe markers.")
    else:
        run(["qemu-img", "create", "-f", "raw", str(cfg.img_path),
             f"{cfg.img_size_gb}G"])

    run([
        "parted", "-s", str(cfg.img_path),
        "mklabel", "gpt",
        "mkpart", "ESP", "fat32", "1MiB", "513MiB",
        "set", "1", "esp", "on",
        "mkpart", "ROOT", "ext4", "513MiB", "100%",
    ])

    ok("partition table written")


def run_mount(cfg: Config) -> str:
    step_banner("Stage 3 — Format & mount")

    loop = loop_for(cfg.img_path) or losetup_attach(cfg.img_path)
    info(f"loop device: {loop}")

    esp_part  = f"{loop}p1"
    root_part = f"{loop}p2"

    def has_fs(part: str) -> bool:
        cp = run(["blkid", "-o", "value", "-s", "TYPE", part],
                 check=False, capture=True)
        return bool(cp.stdout.strip())

    if not has_fs(root_part):
        run(["mkfs.ext4", "-L", "yetios-root", root_part])
    if not has_fs(esp_part):
        run(["mkfs.vfat", "-F", "32", "-n", "YETIOS-ESP", esp_part])

    cfg.mount.mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(cfg.mount):
        run(["mount", root_part, str(cfg.mount)])

    # ESP mounted at /boot — UEFI firmware looks for \EFI\BOOT\BOOTX64.EFI here.
    (cfg.mount / "boot").mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(cfg.mount / "boot"):
        run(["mount", esp_part, str(cfg.mount / "boot")])

    ok(f"target root = {cfg.mount}")
    return loop