#!/usr/bin/env bash
#
# install.sh — set up dependencies for Underscore (Linux + PipeWire)
#
# System tools (your distro's package manager):
#   pipewire     — provides pw-record / pw-loopback   (you almost certainly have it)
#   wireplumber  — provides wpctl, used by `sources`   (standard on KDE + PipeWire)
#   playerctl    — OPTIONAL fallback MPRIS backend; the default path is D-Bus via
#                  jeepney (pip), so you don't need playerctl unless you choose it.
#
# Python deps go into a local .venv (so your system Python stays clean and PEP 668
# doesn't complain). The distro provides Python itself; pip provides the rest:
#   onnxruntime (CPU) + numpy   (torch-free VAD)
#   jeepney                     (D-Bus MPRIS control)
#   PySide6                     (the GUI; the CLI runs without it)
#
# Usage:   ./install.sh            # installs into ./.venv
#          VENV=/path ./install.sh # custom venv location
#
set -euo pipefail

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!!\033[0m %s\n' "$*"; }

# Map the running distro to the command that installs Python 3 + venv + pip.
python_install_hint() {
    local ids=""
    [[ -r /etc/os-release ]] && ids="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")"
    case " $ids " in
        *arch*|*manjaro*|*endeavouros*) echo "sudo pacman -S --needed python" ;;
        *ubuntu*|*debian*) echo "sudo apt install -y python3 python3-venv python3-pip" ;;
        *fedora*|*rhel*)   echo "sudo dnf install -y python3 python3-pip" ;;
        *suse*)            echo "sudo zypper install -y python3 python3-venv python3-pip" ;;
        *) echo "(use your package manager to install Python 3 with the venv + pip modules)" ;;
    esac
}

# ── 1. System tools ────────────────────────────────────────────────────────────
if command -v pacman >/dev/null 2>&1; then
    need=()
    command -v pw-record >/dev/null 2>&1 || need+=(pipewire)
    command -v wpctl     >/dev/null 2>&1 || need+=(wireplumber)
    if ((${#need[@]})); then
        say "Installing missing system packages: ${need[*]}"
        sudo pacman -S --needed "${need[@]}"
    else
        say "System tools already present (pw-record, wpctl)."
    fi
    command -v playerctl >/dev/null 2>&1 || \
        say "(playerctl not installed — fine; the default D-Bus backend doesn't need it.)"
else
    warn "Not an Arch/pacman system. Install these with your package manager:"
    warn "  pipewire (for pw-record/pw-loopback) and wireplumber (wpctl)."
    warn "  playerctl is optional (fallback only)."
fi

# ── 2. Python environment ───────────────────────────────────────────────────────
# Prereq: the distro provides Python 3 with venv + pip; pip provides the rest.
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
    warn "Python 3 with the venv + pip modules is required, but wasn't found."
    warn "Install it with your package manager, then re-run ./install.sh :"
    printf '    %s\n' "$(python_install_hint)"
    exit 1
fi

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
