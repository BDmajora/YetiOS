"""
src/common.py — shared utilities used by every stage module.

Logging, subprocess wrapper, Config dataclass, BuildState for resumability,
and loop-device helpers. Nothing here should know about specific build
stages.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

USE_COLOR = sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if USE_COLOR else s


def info(msg: str) -> None: print(_c("36", "[*]"), msg)
def ok(msg: str)   -> None: print(_c("32", "[+]"), msg)
def warn(msg: str) -> None: print(_c("33", "[!]"), msg, file=sys.stderr)
def err(msg: str)  -> None: print(_c("31", "[x]"), msg, file=sys.stderr)


def step_banner(name: str) -> None:
    bar = "=" * 72
    print()
    print(_c("35", bar))
    print(_c("35;1", f"  {name}"))
    print(_c("35", bar))


# ---------------------------------------------------------------------------
# Shell helpers
# ---------------------------------------------------------------------------

def run(cmd: "list[str] | str", *, check: bool = True, env: "dict | None" = None,
        cwd: "Path | str | None" = None,
        capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command, streaming output by default."""
    if isinstance(cmd, str):
        printable = cmd
        shell = True
    else:
        printable = " ".join(shlex.quote(c) for c in cmd)
        shell = False
    info(f"$ {printable}")
    return subprocess.run(
        cmd, shell=shell, check=check, env=env, cwd=cwd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


# ---------------------------------------------------------------------------
# Stage tracking
# ---------------------------------------------------------------------------

STAGES = [
    "01_host_check",
    "02_image_create",
    "02_image_mount",
    "03_fetch",
    "04_extract",
    "05_portage_setup",
    "06_install_packages",
    "07_bootloader",
    "08_splash",
    "09_unmount",
]


@dataclass
class BuildState:
    """Tracks which stages have completed via marker files in .yeti-state/."""
    build_dir: Path
    completed: set = field(default_factory=set)

    @property
    def state_dir(self) -> Path:
        return self.build_dir / ".yeti-state"

    def load(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for stage in STAGES:
            if (self.state_dir / stage).exists():
                self.completed.add(stage)

    def mark(self, stage: str) -> None:
        (self.state_dir / stage).touch()
        self.completed.add(stage)
        ok(f"stage complete: {stage}")

    def clear(self) -> None:
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir)
        self.completed.clear()

    def done(self, stage: str) -> bool:
        return stage in self.completed


# ---------------------------------------------------------------------------
# Config — all build-time parameters in one place
# ---------------------------------------------------------------------------

@dataclass
class Config:
    build_dir: Path
    img_path: Path
    img_size_gb: int
    mount: Path
    yeti_user: str
    hostname: str
    timezone: str
    jobs: int
    overlay_dir: Path
    stage3_mirror: str
    stage3_variant: str

    @classmethod
    def from_args(cls, args: argparse.Namespace, overlay_dir: Path) -> "Config":
        build_dir = Path(args.build_dir).resolve()
        return cls(
            build_dir=build_dir,
            img_path=build_dir / "yetios.img",
            img_size_gb=args.size,
            mount=Path(args.mount),
            yeti_user=args.yeti_user,
            hostname=args.hostname,
            timezone=args.tz,
            jobs=args.jobs,
            overlay_dir=overlay_dir,
            stage3_mirror=args.mirror,
            stage3_variant=args.variant,
        )

    @property
    def stage3_cache(self) -> Path:
        return self.build_dir / "stage3-cache"

    @property
    def stage3_tarball(self) -> Path:
        return self.stage3_cache / "stage3.tar.xz"

    @property
    def postbuild_script(self) -> Path:
        return self.build_dir.parent / "postbuild.sh"


# ---------------------------------------------------------------------------
# Loop device helpers
# ---------------------------------------------------------------------------

def losetup_attach(img: Path) -> str:
    cp = run(["losetup", "--show", "-fP", str(img)], capture=True)
    return cp.stdout.strip()


def losetup_detach(loop: str) -> None:
    run(["losetup", "-d", loop], check=False)


def loop_for(img: Path) -> "str | None":
    cp = run(["losetup", "-j", str(img)], capture=True, check=False)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    return cp.stdout.split(":", 1)[0]


# ---------------------------------------------------------------------------
# Chroot helpers — used by stages 5, 6, 7, 8
# ---------------------------------------------------------------------------

CHROOT_BINDS = [
    ("/dev", "dev"),
    ("/dev/pts", "dev/pts"),
    ("/proc", "proc"),
    ("/sys", "sys"),
    ("/run", "run"),
]


def chroot_mount(cfg: Config) -> None:
    """Bind-mount kernel filesystems into the target so chroot works."""
    for src, dst in CHROOT_BINDS:
        target = cfg.mount / dst
        target.mkdir(parents=True, exist_ok=True)
        if not os.path.ismount(target):
            run(["mount", "--bind", src, str(target)])
    resolv = cfg.mount / "etc/resolv.conf"
    resolv.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy("/etc/resolv.conf", resolv)


def chroot_umount(cfg: Config) -> None:
    """Reverse of chroot_mount, robust to partial state."""
    for _, dst in reversed(CHROOT_BINDS):
        target = cfg.mount / dst
        if os.path.ismount(target):
            run(["umount", "-l", str(target)], check=False)


def in_chroot(cfg: Config, script: str, *, env: "dict | None" = None,
              check: bool = True) -> subprocess.CompletedProcess:
    """Run a bash -c script inside the target's chroot."""
    full_env = {"LC_ALL": "C", "LANG": "C"}
    if env:
        full_env.update(env)
    return run(
        ["chroot", str(cfg.mount), "/bin/bash", "-c", script],
        env={**os.environ, **full_env},
        check=check,
    )


# ---------------------------------------------------------------------------
# Cleanup helper used by the entry point on failure
# ---------------------------------------------------------------------------

def emergency_unmount(cfg: Config) -> None:
    """Best-effort teardown when something goes sideways mid-build."""
    chroot_umount(cfg)
    for sub in ["boot", ""]:
        target = cfg.mount / sub if sub else cfg.mount
        if os.path.ismount(target):
            run(["umount", "-l", str(target)], check=False)
    loop = loop_for(cfg.img_path)
    if loop:
        losetup_detach(loop)