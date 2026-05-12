"""Stages 2 — disk image creation, partitioning, formatting, mounting."""

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
    """Stage 2: create the sparse image file and write the partition table."""
    step_banner("Stage 2 — Create disk image")
    cfg.build_dir.mkdir(parents=True, exist_ok=True)

    if cfg.img_path.exists():
        warn(f"{cfg.img_path} exists; reusing. Pass --restart to wipe markers.")
    else:
        run(["qemu-img", "create", "-f", "raw", str(cfg.img_path),
             f"{cfg.img_size_gb}G"])

    # MBR layout:
    #   p1  ext2   256 MiB   /boot
    #   p2  ext4   rest      /
    run(["parted", "-s", str(cfg.img_path),
         "mklabel", "msdos",
         "mkpart", "primary", "ext2", "1MiB", "257MiB",
         "set", "1", "boot", "on",
         "mkpart", "primary", "ext4", "257MiB", "100%"])

    ok("partition table written")


def run_mount(cfg: Config) -> str:
    """Stage 3: loop-attach, format if blank, mount root + /boot. Returns loop dev."""
    step_banner("Stage 3 — Format & mount")

    loop = loop_for(cfg.img_path) or losetup_attach(cfg.img_path)
    info(f"loop device: {loop}")

    boot_part = f"{loop}p1"
    root_part = f"{loop}p2"

    # blkid's exit code is unreliable on unformatted partitions on some
    # kernels; probe for an actual filesystem TYPE string instead.
    def has_fs(part: str) -> bool:
        cp = run(["blkid", "-o", "value", "-s", "TYPE", part],
                 check=False, capture=True)
        return bool(cp.stdout.strip())

    if not has_fs(root_part):
        run(["mkfs.ext4", "-L", "yetios-root", root_part])
    if not has_fs(boot_part):
        run(["mkfs.ext2", "-L", "yetios-boot", boot_part])

    cfg.mount.mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(cfg.mount):
        run(["mount", root_part, str(cfg.mount)])
    (cfg.mount / "boot").mkdir(parents=True, exist_ok=True)
    if not os.path.ismount(cfg.mount / "boot"):
        run(["mount", boot_part, str(cfg.mount / "boot")])

    ok(f"target root = {cfg.mount}")
    return loop