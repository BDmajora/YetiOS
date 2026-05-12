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
echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

echo "[yeti] creating user $YETI_USER"
if ! id "$YETI_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G wheel,audio,video,input "$YETI_USER"
fi
echo "$YETI_USER:yeti" | chpasswd

echo "[yeti] setting root password"
echo "root:root" | chpasswd

echo "[yeti] wiring OpenRC autologin on tty1"
sed -i "s|^c1:.*|c1:12345:respawn:/sbin/agetty --autologin $YETI_USER --noclear 38400 tty1 linux|" /etc/inittab

echo "[yeti] enabling services"
rc-update add dhcpcd default
rc-update add elogind boot

echo "[yeti] done"