"""Stage 5 - assemble build/yetios.img with Linux host image tools."""

from __future__ import annotations

import math
import os
import shutil
from pathlib import Path

from .core import Config, info, ok, parse_size_to_bytes, run, step_banner, warn


def _mib(size: str) -> int:
    return math.ceil(parse_size_to_bytes(size) / (1024 ** 2))


def _copy_tree_contents(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _loop_for(img: Path) -> str | None:
    cp = run(["losetup", "-j", str(img)], capture=True, check=False)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    return cp.stdout.split(":", 1)[0]


def _losetup_attach(img: Path) -> str:
    cp = run(["losetup", "--show", "-fP", str(img)], capture=True)
    return cp.stdout.strip()


def _losetup_detach(loop: str) -> None:
    run(["losetup", "-d", loop], check=False)


def _partition_path(loop: str, index: int) -> str:
    return f"{loop}p{index}"


def _unmount(path: Path) -> None:
    if os.path.ismount(path):
        run(["umount", str(path)], check=False)


def _require_files(label: str, paths: list[Path]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        names = "\n  ".join(str(path) for path in missing)
        raise RuntimeError(f"{label} is missing required files:\n  {names}")


def _require_dirs(label: str, paths: list[Path]) -> None:
    missing = [path for path in paths if not path.is_dir()]
    if missing:
        names = "\n  ".join(str(path) for path in missing)
        raise RuntimeError(f"{label} is missing required directories:\n  {names}")


def _require_ext2_root_policy(fstab: Path) -> None:
    has_root = False
    has_esp = False
    has_usr_local_ufs = False
    has_home_tmpfs = False

    for line in fstab.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "/boot/efi" and parts[2] == "msdosfs":
            has_esp = True
        if len(parts) >= 3 and parts[1] == "/usr/local" and parts[2] == "ufs":
            has_usr_local_ufs = True
        if len(parts) >= 3 and parts[1] == "/home" and parts[2] == "tmpfs":
            has_home_tmpfs = True
        if len(parts) < 6 or parts[1] != "/" or parts[2] != "ext2fs":
            continue
        has_root = True
        options = set(parts[3].split(","))
        if "ro" not in options or "rw" in options:
            raise RuntimeError(
                f"{fstab} must mount the ext2 root read-only for runtime safety."
            )
        if parts[5] != "0":
            raise RuntimeError(
                f"{fstab} enables fsck pass {parts[5]} for ext2fs root. "
                "FreeBSD base has no fsck_ext2fs; set passno to 0."
            )

    if not has_root:
        raise RuntimeError(f"{fstab} does not contain the expected ext2fs root entry.")
    if not has_esp:
        raise RuntimeError(f"{fstab} must include the ESP mount at /boot/efi.")
    if not has_usr_local_ufs:
        raise RuntimeError(f"{fstab} must reserve /usr/local for FreeBSD UFS storage.")
    if not has_home_tmpfs:
        raise RuntimeError(f"{fstab} must mount /home as tmpfs for user writes.")


def _require_ext2_host_compat(root_part: str) -> None:
    cp = run(["tune2fs", "-l", root_part], capture=True)
    text = cp.stdout
    required = (
        "Filesystem features:      (none)",
        "Default mount options:    (none)",
        "Filesystem state:         clean",
    )
    for needle in required:
        if needle not in text:
            raise RuntimeError(
                f"{root_part} is not using the conservative YetiOS ext2 profile; "
                f"missing: {needle}"
            )


def _require_text(path: Path, needle: str) -> None:
    if needle not in path.read_text(errors="replace"):
        raise RuntimeError(f"{path} does not contain required text: {needle}")


def _require_absent_text(path: Path, needle: str) -> None:
    if needle in path.read_text(errors="replace"):
        raise RuntimeError(f"{path} contains forbidden text: {needle}")


def _require_symlink(path: Path, target: str) -> None:
    if not path.is_symlink():
        raise RuntimeError(f"{path} is not a symlink")
    actual = os.readlink(path)
    if actual != target:
        raise RuntimeError(f"{path} points to {actual}, expected {target}")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 5 - Assemble YetiOS image")

    if not cfg.rootfs_dir.is_dir():
        raise FileNotFoundError(cfg.rootfs_dir)
    if not cfg.esp_dir.is_dir():
        raise FileNotFoundError(cfg.esp_dir)
    if not (cfg.esp_dir / "boot" / "kernel" / "kernel").is_file():
        raise FileNotFoundError(cfg.esp_dir / "boot" / "kernel" / "kernel")

    cfg.build_dir.mkdir(parents=True, exist_ok=True)
    tmp_img = cfg.img_path.with_suffix(cfg.img_path.suffix + ".part")
    if tmp_img.exists():
        tmp_img.unlink()

    esp_mib = _mib(cfg.esp_size)
    root_mib = _mib(cfg.root_size)
    local_mib = _mib(cfg.local_size)
    swap_mib = _mib(cfg.swap_size)
    image_mib = 1 + esp_mib + root_mib + local_mib + swap_mib + 8
    esp_start = 1
    esp_end = esp_start + esp_mib
    root_end = esp_end + root_mib
    local_end = root_end + local_mib
    swap_end = local_end + swap_mib

    run(["qemu-img", "create", "-f", "raw", str(tmp_img), f"{image_mib}M"])
    run([
        "parted", "-s", str(tmp_img),
        "mklabel", "gpt",
        "mkpart", "ESP", "fat32", f"{esp_start}MiB", f"{esp_end}MiB",
        "mkpart", "YETIOS-ROOT", "ext2", f"{esp_end}MiB", f"{root_end}MiB",
        "mkpart", "YETIOS-LOCAL", f"{root_end}MiB", f"{local_end}MiB",
        "mkpart", "YETIOS-SWAP", f"{local_end}MiB", f"{swap_end}MiB",
    ])
    run(["parted", "-s", str(tmp_img), "set", "1", "esp", "on"])
    run(["parted", "-s", str(tmp_img), "name", "1", "yetios-esp"])
    run(["parted", "-s", str(tmp_img), "name", "2", "yetios-root"])
    run(["parted", "-s", str(tmp_img), "name", "3", "yetios-local"])
    run(["parted", "-s", str(tmp_img), "name", "4", "yetios-swap"])

    loop = _loop_for(tmp_img) or _losetup_attach(tmp_img)
    esp_mount = cfg.build_dir / "esp-mount"
    root_mount = cfg.build_dir / "root-mount"
    esp_mount.mkdir(parents=True, exist_ok=True)
    root_mount.mkdir(parents=True, exist_ok=True)

    try:
        esp_part = _partition_path(loop, 1)
        root_part = _partition_path(loop, 2)
        root_label = "yetios-root"

        run([
            "mkfs.ext2",
            "-F",
            "-q",
            "-L", root_label,
            "-I", "128",
            "-O", "none",
            "-E", "lazy_itable_init=0,lazy_journal_init=0,nodiscard",
            "-d", str(cfg.rootfs_dir),
            root_part,
        ])
        run(["tune2fs", "-o", "^user_xattr,^acl", root_part])
        run(["e2fsck", "-fy", root_part])
        _require_ext2_host_compat(root_part)
        run(["mount", "-o", "ro", root_part, str(root_mount)])
        _require_files("root partition", [
            root_mount / "assemble",
            root_mount / "boot" / "kernel" / "kernel",
            root_mount / "boot" / "loader.conf",
            root_mount / "etc" / "fstab",
            root_mount / "etc" / "rc.conf",
            root_mount / "etc" / "motd.template",
            root_mount / "etc" / "rc.d" / "root",
            root_mount / "usr" / "share" / "skel" / "dot.profile",
            root_mount / "usr" / "src" / "yetios" / "desktop-packages.txt",
            root_mount / "usr" / "src" / "yetios" / "sources" / "libreldr" / "Makefile",
            root_mount / "usr" / "src" / "yetios" / "sources" / "libreldr" / "src" / "libreldr.c",
            root_mount / "usr" / "src" / "yetios" / "sources" / "SnowCone" / "Makefile",
            root_mount / "usr" / "src" / "yetios" / "sources" / "SnowCone" / "main_freebsd.c",
            root_mount / "usr" / "src" / "yetios" / "sources" / "FrostedWeb" / "meson.build",
            root_mount / "usr" / "src" / "yetios" / "sources" / "FrostedWeb" / "src" / "fw_moonshine.c",
            root_mount / "usr" / "src" / "yetios" / "sources" / "Moonshine" / "configure",
            root_mount / "usr" / "src" / "yetios" / "sources" / "Moonshine" / "dlls" / "winewayland.drv" / "Makefile.in",
            root_mount / "usr" / "src" / "yetios" / "sources" / "snowfall" / "Makefile",
            root_mount / "usr" / "src" / "yetios" / "sources" / "snowfall" / "src" / "session.c",
            root_mount / "usr" / "libexec" / "yetios-sudo.c",
            root_mount / "usr" / "libexec" / "yetios" / "assemble",
            root_mount / "usr" / "libexec" / "yetios" / "assemble-home-wrapper",
            root_mount / "usr" / "bin" / "cc",
            root_mount / "usr" / "include" / "sys" / "consio.h",
            root_mount / "usr" / "include" / "sys" / "fbio.h",
            root_mount / "usr" / "include" / "grp.h",
            root_mount / "usr" / "include" / "pwd.h",
            root_mount / "usr" / "include" / "stdio.h",
            root_mount / "usr" / "include" / "unistd.h",
            root_mount / "boot" / "yetios-snowcone.bmp",
            root_mount / "boot" / "images" / "yetios-snowcone.png",
            root_mount / "boot" / "yetios-black.bmp",
            root_mount / "boot" / "images" / "yetios-black.png",
            root_mount / "boot" / "images" / "freebsd-logo-rev.png",
        ])
        _require_dirs("root partition", [
            root_mount / "home",
            root_mount / "boot" / "efi",
            root_mount / "usr" / "local",
            root_mount / "usr" / "libexec" / "yetios",
            root_mount / "usr" / "src" / "yetios" / "sources",
            root_mount / "var" / "cache" / "pkg",
            root_mount / "var" / "db" / "pkg",
        ])
        _require_ext2_root_policy(root_mount / "etc" / "fstab")
        _require_symlink(root_mount / "etc" / "resolv.conf", "/var/run/resolv.conf")
        _require_text(root_mount / "etc" / "rc.conf", 'rc_info="NO"')
        _require_text(root_mount / "etc" / "rc.conf", 'root_rw_mount="NO"')
        _require_text(root_mount / "etc" / "rc.conf", 'tmpmfs="YES"')
        _require_text(root_mount / "etc" / "rc.conf", 'varmfs="YES"')
        _require_text(root_mount / "etc" / "rc.conf", 'sshd_enable="NO"')
        _require_text(root_mount / "etc" / "rc.conf", 'yetios_snowcone_enable="NO"')
        _require_text(root_mount / "boot" / "loader.conf", 'beastie_disable="YES"')
        _require_text(root_mount / "boot" / "loader.conf", 'console="efi"')
        _require_text(root_mount / "boot" / "loader.conf", 'boot_mute="NO"')
        _require_text(root_mount / "boot" / "loader.conf", 'kern.consmute="0"')
        _require_text(root_mount / "etc" / "rc", "keep rc output off the primary console")
        _require_absent_text(root_mount / "etc" / "rc.d" / "root", "mount -u -f -w /")
        _require_text(root_mount / "etc" / "rc.local", "mount -u -w /")
        _require_text(root_mount / "etc" / "rc.local", "mount -u -r /")
        _require_text(root_mount / "etc" / "rc.local", "/usr/bin/sudo")
        _require_text(root_mount / "etc" / "rc.local", "prepare_runtime_dirs")
        _require_text(root_mount / "etc" / "rc.local", "yetios-local")
        _require_text(root_mount / "usr" / "libexec" / "yetios" / "assemble", "Building libreldr inside FreeBSD")
        _require_text(root_mount / "usr" / "libexec" / "yetios" / "assemble", "--with-wayland --without-x")
        _require_text(root_mount / "usr" / "libexec" / "yetios" / "assemble", "frostedweb")
        info("Installed FreeBSD base plus YetiOS assembler onto the root partition")

        run(["mkfs.vfat", "-F", "32", "-n", "YETIOS-ESP", esp_part])
        run(["mount", esp_part, str(esp_mount)])
        _copy_tree_contents(cfg.esp_dir, esp_mount)
        _require_files("ESP", [
            esp_mount / "EFI" / "BOOT" / "BOOTX64.EFI",
            esp_mount / "EFI" / "freebsd" / "loader.efi",
            esp_mount / "boot" / "loader.efi",
            esp_mount / "boot" / "kernel" / "kernel",
            esp_mount / "boot" / "loader.conf",
            esp_mount / "boot" / "yetios-snowcone.bmp",
            esp_mount / "boot" / "images" / "yetios-snowcone.png",
            esp_mount / "boot" / "yetios-black.bmp",
            esp_mount / "boot" / "images" / "yetios-black.png",
            esp_mount / "boot" / "images" / "freebsd-logo-rev.png",
        ])
        _require_text(esp_mount / "boot" / "loader.conf", 'beastie_disable="YES"')
        _require_text(esp_mount / "boot" / "loader.conf", 'console="efi"')
        _require_text(esp_mount / "boot" / "loader.conf", 'vfs.root.mountfrom="ext2fs:/dev/gpt/yetios-root"')
        info("Installed stock FreeBSD loader onto the ESP for first boot")
        run(["sync"])
    finally:
        _unmount(esp_mount)
        _unmount(root_mount)
        _losetup_detach(loop)

    if cfg.img_path.exists():
        warn(f"Replacing existing image: {cfg.img_path}")
    tmp_img.replace(cfg.img_path)

    ok(f"assembled {cfg.img_path} with Linux host tools")
