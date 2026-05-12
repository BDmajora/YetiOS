"""Stage 3 — fetch the Gentoo stage3 tarball.

The stage3 tarball is a minimal Gentoo system: glibc, gcc, coreutils,
portage, openrc, and not much else. We use it as the base of YetiOS,
then emerge precompiled binpkgs on top for the userland and Wayland stack.

Gentoo's autobuild directory contains a `latest-*.txt` file pointing at
the current tarball. We parse it, download the tarball + checksum, verify,
and cache to build/stage3-cache/.
"""

from __future__ import annotations

import hashlib
import sys
from urllib.parse import urljoin

from .common import Config, err, info, ok, run, step_banner, warn


def _latest_tarball_path(cfg: Config) -> str:
    """Read latest-stage3-<variant>.txt from the mirror; return relative path."""
    latest_url = urljoin(
        cfg.stage3_mirror,
        f"releases/amd64/autobuilds/latest-stage3-{cfg.stage3_variant}.txt",
    )
    info(f"fetching {latest_url}")
    cp = run(["wget", "-qO-", latest_url], capture=True)
    
    for line in cp.stdout.splitlines():
        line = line.strip()
        
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue
            
        # Robust check: The line we want contains the filename and ends in .tar.xz
        if ".tar.xz" in line:
            return line.split()[0]
            
    err(f"Couldn't parse a valid tarball path from {latest_url}")
    sys.exit(1)


def _sha512_of(path) -> str:
    """Calculate SHA512 hash of a file in chunks."""
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_stage(cfg: Config) -> None:
    step_banner("Stage 3 — Fetch Gentoo stage3")
    cfg.stage3_cache.mkdir(parents=True, exist_ok=True)

    rel = _latest_tarball_path(cfg)
    tarball_url = urljoin(
        cfg.stage3_mirror,
        f"releases/amd64/autobuilds/{rel}",
    )
    
    # Gentoo autobuilds use .DIGESTS (containing SHA512 and BLAKE2B)
    digests_url = tarball_url + ".DIGESTS"
    digest_path = cfg.stage3_cache / "stage3.DIGESTS"
    fname = rel.split("/")[-1]

    # 1. Fetch the digest file
    info("fetching digests...")
    run(["wget", "-qO", str(digest_path), digests_url])
    
    expected_hash = None
    if digest_path.exists():
        # Parser must be section-aware because BLAKE2B and SHA512 are both 128 chars.
        is_sha512_section = False
        for line in digest_path.read_text().splitlines():
            line = line.strip()
            
            if "# SHA512 HASH" in line:
                is_sha512_section = True
                continue
            elif line.startswith("#") and is_sha512_section:
                # Entered a different hash section (e.g., # BLAKE2B HASH)
                is_sha512_section = False
                continue
                
            if is_sha512_section:
                parts = line.split()
                # Match line format: <hash> <filename>
                if len(parts) >= 2 and parts[-1].endswith(fname) and len(parts[0]) == 128:
                    expected_hash = parts[0].lower()
                    break

    if not expected_hash:
        err(f"Could not find valid SHA512 hash for {fname} in {digests_url}.")
        sys.exit(1)

    # 2. Verify cache integrity
    if cfg.stage3_tarball.exists():
        info("verifying cached stage3...")
        if _sha512_of(cfg.stage3_tarball) == expected_hash:
            ok(f"stage3 verified in cache: {cfg.stage3_tarball}")
            return
        else:
            warn("Cached stage3 hash mismatch. Deleting for re-download.")
            cfg.stage3_tarball.unlink()

    # 3. Download tarball
    info(f"downloading: {tarball_url}")
    run(["wget", "-O", str(cfg.stage3_tarball), tarball_url])

    # 4. Final verification
    info("verifying downloaded stage3...")
    actual_hash = _sha512_of(cfg.stage3_tarball)
    
    if actual_hash != expected_hash:
        err("SHA512 mismatch for stage3 tarball!")
        err(f"  expected: {expected_hash}")
        err(f"  actual:   {actual_hash}")
        # Clean up the bad file so next run doesn't try to use it
        if cfg.stage3_tarball.exists():
            cfg.stage3_tarball.unlink()
        sys.exit(1)
        
    ok("SHA512 verified successfully")

    size_mb = cfg.stage3_tarball.stat().st_size // (1024 * 1024)
    ok(f"stage3 cached ({size_mb} MB): {cfg.stage3_tarball}")