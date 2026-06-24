# YetiOS

A minimal Linux distribution built on an Artix Linux (OpenRC) base, a custom user session, and a fully automated build pipeline.

## Vision

YetiOS is a lightweight, from-scratch Linux distribution that boots into a clean, minimal environment. Built on Artix Linux (Arch-based, OpenRC, systemd-free) with pacman binary packages, it assembles a working system in under an hour on modern hardware — no compilation marathon required.

Future versions will include:
- **Wayland desktop session** — labwc compositor with a minimal launcher
- **Custom boot splash** — fbdev/DRM initramfs program
- **UEFI + SecureBoot support** — GPT partition scheme and signed kernel images
- **Graphical installer** — automated image-to-disk deployment tool

## Project Structure

```
run.py                         # Build orchestrator entry point
packages.txt                   # Runtime package list (pacman names, one per line)
postbuild.sh                   # Post-install user/hostname/locale/service configuration
yetios-vm.xml                  # libvirt VM definition template
test.py                        # Register and start the image in virt-manager
src/
  core.py                      # Shared toolkit: Config, BuildState, chroot/loop helpers
  rootfs.py                    # pacman.conf, mirror lists, fstab, OpenRC service templates
  stage_01_host_check.py       # Verify tools, platform, disk space
  stage_02_image.py            # Create sparse image, partition, format, mount
  stage_03_fetch.py            # Download the Artix bootstrap script
  stage_04_extract.py          # Bootstrap a minimal Artix base into the image
  stage_05_pacman_setup.py     # pacman.conf, mirror lists, keyrings, sync
  stage_06_install_packages.py # pacman -S packages.txt + post-install configuration
  stage_07_moonshine.py        # Build/install Moonshine (Wine fork) in chroot
  stage_08_bootloader.py       # libreldr UEFI install + kernel/initramfs to ESP
  stage_09_snowfall.py         # Build/install snowfall login manager
  stage_10_crystallinelattice.py # Build/install CrystallineLattice compositor
  stage_11_splash.py           # Build/install snowcone boot splash
  stage_12_unmount.py          # Clean unmount, detach loop device
build/                         # Created during build
  yetios.img                   # Final bootable disk image
  bootstrap-cache/             # Cached artix-bootstrap.sh + downloaded base packages
  .yeti-state/                 # Stage completion markers for resumable builds
```

## Quick Start

### Prerequisites

- Linux host (x86_64)
- Root access (loop devices and chroot require it)
- ~25 GB free disk space
- Standard tools: `parted`, `qemu-img`, `wget`, `curl`, `tar`, `xz`, `zstd`, `gawk`

On Debian/Ubuntu/Mint:
```bash
sudo apt install parted util-linux dosfstools qemu-utils wget curl \
                 tar xz-utils zstd gawk git build-essential gnu-efi
```

### Building YetiOS

```bash
git clone https://github.com/yourusername/yetios.git
cd yetios
sudo ./run.py
```

The build is fully resumable. If interrupted, re-run and completed stages are skipped automatically. To restart from scratch:

```bash
sudo ./run.py --restart
```

To re-run a single stage:

```bash
sudo ./run.py --only 06_install_packages
```

**Build stages:**

| Stage | Name               | Time     | Description                                 |
|-------|--------------------|----------|---------------------------------------------|
| 1     | host_check         | seconds  | Verify tools, disk space, and permissions   |
| 2     | image_create       | seconds  | Create sparse 20 GB raw image               |
| 2     | image_mount        | seconds  | Partition, format ext2/ext4, loop-mount     |
| 3     | fetch              | seconds  | Download the Artix bootstrap script         |
| 4     | extract            | ~5 min   | Bootstrap a minimal Artix base into the image |
| 5     | pacman_setup       | ~3 min   | Configure pacman repos + keyrings, sync     |
| 6     | install_packages   | ~15 min  | pacman -S the userland + post-install config |
| 7     | bootloader         | seconds  | Install extlinux + MBR boot stub            |
| 8     | unmount            | seconds  | Detach loop device, print boot command      |

### Booting YetiOS

Boot directly with QEMU (printed at the end of a successful build):

```bash
qemu-system-x86_64 -enable-kvm -m 4G \
    -drive file=build/yetios.img,format=raw \
    -vga virtio -display gtk,gl=on
```

Or register it in virt-manager:

```bash
python3 test.py
virsh -c qemu:///system start yetios
```

**Default credentials:** User `yeti`, password `yeti`. The system autologins on tty1.

## Command-Line Options

```
--build-dir DIR     Output directory for image and cache (default: ./build)
--size N            Image size in GB (default: 20)
--mount PATH        Mountpoint during build (default: /mnt/yetios)
--yeti-user NAME    Default user inside YetiOS (default: yeti)
--hostname NAME     System hostname (default: yetios)
--tz TZ             Timezone (default: UTC)
--jobs N            Parallel build jobs (default: nproc)
--artix-mirror URL  Artix repo mirror (default: https://mirror1.artixlinux.org/repos)
--arch-mirror URL   Arch repo mirror  (default: https://geo.mirror.pkgbuild.com)
--init NAME         Artix init system: openrc|runit|s6|dinit (default: openrc)
--restart           Wipe stage markers and start over
--only STAGE        Run a single stage and exit
```

## Packages

The runtime package set lives in [`packages.txt`](packages.txt) at the repo root —
one pacman package per line, `#` for comments. Add or remove packages there;
stage 6 installs them with `pacman -S --needed`. Names are Artix/Arch package
names (e.g. `pipewire`, `mesa`, `vulkan-icd-loader`).

## Updating the System

From inside YetiOS:

```bash
sudo pacman -Syu          # refresh repos and upgrade everything
sudo pacman -S <package>  # install a package
sudo pacman -Rns <package> # remove a package and its unused deps
```

## Current Limitations (v0)

- **BIOS + MBR only.** No UEFI or GPT support. Planned for v1.
- **No graphical session.** Boots to a text login. Wayland/labwc session planned for v1.
- **No boot splash.** Standard kernel quiet mode. Custom splash planned for v1.
- **Minimal package set.** Only core packages are installed. Extend via `emerge` inside the VM.

## Troubleshooting

### Login incorrect at boot

Boot into single-user mode by pressing `Tab` at the extlinux prompt and appending `single` to the kernel line, then set a password with `passwd yeti`.

### Image doesn't boot in QEMU / virt-manager

- Ensure the VM is configured for **BIOS** (not UEFI) — the image uses extlinux + MBR.
- Verify stage 7 and 8 completed in the build output.
- Inspect the image directly:
  ```bash
  sudo losetup -P /dev/loop0 build/yetios.img
  sudo mount /dev/loop0p2 /mnt && ls /mnt
  ```

### virt-manager: "Network not found: default"

```bash
virsh net-define /usr/share/libvirt/networks/default.xml
virsh net-start default
virsh net-autostart default
```

### Permission denied on image file

The image is owned by root after a `sudo` build. Fix with:

```bash
sudo chown $USER:$USER build/yetios.img
chmod 644 build/yetios.img
```

## License

YetiOS is built from open-source components and provided as-is. See individual package licenses (Linux kernel, Gentoo, GNU utilities, etc.) for licensing details.

## References

- [Artix Linux](https://artixlinux.org/)
- [Artix Wiki](https://wiki.artixlinux.org/)
- [artix-bootstrap](https://gitea.artixlinux.org/artix/artix-bootstrap)
- [Arch Wiki: pacman](https://wiki.archlinux.org/title/Pacman)
- [libvirt / virt-manager](https://virt-manager.org/)