"""Stage 3 - verify FreeBSD release sets and stage the YetiOS root."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from . import rootfs, snowcone_loader
from .core import Config, ensure_clean_dir, ok, run, step_banner


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

SOURCE_TREES = (
    ("libreldr", "libreldr_dir"),
    ("SnowCone", "snowcone_dir"),
    ("FrostedWeb", "frostedweb_dir"),
    ("Moonshine", "moonshine_dir"),
    ("snowfall", "snowfall_dir"),
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_sha256(manifest_text: str, filename: str) -> str:
    for raw_line in manifest_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if not parts or parts[0] != filename:
            continue
        for part in parts[1:]:
            if _SHA256_RE.fullmatch(part):
                return part.lower()
    raise RuntimeError(f"SHA256 for {filename} not found in FreeBSD MANIFEST")


def _verify_set(cfg: Config, name: str, manifest_text: str) -> str:
    path = cfg.release_set_path(name)
    if not path.is_file():
        raise FileNotFoundError(path)
    expected = _expected_sha256(manifest_text, name)
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(
            f"SHA256 mismatch for {name}: expected {expected}, got {actual}"
        )
    return actual


def _write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode is not None:
        os.chmod(path, mode)


def _append(path: Path, text: str, mode: int | None = None) -> None:
    existing = path.read_text(errors="replace") if path.exists() else ""
    body = existing.rstrip() + "\n\n" + text.rstrip() + "\n"
    _write(path, body, mode=mode)


def _copy(src: Path, dst: Path, mode: int | None = None) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    if mode is not None:
        os.chmod(dst, mode)


def _copy_source_tree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        raise FileNotFoundError(src)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        symlinks=True,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            "autom4te.cache",
            "build",
            "*.o",
            "*.a",
            "*.so",
            "*.efi",
        ),
    )


def _symlink(target: str, link: Path) -> None:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)


def _patch_rc_quiet_handoff(rootfs_dir: Path) -> None:
    path = rootfs_dir / "etc" / "rc"
    text = path.read_text(errors="replace")
    marker = "# YetiOS: keep rc output off the primary console until login handoff."
    if marker in text:
        return
    old = (
        "files=`rcorder ${skip} ${skip_firstboot} ${system_rc} 2>/dev/null`\n"
        "run_rc_scripts --break ${early_late_divider} ${rc_early_flags} $files\n"
    )
    new = (
        f"{marker}\n"
        "if checkyesno yetios_snowcone_enable; then\n"
        "\texec >/dev/null 2>&1\n"
        "fi\n"
        "\n"
        "files=`rcorder ${skip} ${skip_firstboot} ${system_rc} 2>/dev/null`\n"
        "run_rc_scripts --break ${early_late_divider} ${rc_early_flags} $files\n"
    )
    if old not in text:
        raise RuntimeError(f"Could not patch FreeBSD rc SnowCone output handoff in {path}")
    path.write_text(text.replace(old, new, 1))


def _stage_yetios_assembler(cfg: Config) -> None:
    source_root = cfg.rootfs_dir / "usr" / "src" / "yetios" / "sources"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    for name, attr in SOURCE_TREES:
        _copy_source_tree(getattr(cfg, attr), source_root / name)

    _copy(
        cfg.desktop_packages_file,
        cfg.rootfs_dir / "usr" / "src" / "yetios" / "desktop-packages.txt",
    )
    _write(
        cfg.rootfs_dir / "usr" / "libexec" / "yetios" / "assemble",
        rootfs.assemble_script(cfg.jobs),
        mode=0o755,
    )
    _write(
        cfg.rootfs_dir / "usr" / "libexec" / "yetios" / "assemble-home-wrapper",
        rootfs.ASSEMBLE_HOME_WRAPPER_SH,
        mode=0o755,
    )
    _write(
        cfg.rootfs_dir / "assemble",
        rootfs.ASSEMBLE_HOME_WRAPPER_SH,
        mode=0o755,
    )


def run_stage(cfg: Config) -> None:
    step_banner("Stage 3 - Stage FreeBSD root")

    if not cfg.release_manifest_path.is_file():
        raise FileNotFoundError(cfg.release_manifest_path)

    manifest_text = cfg.release_manifest_path.read_text(errors="replace")
    verified: list[tuple[str, str]] = []
    for name in cfg.release_sets:
        verified.append((name, _verify_set(cfg, name, manifest_text)))

    ensure_clean_dir(cfg.rootfs_dir)
    ensure_clean_dir(cfg.esp_dir)

    for name, _checksum in verified:
        run(["tar", "-xpf", str(cfg.release_set_path(name)), "-C", str(cfg.rootfs_dir)])

    _patch_rc_quiet_handoff(cfg.rootfs_dir)
    _write(cfg.rootfs_dir / "etc" / "rc.conf", rootfs.RC_CONF.format(hostname=cfg.hostname))
    _symlink("/var/run/resolv.conf", cfg.rootfs_dir / "etc" / "resolv.conf")
    _write(cfg.rootfs_dir / "boot" / "loader.conf", rootfs.LOADER_CONF)
    snowcone_loader.write_loader_assets(cfg.rootfs_dir / "boot")
    _stage_yetios_assembler(cfg)
    _write(cfg.rootfs_dir / "etc" / "fstab", rootfs.FSTAB)
    _write(
        cfg.rootfs_dir / "etc" / "motd.template",
        rootfs.MOTD.format(user=cfg.yeti_user, password=cfg.yeti_password),
    )
    _write(
        cfg.rootfs_dir / "etc" / "motd",
        rootfs.MOTD.format(user=cfg.yeti_user, password=cfg.yeti_password),
    )
    _append(
        cfg.rootfs_dir / "usr" / "share" / "skel" / "dot.profile",
        rootfs.USER_PROFILE_APPEND,
    )
    _write(
        cfg.rootfs_dir / "usr" / "libexec" / "yetios-sudo.c",
        rootfs.limited_sudo_source(admin_user=cfg.yeti_user),
    )
    for directory in (
        cfg.rootfs_dir / "home",
        cfg.rootfs_dir / "boot" / "efi",
        cfg.rootfs_dir / "usr" / "local",
        cfg.rootfs_dir / "usr" / "libexec" / "yetios",
        cfg.rootfs_dir / "usr" / "src" / "yetios",
        cfg.rootfs_dir / "var" / "cache" / "pkg",
        cfg.rootfs_dir / "var" / "db" / "pkg",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    _write(
        cfg.rootfs_dir / "etc" / "rc.local",
        rootfs.firstboot_rc_local(
            user=cfg.yeti_user,
            password=cfg.yeti_password,
            timezone=cfg.timezone,
        ),
        mode=0o755,
    )

    cfg.source_record_path.write_text(
        "\n".join(f"{checksum}  {name}" for name, checksum in verified) + "\n"
    )
    ok(f"staged FreeBSD root at {cfg.rootfs_dir}")
