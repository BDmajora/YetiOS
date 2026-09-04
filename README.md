# YetiOS

YetiOS is moving to a FreeBSD base with MIT-licensed YetiOS-owned build code.
The Artix/Linux host now prepares only a bootable FreeBSD base image, applies
the YetiOS identity, stages YetiOS source trees, and installs an in-VM
`assemble` script. `libreldr`, SnowCone, FrostedWeb, Moonshine, and SnowFall
are built from inside FreeBSD, not from the Linux host.

## Base Policy

- FreeBSD release sets provide the permissive BSD-licensed core system.
- YetiOS-owned build code and project metadata are MIT licensed.
- The Artix/Linux host pipeline installs no packages from ports/pkg.
- The first boot uses FreeBSD's stock loader so the VM can run `./assemble`.
- YetiOS-owned components are compiled by `/assemble` inside the FreeBSD VM.
- Moonshine/Wine remains a separate LGPL compliance boundary.

## Project Structure

```text
run.py                         # FreeBSD base-image preparer
packages.txt                   # Reviewed FreeBSD package candidates; empty for alpha
desktop-packages.txt           # FreeBSD package candidates used by /assemble
src/
  core.py                      # Shared config, logging, stage state
  rootfs.py                    # FreeBSD + libreldr configuration templates
  stage_01_host_check.py       # Local host sanity checks
  stage_02_fetch_release.py    # Fetch FreeBSD MANIFEST + base/kernel sets
  stage_03_stage_root.py       # Verify/extract sets, apply identity, stage /assemble
  stage_04_bootstrap_esp.py    # Install stock FreeBSD loader.efi for first boot
  stage_05_assemble_image.py   # Create/populate build/yetios.img with Linux tools
  stage_06_libvirt_access.py   # Grant system libvirt access to the image path
  stage_07_manifest.py         # Write source, login, and boot notes
build/
  yetios.img                   # Assembled YetiOS FreeBSD image
  rootfs/                      # Staged FreeBSD root filesystem
  esp/                         # Staged EFI system partition
  freebsd-cache/               # Cached FreeBSD release files
  FREEBSD_SOURCE.sha256        # Verified source checksum record
  YETIOS_FREEBSD_IMAGE.txt     # Image manifest
  .yeti-state/                 # Stage completion markers
```

## Usage

The image pipeline is still run through `run.py`:

```bash
sudo ./run.py
```

Then boot the VM, log in as `yetios`, and run:

```sh
./assemble
```

That script runs inside FreeBSD. It formats and mounts the persistent
`/usr/local` UFS partition, bootstraps `pkg`, installs the package candidates
from `desktop-packages.txt`, builds `libreldr`, builds SnowCone, builds
FrostedWeb, builds Moonshine with Wine's native Wayland driver, and skips
SnowFall until its FreeBSD backend lands.

The default alpha login is:

```text
user: yetios
password: yetios
root password: yetios
```

FreeBSD package bootstrapping is automated through the YetiOS alpha sudo helper.
From the normal `yetios` login:

```sh
sudo pkg update
```

For this Linux-tool alpha, `/usr/local` is a persistent FreeBSD UFS partition
prepared by first boot or by `./assemble`. `/var` and `/home` are RAM-backed;
the package database and cache are recreated as symlinks into persistent
`/usr/local/var`.

The pipeline is resumable. Re-run the command to continue after a failure, or
after source/config changes; completed stages are only skipped when their
recorded inputs still match. Clear all stage markers with:

```bash
sudo ./run.py --restart
```

Run a single stage with:

```bash
sudo ./run.py --only 04_bootstrap_esp
```

If you use `test.py`/virt-manager, stage 6 grants the system QEMU service user
the narrow ACL permissions it needs to traverse the project path and open
`build/yetios.img`.

## In-VM Assemble Path

The old Moonshine build pattern has been brought forward without pretending
Artix can execute FreeBSD binaries. `run.py` stages the local source trees under:

```text
/usr/src/yetios/sources
```

The FreeBSD-side assembler copies those sources to `/usr/local/src/yetios-build`
and builds there. Moonshine uses the native Wayland path:

```sh
./configure --enable-win64 --with-wayland --without-x
```

SnowFall is intentionally guarded right now. The assembler restores the build
slot, but skips SnowFall until its Linux/OpenRC/udev/VT pieces are ported to
FreeBSD rc.d and FreeBSD device/input assumptions.

The desktop package list is a development/build candidate list, not a
commercial-ready license approval. The Artix/Linux host pipeline still installs
no ports/pkg packages.

## Loading Screen

Before `./assemble`, the image boots with stock FreeBSD loader. After
`./assemble`, the VM installs the YetiOS boot path:

```text
/boot/yetios-black.bmp         black loader-stage handoff cover
/boot/images/yetios-black.png  black vt boot_mute handoff cover
/boot/images/freebsd-logo-rev.png replaced with a black YetiOS-owned image
/boot/yetios-snowcone.bmp      generated SnowCone theme preview
/boot/images/yetios-snowcone.png generated SnowCone theme preview
/etc/rc.d/yetios_snowcone      starts the live FreeBSD framebuffer renderer
/etc/rc.d/yetios_snowcone_handoff stops SnowCone before LOGIN
/usr/libexec/yetios/snowcone   SnowCone built inside FreeBSD
```

`loader.conf` disables the FreeBSD boot menu/countdown and enables `boot_mute`
and `boot_mutemsgs` with a black handoff image selected as the FreeBSD splash.
libreldr also switches the UEFI text console to black-on-black immediately
before chainloading FreeBSD's `loader.efi`, and passes `-m` through the
chainload entry so `loader.efi` starts with `boot_mute` already active.
The ESP copy of `loader.efi` also has its early status format strings blanked
so `Consoles`, `loader.env`, and `currdev` messages do not flash on screen.
`kern.consmute=1` keeps kernel
messages off the primary console before SnowCone starts. YetiOS silences rc
console output before the early rc pass so startup scripts cannot flash text
over the black handoff or SnowCone.
`yetios_snowcone_handoff` stops SnowCone and clears the terminal before the
normal text login or a future login manager, then unmutes the console.
SnowCone uses a built-in readable bitmap font in the FreeBSD renderer so it
does not depend on vt exposing a console font while graphics mode is active.
The broken text fallback is not installed.

The Linux-tool image path creates the root partition with a conservative
old-style ext2 profile: no optional feature flags, no default xattr/ACL mount
options, and a host-side `e2fsck` pass before the image is accepted. At runtime
the ext2 root stays read-only after first-boot setup. `/usr/local` is FreeBSD
UFS; `/tmp`, `/var`, and `/home` are RAM-backed.

## Command-Line Options

```text
--build-dir DIR       Output directory for image work and FreeBSD cache
--release NAME        FreeBSD release to install into the image
--arch NAME           FreeBSD release architecture
--mirror URL          FreeBSD release mirror base URL
--hostname NAME       Target hostname
--yeti-user NAME      Default YetiOS login account
--yeti-password TEXT  Default alpha password
--tz TZ               Target timezone
--root-size SIZE      Root ext2 partition size for the Linux-tool alpha path
--local-size SIZE     Persistent FreeBSD UFS /usr/local partition size
--esp-size SIZE       EFI system partition size
--swap-size SIZE      Swap partition size
--jobs N              Default parallel jobs recorded for in-VM assemble
--libreldr-dir DIR    Path to the libreldr source tree
--snowcone-dir DIR    Path to the SnowCone source tree
--moonshine-dir DIR   Path to the Moonshine source tree
--snowfall-dir DIR    Path to the SnowFall source tree
--frostedweb-dir DIR  Path to the FrostedWeb source tree
--desktop-packages-file FILE
                     FreeBSD pkg list copied for /assemble
--restart             Wipe stage markers and run the pipeline again
--only STAGE          Run one stage and exit
```

## Boot Path

The image uses UEFI:

```text
EFI/BOOT/BOOTX64.EFI          stock FreeBSD loader before ./assemble
EFI/BOOT/BOOTX64.EFI          libreldr after ./assemble
EFI/libreldr/libreldr.efi     copy of libreldr after ./assemble
EFI/libreldr/libreldr.conf    YetiOS boot menu config after ./assemble
EFI/freebsd/loader.efi        FreeBSD loader chainloaded by libreldr after ./assemble
boot/kernel/kernel            FreeBSD kernel staged on ESP for loader.efi
```

The alpha root partition is ext2 so the Artix/Linux host tools can populate it.
Its fstab fsck pass is `0` because FreeBSD base does not ship `fsck_ext2fs`.
The root is mounted read-only during normal runtime. First boot temporarily
remounts it writable only long enough to create the `yetios` account, set the
alpha passwords, install the restricted `/usr/bin/sudo` helper, sync, and
return the root to read-only before login.

## License

YetiOS build code is MIT licensed. The base system is FreeBSD, whose base is
BSD/permissive licensed. Third-party packages must be reviewed before they are
added to the base image.
