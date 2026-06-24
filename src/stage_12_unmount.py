"""Stage 8 — clean unmount, detach loop device, print boot instructions."""

from __future__ import annotations
import os
import subprocess

from .core import Config, losetup_detach, ok, warn, run, step_banner


def _verify_image(cfg: Config) -> None:
    if not cfg.img_path.exists():
        warn("Image file not found!")
        return
    size = cfg.img_path.stat().st_size
    if size < 1 * 1024 ** 3:
        warn(f"Image looks too small ({size // (1024**2)} MB) — build may be incomplete.")
        return

    result = subprocess.run(
        ["parted", "-s", str(cfg.img_path), "print"],
        capture_output=True, text=True
    )
    if "ROOT" not in result.stdout and "ESP" not in result.stdout:
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
    print("Boot it (UEFI, OVMF — adjust path if your distro differs):")
    print(f"  qemu-system-x86_64 -enable-kvm -m 4G -machine q35 \\")
    print(f"      -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \\")
    print(f"      -drive if=pflash,format=raw,file=/tmp/yetios_VARS.fd \\")
    print(f"      -drive file={cfg.img_path},format=raw,if=virtio \\")
    print(f"      -vga virtio -display gtk,gl=on")
    print()
    print("  (Copy /usr/share/OVMF/OVMF_VARS.fd to /tmp/yetios_VARS.fd first")
    print("   so the firmware has a writable NVRAM file for the boot entry.)")
    print()
    print("Or register in virt-manager (recommended — handles OVMF + NVRAM):")
    print(f"  python3 test.py && virsh -c qemu:///system start yetios")
    print()
    print("On first boot, the libreldr-register service writes an NVRAM")
    print("entry called \"LibreLoader (YetiOS)\". After that, the firmware")
    print("boot menu (Esc/F2/F12 depending on firmware) lists LibreLoader")
    print("alongside any other installed operating systems.")