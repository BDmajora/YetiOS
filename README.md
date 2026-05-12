# YetiOS

A minimal Linux distribution built on a Gentoo stage3 base with OpenRC, a custom user session, and a fully automated build pipeline.

## Vision

YetiOS is a lightweight, from-scratch Linux distribution that boots into a clean, minimal environment. Built on Gentoo's stage3 tarball with binary package support (binpkgs), it assembles a working system in under an hour on modern hardware — no compilation marathon required.

Future versions will include:
- **Wayland desktop session** — labwc compositor with a minimal launcher
- **Custom boot splash** — fbdev/DRM initramfs program
- **UEFI + SecureBoot support** — GPT partition scheme and signed kernel images
- **Graphical installer** — automated image-to-disk deployment tool

## Project Structure

```
run.py                         # Build orchestrator entry point
postbuild.sh                   # Post-install user/hostname/service configuration
yetios-vm.xml                  # libvirt VM definition template
test.py                        # Register and start the image in virt-manager
src/
  common.py                    # Shared utilities, Config, BuildState, chroot helpers
  templates.py                 # Portage config, package list, fstab, extlinux templates
  stage_01_host_check.py       # Verify tools, platform, disk space
  stage_02_image.py            # Create sparse image, partition, format, mount
  stage_03_fetch.py            # Download and verify Gentoo stage3 tarball
  stage_04_extract.py          # Extract stage3 into mounted image
  stage_05_portage_setup.py    # make.conf, binhost, portage sync, profile
  stage_06_install_packages.py # emerge packages + post-install configuration
  stage_07_bootloader.py       # extlinux + MBR boot stub
  stage_08_unmount.py          # Clean unmount, detach loop device
build/                         # Created during build
  yetios.img                   # Final bootable disk image
  stage3-cache/                # Cached stage3 tarball
  .yeti-state/                 # Stage completion markers for resumable builds
```

## Quick Start

### Prerequisites

- Linux host (x86_64)
- Root access (loop devices and chroot require it)
- ~25 GB free disk space
- Standard tools: `parted`, `extlinux`, `qemu-img`, `wget`, `tar`, `xz`

On Debian/Ubuntu/Mint:
```bash
sudo apt install parted util-linux extlinux qemu-utils wget tar xz-utils
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
| 3     | fetch              | ~1 min   | Download and verify Gentoo stage3 tarball   |
| 4     | extract            | ~1 min   | Extract stage3 into the mounted image       |
| 5     | portage_setup      | ~5 min   | Configure Portage, sync package tree        |
| 6     | install_packages   | ~30 min  | emerge binpkgs + post-install configuration |
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
--jobs N            Parallel emerge jobs (default: nproc)
--mirror URL        Gentoo distfiles mirror (default: https://distfiles.gentoo.org/)
--variant STR       Stage3 variant (default: amd64-openrc)
--restart           Wipe stage markers and start over
--only STAGE        Run a single stage and exit
```

## Updating the System

From inside YetiOS:

```bash
sudo emerge --sync
sudo emerge --update --deep --newuse @world
sudo emerge --depclean
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

- [Gentoo Linux](https://www.gentoo.org/)
- [Gentoo Handbook](https://wiki.gentoo.org/wiki/Handbook:AMD64)
- [Portage Package Manager](https://wiki.gentoo.org/wiki/Portage)
- [extlinux / Syslinux](https://wiki.syslinux.org/)
- [libvirt / virt-manager](https://virt-manager.org/)