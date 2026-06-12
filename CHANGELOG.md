# Changelog

All notable changes to Underscore. Versions are pre-1.0 while the project
stabilises; the patch number bumps with each meaningful change. Numbering starts
from when the GUI work began (earlier CLI-only history is not versioned here).

## 0.0.19
- **GUI guide tab.** The window is now split into two tabs: **Ducker** (the
  controls) and **Guide**, a scrollable in-app explainer covering how it works,
  getting game-only audio (with the GNOME/pavucontrol note), menu behavior, and the
  override key — with the About/credits/license folded in at the bottom. The tray
  "About" entry now jumps to the Guide tab instead of a popup.

## 0.0.18
- **Virtual sink follows the default output.** `setup` no longer pins the
  Underscore_Game loopback to whichever device was default at setup time — it now
  mirrors to your *current* default output and follows it when you switch devices
  (plug in Bluetooth, HDMI, etc.). No more teardown/re-setup after a device change.
  This also removes the old "couldn't determine your real output sink" failure mode.
  (Re-run `setup` once to adopt the new config.)

## 0.0.17
- **Installer overhaul.** `install.sh` is now a proper user-level installer: it
  detects your package manager (pacman/apt/dnf/zypper), lists the missing system
  packages it needs, and asks before installing them; then builds the pip venv and
  installs Underscore under `~/.local/share/underscore` (XDG_DATA_HOME) with
  `underscore` / `underscore-gui` wrappers in `~/.local/bin`. Same location on
  every distro, no shell alias, and `./install.sh uninstall` cleans it back up.
- **GNOME dock icon.** The GUI now sets its Wayland app_id via
  `setDesktopFileName("underscore")`, and the desktop entry carries
  `StartupWMClass=underscore`, so GNOME's dock/panel matches the window to the
  installed icon instead of showing a generic one. (The tray was already correct.)
- Dropped the "not affiliated with Segue" line from the About dialog.

## 0.0.16
- The override toggle now fires a desktop notification ("Ducking suspended" /
  "Ducking resumed") via `notify-send`, so you get feedback when you hit the key
  mid-game with the GUI hidden. Best-effort: it carries the Underscore app name
  and icon, and silently no-ops if `libnotify`/`notify-send` isn't installed
  (added as a PKGBUILD optdepend).

## 0.0.15
- **On-the-fly override (suspend ducking).** A toggle that holds the music at
  full volume and ignores speech until you toggle back — borrowed from the BeamNG
  mixer. Available as a GUI button + tray entry, and as `underscore toggle`, which
  signals a running instance over `SIGUSR1`. Bind a desktop keyboard shortcut to
  `underscore toggle` for a true override key (this works on Wayland, where apps
  can't grab global hotkeys themselves — the DE owns the key and just pokes the
  process). The running `run`/GUI writes a pidfile so `toggle` can find it.
- `install.sh`: added a Python prerequisite preflight — if `python3`/`venv`/`pip`
  are missing it prints the exact install command for the detected distro
  (pacman/apt/dnf/zypper) instead of failing cryptically, then does the rest via
  pip in the venv. Also corrected the stale "playerctl required" note (it's an
  optional fallback now that D-Bus/jeepney is the default).

## 0.0.14
- Added a proper app icon (`underscore.svg`) — a ducking audio waveform on an
  amber underscore baseline. The desktop entry now uses `Icon=underscore`, and
  the GUI sets it as both the window and tray icon (resolving the themed name
  when installed, the bundled SVG when run from source). The PKGBUILD installs
  it into the hicolor theme and alongside the app.

## 0.0.13
- `run` now handles `SIGTERM` (e.g. `systemctl --user stop`) the same way it
  handles Ctrl-C: it restores the player's volume and stops cleanly, instead of
  being killed mid-duck and leaving the music turned down.
- Added project metadata for release: `LICENSE` (MIT), `README.md`, attribution
  in the GUI About dialog / `--version` / module headers, plus repo hygiene
  (`.gitignore`) and a `RELEASE.md` checklist.

## 0.0.12
- **Stabilization pass (no new features).**
  - D-Bus backend now recovers from a dropped session bus. Previously only the
    player *name* was re-resolved on error, never the connection, so a bus drop
    (suspend/resume, D-Bus restart, player crash) would wedge ducking for the
    rest of the session. It now closes the dead connection and reconnects on the
    next call.
  - The engine frees its fader and telemetry threads if capture ends on its own
    (you quit the game, or the sink disappears) instead of leaking them until
    Stop. `_cleanup` is now lock-guarded so the loop and an explicit stop can't
    race, and the capture child is reaped rather than left a zombie.

## 0.0.11
- **Direct D-Bus MPRIS control.** New `MPRISBackend` talks to the player's
  volume and transport straight over the session bus via `jeepney` (pure-Python)
  — no `playerctl` binary and no per-fade subprocess spawns. It's now the `auto`
  default, with `playerctl` kept as a fallback (`--volume-backend playerctl`).
  Player discovery also goes through D-Bus first.
  - Why: removes the process-spawn overhead during fades and drops the hard
    `playerctl` dependency, which matters on locked-down systems like the Steam
    Deck where you can't `pacman -S playerctl`.
  - Packaging: `python-jeepney` replaces `playerctl` in `depends`; `playerctl`
    is now an optdepend.

## 0.0.10
- **Persistent virtual sink (the big one).** `setup` / `teardown` now write a
  PipeWire config drop-in (`~/.config/pipewire/pipewire.conf.d/underscore.conf`)
  instead of spawning a transient `pw-loopback` process. The `Underscore_Game`
  sink is recreated automatically at every login and survives reboots.
- New GUI **Create / Remove Virtual Sink** button, which can restart PipeWire to
  apply the change immediately.
- Exposed `create_virtual_sink()` / `remove_virtual_sink()` / `restart_pipewire()`
  as library functions.
- Added `--version` and an `__version__` source of truth.

## 0.0.9
- **Fixed onnx speech detection.** The Silero v5/v6 model needs 64 samples of
  left-context prepended to each 512-sample frame; without it the detector
  returned ~0 for everything and never ducked. Now feeds the context correctly —
  verified speech reads ~1.0 and silence stays near 0.

## 0.0.8
- Hover tooltips on every setting (help text on controls and their labels).
- Speech-detection thresholds now display as percentages (confidence), matching
  Duck Level.

## 0.0.7
- GUI layout: content is width-capped and centered so maximizing looks
  intentional; the log pane absorbs extra vertical space (no odd gaps).
- Capitalized on-screen labels and status text; fixed the "Player & Monitor"
  group title (ampersand was being eaten as a mnemonic).

## 0.0.6
- PKGBUILD fetches the Silero model from a pinned upstream release
  (silero-vad v6.2.1) with a verified `sha256` — no local model file needed for
  the build.

## 0.0.5
- Renamed the project to **Underscore** throughout (module, config dir, paths,
  sink name, CLI program name).
- PKGBUILD installs the GUI too: added the `pyside6` dependency, a `.desktop`
  entry, and both `underscore` (CLI) and `underscore-gui` launchers.

## 0.0.4
- PySide6 GUI (`underscore_gui.py`): start/stop, live speech & music-level
  meters, all engine settings, player/monitor pickers, and a system-tray icon.

## 0.0.3
- First Arch packaging: a PKGBUILD that *declares* the system tools
  (playerctl/pipewire/wireplumber) and bundles the model, plus guidance to pick
  the `python-onnxruntime-cpu` provider.

## 0.0.2
- Torch-free speech detection: run Silero VAD through `onnxruntime` instead of
  PyTorch, cutting the dependency footprint from ~1 GB to ~50 MB.

## 0.0.1
- Split the monolithic CLI into an importable module: a `Config` dataclass and
  an `Engine` class with `start()`/`stop()` and a live status callback — the
  seam the GUI and any automation drive. Settings persist to
  `~/.config/underscore/config.toml`.
