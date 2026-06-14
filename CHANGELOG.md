# Changelog

All notable changes to Underscore. Versions are pre-1.0 while the project
stabilises; the patch number bumps with each meaningful change. Numbering starts
from when the GUI work began (earlier CLI-only history is not versioned here).

## 0.0.28
- **Inside a duck-zone, ducking now beats the pause policy.** Previously a game
  pause would override geofence ducking; now, while you're parked in a saved spot,
  Underscore keeps the music ducked instead of pausing. The geofence state is
  "sticky" — it survives the brief telemetry blackout when you swap cars, so a car
  swap no longer triggers a pause/resume cycle (or its resume blip); the music just
  stays smoothly ducked. The old `pause_confirm` car-swap holdover is bypassed
  entirely inside zones (it still applies to normal pauses elsewhere).
- **`--geofence-pause-grace` (default 8 s).** How long ducking persists into a
  pause while in a zone before normal pause behaviour resumes — long enough to
  cover a car swap, short enough that quitting to a menu doesn't leave the music
  ducked indefinitely.
- **README:** documented parked/garage ducking — idle-duck, geofence duck-zones,
  marking spots, and the pause-priority behaviour — and expanded the config table.

## 0.0.27
- **Geofence duck-zones (Forza).** You can now mark a spot — sit in a garage and
  hit "Mark Current Spot" (GUI) or run `underscore mark` — and the music ducks
  whenever the car is parked inside that saved location, raising back up the
  instant you drive out of it. Unlike idle-duck (which fires anywhere you stop),
  this only triggers at *your* saved spots, so a stoplight on the open road
  leaves the music alone. Built on the confirmed finding that Forza streams live
  PositionX/Y/Z (offsets 244/248/252) even in the garage, snapping to a fixed
  per-location coordinate.
- **How it works.** Each saved spot is a centre point; "inside" means within a
  per-axis box (default ±20 world units on x, y and z — `--geofence-radius` or
  the "Geofence Size" slider). The box is deliberately small: at ~20 units the
  car's drivable position sits outside it, so the moment you take control the
  music comes back. A game pause still overrides everything (the music
  pauses/mutes as usual). Enable with `--geofence-duck` or the "Duck inside saved
  spots" checkbox.
- **Managing zones.** `underscore mark` records the current spot in a running
  instance (over SIGUSR2, like `toggle`); `underscore mark --clear` or the GUI
  "Clear Zones" button wipes them. Saved zones persist in config.toml and are
  per-save / per-map (the coordinates only mean anything on the map they were
  recorded on). Position offset is `--pos-offset` (244 for FH6) for other titles.

## 0.0.26
- **Transport-mode pausing now works for Flatpak Spotify too.** The previous
  build could only pin a stream that carried identity on its own PipeWire node;
  a Flatpak's node is anonymous ('audio-src', and a useless in-sandbox PID of 4).
  The fix: resolve the stream through its PipeWire *client*, which does carry the
  truth — `application.name`/`binary` = "spotify" and the real host PID in
  `pipewire.sec.pid`. The stream-mute gate now reads `pactl list clients`, folds
  each sink-input's client identity into the match, and pins by the player's PID
  (node PID, client PID, or sec.pid) then by name (node or client labels). Net:
  real track-freeze pausing, blip-free, works for native, browser, and Flatpak
  Spotify — which also clears the path for the Steam Deck (where Spotify is a
  Flatpak). 'mute' mode remains the default and the zero-identification fallback.

## 0.0.25
- **New default pause method: "mute" — the blip is gone for good.** Diagnosis
  (thanks to live pactl/pw traces) showed the player's PipeWire stream is *stable*
  across a pause (it corks/uncorks, same index) — Spotify was never tearing it
  down. The slam came from the uncork-on-Play flush, which MPRIS volume can't
  catch. "mute" mode sidesteps the whole problem: on pause it just drives the
  player's volume to 0 and leaves the stream uncorked and playing; on resume it
  fades back up. Nothing corks, so nothing can flush — no blip, on any player
  (Flatpak, browser, native), with no stream identification needed at all. The
  one trade-off: the track keeps advancing silently while paused. Set
  `--pause-method transport` (or the GUI "Pause Method" dropdown) to get the old
  real-Pause/Play behaviour back, where the track freezes.
- **Transport mode now finds the stream by PID.** When you do want real track-
  freeze pausing, the resume gate now pins the music sink-input by the *PID* of
  the MPRIS player it controls (matching `application.process.id`), instead of by
  a name that may be a generic "audio-src". This makes the blip-free gate work for
  players that expose a PID (browser, native). A sandboxed Flatpak whose stream
  carries no process id still can't be pinned — that's exactly the case "mute"
  mode is for.
- **GUI: "Pause Method" dropdown** (Mute / Transport) in the Ducking group,
  enabled when Menu Policy is "pause".

## 0.0.24
- **Actually killed the pause-resume blip.** The 0.0.23 fix wrote MPRIS volume 0
  on resume, but that's the wrong lever: Spotify restores its *own* volume and
  flushes buffered audio the instant it receives Play, before any MPRIS Volume
  write can land — which is why turning `resume-hold` up to a full second changed
  nothing, and why menu->gameplay (no Play) never blipped. Resume now mutes the
  music stream at the **PipeWire graph level** (server-enforced, instant) for the
  `resume-hold` window, sends Play, starts the fade, then unmutes — so the slam is
  gated where Spotify can't override it. Uses pactl, falling back to wpctl; if
  neither can find the stream it degrades to the old MPRIS-only behaviour. Applies
  to every resume path (Forza pause, BeamNG driving-resume, override-resume).
- **GUI: exposed the resume/pause timing controls.** The Ducking group now has
  "Resume Hold" (mute window that kills the resume blip) and "Pause Confirm" (how
  long a pause must hold before pausing — the garage car-swap filter) sliders,
  matching the `--resume-hold` / `--pause-confirm` flags.

## 0.0.23
- **Fixed the resume blip for real this time.** Players like Spotify snap their
  own volume back to full the instant they receive Play, and that reset was
  landing *after* our mute, leaking a fraction of a second of loud music before
  the fade-in. Resume now holds the volume at 0 and re-writes it every ~10 ms
  across a short window (`--resume-hold`, default 0.2 s), so whenever the player
  resets, it's stomped straight back down — then the fade-in starts. Applies to
  Forza pause-resume and both BeamNG resume paths.
- **Garage car-swaps no longer pause the music.** Switching cars drops telemetry
  for a packet or two while the physics engine reloads (a ~50 ms `IsRaceOn=0`
  blip that read as PAUSED). The pause policy now waits for the pause to hold for
  `--pause-confirm` seconds (default 0.7) before pausing, so those reload blips
  are ignored while genuine pauses still pause. A real pause now stops the music
  ~0.7 s in, which is imperceptible in a menu.

## 0.0.22
- **Idle-duck for Forza (parked / garage).** When the car sits still during
  gameplay — in the garage, or stopped anywhere — Underscore now ducks the music
  after a short timeout, then restores it the instant you move again. Telemetry
  confirmed FH6 keeps the garage as live *gameplay* (engine revs, RPM responds),
  with `Speed` the only thing that goes to zero, so that's the signal used.
  Enable with `--idle-duck` (CLI) or the "Duck when parked / in garage" checkbox
  (GUI). Pair it with `--menu-policy pause` for "duck when idle, pause when
  paused".
- **Configurable idle timing.** `--idle-grace` (default 4 s) sets how long the
  car must be stationary before ducking; `--idle-speed` (default 1.0 m/s) is the
  stopped threshold; `--speed-offset` (default 256, FH6) sets the `Speed` field
  byte offset for other Forza titles. The GUI exposes an "Idle Timeout" slider.
  A safeguard ignores the reading until a real packet provides it, so paused/menu
  frames (which zero the payload) never trigger a false idle-duck.

## 0.0.21
- **Fixed a volume blip on resume.** Coming back from a pause (Forza pause-policy
  or BeamNG driving-resume), some players (e.g. Spotify) jump back to their own
  volume the instant they receive Play, so a fraction of a second of full-volume
  music leaked through before the fade-in started. Resume now slams the volume to
  0 synchronously the instant playback resumes, *then* ramps up — no more blip.
- **More verbose `diag`.** Added a packet-length (`len`) column and a repeatable
  `--watch OFFSET:TYPE` flag (e.g. `--watch 16:f`) that decodes any byte offset
  live — handy for checking fields without code changes, and it works on any
  `--port` (including BeamNG's OutGauge on 4444).

## 0.0.20
- **BeamNG.drive media-sync mode.** Underscore now auto-detects BeamNG's OutGauge
  telemetry (a 96-byte UDP packet, vs Forza's ~324) and switches to a telemetry-only
  mode with no audio capture or VAD: it pauses your music when you're not driving and
  resumes it when you are. "Driving" = OutGauge packets arriving *and* RPM above
  idle-off, which covers all three quiet cases — sim paused (packets stop), on-foot,
  and engine off (packets continue but RPM is 0). A ~1s hold avoids pausing through
  respawns. Notice printed to the terminal and GUI; the override button becomes
  "Keep music playing". Enable OutGauge in BeamNG → `127.0.0.1:4444`. Manual override
  via `--game {auto,forza,beamng}` / `--beamng-port`. (Ignition/accessory awareness
  stays parked for the Lua mod; this is the mod-free path.)
- **Packaging:** PKGBUILD reworked to the verifiable AUR form — code from a pinned
  release tarball (`sha256sums` via `updpkgsums`), the Silero model still pinned to
  its upstream hash, plus documented GPG-signing support — so the sources can be
  integrity-checked instead of `SKIP`ed.

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
