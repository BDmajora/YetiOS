"""Stage 7 - write the YetiOS FreeBSD image manifest."""

from __future__ import annotations

import datetime as _dt

from .core import Config, ok, step_banner


def _boot_command(cfg: Config) -> str:
    return (
        "qemu-system-x86_64 -m 8192 -smp 24 "
        "-bios /usr/share/OVMF/OVMF_CODE.fd "
        f"-drive file={cfg.img_path},format=raw,if=virtio "
        "-netdev user,id=net0 "
        "-device virtio-net-pci,netdev=net0"
    )


def run_stage(cfg: Config) -> None:
    step_banner("Stage 7 - Write YetiOS image manifest")

    if not cfg.img_path.is_file():
        raise FileNotFoundError(cfg.img_path)

    source_record = (
        cfg.source_record_path.read_text().strip()
        if cfg.source_record_path.exists()
        else "not recorded"
    )
    generated = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    cfg.manifest_path.write_text(
        f"""YetiOS FreeBSD image
Generated: {generated}

Image:
  {cfg.img_path}

FreeBSD source:
  release: {cfg.release}
  arch: {cfg.arch}
  mirror: {cfg.release_dir_url}
  verified sets:
{source_record}

YetiOS identity:
  hostname: {cfg.hostname}
  user: {cfg.yeti_user}
  default alpha password: {cfg.yeti_password}
  root password: {cfg.yeti_password}
  timezone: {cfg.timezone}

Package management:
  No pkg/ports packages are installed by the Artix/Linux host pipeline.
  The YetiOS alpha sudo helper permits pkg commands from the default admin user:
    sudo pkg update
  The in-VM assembler uses:
    {cfg.desktop_packages_file}

In-VM assembler:
  Run after first boot from the yetios account:
    ./assemble
  Staged assembler:
    /usr/libexec/yetios/assemble
  Staged source root:
    /usr/src/yetios/sources
  libreldr source: {cfg.libreldr_dir}
  SnowCone source: {cfg.snowcone_dir}
  FrostedWeb source: {cfg.frostedweb_dir}
  Moonshine source: {cfg.moonshine_dir}
  SnowFall source: {cfg.snowfall_dir}
  Moonshine configuration: native Wine Wayland driver (--with-wayland)
  SnowFall note: skipped until its FreeBSD backend lands

Boot:
  UEFI entry: EFI/BOOT/BOOTX64.EFI
  First boot loader: stock FreeBSD loader.efi
  After ./assemble: libreldr replaces EFI/BOOT/BOOTX64.EFI and chainloads EFI/freebsd/loader.efi
  After ./assemble: SnowCone is built inside FreeBSD and enabled for the loading screen
  Root filesystem: conservative ext2, populated with Linux host tools for this alpha path
  Root ext2 profile: no optional ext feature flags; xattr/ACL defaults cleared; e2fsck-cleaned
  Root fsck: disabled because FreeBSD base does not ship fsck_ext2fs
  Root runtime policy: root stays read-only after first-boot account setup
  Persistent FreeBSD local storage: /dev/gpt/yetios-local mounted at /usr/local
  Writable runtime paths: /tmp, /var, and /home are memory-backed

License boundary:
  The installed core system is FreeBSD from official release sets.
  No pkg/ports packages are installed by the Artix/Linux host pipeline.
  YetiOS-owned code staged for in-VM build is MIT licensed where owned by YetiOS.
  Moonshine/Wine remains a separate LGPL compliance boundary.
  Desktop pkg/ports candidates require license review before commercial use.

Libvirt access:
  Stage 6 grants the system QEMU service user execute permission on the project
  path and read/write permission on the image with POSIX ACLs.

Boot command:
  {_boot_command(cfg)}
""")

    ok(f"wrote {cfg.manifest_path}")
    print()
    print("Boot command:")
    print(f"  {_boot_command(cfg)}")
