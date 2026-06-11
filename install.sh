#!/usr/bin/env bash
#
# install.sh — set up dependencies for underscore.py (Arch Linux + PipeWire)
#
# System tools (pacman):
#   playerctl    — volume control over MPRIS (REQUIRED; the pactl-free path)
#   pipewire     — provides pw-record / pw-loopback   (you almost certainly have it)
#   wireplumber  — provides wpctl, used by `sources`   (standard on KDE + PipeWire)
#
# Python (installed into a local .venv so your system Python stays clean and
# PEP 668 doesn't complain):
#   onnxruntime (CPU) + numpy   (torch-free VAD)
#
# Usage:   ./install.sh            # installs into ./.venv
#          VENV=/path ./install.sh # custom venv location
#
set -euo pipefail

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!!\033[0m %s\n' "$*"; }

# ── 1. System tools ────────────────────────────────────────────────────────────
if command -v pacman >/dev/null 2>&1; then
    need=()
    command -v playerctl >/dev/null 2>&1 || need+=(playerctl)
    command -v pw-record >/dev/null 2>&1 || need+=(pipewire)
    command -v wpctl     >/dev/null 2>&1 || need+=(wireplumber)
    if ((${#need[@]})); then
        say "Installing missing system packages: ${need[*]}"
        sudo pacman -S --needed "${need[@]}"
    else
        say "System tools already present (playerctl, pw-record, wpctl)."
    fi
else
    warn "Not an Arch/pacman system. Install these with your package manager:"
    warn "  playerctl, pipewire (for pw-record/pw-loopback), wireplumber (wpctl)"
fi

# ── 2. Python environment ───────────────────────────────────────────────────────
VENV="${VENV:-.venv}"
if [[ ! -d "$VENV" ]]; then
    say "Creating virtualenv at $VENV"
    python3 -m venv "$VENV"
fi
PIP="$VENV/bin/pip"

say "Upgrading pip"
"$PIP" install --upgrade pip >/dev/null

# Torch-free: the VAD runs on onnxruntime (~50 MB) instead of PyTorch (~1 GB).
# PySide6 is for the GUI (underscore_gui.py); the CLI doesn't need it.
say "Installing onnxruntime + numpy + jeepney + PySide6"
"$PIP" install onnxruntime numpy jeepney PySide6-Essentials

# ── 3. Done ─────────────────────────────────────────────────────────────────────
if [[ -f underscore.py ]]; then
    chmod +x underscore.py 2>/dev/null || true
fi

cat <<EOF

$(say "Setup complete.")
Because the Python deps live in $VENV, run the tool with that venv's Python:

    $VENV/bin/python underscore.py players      # confirm your player name
    $VENV/bin/python underscore.py sources       # find the capture monitor
    $VENV/bin/python underscore.py run --player spotify
    $VENV/bin/python underscore_gui.py           # or the graphical version

Optional convenience — add an alias to your shell rc:

    alias underscore="$PWD/$VENV/bin/python $PWD/underscore.py"

(If you'd rather not use a venv, you can instead:
    pip install --user --break-system-packages onnxruntime numpy jeepney PySide6-Essentials
 and then just run ./underscore.py or ./underscore_gui.py directly.)

The speech model (silero_vad.onnx) must sit next to underscore.py, or point
\$UNDERSCORE_VAD_MODEL at it. The system package installs it to /usr/share/underscore/.
EOF
