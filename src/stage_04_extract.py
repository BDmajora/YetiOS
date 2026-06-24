"""
Stage 4 — bootstrap a minimal Artix base into the mounted image.

Runs the cached artix-bootstrap.sh (stage 3) against the target mountpoint.
The script downloads pacman + glibc, then pacstraps `base`, the chosen init
(OpenRC), `elogind-<init>`, and `artix-keyring` into the image. After this the
image holds a working, self-contained pacman; stage 5 configures the repos and
stage 6 installs the YetiOS userland.
"""

from __future__ import annotations

import subprocess

from .core import Config, err, info, ok, run, step_banner, warn


def run_stage(cfg: Config) -> None:
    step_banner("Stage 4 — Bootstrap Artix base")

    # Sanity: skip if the target already looks bootstrapped.
    if (cfg.mount / "usr/bin/pacman").exists():
        warn("Target already contains pacman; skipping bootstrap.")
        return

    if not cfg.bootstrap_script.exists():
        err(f"artix-bootstrap.sh not found at {cfg.bootstrap_script}.")
        err("Re-run stage 3 (fetch) first.")
        raise FileNotFoundError(cfg.bootstrap_script)

    # Preserve the downloaded packages across retries so a re-run after a
    # transient failure doesn't redownload the whole base.
    pkg_cache = cfg.bootstrap_cache / "pkgs"
    pkg_cache.mkdir(parents=True, exist_ok=True)

    info(f"bootstrapping {cfg.init} base into {cfg.mount} ...")
    info("(downloads pacman + the Artix base — this fetches a few hundred MB)")

    try:
        run([
            "bash", str(cfg.bootstrap_script),
            "-i", cfg.init,
            "-r", cfg.artix_mirror,
            "-d", str(pkg_cache),
            str(cfg.mount),
        ])
    except subprocess.CalledProcessError:
        err("artix-bootstrap failed.")
        # Drop the stage-4 marker so a re-run retries the bootstrap.
        marker = cfg.build_dir / ".yeti-state" / "04_extract"
        if marker.exists():
            warn(f"Removing stage 4 marker to force re-bootstrap: {marker}")
            marker.unlink()
        raise

    if not (cfg.mount / "usr/bin/pacman").exists():
        err("Bootstrap finished but /usr/bin/pacman is missing in the target.")
        raise RuntimeError("artix-bootstrap produced an incomplete rootfs")

    ok(f"Artix {cfg.init} base bootstrapped into {cfg.mount}")
