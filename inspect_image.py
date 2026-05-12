#!/usr/bin/env python3
"""
inspect_image.py — Diagnose why OVMF isn't finding a bootloader on yetios.img.

Run as root on the host AFTER the build has completed:

    sudo python3 inspect_image.py

This loop-mounts build/yetios.img read-only and reports:
  1. The GPT partition table (looking for the ESP type GUID).
  2. Whether parted's `esp` flag stuck.
  3. The filesystem on each partition.
  4. The contents of \\EFI\\BOOT\\ and \\EFI\\libreldr\\ on the ESP.
  5. Whether the kernel + initramfs are actually present on the ESP.

It does not modify anything. It cleans up loop devices and mounts on exit.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Standard ESP partition type GUID, defined by the UEFI specification.
# OVMF and every other UEFI firmware identifies the ESP by THIS GUID,
# not by parted's "esp" flag name.
ESP_TYPE_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B".lower()

REPO_ROOT = Path(__file__).resolve().parent
IMG = REPO_ROOT / "build" / "yetios.img"

# Track cleanup state so atexit can unwind safely.
_loop_device: "str | None" = None
_mount_points: "list[str]" = []


def run(cmd: list[str], *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, check=check, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def cleanup() -> None:
    for mp in reversed(_mount_points):
        subprocess.run(["umount", mp], check=False, capture_output=True)
        try:
            os.rmdir(mp)
        except OSError:
            pass
    if _loop_device:
        subprocess.run(["losetup", "-d", _loop_device], check=False, capture_output=True)


atexit.register(cleanup)


def hdr(title: str) -> None:
    bar = "=" * 72
    print(f"\n{bar}\n  {title}\n{bar}")


def check_root() -> None:
    if os.geteuid() != 0:
        print("ERROR: run as root (loop devices and FAT mounts require it).")
        sys.exit(1)


def check_image() -> None:
    if not IMG.exists():
        print(f"ERROR: {IMG} does not exist. Build first with sudo ./run.py")
        sys.exit(1)
    print(f"Image: {IMG}")
    print(f"Size:  {IMG.stat().st_size // (1024 ** 2)} MB")


def attach_loop() -> str:
    global _loop_device
    cp = run(["losetup", "--show", "-fP", "-r", str(IMG)])  # -r = read-only
    loop = cp.stdout.strip()
    _loop_device = loop
    print(f"Loop device: {loop}")
    return loop


def gpt_dump(loop: str) -> dict:
    """Use sfdisk to dump the GPT in script form. Returns {part_num: {guid, name, ...}}."""
    cp = run(["sfdisk", "-d", loop])
    out = cp.stdout

    print("\n--- sfdisk -d output ---")
    print(out)

    parts: dict = {}
    for line in out.splitlines():
        # Format: /dev/loop0p1 : start=2048, size=1048576, type=C12A7328-F81F-11D2-BA4B-00A0C93EC93B, ..., name="ESP"
        if ":" not in line or "type=" not in line:
            continue
        dev, _, body = line.partition(":")
        dev = dev.strip()
        try:
            num = int(dev.rstrip("p")[-1]) if "p" in dev else None
            # safer: parse the trailing digits
            num_str = ""
            for c in reversed(dev):
                if c.isdigit():
                    num_str = c + num_str
                else:
                    break
            num = int(num_str) if num_str else None
        except ValueError:
            num = None
        if num is None:
            continue

        fields = {}
        for piece in body.split(","):
            piece = piece.strip()
            if "=" in piece:
                k, v = piece.split("=", 1)
                fields[k.strip()] = v.strip().strip('"')
        parts[num] = {"dev": dev, **fields}
    return parts


def diagnose_gpt(parts: dict) -> "int | None":
    """Find the ESP partition number, or return None and report why."""
    hdr("1. GPT layout & ESP detection")

    if not parts:
        print("FAIL: No GPT partitions found. The partition table is missing or unreadable.")
        return None

    esp_num = None
    for num, info in sorted(parts.items()):
        type_guid = info.get("type", "").lower()
        name = info.get("name", "")
        is_esp = type_guid == ESP_TYPE_GUID
        marker = "  <-- ESP" if is_esp else ""
        print(f"  Partition {num}: name='{name}' type={type_guid}{marker}")
        if is_esp and esp_num is None:
            esp_num = num

    if esp_num is None:
        print()
        print("FAIL: No partition has the ESP type GUID.")
        print(f"      Expected: {ESP_TYPE_GUID}")
        print()
        print("This is almost certainly why OVMF shows 'UEFI Misc Device' and")
        print("nothing else. UEFI firmware identifies the ESP by its partition")
        print("type GUID, not by name or by parted's 'boot' flag.")
        print()
        print("Fix: in Stage 2, ensure `parted set <num> esp on` actually runs")
        print("and is committed. The current code combines mkpart and set in one")
        print("parted invocation, which sometimes silently fails.")
        return None

    print(f"\nOK: ESP is partition {esp_num}.")
    return esp_num


def diagnose_filesystem(loop: str, esp_num: int) -> "str | None":
    hdr("2. ESP filesystem")
    esp_dev = f"{loop}p{esp_num}"
    cp = run(["blkid", "-o", "export", esp_dev], check=False)
    print(f"--- blkid {esp_dev} ---")
    print(cp.stdout or "(no output)")

    fstype = None
    for line in cp.stdout.splitlines():
        if line.startswith("TYPE="):
            fstype = line.split("=", 1)[1]
            break

    if fstype not in ("vfat", "msdos"):
        print(f"FAIL: ESP filesystem is '{fstype}', expected vfat (FAT32).")
        print("      OVMF only reads FAT32/16/12 from the ESP.")
        return None

    print(f"OK: ESP is {fstype}.")
    return esp_dev


def diagnose_contents(esp_dev: str) -> None:
    hdr("3. ESP contents")
    mp = tempfile.mkdtemp(prefix="yetios-esp-")
    _mount_points.append(mp)
    run(["mount", "-o", "ro", esp_dev, mp])

    print(f"Mounted ESP at {mp}\n")

    # Walk the tree
    print("--- tree of ESP ---")
    if shutil.which("tree"):
        cp = run(["tree", "-a", "--noreport", mp], check=False)
        print(cp.stdout)
    else:
        for root, dirs, files in os.walk(mp):
            rel = os.path.relpath(root, mp)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            indent = "  " * depth
            label = "(root)" if rel == "." else os.path.basename(root) + "/"
            print(f"{indent}{label}")
            for f in sorted(files):
                full = os.path.join(root, f)
                size = os.path.getsize(full)
                print(f"{indent}  {f}  ({size} bytes)")

    print("\n--- critical paths ---")
    checks = [
        ("EFI/BOOT/BOOTX64.EFI",       "UEFI fallback path (REQUIRED for blank-NVRAM boot)"),
        ("EFI/libreldr/libreldr.efi",  "canonical libreldr path"),
        ("EFI/libreldr/libreldr.conf", "libreldr config"),
        ("EFI/yetios/vmlinuz.efi",     "kernel"),
        ("EFI/yetios/initramfs.img",   "initramfs"),
    ]
    missing = []
    for rel_path, what in checks:
        full = Path(mp) / rel_path
        # FAT is case-insensitive, but Linux's vfat driver is case-sensitive by default.
        # Try the literal path first, then fall back to a case-insensitive search.
        if full.exists():
            size = full.stat().st_size
            print(f"  OK    {rel_path:40s}  ({size} bytes)  -- {what}")
        else:
            # Case-insensitive lookup
            parts = rel_path.split("/")
            cur = Path(mp)
            found = True
            for part in parts:
                if not cur.exists():
                    found = False
                    break
                children = {c.name.lower(): c.name for c in cur.iterdir()}
                if part.lower() in children:
                    cur = cur / children[part.lower()]
                else:
                    found = False
                    break
            if found:
                size = cur.stat().st_size
                print(f"  OK    {rel_path:40s}  ({size} bytes, case differs)  -- {what}")
            else:
                missing.append(rel_path)
                print(f"  MISS  {rel_path:40s}  -- {what}")

    print()
    if "EFI/BOOT/BOOTX64.EFI" in missing:
        print("FAIL: \\EFI\\BOOT\\BOOTX64.EFI is missing. This is the fallback")
        print("      path that EVERY UEFI firmware checks when no NVRAM entry")
        print("      points to a bootloader. Without it, a freshly-defined VM")
        print("      with empty NVRAM will drop straight to the firmware menu.")
        print("      Fix: ensure Stage 7 copies libreldr.efi to EFI/BOOT/BOOTX64.EFI.")
    elif missing:
        print(f"Note: {len(missing)} non-critical file(s) missing. Boot may still")
        print("      work via the fallback path, but the named entry and kernel")
        print("      hand-off will fail.")
    else:
        print("OK: all critical files present on ESP.")


def main() -> int:
    check_root()
    check_image()

    print("\nThis script is read-only — it will not modify the image.")
    loop = attach_loop()

    parts = gpt_dump(loop)
    esp_num = diagnose_gpt(parts)
    if esp_num is None:
        return 1

    esp_dev = diagnose_filesystem(loop, esp_num)
    if esp_dev is None:
        return 1

    diagnose_contents(esp_dev)

    hdr("Summary")
    print("Paste the entire output of this script back to continue diagnosis.")
    print("In particular, the '1. GPT layout' and '3. ESP contents' sections")
    print("will tell us exactly which of these is broken:")
    print("  - Partition type GUID isn't ESP (firmware ignores the partition)")
    print("  - FAT32 filesystem isn't there (firmware can't read it)")
    print("  - BOOTX64.EFI never landed (firmware finds nothing to load)")
    print("  - Kernel/initramfs never landed (libreldr loads but boot fails)")
    return 0


if __name__ == "__main__":
    sys.exit(main())