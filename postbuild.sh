#!/bin/bash
set -euo pipefail

YETI_USER="{yeti_user}"
HOSTNAME="{hostname}"
TIMEZONE="{timezone}"

echo "[yeti] hostname: $HOSTNAME"
echo "$HOSTNAME" > /etc/hostname
sed -i "s/localhost/$HOSTNAME localhost/" /etc/hosts || \
    echo "127.0.0.1 $HOSTNAME localhost" >> /etc/hosts

echo "[yeti] timezone: $TIMEZONE"
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime

echo "[yeti] locale"
echo "en_US.UTF-8 UTF-8" > /etc/locale.gen
locale-gen
echo 'LANG="en_US.UTF-8"' > /etc/env.d/02locale
env-update

echo "[yeti] installing sudo"
emerge --noreplace app-admin/sudo
mkdir -p /etc/sudoers.d
echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

echo "[yeti] creating user $YETI_USER"
if ! id "$YETI_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G wheel,audio,video,input "$YETI_USER"
fi
echo "$YETI_USER:yeti" | chpasswd

echo "[yeti] setting root password"
echo "root:root" | chpasswd

# NOTE: tty1 autologin is intentionally disabled. snowfall (the login
# manager) runs in the 'default' runlevel and takes over the display
# via DRM. If agetty also opens tty1 with --autologin, it scribbles
# over snowfall's framebuffer and login becomes a race condition.
#
# tty2..tty6 still get a normal agetty from the default /etc/inittab,
# so Ctrl+Alt+F2 etc. still give you a text console for recovery.
echo "[yeti] tty1 is owned by snowfall — leaving inittab default"

echo "[yeti] enabling services"
rc-update add dhcpcd default
rc-update add elogind boot

echo "[yeti] done"