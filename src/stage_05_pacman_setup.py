"""Stage 5 — pacman configuration (repos + keyrings).

After the bootstrap (stage 4) we have a minimal Artix base with a working
pacman but only the Artix repos and no validated keyrings. This stage:

  1. Drops fstab.
  2. Writes the Artix + Arch mirror lists and a /etc/pacman.conf that enables
     both the Artix repos ([system] [world] [galaxy]) and the Arch repos
     ([extra] [multilib], via artix-archlinux-support).
  3. Initializes the pacman keyring and populates the Artix keys.
  4. Installs artix-archlinux-support (pulls archlinux-keyring), populates the
     Arch keys, then refreshes and upgrades the system.
"""

from __future__ import annotations

from .core import (
    Config,
    chroot_mount,
    chroot_umount,
    in_chroot,
    ok,
    step_banner,
)
from .rootfs import ARCH_MIRRORLIST, ARTIX_MIRRORLIST, FSTAB, PACMAN_CONF


def run_stage(cfg: Config) -> None:
    step_banner("Stage 5 — Configure pacman (repos + keyrings)")

    # ---- fstab ----
    (cfg.mount / "etc/fstab").write_text(FSTAB)
    ok("wrote /etc/fstab")

    # ---- mirror lists ----
    pacman_d = cfg.mount / "etc/pacman.d"
    pacman_d.mkdir(parents=True, exist_ok=True)
    (pacman_d / "mirrorlist").write_text(
        ARTIX_MIRRORLIST.format(mirror=cfg.artix_mirror))
    (pacman_d / "mirrorlist-arch").write_text(
        ARCH_MIRRORLIST.format(mirror=cfg.arch_mirror))
    ok("wrote Artix + Arch mirror lists")

    # ---- pacman.conf ----
    (cfg.mount / "etc/pacman.conf").write_text(PACMAN_CONF)
    ok("wrote /etc/pacman.conf (Artix + Arch repos)")

    # ---- keyrings + sync ----
    chroot_mount(cfg)
    try:
        # Artix keys first — needed to install anything from the Artix repos.
        in_chroot(cfg, "pacman-key --init")
        in_chroot(cfg, "pacman-key --populate artix")
        ok("pacman keyring initialized (Artix keys)")

        # Pull archlinux-keyring + Arch mirror support, then trust Arch keys.
        # DB sync of the Arch repos is harmless before this (DatabaseOptional);
        # only package *installs* need the populated keyring.
        in_chroot(cfg,
                  "pacman -Sy --needed --noconfirm artix-archlinux-support")
        in_chroot(cfg, "pacman-key --populate archlinux")
        ok("Arch repo support installed and keys populated")

        # Full refresh + upgrade so the base is current before stage 6.
        in_chroot(cfg, "pacman -Syu --noconfirm")
        ok("system synced and upgraded")
    finally:
        chroot_umount(cfg)
