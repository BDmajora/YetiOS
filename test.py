#!/usr/bin/env python3
"""Create a libvirt KVM VM from yetios.img"""

import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
IMG_PATH = REPO_ROOT / "build" / "yetios.img"
XML_PATH = REPO_ROOT / "yetios-vm.xml"
CONN = "qemu:///system"

if not IMG_PATH.exists():
    print(f"Error: {IMG_PATH} not found", file=sys.stderr)
    sys.exit(1)

xml = XML_PATH.read_text().replace("__IMG_PATH__", str(IMG_PATH))

# Ensure the default network is up (idempotent)
subprocess.run(["virsh", "-c", CONN, "net-start", "default"], capture_output=True)
subprocess.run(["virsh", "-c", CONN, "net-autostart", "default"], capture_output=True)

# Undefine existing VM if present (with nvram cleanup for EFI)
subprocess.run(["virsh", "-c", CONN, "destroy", "yetios"], capture_output=True)
subprocess.run(["virsh", "-c", CONN, "undefine", "yetios", "--nvram"], capture_output=True)

result = subprocess.run(
    ["virsh", "-c", CONN, "define", "/dev/stdin"],
    input=xml, text=True, capture_output=True
)

if result.returncode == 0:
    print("✓ VM 'yetios' defined in qemu:///system — check virt-manager.")
    print("  Start it with: virsh -c qemu:///system start yetios")
else:
    print(f"Error: {result.stderr}", file=sys.stderr)
    sys.exit(1)