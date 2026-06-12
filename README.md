<p align="center">
  <img src="docs/underscore.png" alt="Underscore icon" width="128">
</p>


# Underscore

**Audio-side dialogue ducker for Forza Horizon on Linux.** Underscore turns your
music down when someone in the game starts talking, then brings it back up when
they stop — so story dialogue doesn't get buried under
Spotify, and you don't have to ride the volume knob yourself.

It listens to the game's *audio* to decide when dialogue is happening (Forza's
telemetry has no "someone is talking" field), so it works on stock Forza with no
mods. Everything runs locally; nothing is sent anywhere.

---

## What it does

- Detects speech in the game's audio with a small on-device voice-activity model
  (Silero VAD) and smoothly ducks your music player while dialogue plays.
- Controls your player over MPRIS, so it works with Spotify and most other Linux
  media players without touching system volume.
- Optionally reads Forza's "Data Out" telemetry to tell *gameplay* from
  *menus/pauses*, which unlocks policies like "actually pause my music when I
  pause the game."
- Ships as both a GUI (`underscore-gui`) and a headless CLI (`underscore`).

## How it works

Underscore captures the game's audio output through PipeWire, downmixes it to 16
kHz mono, and runs it through Silero VAD frame by frame. When the model's
speech-confidence crosses a threshold it fades your player's volume down to a set
"ducked" level; when speech stops (after a short hangover) it fades back up. A
hysteresis band — a high bar to *start* ducking and a lower bar to *keep* it —
keeps it from flickering on and off mid-sentence.

Volume and transport are driven directly over the session D-Bus using the MPRIS
interface (via `jeepney`, pure-Python), so there's no `playerctl` binary in the
hot path and no per-fade process spawns. `playerctl` and `pactl` remain as
fallbacks.

Forza telemetry is optional and only used by some menu policies (below). Forza
reports the same zeroed packet for the main menu, loading screens, *and* the
pause menu, so a pause can't be told from a menu by telemetry alone — which is
exactly why the default policy keys off the audio instead.

<p align="center">
  <img src="docs/Underscore GUI.png" alt="Underscore GUI" width="640">
</p>

## Requirements

- Linux with **PipeWire** (developed on Arch + KDE Plasma; works without
  `pipewire-pulse`).
- **Python 3**, plus `numpy`, `onnxruntime`, and `jeepney`.
- **PySide6** for the GUI (the CLI runs without it).
- `wireplumber` (`wpctl`) for source/sink queries; `pw-record` for capture (both
  come with PipeWire).
- An MPRIS-capable media player (Spotify by default).

The Silero VAD model (`silero_vad.onnx`, ~2 MB) must sit next to `underscore.py`,
or be pointed to with the `UNDERSCORE_VAD_MODEL` environment variable. Packaged
builds bundle it automatically.

## Installation

Underscore lives on GitHub, but there's no prebuilt binary package yet — you
clone the repo and install locally with one of the methods below.

### Arch (PKGBUILD)

```bash
git clone https://github.com/c1hucktay4lors/Underscore.git
cd Underscore
makepkg -sic
```

`makepkg -sic` builds Underscore from the bundled `PKGBUILD` and installs
it system-wide with pacman. When prompted for an `onnxruntime` provider, choose
**`python-onnxruntime-cpu`** — the VAD is tiny and runs on CPU, so the CUDA/ROCm
builds pull in multi-GB toolkits for no benefit.

### Manual (virtualenv)

```sh
./install.sh
```

This sets up a self-contained environment and installs launchers. See the script
for details.

### From source

```sh
pip install onnxruntime numpy jeepney PySide6-Essentials
python underscore.py --version
```

## First-time CLI setup

**1. Find your player name**

```sh
underscore players
```

Confirm `spotify` (or your player) is listed.

**2. Find the audio to capture**

```sh
underscore sources
```

This lists capturable targets. You want the monitor of whatever sink the game
plays to.

**3. (Optional but recommended) Isolate the game's audio**

If Underscore listens to your *default* output, it will also hear your music and
can trigger on vocals in songs. To avoid that, give the game its own sink:

```sh
underscore setup           # creates a persistent "Underscore_Game" sink
```

Then, in the KDE audio applet (Applications tab), route **Forza's** output to
**Underscore_Game**. Now the VAD hears only the game. Remove it later with
`underscore teardown`.

**4. (Optional) Enable Forza "Data Out"**

Only needed for the `always` and `pause` menu policies. In Forza's settings,
enable **Data Out**, set the IP to `127.0.0.1` and the port to `5335` (Underscore's
default).

## Usage

### GUI

```sh
underscore-gui
```

Pick your player and capture source, set the ducking level and detection
thresholds, and hit Start. Live meters show the model's speech confidence and the
current music level. It minimizes to the system tray.

### CLI

```sh
# Simplest: duck on detected speech, default player (spotify)
underscore run --game-monitor <name-from-sources>

# After `setup`, the game monitor defaults to underscore_game.monitor:
underscore run --player spotify
```

Run `underscore run --help` for the full set of options (thresholds, fade times,
ducking levels, telemetry port, etc.). Ctrl-C stops it and restores your volume.

### Suspending ducking on the fly
---

Sometimes you just want the music at full volume — a favorite track, a quiet
stretch, a cutscene you'd rather hear scored. Underscore has an override toggle
that holds the music up and ignores speech until you turn it back off.

- **GUI:** the **Suspend ducking** button, or the tray entry.
- **Any setup:** `underscore toggle` flips it on a running instance.

For a real "hit a key mid-race" override, bind a keyboard shortcut to that
command. On KDE: **System Settings → Keyboard → Shortcuts → Add New → Command**,
set the command to `underscore toggle`, and assign a key. Works with both the
CLI and the GUI.

> Why a command rather than Underscore grabbing the key itself? On Wayland, apps
> can't capture global hotkeys by design — the compositor owns them. So the
> desktop owns the key and `underscore toggle` just signals the running process,
> which works on both Wayland and X11.

## Menu policies

`--menu-policy` controls how menus and pauses are handled:

- **`speech`** *(default, recommended)* — duck whenever speech is detected, in any
  state. Needs no telemetry. A silent pause leaves music at full; a loading-screen
  briefing ducks because it has speech; menu music is ignored because it isn't
  speech.
- **`always`** — duck whenever telemetry is zeroed (menu/loading), with a grace
  window so a freshly-entered pause stays full for a few seconds.
- **`never`** — only ever duck on speech during live gameplay.
- **`pause`** — like `speech` during gameplay, but when telemetry zeroes it
  actually **pauses** playback (and resumes on return). `--pause-scope from-gameplay`
  (default) only pauses when the zeroed state follows gameplay — a real pause or
  quit — so navigated menus keep playing.

## Configuration

Settings persist to `~/.config/underscore/config.toml` (shared by the GUI and
CLI). Useful knobs and their defaults:

| Setting | Default | Meaning |
|---|---|---|
| `idle` | `0.25` | Music level (fraction of base) while ducking |
| `threshold` | `0.50` | Speech confidence to **start** ducking |
| `release_threshold` | `0.35` | Lower confidence to **keep** ducking (hysteresis) |
| `player` | `spotify` | MPRIS player to control |
| `port` | `5335` | Forza Data Out UDP port |

CLI flags override the saved config for a single run.

## Troubleshooting

**It never ducks.** Check the backend line printed at startup (or the GUI log): it
reads `mpris:spotify` when controlling the player over D-Bus, or `playerctl:…` if
it fell back. If it says it found no target, make sure the player is actually
running and the name matches `underscore players`.

**It ducks on my music, not the game.** Underscore is hearing your music in the
captured audio. Use the virtual-sink isolation (setup, then route Forza into
`Underscore_Game`) so it only hears the game.

**No audio is captured.** Re-check the monitor name with `underscore sources`. The
exact `pw-record` invocation that works varies by PipeWire build; Underscore tries
several automatically and prints a manual test command if none produce audio.

**Pause policy does nothing.** `--menu-policy pause` needs Forza "Data Out" enabled
(IP `127.0.0.1`, port `5335`) and an MPRIS transport backend (the default D-Bus or
playerctl).

## Credits

Created by **c1hucktay4lors**, with help from **Claude**.

Speech detection uses the [Silero VAD](https://github.com/snakers4/silero-vad)
model (MIT).

## License

Released under the MIT License. See [`LICENSE`](LICENSE).
