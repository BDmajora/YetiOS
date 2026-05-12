""""Stage 8 — clean unmount, detach loop device, print boot instructions."""

from __future__ import annotations
import os
import subprocess

from .common import Config, losetup_detach, ok, warn, run, step_banner


def _verify_image(cfg: Config) -> None:
    """Basic sanity checks on the finished image before declaring success."""
    # Check image exists and is non-trivially sized (>= 1 GB)
    if not cfg.img_path.exists():
        warn("Image file not found!")
        return
    size = cfg.img_path.stat().st_size
    if size < 1 * 1024 ** 3:
        warn(f"Image looks too small ({size // (1024**2)} MB) — build may be incomplete.")
        return

    # Check partitions are visible
    result = subprocess.run(
        ["parted", "-s", str(cfg.img_path), "print"],
        capture_output=True, text=True
    )
    if "yetios-boot" not in result.stdout and "yetios-root" not in result.stdout:
        warn("Expected partition labels not found — image may not be bootable.")
        return

    ok(f"Image looks good: {size // (1024**2)} MB, partitions present.")


def run_stage(cfg: Config, loop: "str | None") -> None:
    step_banner("Stage 8 — Unmount & detach")

    for sub in ["boot", ""]:
        target = cfg.mount / sub if sub else cfg.mount
        if os.path.ismount(target):
            run(["umount", str(target)], check=False)

    if loop:
        losetup_detach(loop)

    _verify_image(cfg)

    ok(f"YetiOS image: {cfg.img_path}")
    print()
    print("Boot it:")
    print(f"  qemu-system-x86_64 -enable-kvm -m 4G \\")
    print(f"      -drive file={cfg.img_path},format=raw \\")
    print(f"      -vga virtio -display gtk,gl=on")
    print()
    print("Or register in virt-manager:")
    print(f"  python3 test.py && virsh -c qemu:///system start yetios")