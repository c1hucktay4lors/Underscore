#!/usr/bin/env bash
#
# install.sh — install Underscore for the current user (Linux + PipeWire).
#
# What it does:
#   1. Detects your package manager and offers to install the system packages
#      Underscore needs (PipeWire tools, WirePlumber, libnotify, Python+venv).
#   2. Creates a private virtualenv and pip-installs the Python libraries.
#   3. Installs Underscore under ~/.local/share/underscore (XDG_DATA_HOME),
#      registers a .desktop entry + icon, and drops `underscore` / `underscore-gui`
#      wrappers in ~/.local/bin so the commands work anywhere — no shell alias.
#
# Everything is user-level (only the system-package step uses sudo). Uninstall with:
#   ./install.sh uninstall
#
set -euo pipefail

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!!\033[0m %s\n' "$*"; }

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"
APPDIR="$DATA/underscore"
DESKTOP="$DATA/applications"
ICONS="$DATA/icons/hicolor"

# ── uninstall ───────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "uninstall" ]]; then
    rm -rf "$APPDIR"
    rm -f "$BIN/underscore" "$BIN/underscore-gui" \
          "$DESKTOP/underscore.desktop" "$ICONS/scalable/apps/underscore.svg"
    update-desktop-database "$DESKTOP" 2>/dev/null || true
    gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true
    say "Uninstalled. (Your config in ~/.config/underscore was left in place.)"
    exit 0
fi

# ── 1. System packages ──────────────────────────────────────────────────────────
# Detect the package manager and the package names that provide what we need.
PM=""; INSTALL=""
PKG_PIPEWIRE=""; PKG_WIREPLUMBER=""; PKG_LIBNOTIFY=""; PKG_PYTHON=""
if   command -v pacman  >/dev/null 2>&1; then
    PM=pacman;  INSTALL="sudo pacman -S --needed --noconfirm"
    PKG_PIPEWIRE=pipewire;       PKG_WIREPLUMBER=wireplumber
    PKG_LIBNOTIFY=libnotify;     PKG_PYTHON="python"
elif command -v apt-get >/dev/null 2>&1; then
    PM=apt;     INSTALL="sudo apt-get install -y"
    PKG_PIPEWIRE=pipewire-bin;   PKG_WIREPLUMBER=wireplumber
    PKG_LIBNOTIFY=libnotify-bin; PKG_PYTHON="python3 python3-venv python3-pip"
elif command -v dnf     >/dev/null 2>&1; then
    PM=dnf;     INSTALL="sudo dnf install -y"
    PKG_PIPEWIRE=pipewire-utils; PKG_WIREPLUMBER=wireplumber
    PKG_LIBNOTIFY=libnotify;     PKG_PYTHON="python3 python3-pip"
elif command -v zypper  >/dev/null 2>&1; then
    PM=zypper;  INSTALL="sudo zypper install -y"
    PKG_PIPEWIRE=pipewire-tools; PKG_WIREPLUMBER=wireplumber
    PKG_LIBNOTIFY=libnotify-tools; PKG_PYTHON="python3 python3-venv python3-pip"
fi

# Only ask for what's actually missing (a desktop usually has PipeWire already).
need=()
command -v pw-record   >/dev/null 2>&1 || need+=("$PKG_PIPEWIRE")
command -v wpctl       >/dev/null 2>&1 || need+=("$PKG_WIREPLUMBER")
command -v notify-send >/dev/null 2>&1 || need+=("$PKG_LIBNOTIFY")
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    need+=($PKG_PYTHON)
fi

if ((${#need[@]})); then
    if [[ -n "$PM" ]]; then
        echo
        say "Underscore needs these system packages:"
        printf '      %s\n' "${need[@]}"
        echo "    (PipeWire/WirePlumber provide pw-record + wpctl; libnotify enables the"
        echo "     override notification; python3+venv build the private environment.)"
        read -rp "    Install them now with $PM? [y/N] " ans
        if [[ "$ans" == [yY]* ]]; then
            $INSTALL "${need[@]}" || warn "Some packages failed to install — you may need to do those by hand."
        else
            warn "Skipping. Underscore may not run until those are installed."
        fi
    else
        warn "Couldn't detect your package manager. Install these with your distro's tools:"
        printf '      %s\n' "${need[@]}"
    fi
else
    say "All required system tools are already present."
fi

# Hard requirement: we need python3 + venv to build the environment.
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
    warn "Python 3 with the venv + pip modules is required but still missing — stopping."
    [[ -n "$PM" ]] && warn "Try:  $INSTALL $PKG_PYTHON"
    exit 1
fi

# ── 2. Install app files + Python environment ────────────────────────────────────
say "Installing Underscore to $APPDIR"
mkdir -p "$APPDIR" "$BIN" "$DESKTOP" "$ICONS/scalable/apps"
if [[ "$SRC" != "$APPDIR" ]]; then
    install -m644 "$SRC/underscore.py" "$SRC/underscore_gui.py" \
                  "$SRC/silero_vad.onnx" "$SRC/underscore.svg" "$APPDIR/"
fi

say "Creating a private virtualenv and installing Python libraries via pip:"
say "  onnxruntime, numpy, jeepney, PySide6  (this can take a minute)"
python3 -m venv "$APPDIR/.venv"
"$APPDIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APPDIR/.venv/bin/pip" install onnxruntime numpy jeepney PySide6

# ── 3. Wrappers, desktop entry, icon ─────────────────────────────────────────────
cat > "$BIN/underscore" <<EOF
#!/usr/bin/env bash
exec "$APPDIR/.venv/bin/python" "$APPDIR/underscore.py" "\$@"
EOF
cat > "$BIN/underscore-gui" <<EOF
#!/usr/bin/env bash
exec "$APPDIR/.venv/bin/python" "$APPDIR/underscore_gui.py" "\$@"
EOF
chmod +x "$BIN/underscore" "$BIN/underscore-gui"

install -m644 "$SRC/underscore.svg" "$ICONS/scalable/apps/underscore.svg"
sed "s|^Exec=.*|Exec=$BIN/underscore-gui|" "$SRC/underscore.desktop" > "$DESKTOP/underscore.desktop"
gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true
update-desktop-database "$DESKTOP" 2>/dev/null || true

# ── 4. PATH check + summary ──────────────────────────────────────────────────────
case ":$PATH:" in
    *":$BIN:"*) : ;;
    *) warn "$BIN isn't on your PATH yet. Add this line to ~/.profile (then re-login):"
       echo "        export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

say "Done."
cat <<EOF

  GUI:           underscore-gui      (also in your app menu as "Underscore")
  CLI:           underscore run
  Override key:  bind a desktop keyboard shortcut to:  underscore toggle
  Uninstall:     ./install.sh uninstall

EOF
