# YetiOS FreeBSD Migration Plan

This is the working plan for moving YetiOS from an Artix Linux/OpenRC base to a
FreeBSD base with a permissive commercial distribution posture.

This is not legal advice. Treat it as an engineering and compliance checklist
to take to a qualified attorney before selling a product.

## Goal

Build YetiOS on top of FreeBSD base instead of Linux/Artix, and keep shipped
YetiOS-owned code under permissive terms such as MIT, BSD-2-Clause,
BSD-3-Clause, ISC, zlib, or Apache-2.0.

Important wording: FreeBSD is not "MIT only." FreeBSD is primarily BSD-licensed
and permissive-friendly. The FreeBSD Project license policy prefers the
two-clause BSD license and isolates differently licensed code so BSD-only
derivatives are easier to produce.

Official references:

- https://www.freebsd.org/internal/software-license/
- https://www.freebsd.org/copyright/freebsd-license/
- https://docs.freebsd.org/en/books/handbook/
- https://docs.freebsd.org/en/books/handbook/wayland/

## License Findings

These are the current workspace findings after the project-owned license cleanup:

- `YetiOS/` is MIT at the builder level, but its generated OS image currently
  includes GPL/LGPL components through Linux, GNU tools, syslinux/extlinux,
  Wine/Moonshine, and the Artix/Arch package set.
- `SnowCone/`, `snowfall/`, `libreldr/`, `CrystallineLattice/`, and
  `FrostedGlass/` now carry MIT license files as YetiOS-owned components.
- `Moonshine/` is a Wine fork under LGPL-2.1-or-later. This can be commercially
  distributed with the usual LGPL obligations, and should be tracked as a
  separate LGPL component boundary rather than represented as MIT.

If any third-party GPL code was copied into the newly MIT-labeled YetiOS
components, those parts still need replacement or a compatible licensing
decision. The MIT files are correct only for code you own or have permission to
relicense.

## Migration Strategy

### Phase 0 - Decide The License Boundary

Make one hard product decision before rewriting the builder:

- Strict permissive-only core: no GPL, AGPL, or similarly reciprocal components
  in the YetiOS-owned base layer.
- Permissive base plus compliant LGPL component boundary: FreeBSD/YetiOS core is
  permissive, while Moonshine/Wine is shipped with its LGPL notices, source
  access, and user modification/replacement path.

The second option is the practical path if Windows app compatibility remains
central, similar in spirit to commercial Wine-based products that sell
proprietary value-add layers while complying with Wine's LGPL terms.

### Phase 1 - Freeze The Current Linux Builder

Keep the existing Artix builder working as a legacy target while creating a new
FreeBSD path. Do not mutate every stage in place at once.

Suggested layout:

```text
YetiOS/
  run.py                    # dispatcher, later grows --target linux|freebsd
  packages.txt              # legacy Artix package list
  packages.freebsd.txt      # new FreeBSD pkg list
  src/
    linux/                  # current stages moved here later
    freebsd/                # new FreeBSD stages
```

### Phase 2 - Replace The OS Image Pipeline

Current Linux-specific pipeline:

- `artix-bootstrap.sh`
- pacman repositories and keyrings
- ext4 root filesystem
- Linux kernel and mkinitcpio
- OpenRC services
- Linux chroot with `/bin/bash`

FreeBSD replacement pipeline:

- Download or locally supply official FreeBSD release sets.
- Create GPT image with an EFI System Partition and a FreeBSD root partition.
- Use UFS first for the root filesystem. Add ZFS later only if needed.
- Extract FreeBSD base/kernel release sets into the mounted root.
- Configure `/etc/rc.conf`, `/boot/loader.conf`, `/etc/fstab`, hostname,
  users, networking, and services.
- Use FreeBSD `pkg` for non-base packages.
- Use FreeBSD `loader.efi` first instead of custom libreldr. Revisit a custom
  permissive loader after the base image boots.

### Phase 3 - Replace Package And Service Mapping

Current Artix package concepts map roughly like this:

```text
pacman                 -> pkg
packages.txt           -> packages.freebsd.txt
OpenRC init scripts    -> rc.d scripts plus rc.conf enable flags
mkinitcpio             -> FreeBSD loader/kernel modules
linux-firmware         -> drm-kmod and GPU firmware packages where needed
eudev/libudev          -> devd plus libudev-devd compatibility where needed
seatd-openrc           -> seatd service enabled in rc.conf
```

Likely first FreeBSD package set to test:

```text
pkgconf
meson
ninja
git
wayland
wayland-protocols
libdrm
mesa-dri
mesa-libs
libinput
libxkbcommon
seatd
libudev-devd
cairo
xwayland
drm-kmod
```

Exact package names should be validated against the target FreeBSD release.

### Phase 4 - Port YetiOS Components

Prioritize in this order:

1. Boot a plain FreeBSD YetiOS image to console.
2. Enable graphics stack: `drm-kmod`, `seatd`, user in `video` group.
3. Port and build `CrystallineLattice` on FreeBSD.
4. Port `snowfall` to FreeBSD rc.d/PAM/device paths.
5. Port or replace `SnowCone`.
6. Keep `Moonshine` as a tracked LGPL component boundary.
7. Only after the FreeBSD image boots reliably, revisit a custom bootloader.

Expected component changes:

- `CrystallineLattice`: remove Linux assumptions where possible. `libudev` may
  be provided through `libudev-devd`, but direct devd/kqueue integration may be
  cleaner long term.
- `snowfall`: replace OpenRC integration with rc.d, verify PAM paths, groups,
  VT/device behavior, and libinput device discovery.
- `SnowCone`: FreeBSD boot graphics handoff may differ from Linux DRM/KMS. Keep
  it optional until the base desktop path is stable.
- `libreldr`: do not block the migration on this. FreeBSD's loader can boot the
  first FreeBSD-based image.
- `Moonshine`: Wine already has FreeBSD awareness upstream, but it remains LGPL
  and needs its own compliance packaging.

## First Engineering Milestone

Create a minimal FreeBSD image builder that does only this:

1. Create a GPT disk image.
2. Add an ESP and UFS root partition.
3. Install FreeBSD base and kernel sets.
4. Install FreeBSD `loader.efi` to the ESP fallback path.
5. Configure root password, a `yeti` user, networking, and SSH or serial login.
6. Boot it in QEMU to a login prompt.

No desktop, no Wine, no splash, no custom loader. Once that works, every later
problem becomes smaller and testable.

## Things To Avoid

- Do not keep describing the product as "MIT only" if BSD-licensed FreeBSD code
  is accepted. Use "permissive-only" or "BSD/MIT-style" instead.
- Do not describe Moonshine/Wine as MIT. Ship it, if included, as an LGPL
  component with the required notices, source access, and replacement path.
- Do not rewrite the desktop stack before the FreeBSD base image boots.
- Do not assume FreeBSD packages are license-safe just because they install with
  `pkg`; packages and ports have their own licenses.
