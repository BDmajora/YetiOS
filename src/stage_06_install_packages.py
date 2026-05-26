"""Stage 6 — install packages via emerge with explicit multi-threading."""

from __future__ import annotations
from pathlib import Path

from .common import (
    Config,
    chroot_mount,
    chroot_umount,
    in_chroot,
    info,
    ok,
    err,
    step_banner,
    warn,
)
from .templates import (
    LIBRELDR_REGISTER_SERVICE,
    WINE_FIRSTBOOT_SERVICE,
    YETI_PACKAGE_LIST,
)

# ---------------------------------------------------------------------------
# wlr-randr — not in the main Gentoo repo, built from source.
# desk.cpl uses it at runtime for resolution / refresh / VRR control.
# ---------------------------------------------------------------------------
WLR_RANDR_VERSION = "0.5.0"
WLR_RANDR_URL = (
    f"https://gitlab.freedesktop.org/emersion/wlr-randr/-/archive/"
    f"v{WLR_RANDR_VERSION}/wlr-randr-v{WLR_RANDR_VERSION}.tar.gz"
)


def _build_wlr_randr(cfg: Config) -> None:
    """Download and build wlr-randr from source inside the chroot.

    wlr-randr is only available in the Gentoo GURU overlay, which we
    don't enable.  It's a tiny meson project (~200 lines) whose only
    deps are wayland-client and wayland-protocols — both already
    installed by this point.
    """
    info(f"Building wlr-randr {WLR_RANDR_VERSION} from source ...")

    build_script = f"""\
set -e
cd /tmp

# Download
wget -q '{WLR_RANDR_URL}' -O wlr-randr.tar.gz

# Extract
tar xzf wlr-randr.tar.gz
cd wlr-randr-v{WLR_RANDR_VERSION}

# Build
meson setup build --prefix=/usr --buildtype=release
ninja -C build

# Install
ninja -C build install

# Cleanup
cd /tmp
rm -rf wlr-randr-v{WLR_RANDR_VERSION} wlr-randr.tar.gz
"""
    in_chroot(cfg, build_script)
    ok(f"wlr-randr {WLR_RANDR_VERSION} installed to /usr/bin/wlr-randr")


def _install_wine_firstboot(cfg: Config) -> None:
    """Install a one-shot service that initializes the Wine prefix on first boot.

    Ensures Wine Mono/Gecko are downloaded while networking is available,
    and applies registry prefs to a fresh prefix.
    """
    info("Installing wine-firstboot service ...")

    svc_path = cfg.mount / "etc/init.d/wine-firstboot"
    svc_path.parent.mkdir(parents=True, exist_ok=True)
    svc_path.write_text(WINE_FIRSTBOOT_SERVICE.format(yeti_user=cfg.yeti_user))
    svc_path.chmod(0o755)

    in_chroot(cfg, "rc-update add wine-firstboot default")
    ok("wine-firstboot service installed and enabled")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 6 — Install Base Packages")

    chroot_mount(cfg)
    try:
        # 1. Kernel/dracut bootstrap marker
        in_chroot(
            cfg,
            "mkdir -p /etc/kernel/preinst.d && "
            "touch /etc/kernel/preinst.d/05-check-chroot.install && "
            "echo 'root=LABEL=yetios-root ro quiet' > /etc/kernel/cmdline",
        )

        # 2. Pre-accept licenses
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.license && "
            "echo 'sys-kernel/linux-firmware @BINARY-REDISTRIBUTABLE' "
            "> /etc/portage/package.license/firmware && "
            "echo 'sys-kernel/gentoo-kernel-bin linux-fw-redistributable' "
            ">> /etc/portage/package.license/firmware",
        )

        # 3. USE flags
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.use && "
            "echo 'sys-kernel/installkernel dracut' > /etc/portage/package.use/installkernel && "
            "echo 'sys-auth/seatd server' > /etc/portage/package.use/seatd",
        )

        # --load-average keeps the host from locking up under heavy parallelism.
        # --usepkg=n forces emerge to re-fetch/rebuild every time instead of
        # silently skipping already-cached packages.
        # --noreplace (not --oneshot) ensures packages are recorded in the world
        # file so that depclean does not treat them as orphans and remove them.
        parallel_flags = f"--jobs={cfg.jobs} --load-average={float(cfg.jobs) * 0.9} --usepkg=n"

        # 4. Sync @world
        info(f"Updating base system using {cfg.jobs} parallel jobs...")
        in_chroot(cfg, f"emerge --update --deep --newuse {parallel_flags} @world")

        # 5. Install YetiOS userland
        # --noreplace: skip already-installed atoms but still write them to world.
        # --usepkg=n:  never use cached binpkgs — always fetch/build fresh.
        info(f"Installing YetiOS userland using {cfg.jobs} parallel jobs...")
        in_chroot(cfg, f"emerge --noreplace {parallel_flags} {' '.join(YETI_PACKAGE_LIST)}")

        # 6. Remove orphaned packages
        # Safe now because step 5 populated /var/lib/portage/world.
        in_chroot(cfg, "emerge --depclean --quiet")

        # 7. Build wlr-randr from source (not in main Gentoo repo).
        #    Must run after emerge so meson + wayland-client are present.
        _build_wlr_randr(cfg)

        # 8. Post-install: user creation, hostname, timezone, locale,
        #    dhcpcd, seatd, elogind, dbus, sudoers.
        info("Running post-install configuration...")
        postbuild_src = (Path(__file__).resolve().parent.parent / "postbuild.sh").read_text()
        in_chroot(
            cfg,
            postbuild_src.format(
                yeti_user=cfg.yeti_user,
                hostname=cfg.hostname,
                timezone=cfg.timezone,
            ),
        )

        # 9. First-boot UEFI registration service
        info("Installing libreldr-register first-boot service...")
        svc_path = cfg.mount / "etc/init.d/libreldr-register"
        svc_path.parent.mkdir(parents=True, exist_ok=True)
        svc_path.write_text(LIBRELDR_REGISTER_SERVICE)
        svc_path.chmod(0o755)
        in_chroot(cfg, "rc-update add libreldr-register default")
        ok("libreldr-register service installed and enabled")

        # 10. Wine prefix first-boot initializer
        _install_wine_firstboot(cfg)

        # 11. Sanity-check: ensure the user was actually created
        if cfg.yeti_user not in (cfg.mount / "etc/passwd").read_text():
            err(f"User '{cfg.yeti_user}' was NOT found in /etc/passwd after postbuild!")
            raise RuntimeError("User creation failed")
        ok(f"User '{cfg.yeti_user}' verified in /etc/passwd.")

        ok(f"Installed {len(YETI_PACKAGE_LIST)} core packages + wlr-randr.")
    finally:
        chroot_umount(cfg)