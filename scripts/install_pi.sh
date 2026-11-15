#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root" >&2
  exit 1
fi

AURA_USER=${1:-zero}
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt

if ! id "$AURA_USER" >/dev/null 2>&1; then
  echo "User $AURA_USER does not exist" >&2
  exit 1
fi

if ! grep -q '^dtparam=i2c_arm=on' "$BOOT_CONFIG"; then
  printf '\ndtparam=i2c_arm=on\n' >> "$BOOT_CONFIG"
fi
if ! grep -q '^dtparam=i2c_arm_baudrate=' "$BOOT_CONFIG"; then
  printf 'dtparam=i2c_arm_baudrate=400000\n' >> "$BOOT_CONFIG"
fi

printf 'i2c-dev\n' > /etc/modules-load.d/auracam-i2c.conf
modprobe i2c-dev || true

for AURA_GROUP in video plugdev i2c; do
  getent group "$AURA_GROUP" >/dev/null 2>&1 || groupadd --system "$AURA_GROUP"
done
usermod -a -G video,plugdev,i2c "$AURA_USER"
install -m 0644 "$PROJECT_DIR/99-supercamera.rules" /etc/udev/rules.d/99-supercamera.rules
udevadm control --reload-rules
udevadm trigger || true

"$PROJECT_DIR/scripts/build_native.sh"
python3 -m venv --system-site-packages "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m compileall -q \
  "$PROJECT_DIR/auracam" "$PROJECT_DIR/protocol_camera.py" "$PROJECT_DIR/supercamera"

install -m 0755 "$PROJECT_DIR/scripts/aura-launcher" /usr/local/bin/aura
sed "s/@AURA_USER@/$AURA_USER/g" "$PROJECT_DIR/systemd/auracam.service" \
  > /etc/systemd/system/auracam.service
chmod 0644 /etc/systemd/system/auracam.service
sed "s/@AURA_USER@/$AURA_USER/g" "$PROJECT_DIR/systemd/auracam-sudoers" \
  > /etc/sudoers.d/auracam
chmod 0440 /etc/sudoers.d/auracam
visudo -cf /etc/sudoers.d/auracam >/dev/null

install -d -o "$AURA_USER" -g "$AURA_USER" -m 0755 \
  "/home/$AURA_USER/.config/auracam" "/home/$AURA_USER/Pictures/auracam"
chown -R root:root "$PROJECT_DIR"
chmod -R a+rX "$PROJECT_DIR"

systemctl daemon-reload
systemctl enable --now ssh.service
systemctl enable --now auracam.service

echo "AuraCam installed. SSH in and run: aura"
