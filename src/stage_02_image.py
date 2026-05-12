"""Stages 2 — disk image creation, partitioning, formatting, mounting.

GPT layout supporting both BIOS and UEFI boot:
  p1   1 MiB     BIOS Boot Partition  (syslinux core; no filesystem)
  p2   512 MiB   ESP (FAT32)          (libreldr.efi + kernel for both paths)
  p3   rest      ext4                 (yetios-root)

The ESP doubles as /boot for the BIOS kernel/initrd, so one partition
serves both firmwares.
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
    step_banner("Stage 2 — Create disk image (GPT, hybrid BIOS+UEFI)")
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    if cfg.img_path.exists():
        warn(f"{cfg.img_path} exists; reusing. Pass --restart to wipe markers.")
    else:
        run(["qemu-img", "create", "-f", "raw", str(cfg.img_path),
             f"{cfg.img_size_gb}G"])

    run([
        "parted", "-s", str(cfg.img_path),
        "mklabel", "gpt",
        "mkpart", "BIOS-BOOT", "1MiB", "2MiB",
        "set", "1", "bios_grub", "on",
        "mkpart", "ESP", "fat32", "2MiB", "514MiB",
        "set", "2", "esp", "on",
        "mkpart", "ROOT", "ext4", "514MiB", "100%",
    ])

    ok("partition table written")


def run_mount(cfg: Config) -> str:
    step_banner("Stage 3 — Format & mount")

    loop = loop_for(cfg.img_path) or losetup_attach(cfg.img_path)
    info(f"loop device: {loop}")

    esp_part  = f"{loop}p2"
    root_part = f"{loop}p3"

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

    # ESP mounted at /boot — same FAT partition serves BIOS and UEFI.
    (cfg.mount / "boot").mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(cfg.mount / "boot"):
        run(["mount", esp_part, str(cfg.mount / "boot")])

    ok(f"target root = {cfg.mount}")
    return loop