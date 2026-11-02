#!/usr/bin/env bash
# Builds CpSync-x86_64.AppImage.
# Needs: a Python env with requirements.txt + pyinstaller ($PYTHON), wl-copy ($WL_COPY
# or on PATH) and appimagetool ($APPIMAGETOOL or on PATH).
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python}
WL_COPY=${WL_COPY:-$(command -v wl-copy)}

# Drop Qt's GTK platform theme: it drags the build host's whole GTK stack into
# the bundle (+100 MB) and mixing it with the user's GTK is a known crash source.
find "$($PYTHON -c 'import PySide6, os; print(os.path.dirname(PySide6.__file__))')" -name libqgtk3.so -delete

rm -rf build dist
$PYTHON -m PyInstaller --noconfirm --onedir --name CpSync --python-option u \
  --add-data icon.png:. --add-binary "$WL_COPY:." cpsync_tray.py

# appimagetool chokes on an AppDir that lives inside a git checkout; stage it in /tmp.
APPDIR=$(mktemp -d)/AppDir
mkdir -p "$APPDIR/usr/bin"
cp -r dist/CpSync "$APPDIR/usr/bin/"
cp cpsync.desktop "$APPDIR/" && cp icon.png "$APPDIR/cpsync.png"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
exec "${APPDIR:-$(dirname "$(readlink -f "$0")")}/usr/bin/CpSync/CpSync" "$@"
RUN
chmod +x "$APPDIR/AppRun"

ARCH=x86_64 ${APPIMAGETOOL:-appimagetool} "$APPDIR" "$PWD/CpSync-x86_64.AppImage"
rm -rf "$(dirname "$APPDIR")"
