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
    ALSA_UNMUTE_SERVICE,
    LIBRELDR_REGISTER_SERVICE,
    WINE_FIRSTBOOT_SERVICE,
    YETI_PACKAGE_LIST,
)

# ---------------------------------------------------------------------------
# wlr-randr — not in the main Gentoo repo, built from source.
# desk.cpl uses it at runtime for resolution / refresh / VRR control.
# ---------------------------------------------------------------------------
WLR_RANDR_VERSION = "0.5.0"
WLR_RANDR_REPO = "https://gitlab.freedesktop.org/emersion/wlr-randr.git"

# ---------------------------------------------------------------------------
# System sound generator.
#
# Installed to /usr/lib/yetios/gen-media.py. frostedglass runs it during
# first-boot prefix initialization, writing the system event sounds DIRECTLY
# into the NT file structure (C:\windows\Media) — the canonical, themeable
# location. No audio assets are stored in the Linux tree; replace the .wav
# files in C:\windows\Media to retheme.
# ---------------------------------------------------------------------------
GEN_MEDIA_PY = '''\
#!/usr/bin/env python3
"""Generate the YetiOS system event sounds (ding/chord/tada) as 16-bit
44.1 kHz mono WAVs into the directory given as argv[1] — normally the Wine
prefix's drive_c/windows/Media. Idempotent: existing files are kept, so
user-themed replacements survive."""

import math
import os
import struct
import sys
import wave

RATE = 44100


def synth(notes, total):
    """notes: list of (freq_hz, start_s, dur_s, amp). Returns sample list."""
    n = int(total * RATE)
    buf = [0.0] * n
    for freq, start, dur, amp in notes:
        s0 = int(start * RATE)
        nd = int(dur * RATE)
        for i in range(nd):
            t = i / RATE
            # 5 ms attack, exponential decay — no clicks, bell-like tail
            env = min(1.0, t / 0.005) * math.exp(-3.5 * t / dur)
            v = amp * env * math.sin(2 * math.pi * freq * t)
            # soft second harmonic for warmth
            v += 0.25 * amp * env * math.sin(4 * math.pi * freq * t)
            if s0 + i < n:
                buf[s0 + i] += v
    return buf


def write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for s in samples:
            s = max(-1.0, min(1.0, s))
            frames += struct.pack("<h", int(s * 32000))
        w.writeframes(bytes(frames))


SOUNDS = {
    # short two-note chime — the default beep
    "ding.wav": ([(1318.51, 0.00, 0.18, 0.40),
                  (1046.50, 0.10, 0.35, 0.40)],
                 0.50),

    # solemn triad — errors / critical stop / disconnect
    "chord.wav": ([(523.25, 0.0, 0.55, 0.30),
                   (659.25, 0.0, 0.55, 0.28),
                   (783.99, 0.0, 0.55, 0.26)],
                  0.60),

    # rising arpeggio — logon
    "tada.wav": ([(523.25, 0.00, 0.14, 0.36),
                  (659.25, 0.09, 0.14, 0.36),
                  (783.99, 0.18, 0.14, 0.36),
                  (1046.50, 0.27, 0.50, 0.40)],
                 0.85),
}


def main():
    if len(sys.argv) != 2:
        print("usage: gen-media.py <target-dir>", file=sys.stderr)
        return 1

    target = sys.argv[1]
    os.makedirs(target, exist_ok=True)

    for name, (notes, total) in SOUNDS.items():
        path = os.path.join(target, name)

        if os.path.exists(path):
            continue

        write_wav(path, synth(notes, total))
        print(f"generated {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _build_wlr_randr(cfg: Config) -> None:
    """Download and build wlr-randr from source inside the chroot."""

    info(f"Building wlr-randr {WLR_RANDR_VERSION} from source ...")

    build_script = f"""\
set -e
cd /tmp

git clone --branch v{WLR_RANDR_VERSION} --depth 1 '{WLR_RANDR_REPO}' wlr-randr
cd wlr-randr

meson setup build --prefix=/usr --buildtype=release
ninja -C build

ninja -C build install

cd /tmp
rm -rf wlr-randr
"""

    in_chroot(cfg, build_script)

    ok(f"wlr-randr {WLR_RANDR_VERSION} installed to /usr/bin/wlr-randr")


def _install_media_generator(cfg: Config) -> None:
    """Install the system-sound generator script."""

    info("Installing system-sound generator ...")

    gen_path = cfg.mount / "usr/lib/yetios/gen-media.py"

    gen_path.parent.mkdir(parents=True, exist_ok=True)
    gen_path.write_text(GEN_MEDIA_PY)
    gen_path.chmod(0o755)

    ok("gen-media.py installed to /usr/lib/yetios/")


def _install_wine_firstboot(cfg: Config) -> None:
    """Install a one-shot service that initializes the Wine prefix on first boot.

    Ensures Wine Mono/Gecko are downloaded while networking is available,
    and applies registry prefs to a fresh prefix.
    """

    info("Installing wine-firstboot service ...")

    svc_path = cfg.mount / "etc/init.d/wine-firstboot"

    svc_path.parent.mkdir(parents=True, exist_ok=True)

    service_text = WINE_FIRSTBOOT_SERVICE.format(
        yeti_user=cfg.yeti_user
    )

    svc_path.write_text(service_text)
    svc_path.chmod(0o755)

    in_chroot(cfg, "rc-update add wine-firstboot default")

    ok("wine-firstboot service installed and enabled")


def _install_alsa_init(cfg: Config) -> None:
    """Install a boot service that unmutes the ALSA mixer.

    A fresh ALSA state on the QEMU HDA codec usually comes up with Master/PCM
    muted, which makes PipeWire output silence even though its graph is fully
    wired. This unmutes and raises the card before the graphical session
    (and thus PipeWire/Moonshine) starts.
    """

    info("Installing ALSA mixer-init service ...")

    svc_path = cfg.mount / "etc/init.d/yetios-audio-init"

    svc_path.parent.mkdir(parents=True, exist_ok=True)

    # Written verbatim — the template uses plain shell braces, no .format().
    svc_path.write_text(ALSA_UNMUTE_SERVICE)
    svc_path.chmod(0o755)

    in_chroot(cfg, "rc-update add yetios-audio-init default")

    ok("yetios-audio-init service installed and enabled")


def _setup_flatpak(cfg: Config) -> None:
    """Register the Flathub remote so flatpak can install apps.

    sys-apps/flatpak itself is in YETI_PACKAGE_LIST (installed by the userland
    emerge above); this only adds the remote. `remote-add` fetches the
    .flatpakrepo (GPG key + repo config) over the network, so it needs the
    build host online. Non-fatal: if it can't reach Flathub at build time, the
    remote can be added at runtime with the identical command.

    NB: Flatpak's bwrap sandbox needs unprivileged user namespaces in the guest
    kernel. If apps fail with "CanCreateUserNamespace() clone() failure: EPERM",
    that's a kernel-config matter (CONFIG_USER_NS + unprivileged userns must be
    enabled), or use a setuid bubblewrap — neither is fixable from this stage.
    """

    info("Registering Flathub remote ...")

    cp = in_chroot(
        cfg,
        "flatpak remote-add --if-not-exists flathub "
        "https://dl.flathub.org/repo/flathub.flatpakrepo",
        check=False,
    )

    if cp.returncode != 0:
        warn("Could not register Flathub remote at build time (no network?).")
        warn("Add it later at runtime with:")
        warn("  flatpak remote-add --if-not-exists flathub "
             "https://dl.flathub.org/repo/flathub.flatpakrepo")
    else:
        ok("Flathub remote registered")


def run_stage(cfg: Config) -> None:
    step_banner("Stage 6 — Install Base Packages")

    chroot_mount(cfg)

    try:
        # Ensure /dev/shm exists
        in_chroot(
            cfg,
            "mkdir -p /dev/shm && "
            "mount -t tmpfs tmpfs /dev/shm -o mode=1777"
        )

        # Kernel/dracut bootstrap marker
        in_chroot(
            cfg,
            "mkdir -p /etc/kernel/preinst.d && "
            "touch /etc/kernel/preinst.d/05-check-chroot.install && "
            "echo 'root=LABEL=yetios-root ro quiet' > /etc/kernel/cmdline",
        )

        # Pre-accept licenses
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.license && "
            "echo 'sys-kernel/linux-firmware @BINARY-REDISTRIBUTABLE' "
            "> /etc/portage/package.license/firmware && "
            "echo 'sys-kernel/gentoo-kernel-bin linux-fw-redistributable' "
            ">> /etc/portage/package.license/firmware",
        )

        # USE flags
        in_chroot(
            cfg,
            "mkdir -p /etc/portage/package.use && "
            "echo 'sys-kernel/installkernel dracut' "
            "> /etc/portage/package.use/installkernel && "
            "echo 'sys-auth/seatd server' "
            "> /etc/portage/package.use/seatd",
        )

        # Upgrade portage first
        info("Upgrading portage before @world update...")

        in_chroot(
            cfg,
            "emerge --oneshot --usepkg=n sys-apps/portage"
        )

        ok("portage upgraded")

        # Commit to Python 3.14 only
        info("Committing system to python3.14 only...")

        in_chroot(
            cfg,
            "emerge --oneshot --usepkg=n "
            "app-eselect/eselect-python "
            "dev-lang/python:3.14 && "
            "eselect python update && "
            "eselect python set python3.14 && "
            "sed -i "
            "-e 's/^PYTHON_TARGETS=.*/PYTHON_TARGETS=\"python3_14\"/' "
            "-e 's/^PYTHON_SINGLE_TARGET=.*/PYTHON_SINGLE_TARGET=\"python3_14\"/' "
            "/etc/portage/make.conf",
        )

        ok("python3.14 is now the sole Python target")

        parallel_flags = (
            f"--jobs={cfg.jobs} "
            f"--load-average={float(cfg.jobs) * 0.9}"
        )

        # Update @world
        info(f"Updating base system using {cfg.jobs} parallel jobs...")

        in_chroot(
            cfg,
            f"emerge --update --deep --newuse "
            f"--with-bdeps=y {parallel_flags} @world",
        )

        # Install YetiOS userland
        info(f"Installing YetiOS userland using {cfg.jobs} parallel jobs...")

        in_chroot(
            cfg,
            f"emerge --noreplace {parallel_flags} "
            f"{' '.join(YETI_PACKAGE_LIST)}",
        )

        # Reconcile Python targets
        info("Reconciling Python targets...")

        in_chroot(
            cfg,
            f"emerge --oneshot --getbinpkg=n --usepkg=n "
            f"{parallel_flags} "
            "dev-python/markupsafe "
            "dev-python/jinja2",
        )

        # depclean
        cp = in_chroot(
            cfg,
            "emerge --depclean --quiet",
            check=False,
        )

        if cp.returncode != 0:
            warn("depclean did not complete cleanly.")
            warn("Build continues.")
        else:
            ok("orphaned packages removed")

        # Build wlr-randr
        _build_wlr_randr(cfg)

        # Install media generator
        _install_media_generator(cfg)

        # Post-install config
        info("Running post-install configuration...")

        postbuild_src = (
            Path(__file__).resolve().parent.parent / "postbuild.sh"
        ).read_text()

        in_chroot(
            cfg,
            postbuild_src.format(
                yeti_user=cfg.yeti_user,
                hostname=cfg.hostname,
                timezone=cfg.timezone,
            ),
        )

        # libreldr-register service
        info("Installing libreldr-register first-boot service...")

        svc_path = cfg.mount / "etc/init.d/libreldr-register"

        svc_path.parent.mkdir(parents=True, exist_ok=True)

        svc_path.write_text(LIBRELDR_REGISTER_SERVICE)
        svc_path.chmod(0o755)

        in_chroot(cfg, "rc-update add libreldr-register default")

        ok("libreldr-register service installed and enabled")

        # Wine firstboot initializer
        _install_wine_firstboot(cfg)

        # ALSA mixer unmute on boot (fixes default-muted HDA codec → silence)
        _install_alsa_init(cfg)

        # Enable the system D-Bus bus at boot. rtkit and polkit are
        # D-Bus-activated on the *system* bus, so PipeWire's module-rt can
        # only reach RealtimeKit1 — and thus silence the RTKit warnings and
        # get RT scheduling — when this is running. This is separate from the
        # per-session bus that dbus-run-session gives WirePlumber; the two
        # coexist. Idempotent if a dependency already pulled dbus into a
        # runlevel.
        info("Enabling system D-Bus service for rtkit/polkit ...")
        in_chroot(cfg, "rc-update add dbus default")
        ok("system D-Bus enabled at boot")

        # Register the Flathub remote (flatpak package is in YETI_PACKAGE_LIST)
        _setup_flatpak(cfg)

        # Verify user creation
        if cfg.yeti_user not in (
            cfg.mount / "etc/passwd"
        ).read_text():
            err(
                f"User '{cfg.yeti_user}' was NOT found "
                "in /etc/passwd after postbuild!"
            )
            raise RuntimeError("User creation failed")

        ok(f"User '{cfg.yeti_user}' verified in /etc/passwd.")

        ok(
            f"Installed {len(YETI_PACKAGE_LIST)} "
            "core packages + wlr-randr."
        )

    finally:
        in_chroot(
            cfg,
            "umount /dev/shm 2>/dev/null || true",
            check=False,
        )

        chroot_umount(cfg)