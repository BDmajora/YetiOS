"""Stage 7 — bootloader installation.

The gentoo-kernel-bin package installs a kernel as /boot/vmlinuz-<ver>
plus a matching initramfs. We:

  1. Symlink /boot/vmlinuz and /boot/initramfs.img to the latest ones
     (extlinux.conf references those generic names).
  2. Write /boot/extlinux.conf.
  3. Install extlinux's stage-1.5 onto the /boot partition.
  4. dd the MBR boot stub from syslinux (now installed in the target by
     stage 7) onto the front of the image so BIOS hands off to extlinux.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .common import (
    Config,
    chroot_mount,
    chroot_umount,
    err,
    in_chroot,
    ok,
    run,
    step_banner,
)
from .templates import EXTLINUX_CONF


# Look for syslinux's MBR boot stub in the target (installed by stage 7).
TARGET_MBR_CANDIDATES = [
    "usr/share/syslinux/mbr.bin",
    "usr/lib/syslinux/bios/mbr.bin",
    "usr/lib/syslinux/mbr/mbr.bin",
]


def run_stage(cfg: Config, loop: str) -> None:
    step_banner("Stage 7 — Install extlinux bootloader")

    # 1. Symlink generic kernel/initramfs names. Use a chroot one-liner so
    # the symlink targets are correct relative to the boot partition.
    chroot_mount(cfg)
    try:
        in_chroot(cfg, r"""
set -e
cd /boot
# Pick the highest-versioned vmlinuz / initramfs the kernel-bin package put down.
KERNEL=$(ls vmlinuz-* 2>/dev/null | sort -V | tail -n1)
INITRD=$(ls initramfs-*.img 2>/dev/null | sort -V | tail -n1)
[ -n "$KERNEL" ] || { echo 'no kernel found in /boot' >&2; exit 1; }
ln -sf "$KERNEL" vmlinuz
[ -n "$INITRD" ] && ln -sf "$INITRD" initramfs.img || true
ls -l /boot
""")
    finally:
        chroot_umount(cfg)

    # 2. extlinux config on the boot partition
    (cfg.mount / "boot/extlinux.conf").write_text(EXTLINUX_CONF)

    # 3. Install extlinux's loader files
    run(["extlinux", "--install", str(cfg.mount / "boot")])

    # 4. MBR boot stub — prefer the one shipped by syslinux *inside* the target
    #    so the version matches extlinux. Fall back to host paths.
    mbr_candidates = [cfg.mount / p for p in TARGET_MBR_CANDIDATES] + [
        Path("/usr/lib/syslinux/mbr/mbr.bin"),
        Path("/usr/share/syslinux/mbr.bin"),
    ]
    mbr = next((p for p in mbr_candidates if p.is_file()), None)
    if mbr is None:
        err("Couldn't find mbr.bin in target or host.")
        err("Stage 7 should have installed sys-boot/syslinux into the target.")
        sys.exit(1)
    run(f"dd if={mbr} of={loop} bs=440 count=1 conv=notrunc")

    # 5. Belt-and-suspenders: ensure partition 1 is bootable
    run(["parted", "-s", loop, "set", "1", "boot", "on"])

    ok("bootloader installed")