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

echo "[yeti] installing sudo and seatd"
mkdir -p /etc/portage/package.use
echo "sys-auth/seatd server" > /etc/portage/package.use/seatd
emerge --noreplace app-admin/sudo
emerge --oneshot sys-auth/seatd
mkdir -p /etc/sudoers.d
echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

# Ensure the seat group exists (seatd should create it, but be safe)
getent group seat >/dev/null 2>&1 || groupadd seat

echo "[yeti] creating user $YETI_USER"
if ! id "$YETI_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G wheel,audio,video,input,seat "$YETI_USER"
fi
usermod -aG seat "$YETI_USER" 2>/dev/null || true
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
# seatd's OpenRC service may not be installed if the binpkg lacked
# the 'server' USE flag.  Write a minimal one ourselves if missing.
if [ ! -f /etc/init.d/seatd ]; then
    echo "[yeti] creating seatd OpenRC service (not shipped by binpkg)"
    cat > /etc/init.d/seatd <<'SEATD_EOF'
#!/sbin/openrc-run

description="Seat management daemon"
command="/usr/bin/seatd"
command_args="-g seat"
command_background=true
pidfile="/run/seatd.pid"

depend() {{
    need udev
}}
SEATD_EOF
    chmod 755 /etc/init.d/seatd
fi
rc-update add seatd boot
rc-update add dhcpcd default
rc-update add elogind boot

echo "[yeti] done"