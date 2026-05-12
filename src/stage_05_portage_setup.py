"""Stage 5 — Portage configuration.

After stage3 extraction we have a Gentoo skeleton with Portage installed
but uninitialized. This stage:

  1. Writes /etc/portage/make.conf (with binhost enabled).
  2. Writes /etc/portage/binrepos.conf/gentoobinhost.conf so binpkgs are
     fetched from the official binhost.
  3. Drops fstab + locale + timezone defaults.
  4. Bind-mounts kernel filesystems and runs `emerge-webrsync` inside
     the chroot to populate /var/db/repos/gentoo with the package tree.
  5. Runs `getuto` to install the Gentoo release-signing key so
     binpkg-request-signature works.
"""

from __future__ import annotations

from .common import (
    Config,
    chroot_mount,
    chroot_umount,
    in_chroot,
    ok,
    step_banner,
    warn,
)
from .templates import FSTAB, PORTAGE_BINHOST_CONF, PORTAGE_MAKE_CONF


def run_stage(cfg: Config) -> None:
    step_banner("Stage 5 — Configure Portage (binhost + sync)")

    # ---- make.conf ----
    make_conf = cfg.mount / "etc/portage/make.conf"
    make_conf.parent.mkdir(parents=True, exist_ok=True)
    make_conf.write_text(PORTAGE_MAKE_CONF.format(jobs=cfg.jobs))
    ok("wrote /etc/portage/make.conf")

    # ---- binhost ----
    binhost_dir = cfg.mount / "etc/portage/binrepos.conf"
    binhost_dir.mkdir(parents=True, exist_ok=True)
    (binhost_dir / "gentoobinhost.conf").write_text(PORTAGE_BINHOST_CONF)
    ok("wrote binrepos.conf/gentoobinhost.conf")

    # ---- fstab ----
    (cfg.mount / "etc/fstab").write_text(FSTAB)
    ok("wrote /etc/fstab")

    # ---- chroot setup ----
    chroot_mount(cfg)
    try:
        # `getuto` fetches and installs the Gentoo release keys for binpkg
        # signature verification. Ships in app-portage/getuto, included in
        # current stage3 tarballs.
        in_chroot(cfg, "getuto")

        # Sync the package tree. emerge-webrsync is faster than rsync for a
        # first sync and doesn't need a working rsync.gentoo.org route.
        in_chroot(cfg, "emerge-webrsync")
        ok("portage tree synced")

        # Select an OpenRC profile. The desktop/wayland profile would be
        # ideal but doesn't exist as a flat name; use the base amd64 openrc
        # profile and enable wayland via USE flag in make.conf.
        in_chroot(cfg, "eselect profile set default/linux/amd64/23.0")
        ok("portage profile set")
    finally:
        chroot_umount(cfg)