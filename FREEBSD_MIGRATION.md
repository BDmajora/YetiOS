# YetiOS FreeBSD Migration Plan

This is the working plan for the FreeBSD-based YetiOS builder. It is not legal
advice; use it as an engineering and compliance checklist.

## Goal

Build the YetiOS image from FreeBSD release sets and keep YetiOS-owned code
under MIT. FreeBSD itself is BSD/permissive, so the current product boundary is:

```text
FreeBSD base: BSD/permissive
YetiOS-owned build code: MIT
Default alpha packages: none
First boot component: stock FreeBSD loader
In-VM YetiOS assembler: builds libreldr, SnowCone, FrostedWeb, Moonshine
Moonshine/Wine: separate LGPL boundary, installed only by in-VM assemble
```

## Current Alpha Scope

`run.py` prepares the FreeBSD image from the Artix/Linux host. It does not
compile YetiOS-owned FreeBSD components. All host-side build stages live inside
`src/`, and the staged `/assemble` script performs component builds from inside
the FreeBSD VM.

The alpha now does this:

1. Check the host has the Linux image tools from the original Artix builder.
2. Fetch the official FreeBSD `MANIFEST`, `base.txz`, and `kernel.txz`.
3. Verify release sets against the upstream SHA256 values.
4. Extract the release sets into `build/rootfs`.
5. Write the YetiOS hostname, fstab, first-boot account setup, restricted sudo
   helper, and `/assemble` in-VM build script for the `yetios` account.
6. Stage local YetiOS source trees under `/usr/src/yetios/sources`.
7. Install stock FreeBSD `loader.efi` onto the ESP so the VM can boot once
   before libreldr exists.
8. Assemble `build/yetios.img` with Linux host tools as a GPT image with an
   ESP, conservative ext2 YetiOS root partition, persistent FreeBSD UFS
   `/usr/local` partition, and swap partition. The ext2 root is created with
   optional features disabled, default xattr/ACL mount flags cleared, and a
   host-side `e2fsck` pass before the image is accepted. It must still use
   fstab pass `0` because FreeBSD base does not ship `fsck_ext2fs`. The root is
   read-only after first-boot account setup; `/usr/local` is FreeBSD-native
   persistent storage; `/tmp`, `/var`, and `/home` are memory-backed.
9. Grant system libvirt narrow ACL access to the image path.
10. Write `build/YETIOS_FREEBSD_IMAGE.txt`.

It does not install packages, build libreldr, build SnowCone, install
Moonshine, or install the desktop stack from the Artix/Linux host.

After first boot, log in as `yetios` and run `./assemble`. That script runs
inside FreeBSD, formats/mounts `/dev/gpt/yetios-local` as `/usr/local`,
bootstraps `pkg`, installs package candidates from `desktop-packages.txt`,
builds libreldr, builds SnowCone, builds FrostedWeb, builds Moonshine using the
native Wayland configuration, and skips SnowFall until its FreeBSD backend
lands.

## Source Layout

```text
run.py
packages.txt
desktop-packages.txt
src/
  core.py
  rootfs.py
  stage_01_host_check.py
  stage_02_fetch_release.py
  stage_03_stage_root.py
  stage_04_bootstrap_esp.py
  stage_05_assemble_image.py
  stage_06_libvirt_access.py
  stage_07_manifest.py
```

## Immediate Engineering Focus

1. Keep the base image booting to a FreeBSD command line with stock FreeBSD
   loader before assembly.
2. Keep `./assemble` usable from the default `yetios` account.
3. Build `libreldr` and SnowCone inside FreeBSD, then install the quiet YetiOS
   boot handoff from there.
4. Keep the default alpha login as `yetios` / `yetios`.
5. Keep `packages.txt` empty until each package license is reviewed.
6. Decide whether `libreldr` may keep its BSD-licensed `gnu-efi` support layer
   or must be ported to YetiOS-owned/minimal UEFI startup code.
7. Keep package-manager bootstrapping usable from the default admin account:
   `sudo pkg update` uses the restricted YetiOS sudo helper and only permits
   FreeBSD `pkg` commands plus the fixed YetiOS assembler.

## Desktop Component Milestones

1. Build FrostedWeb as the combined compositor/window-manager middle layer for
   the FreeBSD Wayland stack.
2. Keep Moonshine on Wine's native Wayland driver and integrate it through
   FrostedWeb instead of the old CrystallineLattice DRM path.
3. Port `snowfall` from Linux/OpenRC/udev/VT assumptions to FreeBSD rc.d and
   FreeBSD device/input assumptions.
4. Harden SnowCone's FreeBSD framebuffer backend across more physical GPUs.
5. Track Moonshine/Wine as a separate LGPL compliance boundary.

## Compliance Notes

- Do not describe FreeBSD base as MIT; it is BSD/permissive.
- Do not describe Moonshine/Wine as MIT; it remains LGPL.
- Do not add packages to the base image until their licenses are reviewed.
- Treat `desktop-packages.txt` as a development/build candidate list until
  every package license and runtime payload is reviewed.
- Keep ReactOS and similar GPL projects as behavioral references only, not code
  sources.
