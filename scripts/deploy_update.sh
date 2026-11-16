#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this updater as root" >&2
  exit 1
fi

ARCHIVE=${1:-/home/zero/auracam-next.tar.gz}
AURA_USER=${2:-zero}
PROJECT_DIR=/opt/auracam
BACKUP_DIR=/opt/auracam-backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUP_DIR/auracam-$STAMP.tar.gz"
SERVICE_WAS_ACTIVE=0
BACKUP_READY=0
MANAGED_ITEMS="auracam protocol_camera.py pyproject.toml README.md scripts supercamera systemd tests"

restart_on_failure() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$BACKUP_READY" -eq 1 ]; then
    for item in $MANAGED_ITEMS; do
      target="$PROJECT_DIR/$item"
      if [ -d "$target" ] && [ ! -L "$target" ]; then
        rm -rf "$target"
      else
        rm -f "$target"
      fi
    done
    tar -xzf "$BACKUP" -C "$PROJECT_DIR" || true
    chown -R root:root "$PROJECT_DIR"
    chmod -R a+rX "$PROJECT_DIR"
    if [ "$SERVICE_WAS_ACTIVE" -eq 1 ]; then
      systemctl start auracam.service || true
    fi
  elif [ "$status" -ne 0 ] && [ "$SERVICE_WAS_ACTIVE" -eq 1 ]; then
    systemctl start auracam.service || true
  fi
  exit "$status"
}
trap restart_on_failure EXIT

[ -f "$ARCHIVE" ] || { echo "Update archive not found: $ARCHIVE" >&2; exit 1; }
id "$AURA_USER" >/dev/null 2>&1 || {
  echo "AuraCam user does not exist: $AURA_USER" >&2
  exit 1
}

install -d -m 0755 "$BACKUP_DIR"
set --
for item in $MANAGED_ITEMS; do
  if [ -e "$PROJECT_DIR/$item" ] || [ -L "$PROJECT_DIR/$item" ]; then
    set -- "$@" "$item"
  fi
done
tar -czf "$BACKUP" -C "$PROJECT_DIR" "$@"
BACKUP_READY=1

if systemctl is-active --quiet auracam.service; then
  SERVICE_WAS_ACTIVE=1
fi
systemctl stop auracam.service

tar -xzf "$ARCHIVE" -C "$PROJECT_DIR"
find "$PROJECT_DIR" -type f -name '._*' -delete
chown -R root:root "$PROJECT_DIR"
chmod -R a+rX "$PROJECT_DIR"

sed "s/@AURA_USER@/$AURA_USER/g" "$PROJECT_DIR/systemd/auracam-sudoers" \
  > /etc/sudoers.d/auracam
chmod 0440 /etc/sudoers.d/auracam
visudo -cf /etc/sudoers.d/auracam >/dev/null

"$PROJECT_DIR/.venv/bin/python" -m compileall -q \
  "$PROJECT_DIR/auracam" "$PROJECT_DIR/protocol_camera.py" \
  "$PROJECT_DIR/supercamera"

systemctl daemon-reload
systemctl start auracam.service
SOCKET_ATTEMPTS=0
while [ ! -S /run/auracam/control.sock ] && [ "$SOCKET_ATTEMPTS" -lt 120 ]; do
  sleep 0.25
  SOCKET_ATTEMPTS=$((SOCKET_ATTEMPTS + 1))
done
systemctl is-active --quiet auracam.service
[ -S /run/auracam/control.sock ] || {
  echo "AuraCam control socket did not become ready" >&2
  exit 1
}
trap - EXIT

echo "AuraCam update installed"
echo "Backup: $BACKUP"
