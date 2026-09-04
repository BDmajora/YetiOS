"""Stage 2 - fetch FreeBSD release metadata and base sets."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

from .core import Config, info, ok, step_banner


def _download(url: str, dst: Path) -> None:
    if dst.exists():
        ok(f"using cached {dst.name}")
        return

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    if tmp.exists():
        tmp.unlink()

    info(f"fetching {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "YetiOS FreeBSD image builder"},
    )
    with urllib.request.urlopen(req) as response, open(tmp, "wb") as out:
        shutil.copyfileobj(response, out)
    tmp.replace(dst)
    ok(f"fetched {dst.name}")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 2 - Fetch FreeBSD release sets")
    _download(cfg.release_manifest_url, cfg.release_manifest_path)
    for name in cfg.release_sets:
        _download(cfg.release_set_url(name), cfg.release_set_path(name))
