"""Stage 3 — fetch the Artix bootstrap script.

Artix doesn't publish a stage3-style rootfs tarball (only ISOs), so we use
the official `artix-bootstrap.sh`. From any GNU/Linux host it downloads a
minimal pacman + glibc, then pacstraps an Artix `base` + OpenRC into a
destination directory. Stage 4 runs it against the mounted image.

We just cache the script here (it's tiny); the heavy lifting — and all the
network traffic for actual packages — happens in stage 4.
"""

from __future__ import annotations

import sys

from .core import Config, err, info, ok, run, step_banner, warn


ARTIX_BOOTSTRAP_URL = (
    "https://gitea.artixlinux.org/artix/artix-bootstrap/"
    "raw/branch/master/artix-bootstrap.sh"
)


def _looks_like_bootstrap(text: str) -> bool:
    """Cheap sanity check that we fetched the script, not an error page."""
    return text.startswith("#!/bin/bash") and "artix-bootstrap" in text


def run_stage(cfg: Config) -> None:
    step_banner("Stage 3 — Fetch artix-bootstrap.sh")
    cfg.bootstrap_cache.mkdir(parents=True, exist_ok=True)

    script = cfg.bootstrap_script

    if script.exists() and _looks_like_bootstrap(script.read_text(errors="ignore")):
        ok(f"artix-bootstrap.sh already cached: {script}")
        return

    info(f"downloading: {ARTIX_BOOTSTRAP_URL}")
    run(["wget", "-O", str(script), ARTIX_BOOTSTRAP_URL])

    if not _looks_like_bootstrap(script.read_text(errors="ignore")):
        err("Downloaded file does not look like artix-bootstrap.sh.")
        warn("The mirror may have returned an error page. Deleting it.")
        if script.exists():
            script.unlink()
        sys.exit(1)

    script.chmod(0o755)
    ok(f"artix-bootstrap.sh cached: {script}")
