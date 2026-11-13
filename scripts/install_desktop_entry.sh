#!/usr/bin/env bash
# Install the current NeuroPilot icon for the desktop and Alt+Tab switcher.
#
# GNOME/Wayland resolves the app icon through the desktop file named by
# QApplication.setDesktopFileName("neuropilot"), not through the window icon
# alone.  The old installed theme icon can therefore survive a code update.
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
icon="$repo_dir/src/neuropilot/controller/gui/icon.png"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
icon_dir="$data_home/icons/hicolor/256x256/apps"
apps_dir="$data_home/applications"
desktop="$apps_dir/neuropilot.desktop"

if [ ! -f "$icon" ]; then
    echo "icon not found: $icon" >&2
    exit 1
fi

install -Dm644 "$icon" "$icon_dir/neuropilot-lockon.png"
# Keep the old names in sync for existing launchers and the simulator window.
install -Dm644 "$icon" "$icon_dir/neuropilot.png"
install -Dm644 "$icon" "$icon_dir/neuropilot-sim.png"

if [ -f "$desktop" ]; then
    sed -i 's/^Icon=.*/Icon=neuropilot-lockon/' "$desktop"
else
    mkdir -p "$apps_dir"
    cat > "$desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NeuroPilot
Comment=Guided online TMS mapping with online field optimization
Icon=neuropilot-lockon
StartupWMClass=neuropilot
EOF
fi

# A desktop entry without Exec is not launchable.  Preserve an existing one;
# add the current command only when it is available.
if ! grep -q '^Exec=' "$desktop"; then
    exec_path="$(command -v neuropilot || true)"
    if [ -n "$exec_path" ]; then
        sed -i "/^Name=/a Exec=$exec_path" "$desktop"
    fi
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" >/dev/null || true
fi

echo "installed NeuroPilot icon: $icon_dir/neuropilot-lockon.png"
echo "desktop entry: $desktop"
echo "restart NeuroPilot to refresh the Alt+Tab icon"
