#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script as root" >&2
  exit 1
fi

BAUD=${1:-1000000}
case "$BAUD" in
  100000|400000|1000000) ;;
  *)
    echo "Supported baud rates: 100000, 400000, 1000000" >&2
    exit 1
    ;;
esac

CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
[ -f "$CONFIG" ] || {
  echo "Raspberry Pi boot config was not found" >&2
  exit 1
}

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$CONFIG.auracam-$STAMP.bak"
TEMP="$CONFIG.auracam-new"
cp -p "$CONFIG" "$BACKUP"

awk -v baud="$BAUD" '
  BEGIN { replaced = 0 }
  /^dtparam=i2c_arm_baudrate=/ {
    if (!replaced) {
      print "dtparam=i2c_arm_baudrate=" baud
      replaced = 1
    }
    next
  }
  { print }
  END {
    if (!replaced) print "dtparam=i2c_arm_baudrate=" baud
  }
' "$CONFIG" > "$TEMP"

chown --reference="$CONFIG" "$TEMP"
chmod --reference="$CONFIG" "$TEMP"
mv "$TEMP" "$CONFIG"
sync

echo "I2C baud configured: $BAUD Hz"
echo "Backup: $BACKUP"
echo "Reboot required"
