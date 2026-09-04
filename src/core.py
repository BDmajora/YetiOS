"""Shared toolkit for the YetiOS FreeBSD image pipeline."""

from __future__ import annotations

import argparse
import platform
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


USE_COLOR = sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if USE_COLOR else s


def info(msg: str) -> None: print(_c("36", "[*]"), msg)
def ok(msg: str) -> None: print(_c("32", "[+]"), msg)
def warn(msg: str) -> None: print(_c("33", "[!]"), msg, file=sys.stderr)
def err(msg: str) -> None: print(_c("31", "[x]"), msg, file=sys.stderr)


def step_banner(name: str) -> None:
    bar = "=" * 72
    print()
    print(_c("35", bar))
    print(_c("35;1", f"  {name}"))
    print(_c("35", bar))


def run(cmd: list[str], *, check: bool = True, capture: bool = False,
        cwd: Path | str | None = None) -> subprocess.CompletedProcess:
    printable = " ".join(shlex.quote(c) for c in cmd)
    info(f"$ {printable}")
    return subprocess.run(
        cmd,
        check=check,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


STAGES = [
    "01_host_check",
    "02_fetch_release",
    "03_stage_root",
    "04_bootstrap_esp",
    "05_assemble_image",
    "06_libvirt_access",
    "07_manifest",
]

RELEASE_SETS = ("base.txz", "kernel.txz")


def parse_size_to_bytes(value: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([kmgtKMGT]?)\s*", value)
    if not m:
        raise ValueError(f"invalid size value: {value!r}")
    number = int(m.group(1))
    suffix = m.group(2).lower()
    scale = {
        "": 1,
        "k": 1024,
        "m": 1024 ** 2,
        "g": 1024 ** 3,
        "t": 1024 ** 4,
    }[suffix]
    return number * scale


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def host_system() -> str:
    return platform.system()


def read_package_list(path: Path) -> list[str]:
    packages: list[str] = []
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            packages.append(line)
    return packages


@dataclass
class BuildState:
    """Tracks completed stages via marker files in build/.yeti-state/."""

    build_dir: Path
    completed: set[str] = field(default_factory=set)
    signatures: dict[str, str] = field(default_factory=dict)

    @property
    def state_dir(self) -> Path:
        return self.build_dir / ".yeti-state"

    def load(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for stage in STAGES:
            marker = self.state_dir / stage
            if marker.exists():
                self.completed.add(stage)
                self.signatures[stage] = marker.read_text(errors="replace").strip()

    def mark(self, stage: str, signature: str) -> None:
        (self.state_dir / stage).write_text(signature + "\n")
        self.completed.add(stage)
        self.signatures[stage] = signature
        ok(f"stage complete: {stage}")

    def clear(self) -> None:
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir)
        self.completed.clear()
        self.signatures.clear()

    def done(self, stage: str, signature: str) -> bool:
        return stage in self.completed and self.signatures.get(stage) == signature


@dataclass
class Config:
    build_dir: Path
    img_path: Path
    release: str
    arch: str
    mirror: str
    hostname: str
    yeti_user: str
    yeti_password: str
    timezone: str
    root_size: str
    local_size: str
    esp_size: str
    swap_size: str
    jobs: int
    libreldr_dir: Path
    snowcone_dir: Path
    moonshine_dir: Path
    snowfall_dir: Path
    frostedweb_dir: Path
    desktop_packages_file: Path

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Config":
        build_dir = Path(args.build_dir).resolve()
        return cls(
            build_dir=build_dir,
            img_path=build_dir / "yetios.img",
            release=args.release,
            arch=args.arch,
            mirror=args.mirror,
            hostname=args.hostname,
            yeti_user=args.yeti_user,
            yeti_password=args.yeti_password,
            timezone=args.tz,
            root_size=args.root_size,
            local_size=args.local_size,
            esp_size=args.esp_size,
            swap_size=args.swap_size,
            jobs=args.jobs,
            libreldr_dir=Path(args.libreldr_dir).resolve(),
            snowcone_dir=Path(args.snowcone_dir).resolve(),
            moonshine_dir=Path(args.moonshine_dir).resolve(),
            snowfall_dir=Path(args.snowfall_dir).resolve(),
            frostedweb_dir=Path(args.frostedweb_dir).resolve(),
            desktop_packages_file=Path(args.desktop_packages_file).resolve(),
        )

    @property
    def repo_root(self) -> Path:
        return self.build_dir.parent

    @property
    def cache_dir(self) -> Path:
        return self.build_dir / "freebsd-cache"

    @property
    def rootfs_dir(self) -> Path:
        return self.build_dir / "rootfs"

    @property
    def esp_dir(self) -> Path:
        return self.build_dir / "esp"

    @property
    def release_dir_url(self) -> str:
        return f"{self.mirror.rstrip('/')}/{self.arch}/{self.release}"

    @property
    def release_manifest_url(self) -> str:
        return f"{self.release_dir_url}/MANIFEST"

    @property
    def release_manifest_path(self) -> Path:
        return self.cache_dir / self.release / self.arch / "MANIFEST"

    @property
    def source_record_path(self) -> Path:
        return self.build_dir / "FREEBSD_SOURCE.sha256"

    @property
    def manifest_path(self) -> Path:
        return self.build_dir / "YETIOS_FREEBSD_IMAGE.txt"

    @property
    def release_sets(self) -> tuple[str, ...]:
        return RELEASE_SETS

    def release_set_url(self, name: str) -> str:
        return f"{self.release_dir_url}/{name}"

    def release_set_path(self, name: str) -> Path:
        return self.cache_dir / self.release / self.arch / name

    @property
    def total_image_bytes(self) -> int:
        return (
            parse_size_to_bytes(self.root_size)
            + parse_size_to_bytes(self.local_size)
            + parse_size_to_bytes(self.esp_size)
            + parse_size_to_bytes(self.swap_size)
        )
