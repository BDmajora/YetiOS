""""Stage 6 — install packages via emerge."""

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
from .templates import LIBRELDR_REGISTER_SERVICE, YETI_PACKAGE_LIST


def run_stage(cfg: Config) -> None:
    step_banner("Stage 6 — Install Base Packages")

    chroot_mount(cfg)
    try:
        # 1. Setup Kernel/Dracut for Chroot
        in_chroot(
            cfg,
            "mkdir -p /etc/kernel/preinst.d && "
            "touch /etc/kernel/preinst.d/05-check-chroot.install && "
            "echo 'root=LABEL=yetios-root ro quiet' > /etc/kernel/cmdline"
        )

        # 2. Pre-accept licenses
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.license && "
            "echo 'sys-kernel/linux-firmware @BINARY-REDISTRIBUTABLE' "
            "> /etc/portage/package.license/firmware && "
            "echo 'sys-kernel/gentoo-kernel-bin linux-fw-redistributable' "
            ">> /etc/portage/package.license/firmware"
        )

        # 3. Configure USE flags for installkernel
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.use && "
            "echo 'sys-kernel/installkernel dracut' > /etc/portage/package.use/installkernel"
        )

        # 4. Update @world
        info("Updating base system...")
        in_chroot(cfg, "emerge --update --deep --newuse @world")

        # 5. Install our core list
        info("Installing YetiOS userland...")
        packages_str = " ".join(YETI_PACKAGE_LIST)
        in_chroot(cfg, f"emerge --noreplace {packages_str}")

        # 6. Cleanup
        in_chroot(cfg, "emerge --depclean --quiet")

        # 7. Run post-install script from postbuild.sh
        postbuild_src = (Path(__file__).resolve().parent.parent / "postbuild.sh").read_text()
        postbuild = postbuild_src.format(
            yeti_user=cfg.yeti_user,
            hostname=cfg.hostname,
            timezone=cfg.timezone,
        )
        info("Running post-install configuration...")
        in_chroot(cfg, postbuild)

        # 8. Install the first-boot UEFI registration service.
        # This runs once inside the guest (where efivarfs is the *guest's*
        # NVRAM) to register libreldr.efi as a named boot entry.
        info("Installing libreldr-register first-boot service...")
        svc_path = cfg.mount / "etc/init.d/libreldr-register"
        svc_path.parent.mkdir(parents=True, exist_ok=True)
        svc_path.write_text(LIBRELDR_REGISTER_SERVICE)
        svc_path.chmod(0o755)
        in_chroot(cfg, "rc-update add libreldr-register default")
        ok("libreldr-register service installed and enabled")

        # 9. Verify user was actually created
        check = (cfg.mount / "etc" / "passwd")
        if cfg.yeti_user not in check.read_text():
            err(f"User '{cfg.yeti_user}' was NOT found in /etc/passwd after postbuild!")
            raise RuntimeError("User creation failed")
        ok(f"User '{cfg.yeti_user}' verified in /etc/passwd.")

        ok(f"Installed {len(YETI_PACKAGE_LIST)} core packages.")
    finally:
        chroot_umount(cfg)