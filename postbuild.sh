#!/bin/bash
set -euo pipefail

# NOTE: this whole script is rendered through Python str.format() (stage 06),
# so literal curly braces must be avoided and shell vars use the bare $VAR
# form only (no brace-delimited expansions).

YETI_USER="{yeti_user}"
HOSTNAME="{hostname}"
TIMEZONE="{timezone}"

echo "[yeti] hostname: $HOSTNAME"
echo "$HOSTNAME" > /etc/hostname
if grep -q localhost /etc/hosts 2>/dev/null; then
    sed -i "s/localhost/$HOSTNAME localhost/" /etc/hosts
else
    echo "127.0.0.1 $HOSTNAME localhost" >> /etc/hosts
fi

echo "[yeti] timezone: $TIMEZONE"
ln -sf "/usr/share/zoneinfo/$TIMEZONE" /etc/localtime

echo "[yeti] locale (en_US.UTF-8)"
sed -i 's/^#en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen
echo "LANG=en_US.UTF-8" > /etc/locale.conf

echo "[yeti] configuring dhcpcd and DNS fallback"
cat > /etc/dhcpcd.conf <<'DHCP_EOF'
# YetiOS dhcpcd configuration — auto-discovers all wired interfaces
hostname
duid
persistent
option rapid_commit
option domain_name_servers, domain_name, domain_search, host_name
option classless_static_routes
option interface_mtu
require dhcp_server_identifier
nohook lookup-hostname
DHCP_EOF

if [ ! -f /etc/resolv.conf ] || [ ! -s /etc/resolv.conf ]; then
    cat > /etc/resolv.conf <<'DNS_EOF'
# Placeholder — dhcpcd will overwrite with DHCP-provided servers.
nameserver 8.8.8.8
nameserver 1.1.1.1
DNS_EOF
fi

echo "[yeti] sudo: wheel group"
mkdir -p /etc/sudoers.d
echo "%wheel ALL=(ALL) ALL" > /etc/sudoers.d/wheel
chmod 440 /etc/sudoers.d/wheel

# seatd-openrc creates the seat group, but be safe.
getent group seat >/dev/null 2>&1 || groupadd seat

echo "[yeti] creating user $YETI_USER"
if ! id "$YETI_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash -G wheel,audio,video,input,seat "$YETI_USER"
fi
usermod -aG seat "$YETI_USER" 2>/dev/null || true
echo "$YETI_USER:yeti" | chpasswd

echo "[yeti] setting root password"
echo "root:root" | chpasswd

echo "[yeti] creating Wine Mono cache directory"
mkdir -p "/home/$YETI_USER/.cache/wine"
chown -R "$YETI_USER:$YETI_USER" "/home/$YETI_USER/.cache"

# NOTE: tty1 autologin is intentionally disabled. snowfall (the login
# manager) runs in the 'default' runlevel and takes over the display
# via DRM. If agetty also opens tty1 with --autologin, it scribbles
# over snowfall's framebuffer and login becomes a race condition.
#
# tty2..tty6 still get a normal agetty, so Ctrl+Alt+F2 etc. still give
# you a text console for recovery.
echo "[yeti] tty1 is owned by snowfall — leaving inittab default"

echo "[yeti] enabling OpenRC services"
# udev (eudev) lives in sysinit; the rest in boot/default.
#
# No elogind SERVICE here: YetiOS installs elogind for its libs/PAM bits but
# uses seatd-openrc (added below) as the init-logind provider — elogind-openrc
# is deliberately omitted (it conflicts with seatd-openrc over init-logind),
# so /etc/init.d/elogind doesn't exist. See packages.txt.
rc-update add udev sysinit || true
rc-update add dbus default || true
rc-update add dhcpcd default || true

# seatd is REQUIRED: the CrystallineLattice compositor (glacier) acquires DRM
# master and input device fds through it (libseat). Without it the graphical
# session can't start and snowfall just loops back to the greeter. Warn LOUDLY
# if the service is missing rather than shipping a non-booting desktop.
if [ -f /etc/init.d/seatd ]; then
    rc-update add seatd boot
else
    echo "[yeti] WARNING: /etc/init.d/seatd missing — install seatd-openrc!" >&2
fi

# Text consoles. Artix's openrc-init has no /etc/inittab; gettys are per-tty
# agetty-openrc services. snowfall owns tty1, so give logins on tty2-tty6
# (Ctrl+Alt+F2..F6) — also the only way to reach a shell if the GUI fails.
if [ -f /etc/init.d/agetty ]; then
    for n in 2 3 4 5 6; do
        ln -sf agetty /etc/init.d/agetty.tty$n
        rc-update add agetty.tty$n default
    done
else
    echo "[yeti] WARNING: agetty-openrc missing — no text consoles / VT switch!" >&2
fi

echo "[yeti] done"
