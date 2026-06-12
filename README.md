<p align="center">
  <img src="docs/underscore.png" width="120" alt="Underscore">
</p>

# Underscore

**Audio-side dialogue ducker for Forza Horizon on Linux.** Underscore turns your
music down when someone in the game starts talking, then brings it back up when
they stop — so story dialogue doesn't get buried under Spotify, and you don't have
to ride the volume knob yourself.

It decides when dialogue is happening by *listening to the game's audio* (Forza's
telemetry has no "someone is talking" field), so it works on stock Forza with no
mods. Everything runs locally; nothing is sent anywhere.

<p align="center">
  <img src="docs/gui.png" width="420" alt="Underscore GUI">
</p>

---

## How it works

Underscore captures the game's audio from a PipeWire monitor and runs it through
the [Silero VAD](https://github.com/snakers4/silero-vad) model (via ONNX Runtime —
no PyTorch) to detect speech. When speech starts it fades your music down; when it
stops it fades back up. Music volume and play/pause are driven over MPRIS through
D-Bus (so any standard player works — Spotify, mpv, etc.), with `playerctl` and
`pactl` as fallbacks.

---

## Requirements

- Linux with **PipeWire** + **WirePlumber** (standard on modern KDE/GNOME)
- **Python 3** (the installer sets up the rest in a private virtualenv)
- An MPRIS-capable music player (Spotify, mpv, …)

The Python libraries (`onnxruntime`, `numpy`, `jeepney`, `PySide6`) are installed
for you — into a venv by `install.sh`, or as system packages by the PKGBUILD.

---

## Installation

### Arch Linux (PKGBUILD)

From the repo root:

```bash
makepkg -si
```

This installs `underscore` and `underscore-gui` to `/usr/bin`, pulls dependencies
through pacman, and registers the app menu entry and icon.

### Any other distro (`install.sh`)

```bash
git clone https://github.com/c1hucktay4lors/Underscore.git
cd Underscore
./install.sh
```

The installer:

1. Detects your package manager (pacman / apt / dnf / zypper) and **asks before
   installing** the system packages it needs (PipeWire tools, WirePlumber,
   libnotify, and Python + venv if missing).
2. Builds a private virtualenv and pip-installs the Python libraries.
3. Installs Underscore under `~/.local/share/underscore` and drops `underscore`
   and `underscore-gui` wrappers in `~/.local/bin`, so the commands work from
   anywhere — no shell alias needed. It also registers the app-menu entry + icon.

If `~/.local/bin` isn't on your `PATH`, the installer tells you the line to add to
`~/.profile`.

To remove everything (your config is left in place):

```bash
./install.sh uninstall
```

> The PKGBUILD and the script install the **same program** — they only differ in
> where things land (system vs. `~/.local`) and how dependencies are provided.

---

## Usage

### GUI

```bash
underscore-gui
```

Also appears in your application menu as **Underscore**. Pick your player and
capture source, hit **Start**, and watch the speech/volume meters. There's a
**Suspend ducking** button and a system-tray entry.

### CLI

```bash
underscore run                 # start ducking
underscore players             # list MPRIS players (find your --player)
underscore sources             # list capture targets (find --game-monitor)
underscore setup               # create an isolated virtual sink for the game
underscore teardown            # remove it
underscore diag                # environment sanity check
```

### Isolating the game audio (recommended)

Capturing your default output works, but it also hears your music, which can
false-trigger on vocals. To feed Underscore *only* the game:

1. `underscore setup` — creates an **Underscore_Game** virtual sink.
2. Route the game's audio into it. KDE: use the audio applet's per-app output.
   GNOME: install `pavucontrol` (GNOME Settings can't route per-app) and, in its
   **Playback** tab, set the game's output device to **Underscore_Game**.
3. Capture `underscore_game.monitor` (the default after `setup`).

Now your music plays to your real speakers untouched while Underscore listens to
the game alone.

> **GNOME note:** the Sound settings panel deliberately hides "monitor" sources,
> so you won't find the game's audio there — pick the capture source inside
> Underscore (the source dropdown / `underscore sources`) instead.

---

## Suspending ducking on the fly

Sometimes you just want the music at full volume — a favorite track or a quiet
stretch. The override toggle holds the music up and ignores speech until you turn
it back off.

- **GUI:** the **Suspend ducking** button, or the tray entry.
- **Anywhere:** `underscore toggle` flips it on a running instance.

For a real "hit a key mid-race" override, bind a keyboard shortcut to that command.
On KDE/GNOME: **Settings → Keyboard → Shortcuts → add a custom command** set to
`underscore toggle`. You'll get a desktop notification confirming each toggle.

> Why a command instead of Underscore grabbing the key itself? On Wayland, apps
> can't capture global hotkeys by design — the compositor owns them. So the desktop
> owns the key and `underscore toggle` just signals the running process, which works
> on both Wayland and X11.

---

## Configuration

Settings are saved to `~/.config/underscore/config.toml` and can be overridden per
run with CLI flags:

| Flag | Purpose |
|------|---------|
| `--player NAME` | MPRIS player to control (default `spotify`) |
| `--game-monitor NAME` | PipeWire monitor to capture |
| `--volume-backend {auto,mpris,playerctl,pactl}` | How to control volume (default `auto`) |
| `--menu-policy {speech,always,never,pause}` | Behavior in menus (default `speech`) |
| `--verbose` | Debug logging |
| `--version` | Print version |

---

## Troubleshooting

- **`underscore sources` is empty or errors** — install the PipeWire/WirePlumber
  CLI tools (`pw-record`, `wpctl`). On Ubuntu: `sudo apt install pipewire-bin wireplumber`.
- **The virtual sink doesn't appear after `setup`** — restart the audio stack:
  `systemctl --user restart pipewire pipewire-pulse wireplumber` (note
  `pipewire-pulse` on distros that ship it, like Ubuntu), or log out and back in.
- **The dock/panel shows a generic icon** — make sure Underscore is *installed*
  (not run loose from a folder) so the `.desktop` entry and icon are registered,
  then log out/in once so the desktop re-reads them. The tray icon is always correct.
- **`underscore toggle` works in a terminal but not from a keyboard shortcut** —
  the shortcut must run a real command, not a shell alias. The installer's
  `~/.local/bin/underscore` wrapper handles this; point the shortcut at
  `underscore toggle` (or the absolute path to the wrapper).

---

## Credits & License

Created by **c1hucktay4lors**, developed in close collaboration with **Claude**
(Anthropic). Speech detection uses the [Silero VAD](https://github.com/snakers4/silero-vad)
model (MIT). Licensed under the **MIT License** — see [LICENSE](LICENSE).
