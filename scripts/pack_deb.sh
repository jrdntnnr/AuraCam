#!/bin/sh
# Build the CardputerZero AppStore package from a built tree, on the device.
#
#   sh scripts/build_native.sh
#   cmake -S cardputer -B cardputer/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build cardputer/build -j2
#   sh scripts/pack_deb.sh              -> dist/auracam_<version>_arm64.deb
#
# The store only allows shared directories named after the package:
#
#   /usr/lib/auracam/                      engine, native library, frontend
#   /usr/share/APPLaunch/applications/     launcher entry
#   /usr/share/APPLaunch/share/images/     launcher icon
#   /usr/share/doc/auracam/copyright
set -eu

# Package files are root-owned 644/755 whatever the builder's umask.
umask 022

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PACKAGE=auracam
APP_NAME=AuraCam
MAINTAINER="jrdntnnr <jordanmtanner@gmail.com>"
HOMEPAGE=https://github.com/jrdntnnr/AuraCam
DEPENDS="python3 (>= 3.10), python3-numpy, python3-opencv, python3-picamera2, python3-pil, ffmpeg, libc6"
LIB_DIR=usr/lib/$PACKAGE
LAUNCHER_DIR=usr/share/APPLaunch

cd "$PROJECT_DIR"
VERSION=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' app-builder.json)
FRONTEND=cardputer/build/aura-cardputer
NATIVE=auracam/native/libmlx90640.so
for built in "$FRONTEND" "$NATIVE"; do
  if [ ! -f "$built" ]; then
    echo "Missing $built; build first (see the header of this script)" >&2
    exit 1
  fi
done

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

# Engine and native library; launch.sh finds both relative to itself. The
# Pi's USB UV driver is left out: the Cardputer uses the onboard camera.
mkdir -p "$STAGE/$LIB_DIR"
tar -cf - --exclude=__pycache__ auracam | tar -C "$STAGE/$LIB_DIR" -xf -
chmod 755 "$STAGE/$LIB_DIR/$NATIVE"
install -D -m 755 "$FRONTEND" "$STAGE/$LIB_DIR/$FRONTEND"
install -D -m 755 cardputer/launch.sh "$STAGE/$LIB_DIR/cardputer/launch.sh"

# Launcher entry and icon.
install -D -m 644 cardputer/auracam.png "$STAGE/$LAUNCHER_DIR/share/images/$PACKAGE.png"
mkdir -p "$STAGE/$LAUNCHER_DIR/applications"
cat > "$STAGE/$LAUNCHER_DIR/applications/$PACKAGE.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Camera with MLX90640 thermal fusion
Exec=/$LIB_DIR/cardputer/launch.sh
Icon=share/images/$PACKAGE.png
Terminal=false
DESKTOP

install -D -m 644 LICENSE "$STAGE/usr/share/doc/$PACKAGE/copyright"

# Bytecode is compiled on install (the install tree is not user-writable)
# and removed before uninstall.
mkdir -p "$STAGE/DEBIAN"
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PACKAGE
Version: $VERSION
Architecture: arm64
Maintainer: $MAINTAINER
Installed-Size: $(du -sk "$STAGE/usr" | cut -f1)
Depends: $DEPENDS
Section: APPLaunch
Priority: optional
Homepage: $HOMEPAGE
Description: Camera and MLX90640 thermal fusion for CardputerZero
 Blends an MLX90640 thermal array into the IMX219 camera view as a
 registered heat aura, with a HUD, snapshots and H.264 recording.
CONTROL
cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
python3 -m compileall -q /usr/lib/auracam >/dev/null || true
exit 0
POSTINST
cat > "$STAGE/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
find /usr/lib/auracam -name '*.pyc' -delete
find /usr/lib/auracam -name __pycache__ -type d -empty -delete
exit 0
PRERM
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

mkdir -p dist
OUTPUT="dist/${PACKAGE}_${VERSION}_arm64.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUTPUT"
