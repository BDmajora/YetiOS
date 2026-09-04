"""Stage 6 - grant system libvirt access to the assembled image."""

from __future__ import annotations

import os
import pwd
from pathlib import Path

from .core import Config, have, ok, run, step_banner


QEMU_USERS = ("libvirt-qemu", "qemu")


def _qemu_user() -> str | None:
    for user in QEMU_USERS:
        try:
            pwd.getpwnam(user)
            return user
        except KeyError:
            continue
    return None


def _image_access_dirs(image: Path) -> list[Path]:
    image = image.resolve()
    dirs = [path for path in image.parent.parents if path != Path("/")]
    dirs.reverse()
    dirs.append(image.parent)
    return dirs


def run_stage(cfg: Config) -> None:
    step_banner("Stage 6 - Grant system libvirt image access")

    if not cfg.img_path.is_file():
        raise FileNotFoundError(cfg.img_path)

    user = _qemu_user()
    if user is None:
        raise RuntimeError("No libvirt QEMU service user found; cannot grant image access.")

    if not have("setfacl"):
        raise RuntimeError("setfacl not found; install the host acl package.")

    dirs = _image_access_dirs(cfg.img_path)
    for directory in dirs:
        if directory.exists():
            run(["setfacl", "-m", f"u:{user}:x", str(directory)])

    run(["setfacl", "-m", f"u:{user}:rw", str(cfg.img_path)])
    os.chmod(cfg.img_path, cfg.img_path.stat().st_mode | 0o644)
    ok(f"system libvirt user '{user}' can access {cfg.img_path}")
