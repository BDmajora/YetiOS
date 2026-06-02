"""
Stage 4 — extract the stage3 tarball into the mounted image.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .common import Config, ok, run, step_banner, warn, err


def run_stage(cfg: Config) -> None:
    step_banner("Stage 4 — Extract stage3")

    # Sanity: skip if the target already looks populated
    if (cfg.mount / "etc" / "gentoo-release").exists():
        warn("Target already contains a Gentoo system; skipping extract.")
        return

    try:
        # Added sudo to ensure root-level xattr/ownership preservation
        run([
            "sudo", "tar", "xpf", str(cfg.stage3_tarball),
            "--xattrs-include=*.*",
            "--numeric-owner",
            "-C", str(cfg.mount),
        ])
    except subprocess.CalledProcessError:
        err("Tar extraction failed! The archive is likely a corrupt text/HTML file.")

        # 1. Kill the corrupt tarball
        if cfg.stage3_tarball.exists():
            warn(f"Removing corrupt archive: {cfg.stage3_tarball}")
            run(["sudo", "rm", "-f", str(cfg.stage3_tarball)])

        # 2. Kill the Stage 3 marker so the orchestrator re-fetches next time.
        #    Markers live in build_dir/.yeti-state/<stage> (see BuildState),
        #    NOT build_dir/.stage_03_fetch — the old path silently did nothing.
        marker = cfg.build_dir / ".yeti-state" / "03_fetch"
        if marker.exists():
            warn(f"Removing Stage 3 marker to force re-fetch: {marker}")
            run(["sudo", "rm", "-f", str(marker)])

        raise  # Crash out so the user can re-run

    # Ensure critical portage directories exist with proper permissions
    for d in ["var/cache/binpkgs", "var/db/repos/gentoo", "var/log/portage"]:
        target_dir = cfg.mount / d
        run(["sudo", "mkdir", "-p", str(target_dir)])

    ok(f"stage3 extracted into {cfg.mount}")