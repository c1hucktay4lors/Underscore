#!/usr/bin/env python3
"""
underscore.py — an audio-side dialogue ducker for Forza Horizon on Linux.

Forza's "Data Out" UDP telemetry contains NO dialogue/voiceover field, so
per-line ducking comes from the audio itself (Silero VAD on the game's output).
Telemetry classifies the game *state* and picks a
ducking policy per state.

Backends (no pactl/PulseAudio CLI required)
-------------------------------------------
  Volume   : D-Bus MPRIS via jeepney — default (no playerctl binary). The
             playerctl and `pactl` backends remain as fallbacks.
  Capture  : pw-record (native PipeWire). Falls back to parec if present.
  Isolation: `setup` adds a persistent "Underscore_Game" sink via a PipeWire
             config drop-in; route the game into it so the VAD hears ONLY the
             game and not your music. Optional.

Ducking policy by state
-----------------------
Ducking policy
--------------
FH6 reports only two distinguishable telemetry states: a car is LIVE
(is_race_on=1, engine_max>0 — covers both driving AND the garage), or it is not
(is_race_on=0, engine_max=0 — covers the main menu, loading screens, AND the
pause menu, which are byte-identical: nz=3, pi=0). So pause CANNOT be told from
a menu via telemetry. We resolve this with the audio instead.

  --menu-policy speech  (default, recommended)
        Duck whenever Silero detects speech, in any state. A pause is silent so
        the music stays full; a loading-screen briefing has speech so it ducks;
        menu music isn't speech so it's ignored. Needs no telemetry at all.
  --menu-policy always
        Duck unconditionally whenever telemetry is zeroed (menu/loading), using
        --pause-grace to keep a freshly-entered pause full for a while. A pause
        longer than the grace window will duck (unavoidable: pause==menu here).
  --menu-policy never
        Only ever duck on speech during live gameplay.
  --menu-policy pause
        Combine both: VAD ducks during live gameplay/garage as usual, and when
        telemetry zeroes we actually PAUSE playback (MPRIS pause) and resume on
        return. --pause-scope from-gameplay (default) only pauses when the zeroed
        state follows gameplay (a real pause/quit), so navigated menus and
        loading screens keep playing; all-menus pauses on any zeroed state.
        Requires an MPRIS transport backend (the default D-Bus or
        playerctl) + telemetry.

Diagnosis history: confirmed via `diag` that FH6 zeroes telemetry on pause
(nz=3, pi=0, identical to a menu), which is why the speech policy is the default.

Subcommands
-----------
  players   List MPRIS players (find your music player name).
  sources   List capturable audio targets (find the game monitor name).
  setup     Create a virtual sink to isolate the game (optional).
  run       The ducker.
  diag      Print live telemetry state (pause mid-drive to see FH6 behaviour).
  teardown  Remove the virtual sink created by `setup`.

Quick start
-----------
  pip install onnxruntime numpy jeepney    # torch-free VAD (~50 MB, not ~1 GB)
  ./underscore.py players                       # confirm 'spotify' is listed
  ./underscore.py sources                        # find the monitor to capture
  ./underscore.py run --player spotify --game-monitor <name-from-sources>

  # Optional isolation so music never self-triggers the VAD:
  ./underscore.py setup                          # creates 'underscore_game' virtual sink
  # → route Forza's output to "Underscore_Game" in the KDE audio applet (Applications)
  ./underscore.py run --player spotify           # defaults to underscore_game.monitor

The speech model (silero_vad.onnx) must sit next to underscore.py, or set
UNDERSCORE_VAD_MODEL to its path. Packaged builds bundle it under /usr/share/underscore/.

Author / credits
----------------
Created by c1hucktay4lors, developed in close collaboration with Claude
(Anthropic). Speech detection uses the Silero VAD model (silero-vad, MIT).
Independent Linux project; not affiliated with the Windows app "Segue".

Licensed under the MIT License — see the LICENSE file.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Callable, Optional

# ── Constants ─────────────────────────────────────────────────────────────────
__version__ = "0.0.14"

SINK_NAME = "underscore_game"
SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512            # Silero v5 requires exactly 512 samples @16k
CHUNK_BYTES = CHUNK_SAMPLES * 2
STATE_FILE = "/tmp/underscore.loopback.pid"

OFF_IS_RACE_ON = 0            # int32
OFF_ENGINE_MAX = 8           # float; 0.0 when no car/session loaded
MIN_PACKET = 12

GAMEPLAY, MENU, PAUSED, NO_SIGNAL = "GAMEPLAY", "MENU", "PAUSED", "NO_SIGNAL"


# ── Config (shared by CLI and GUI; persisted to ~/.config/underscore/config.toml) ──
@dataclass
class Config:
    player: str = "spotify"           # MPRIS player to control
    volume_backend: str = "auto"      # auto | mpris | playerctl | pactl
    music_match: str = "spotify"      # stream regex (pactl backend only)
    game_monitor: str = ""            # "" → underscore_game.monitor; "auto" → default sink
    menu_policy: str = "speech"       # speech | always | never | pause
    pause_scope: str = "from-gameplay"  # from-gameplay | all-menus
    idle: float = 0.25                # music level while speech detected
    menu_idle: float = 0.25           # 'always' policy menu level
    threshold: float = 0.5            # Silero prob to START ducking
    release_threshold: float = 0.35   # lower prob to KEEP ducking (hysteresis)
    attack: float = 0.12              # fade-down time (s)
    release: float = 0.9              # fade-up time (s)
    resume_fade: float = 2.0          # pause→play fade-in (s)
    hangover: float = 1000.0          # keep ducking after speech drops (ms)
    pause_grace: float = 20.0         # 'always' policy pause grace (s)
    port: int = 5335                  # Forza Data Out UDP port
    no_telemetry: bool = False        # disable the state machine


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "underscore" / "config.toml"


def load_config() -> Config:
    p = config_path()
    if not p.exists():
        return Config()
    try:
        import tomllib
        with open(p, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:                 # tomllib<3.11 or parse error
        logging.warning("Could not read %s (%s); using defaults.", p, e)
        return Config()
    known = {f.name for f in fields(Config)}
    return Config(**{k: v for k, v in data.items() if k in known})


def save_config(cfg: Config) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# underscore configuration\n"]
    for k, v in asdict(cfg).items():
        if isinstance(v, bool):
            val = "true" if v else "false"
        elif isinstance(v, (int, float)):
            val = repr(v)
        else:
            val = '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
        lines.append(f"{k} = {val}")
    p.write_text("\n".join(lines) + "\n")


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# ── Volume backends ─────────────────────────────────────────────────────────--
class VolumeBackend:
    """Interface: present() -> bool, get() -> float[0..1], set(fraction).
    Transport (pause/play) is optional; supports_transport() reports it."""
    name = "base"
    def present(self) -> bool: raise NotImplementedError
    def get(self) -> float: raise NotImplementedError
    def set(self, fraction: float) -> None: raise NotImplementedError
    def supports_transport(self) -> bool: return False
    def pause(self) -> None: pass
    def play(self) -> None: pass


class PlayerctlBackend(VolumeBackend):
    """Controls a player's MPRIS volume and transport. No PulseAudio needed."""
    def __init__(self, player: str):
        self.player = player
        self.name = f"playerctl:{player}"

    def present(self) -> bool:
        out = _run(["playerctl", "-l"]).stdout.lower()
        return self.player.lower() in out

    def get(self) -> float:
        r = _run(["playerctl", "-p", self.player, "volume"])
        try:
            return max(0.0, min(1.0, float(r.stdout.strip())))
        except ValueError:
            return 1.0

    def set(self, fraction: float) -> None:
        f = max(0.0, min(1.0, fraction))
        _run(["playerctl", "-p", self.player, "volume", f"{f:.4f}"])

    def supports_transport(self) -> bool:
        return True

    def pause(self) -> None:
        _run(["playerctl", "-p", self.player, "pause"])

    def play(self) -> None:
        _run(["playerctl", "-p", self.player, "play"])


class MPRISBackend(VolumeBackend):
    """Controls a player's MPRIS volume + transport directly over the session
    D-Bus, via jeepney (pure-Python). No `playerctl` binary and no subprocess
    spawns — important on locked-down systems (e.g. Steam Deck) and far cheaper
    during fades. A lock serialises access since the fader and engine threads
    may both touch the shared connection."""

    def __init__(self, player: str):
        self.player = player
        self.name = f"mpris:{player}"
        self._conn = None
        self._bus_name: Optional[str] = None
        self._lock = threading.RLock()

    # -- low level ------------------------------------------------------------
    def _conn_get(self):
        if self._conn is None:
            from jeepney.io.blocking import open_dbus_connection
            self._conn = open_dbus_connection(bus="SESSION")
        return self._conn

    def _reset_conn(self) -> None:
        """Drop a dead connection so the next call reconnects. Without this a
        bus drop (suspend/resume, D-Bus restart, player crash) would wedge the
        backend permanently — every later send would reuse the dead socket."""
        with self._lock:
            c, self._conn = self._conn, None
        if c is not None:
            try:
                c.close()
            except Exception:
                pass

    def _addr(self):
        from jeepney import DBusAddress
        return DBusAddress("/org/mpris/MediaPlayer2", bus_name=self._bus_name,
                           interface="org.mpris.MediaPlayer2.Player")

    def _resolve(self) -> Optional[str]:
        """Map self.player ('spotify') to a live bus name
        ('org.mpris.MediaPlayer2.spotify[.instanceN]')."""
        from jeepney import DBusAddress, new_method_call
        try:
            with self._lock:
                conn = self._conn_get()
                dbus = DBusAddress("/org/freedesktop/DBus",
                                   bus_name="org.freedesktop.DBus",
                                   interface="org.freedesktop.DBus")
                names = conn.send_and_get_reply(
                    new_method_call(dbus, "ListNames")).body[0]
        except Exception:
            self._reset_conn()
            return None
        pre = "org.mpris.MediaPlayer2."
        want = self.player.lower()
        cands = [n for n in names if n.startswith(pre)]
        for n in cands:                                  # exact
            if n[len(pre):].lower() == want:
                return n
        for n in cands:                                  # base before .instance
            if n[len(pre):].lower().split(".instance")[0] == want:
                return n
        for n in cands:                                  # loose substring
            if want in n.lower():
                return n
        return None

    def _send(self, msg):
        with self._lock:
            try:
                return self._conn_get().send_and_get_reply(msg)
            except Exception:
                self._reset_conn()       # drop dead socket; caller re-resolves
                raise

    # -- VolumeBackend interface ---------------------------------------------
    def present(self) -> bool:
        self._bus_name = self._resolve()
        return self._bus_name is not None

    def get(self) -> float:
        if self._bus_name is None and not self.present():
            return 1.0
        from jeepney import Properties
        try:
            reply = self._send(Properties(self._addr()).get("Volume"))
            return max(0.0, min(1.0, float(reply.body[0][1])))   # variant (sig, val)
        except Exception:
            return 1.0

    def set(self, fraction: float) -> None:
        f = max(0.0, min(1.0, fraction))
        if self._bus_name is None and not self.present():
            return
        from jeepney import Properties
        try:
            self._send(Properties(self._addr()).set("Volume", "d", f))
        except Exception:
            self._bus_name = None                        # stale; re-resolve once
            if self.present():
                try:
                    self._send(Properties(self._addr()).set("Volume", "d", f))
                except Exception:
                    pass

    def supports_transport(self) -> bool:
        return True

    def pause(self) -> None:
        self._call("Pause")

    def play(self) -> None:
        self._call("Play")

    def _call(self, method: str) -> None:
        if self._bus_name is None and not self.present():
            return
        from jeepney import new_method_call
        try:
            self._send(new_method_call(self._addr(), method))
        except Exception:
            self._bus_name = None


class PactlBackend(VolumeBackend):
    """Per-stream volume via pactl. Only used if you explicitly select it."""
    _VOL_RE = re.compile(r"(\d+)%")

    def __init__(self, match: str):
        self.match = re.compile(match, re.IGNORECASE)
        self.name = f"pactl:{match}"
        self._index: Optional[str] = None

    def _scan(self):
        out = _run(["pactl", "list", "sink-inputs"]).stdout
        cur: dict[str, str] = {}
        best = None
        for line in out.splitlines():
            s = line.strip()
            m = re.match(r"Sink Input #(\d+)", s)
            if m:
                if cur and best is None and self.match.search(cur.get("label", "")):
                    best = cur
                cur = {"index": m.group(1), "label": ""}
            elif s.startswith("Volume:") and "vol" not in cur:
                vm = self._VOL_RE.search(s)
                if vm:
                    cur["vol"] = vm.group(1)
            else:
                pm = re.match(r'(application\.name|media\.name|application\.process\.binary)\s*=\s*"(.*)"', s)
                if pm:
                    cur["label"] = cur.get("label", "") + " " + pm.group(2)
        if cur and best is None and self.match.search(cur.get("label", "")):
            best = cur
        return best

    def present(self) -> bool:
        b = self._scan()
        if b:
            self._index = b["index"]
        return b is not None

    def get(self) -> float:
        b = self._scan()
        if b:
            self._index = b["index"]
            return int(b.get("vol", "100")) / 100.0
        return 1.0

    def set(self, fraction: float) -> None:
        if self._index is None and not self.present():
            return
        pct = max(0, min(100, round(fraction * 100)))
        r = _run(["pactl", "set-sink-input-volume", self._index, f"{pct}%"])
        if r.returncode != 0:          # stream index went stale; re-resolve once
            self._index = None
            if self.present():
                _run(["pactl", "set-sink-input-volume", self._index, f"{pct}%"])


def make_volume_backend(kind: str, player: str, match: str) -> VolumeBackend:
    if kind == "mpris":
        return MPRISBackend(player)
    if kind == "playerctl":
        return PlayerctlBackend(player)
    if kind == "pactl":
        return PactlBackend(match)
    # auto: prefer direct D-Bus MPRIS (no binary, no subprocess spawns),
    # then playerctl, then pactl.
    try:
        import jeepney  # noqa: F401
        mb = MPRISBackend(player)
        if mb.present():
            return mb
    except Exception:
        pass
    if have("playerctl"):
        pc = PlayerctlBackend(player)
        if pc.present():
            return pc
    if have("pactl"):
        return PactlBackend(match)
    return MPRISBackend(player)        # surface a clear error later


# ── players / sources discovery ──────────────────────────────────────────────-
def cmd_players(_: argparse.Namespace) -> int:
    if not have("playerctl"):
        print("playerctl not installed.")
        return 1
    out = _run(["playerctl", "-l"]).stdout.strip()
    if not out:
        print("No MPRIS players running. Start Spotify and re-run.")
        return 1
    print("MPRIS players (use one of these with --player):")
    for p in out.splitlines():
        vol = _run(["playerctl", "-p", p, "volume"]).stdout.strip() or "?"
        print(f"  {p}   (volume {vol})")
    return 0


def _pw_nodes() -> Optional[list]:
    """Parse `pw-dump` into (media_class, node_name, description, app) tuples."""
    if not have("pw-dump"):
        return None
    import json
    try:
        data = json.loads(_run(["pw-dump"]).stdout)
    except (ValueError, OSError):
        return None
    out = []
    for o in data:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        p = (o.get("info") or {}).get("props") or {}
        out.append((p.get("media.class", ""), p.get("node.name", ""),
                    p.get("node.description") or p.get("node.nick") or "",
                    p.get("application.name") or p.get("media.name") or ""))
    return out


def _mpris_names_dbus() -> Optional[list]:
    """List MPRIS player names over D-Bus (no playerctl). None on D-Bus failure."""
    try:
        from jeepney.io.blocking import open_dbus_connection
        from jeepney import DBusAddress, new_method_call
        conn = open_dbus_connection(bus="SESSION")
        try:
            dbus = DBusAddress("/org/freedesktop/DBus",
                               bus_name="org.freedesktop.DBus",
                               interface="org.freedesktop.DBus")
            names = conn.send_and_get_reply(
                new_method_call(dbus, "ListNames")).body[0]
        finally:
            conn.close()
    except Exception:
        return None
    pre = "org.mpris.MediaPlayer2."
    out, seen = [], set()
    for n in names:
        if n.startswith(pre):
            base = n[len(pre):].split(".instance")[0]
            if base and base not in seen:
                seen.add(base)
                out.append(base)
    return out


def list_players() -> list:
    """MPRIS player names (for the GUI player picker)."""
    names = _mpris_names_dbus()          # prefer D-Bus (no playerctl binary)
    if names is not None:
        return names
    if not have("playerctl"):
        return []
    try:
        out = _run(["playerctl", "-l"]).stdout.strip()
    except OSError:
        return []
    return [p for p in out.splitlines() if p.strip()] if out else []


def list_capture_targets() -> list:
    """Candidate --game-monitor values: sink monitors + real sources."""
    nodes = _pw_nodes() or []
    out, seen = [], set()
    for media_class, name, _desc, _app in nodes:
        if not name:
            continue
        if "Audio/Sink" in media_class:
            target = name + ".monitor"
        elif "Audio/Source" in media_class and ".monitor" not in name:
            target = name
        else:
            continue
        if target not in seen:
            seen.add(target)
            out.append(target)
    return out


def default_monitor() -> Optional[str]:
    """Monitor source of the current default sink (for --game-monitor auto)."""
    if have("wpctl"):
        out = _run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]).stdout
        m = re.search(r'node\.name = "([^"]+)"', out)
        if m:
            return m.group(1) + ".monitor"
    return None


def cmd_sources(_: argparse.Namespace) -> int:
    """List capturable targets so you can pick a --game-monitor name."""
    nodes = _pw_nodes()
    if nodes is not None:
        sinks = [(n, d) for mc, n, d, _ in nodes if mc == "Audio/Sink"]
        srcs = [(n, d) for mc, n, d, _ in nodes if mc == "Audio/Source"]
        apps = sorted({a or n for mc, n, d, a in nodes
                       if mc.startswith("Stream/Output/Audio")})
        dm = default_monitor()
        print("Capturable sink monitors  (pass one to --game-monitor):\n")
        for n, d in sinks:
            star = "  ← default" if dm and n + ".monitor" == dm else ""
            print(f"  {n}.monitor{star}")
            if d:
                print(f"        {d}")
        if srcs:
            print("\nReal input sources (mics/line-in):")
            for n, d in srcs:
                print(f"  {n}   {d}")
        if apps:
            print("\nApplication audio streams (for `setup --game-match`):")
            for a in apps:
                print(f"  {a}")
        print("\nTip: capturing a sink monitor grabs EVERYTHING on that sink "
              "(incl. your music).\nFor game-only audio, run `setup` and capture "
              "underscore_game.monitor, or use\n--game-monitor auto for the default "
              "sink's monitor (mixed).")
        return 0
    if have("wpctl"):
        print("WirePlumber graph (capture a sink's monitor — its name + '.monitor'):\n")
        print(_run(["wpctl", "status"]).stdout)
        return 0
    print("Neither pw-dump nor wpctl found; cannot list capture targets.")
    return 1


# ── Isolation via a persistent virtual sink (optional) ──────────────────────--
# Instead of a transient `pw-loopback` process (which dies on logout/reboot), we
# write a PipeWire config drop-in that recreates the Underscore_Game sink at
# every session start. It mirrors playback to your real output, so routing the
# game here lets the VAD hear ONLY the game, not your music.
def vsink_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "pipewire" / "pipewire.conf.d" / "underscore.conf"


def vsink_exists() -> bool:
    return vsink_config_path().exists()


def _vsink_conf(real_sink: str) -> str:
    return f"""# Underscore virtual sink — managed by `underscore setup` / `teardown`.
# Audio sent to "Underscore_Game" is mirrored to your real output ({real_sink}),
# so route your game here to capture its audio without your music self-triggering
# speech detection. Delete this file (or run `underscore teardown`) to remove it.
context.modules = [
    {{ name = libpipewire-module-loopback
        args = {{
            node.description = "Underscore Game"
            capture.props = {{
                media.class      = "Audio/Sink"
                node.name        = "{SINK_NAME}"
                node.description = "Underscore_Game"
                audio.position   = [ FL FR ]
                priority.session = 100
            }}
            playback.props = {{
                node.name      = "{SINK_NAME}.output"
                node.passive   = true
                audio.position = [ FL FR ]
                target.object  = "{real_sink}"
            }}
        }}
    }}
]
"""


def create_virtual_sink() -> tuple:
    """Write the persistent config that creates Underscore_Game. (ok, message)."""
    real = default_monitor()
    real_sink = real[:-len(".monitor")] if real and real.endswith(".monitor") else None
    if not real_sink or real_sink == SINK_NAME:
        return (False, "Couldn't determine your real output sink (or it's already "
                       "the Underscore sink). Set your hardware output as the "
                       "default, remove the sink, and try again.")
    p = vsink_config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_vsink_conf(real_sink))
    except OSError as e:
        return (False, f"Could not write {p}: {e}")
    return (True, f"Virtual sink configured (mirrors to {real_sink}).")


def remove_virtual_sink() -> tuple:
    """Remove the persistent config (and any leftover transient loopback)."""
    removed = False
    p = vsink_config_path()
    if p.exists():
        try:
            p.unlink()
            removed = True
        except OSError as e:
            return (False, f"Could not remove {p}: {e}")
    try:                                   # migrate: stop an old transient loopback
        with open(STATE_FILE) as f:
            pid = int(f.read().strip())
        try:
            os.kill(pid, signal.SIGTERM)
            removed = True
        except ProcessLookupError:
            pass
        os.remove(STATE_FILE)
    except (FileNotFoundError, ValueError):
        pass
    except OSError:
        pass
    if not removed:
        return (True, "No Underscore sink was configured — nothing to remove.")
    return (True, "Removed the Underscore_Game sink.")


def restart_pipewire() -> tuple:
    """Restart the user's PipeWire stack so the sink change takes effect now."""
    if not have("systemctl"):
        return (False, "systemctl not found — log out and back in to apply.")
    r = _run(["systemctl", "--user", "restart", "pipewire", "wireplumber"])
    if r.returncode != 0:
        return (False, "Restart failed — log out and back in to apply. "
                       + (r.stderr or "").strip())
    return (True, "PipeWire restarted; the change is active now.")


_APPLY_HINT = "Apply now with:  systemctl --user restart pipewire wireplumber"


def cmd_setup(args: argparse.Namespace) -> int:
    ok, msg = create_virtual_sink()
    print(msg)
    if not ok:
        return 1
    print(f"Loads automatically on your next login. {_APPLY_HINT}")
    print("Then route your game's output to 'Underscore_Game' (Applications tab) "
          "and run:")
    print(f"  {sys.argv[0]} run --player spotify --menu-policy pause")
    return 0


def cmd_teardown(_: argparse.Namespace) -> int:
    ok, msg = remove_virtual_sink()
    print(msg)
    if ok:
        print(_APPLY_HINT)
    return 0 if ok else 1


# ── Telemetry state machine ─────────────────────────────────────────────────--
# FH6 zeroes is_race_on AND engine_max on pause, so a pause is byte-identical to
# a menu/garage/loading screen in the only fields we have. We separate them
# behaviourally: a pause is always entered DIRECTLY from gameplay and is short,
# whereas menus/loading are long and not preceded by gameplay. So when we drop
# from GAMEPLAY straight into zeroed telemetry we call it PAUSED (don't duck)
# for `pause_grace` seconds; if it persists past that, it's a real MENU (duck).
class StateTracker:
    def __init__(self, pause_grace: float = 10.0, escalate: bool = True):
        self.pause_grace = pause_grace
        self.escalate = escalate                    # if False, PAUSED is sticky
        self._prev_stable: Optional[str] = None    # last GAMEPLAY or MENU
        self._pause_candidate = False
        self._deadline = 0.0

    def reset(self) -> None:                        # call on NO_SIGNAL/timeout
        self._prev_stable = None
        self._pause_candidate = False

    def update(self, is_race_on: int, engine_max: float, now: float) -> str:
        if is_race_on == 1 and engine_max > 0.0:    # a car is live
            self._prev_stable = GAMEPLAY
            self._pause_candidate = False
            return GAMEPLAY
        # zeroed telemetry from here on
        if self._pause_candidate:
            if self.escalate and now >= self._deadline:
                self._prev_stable = MENU             # grace expired → real menu
                self._pause_candidate = False
                return MENU
            return PAUSED                            # sticky if escalate=False
        if self._prev_stable == GAMEPLAY:            # just left gameplay → pause?
            self._pause_candidate = True
            self._deadline = now + self.pause_grace
            return PAUSED
        self._prev_stable = MENU                      # menu/loading from the start
        return MENU


class TelemetryClassifier:
    def __init__(self, port: int, pause_grace: float = 10.0,
                 escalate: bool = True, timeout: float = 2.0):
        self.state = NO_SIGNAL
        self._port, self._timeout = port, timeout
        self._tracker = StateTracker(pause_grace, escalate)
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self._timeout)
        try:
            sock.bind(("0.0.0.0", self._port))
        except OSError as e:
            logging.warning("Telemetry disabled (bind :%d failed — %s). VAD-only.",
                            self._port, e)
            return
        logging.info("Telemetry on :%d", self._port)
        while self._running:
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                self.state = NO_SIGNAL
                self._tracker.reset()
                continue
            if len(data) < MIN_PACKET:
                continue
            iro = struct.unpack_from("<i", data, OFF_IS_RACE_ON)[0]
            emax = struct.unpack_from("<f", data, OFF_ENGINE_MAX)[0]
            self.state = self._tracker.update(iro, emax, time.monotonic())


# ── Fader (drives any volume backend) ───────────────────────────────────────--
class Fader:
    def __init__(self, set_fn: Callable[[float], None], attack: float,
                 release: float, base: float, tick_hz: float = 25.0):
        self._set = set_fn
        self._attack = max(attack, 0.02)
        self._release = max(release, 0.02)
        self._target = base
        self._current = base
        self._ramp: Optional[float] = None     # one-shot duration override (s)
        self._ramp_step = 0.0                  # fixed per-tick step for linear ramp
        self._tick = 1.0 / tick_hz
        self._lock = threading.Lock()
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def set_target(self, fraction: float) -> None:
        with self._lock:
            self._target = max(0.0, min(1.0, fraction))
            self._ramp = None                  # revert to attack/release timing

    def fade_to(self, fraction: float, duration: float) -> None:
        """Linearly ramp to `fraction` over `duration` s (the pause→play fade-in),
        until reached or a new set_target interrupts it."""
        with self._lock:
            target = max(0.0, min(1.0, fraction))
            ticks = max(duration / self._tick, 1.0)
            self._ramp_step = abs(target - self._current) / ticks
            self._target = target
            self._ramp = max(duration, 0.02)

    def snap(self, fraction: float) -> None:
        with self._lock:
            self._target = self._current = max(0.0, min(1.0, fraction))
            self._ramp = None
        self._set(fraction)

    def current(self) -> float:
        with self._lock:
            return self._current

    def stop(self) -> None:
        self._running = False
        self._t.join(timeout=1)

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                target, current, ramp = self._target, self._current, self._ramp
            diff = target - current
            if abs(diff) > 0.003:
                if ramp:                            # linear ramp (fade_to)
                    step = self._ramp_step if diff > 0 else -self._ramp_step
                else:                               # exponential attack/release
                    dur = self._release if diff > 0 else self._attack
                    step = diff * (self._tick / dur)
                    if abs(step) < 0.004:
                        step = 0.004 if diff > 0 else -0.004
                new = current + step
                if (diff > 0 and new > target) or (diff < 0 and new < target):
                    new = target
                with self._lock:
                    self._current = new
                    if new == target:
                        self._ramp = None      # ramp complete
                self._set(new)
            time.sleep(self._tick)


# ── Audio capture ───────────────────────────────────────────────────────────--
def _capture_variants(target: str) -> list[list[str]]:
    """Ordered candidate pw-record arg-lists (without the output arg) to try.
    On native PipeWire (no pipewire-pulse) the monitor is captured by targeting
    the SINK with stream.capture.sink=true; the '<sink>.monitor' name only exists
    when pipewire-pulse is installed. We try the most-correct forms first."""
    sink = target[:-len(".monitor")] if target.endswith(".monitor") else target
    fmt = ["--rate", str(SAMPLE_RATE), "--channels", "1", "--format", "s16"]
    return [
        ["pw-record", "-P", "stream.capture.sink=true", "--target", sink] + fmt,
        ["pw-record", "--target", sink] + fmt,
        ["pw-record", "--target", f"{sink}.monitor"] + fmt,   # pipewire-pulse only
    ]


def _probe_capture(argv: list[str]) -> bool:
    """Run a capture variant to a temp file briefly; True if bytes actually flow
    (i.e. the flags/target are valid). Silence counts as success — it still means
    the pipeline works; whether anything is routed to the sink is a separate
    question handled later."""
    tmp = "/tmp/underscore_probe.wav"
    try:
        os.remove(tmp)
    except OSError:
        pass
    try:
        subprocess.run(argv + [tmp], timeout=0.8,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass            # expected — capture runs until we time it out
    except OSError:
        return False
    try:
        ok = os.path.getsize(tmp) > 4000
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return ok


def open_capture(target: str) -> subprocess.Popen:
    """Capture a sink's monitor as 16 kHz mono s16 raw PCM on stdout, auto-finding
    the pw-record invocation that works on this PipeWire build."""
    if not have("pw-record"):
        if have("parec"):                         # pipewire-pulse / PulseAudio
            sink = target[:-len(".monitor")] if target.endswith(".monitor") else target
            cmd = ["parec", "-d", f"{sink}.monitor", f"--rate={SAMPLE_RATE}",
                   "--channels=1", "--format=s16le"]
            return subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        raise RuntimeError("Neither pw-record nor parec found (install pipewire).")
    for argv in _capture_variants(target):
        if _probe_capture(argv):
            logging.info("capture: %s", " ".join(argv))
            return subprocess.Popen(argv + ["-"], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
    sink = target[:-len(".monitor")] if target.endswith(".monitor") else target
    raise RuntimeError(
        f"No pw-record invocation produced audio from sink '{sink}'. Check the "
        f"name with `sources`. Test manually:\n"
        f"  pw-record -P stream.capture.sink=true --target {sink} "
        f"--rate 16000 --channels 1 --format s16 /tmp/t.wav\n"
        f"then Ctrl-C and `pw-play /tmp/t.wav` to confirm it has audio.")


def read_exact(stream, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# ── diag ───────────────────────────────────────────────────────────────────--
def cmd_diag(args: argparse.Namespace) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.bind(("0.0.0.0", args.port))
    except OSError as e:
        print(f"Cannot bind UDP :{args.port} — {e}")
        return 1
    print(f"Listening on :{args.port}. Drive, then PAUSE and watch 'nz' (nonzero")
    print("bytes in the packet) and 'pi' (offset 220). A menu/loading screen is")
    print("~3 nz bytes with pi=0. If during a PAUSE nz jumps well above 3 or pi")
    print("stays nonzero, we have a deterministic pause signal — send me the log.")
    print("STATE shows what the grace-period heuristic decides in the meantime.\n")
    print(f"{'time':>8}  {'STATE':<9}{'race_on':>8}{'engine_max':>11}{'nz':>5}{'pi':>6}{'pkt/s':>7}")
    tracker = StateTracker(args.pause_grace)
    count = 0
    last_report = time.monotonic()
    while True:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            tracker.reset()
            print(f"{time.strftime('%H:%M:%S'):>8}  {NO_SIGNAL:<9}{'-':>8}{'-':>11}{'-':>5}{'-':>6}{0.0:>7.1f}")
            continue
        if len(data) < MIN_PACKET:
            continue
        count += 1
        now = time.monotonic()
        iro = struct.unpack_from("<i", data, OFF_IS_RACE_ON)[0]
        emax = struct.unpack_from("<f", data, OFF_ENGINE_MAX)[0]
        state = tracker.update(iro, emax, now)
        if now - last_report >= 0.5:
            rate = count / (now - last_report)
            count = 0
            last_report = now
            nz = sum(1 for b in data if b != 0)
            pi = struct.unpack_from("<i", data, 220)[0] if len(data) >= 224 else 0
            print(f"{time.strftime('%H:%M:%S'):>8}  {state:<9}"
                  f"{iro:>8}{emax:>11.0f}{nz:>5}{pi:>6}{rate:>7.1f}")


# ── run ──────────────────────────────────────────────────────────────────────-
# ── Silero VAD (torch-free, onnxruntime) ────────────────────────────────────--
class SileroVAD:
    """Speech detector via onnxruntime — no torch. Feed 512-sample (32 ms @16k)
    float32 chunks; returns speech probability in [0, 1]. The v5 model threads a
    recurrent state, so feed chunks in order and call reset() between sessions."""

    def __init__(self, model_path: str):
        import numpy as np
        import onnxruntime as ort
        self._np = np
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self._sess = ort.InferenceSession(
            model_path, sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = self._np.zeros((2, 1, 128), dtype=self._np.float32)
        self._context = self._np.zeros((1, 64), dtype=self._np.float32)

    def prob(self, chunk) -> float:
        np = self._np
        x = chunk.reshape(1, -1).astype(np.float32)            # [1, 512]
        # Silero v5/v6 expects 64 samples of left-context prepended to each
        # 512-sample frame (→ 576), threaded across calls. WITHOUT this the
        # model returns ~0 for everything and never detects speech.
        x = np.concatenate([self._context, x], axis=1)         # [1, 576]
        out, self._state = self._sess.run(
            None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -64:]
        return float(out[0][0])


def find_vad_model() -> Optional[str]:
    """Locate silero_vad.onnx: $UNDERSCORE_VAD_MODEL, next to this file, or a
    standard data dir (where the system package installs it)."""
    env = os.environ.get("UNDERSCORE_VAD_MODEL")
    here = Path(__file__).resolve().parent
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    candidates = [
        env,
        here / "silero_vad.onnx",
        Path("/usr/share/underscore/silero_vad.onnx"),
        Path("/usr/local/share/underscore/silero_vad.onnx"),
        Path(data_home) / "underscore" / "silero_vad.onnx",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


# ── Engine (headless core; driven by CLI or GUI) ─────────────────────────────--
class Engine:
    """Headless ducker engine. Drive from CLI or GUI:

        eng = Engine(cfg, on_status=cb)
        err = eng.start()      # None on success, else an error message string
        ...                     # runs in a background thread
        eng.stop()

    Live state lives in eng.status (a dict); on_status(status) fires on changes
    (state/duck/pause); status['volume'] and status['prob'] update continuously
    for a GUI to poll (e.g. a level meter)."""

    def __init__(self, cfg: Config,
                 on_status: Optional[Callable[[dict], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self.on_status = on_status
        self.on_error = on_error
        self.status = {"running": False, "state": NO_SIGNAL, "ducking": False,
                       "paused": False, "prob": 0.0, "volume": 1.0,
                       "backend": "", "monitor": ""}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._vol = None
        self._fader = None
        self._tele = None
        self._cap = None
        self._base = 1.0
        self._music_paused = False
        self._clean_lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> Optional[str]:
        """Set everything up and launch the loop thread. Returns None on success
        or a human-readable error string (so a GUI can surface it)."""
        cfg = self.cfg
        try:
            import numpy as np
            import onnxruntime  # noqa: F401  (presence check)
        except ImportError as e:
            return f"Missing dependency: {e}. Install: pip install onnxruntime numpy"
        model_path = find_vad_model()
        if not model_path:
            return ("Silero VAD model not found. Put silero_vad.onnx next to "
                    "underscore.py or set UNDERSCORE_VAD_MODEL (the package bundles it).")
        self._np = np

        vol = make_volume_backend(cfg.volume_backend, cfg.player, cfg.music_match)
        if not vol.present():
            return (f"Volume backend '{vol.name}' found no target. Start your "
                    f"player; check names with the players command.")
        if cfg.menu_policy == "pause" and not vol.supports_transport():
            return (f"menu-policy 'pause' needs MPRIS transport, which '{vol.name}' "
                    f"lacks. Use the playerctl backend.")

        if cfg.game_monitor == "auto":
            monitor = default_monitor()
            if not monitor:
                return "Could not resolve the default sink monitor; set one (see sources)."
        else:
            monitor = cfg.game_monitor or f"{SINK_NAME}.monitor"
        if not (have("pw-record") or have("parec")):
            return "No capture tool (pw-record or parec). Install pipewire."

        use_tele = (not cfg.no_telemetry) and cfg.menu_policy in ("always", "pause")
        if cfg.menu_policy == "pause" and not use_tele:
            return "menu-policy 'pause' requires telemetry (don't disable it)."

        self._vol = vol
        self._base = vol.get()
        self._fader = Fader(vol.set, cfg.attack, cfg.release, self._base)
        escalate = cfg.menu_policy != "pause"
        self._tele = (TelemetryClassifier(cfg.port, cfg.pause_grace, escalate)
                      if use_tele else None)

        self._vad = SileroVAD(model_path)
        try:
            self._cap = open_capture(monitor)
        except RuntimeError as e:
            self._cleanup()
            return str(e)

        self.status.update(running=True, backend=vol.name, monitor=monitor,
                           volume=self._base, paused=False)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._emit()
        return None

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self._cleanup()
        self.status.update(running=False, state=NO_SIGNAL, ducking=False, paused=False)
        self._emit()

    def _cleanup(self) -> None:
        with self._clean_lock:                 # safe if loop + stop() both call
            if self._tele:
                self._tele.stop()
            if self._music_paused and self._vol:
                self._vol.play()
                self._music_paused = False
            if self._fader:
                self._fader.snap(self._base)
                self._fader.stop()
            if self._cap:
                self._cap.terminate()
                try:                           # reap it so it isn't left a zombie
                    self._cap.wait(timeout=1)
                except Exception:
                    try:
                        self._cap.kill()
                    except Exception:
                        pass
            self._tele = self._fader = self._cap = None

    def _emit(self) -> None:
        if self.on_status:
            try:
                self.on_status(dict(self.status))
            except Exception:
                pass

    def _tick_status(self, state, ducking, prob) -> None:
        changed = (state != self.status["state"] or ducking != self.status["ducking"])
        vol = self._fader.current() if self._fader else self.status["volume"]
        self.status.update(state=state, ducking=ducking,
                           prob=round(prob, 3), volume=round(vol, 3))
        if changed:
            self._emit()

    # -- the loop --------------------------------------------------------------
    def _run(self) -> None:
        np = self._np
        cfg = self.cfg
        vol, fader, tele, vad = self._vol, self._fader, self._tele, self._vad
        stream = self._cap.stdout
        base = self._base
        speech = False
        last_speech = 0.0
        last_state = None
        cmd = base
        self._music_paused = False

        while not self._stop.is_set():
            raw = read_exact(stream, CHUNK_BYTES)
            if raw is None:
                msg = "Capture ended — check the game monitor name (see sources)."
                logging.error(msg)
                if self.on_error:
                    self.on_error(msg)
                break
            now = time.monotonic()

            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            prob = vad.prob(chunk)
            # Hysteresis: high bar to start ducking, lower bar to keep it.
            if prob >= cfg.threshold:
                speech = True
                last_speech = now
            elif speech:
                if prob >= cfg.release_threshold:
                    last_speech = now
                elif (now - last_speech) * 1000.0 >= cfg.hangover:
                    speech = False

            state = tele.state if tele else GAMEPLAY

            if cfg.menu_policy == "pause":
                if cfg.pause_scope == "from-gameplay":
                    want_pause = (state == PAUSED)
                else:
                    want_pause = state in (PAUSED, MENU)
                if want_pause and not self._music_paused:
                    logging.info("pausing + muting (%s)", state)
                    vol.pause()
                    fader.snap(0.0)        # mute now; resume can't blip
                    self._music_paused = True
                    self.status["paused"] = True
                    self._emit()
                elif not want_pause and self._music_paused:
                    logging.info("resuming playback (fade-in %.1fs)", cfg.resume_fade)
                    vol.play()
                    fader.fade_to(base, cfg.resume_fade)
                    cmd = base
                    self._music_paused = False
                    self.status["paused"] = False
                    self._emit()
                if self._music_paused:
                    self._tick_status(state, False, prob)
                    continue

            if cfg.menu_policy in ("speech", "pause"):
                ducking = speech
                menu_duck = False
            elif cfg.menu_policy == "always":
                menu_duck = (state == MENU)
                ducking = menu_duck or (state in (GAMEPLAY, NO_SIGNAL) and speech)
            else:
                menu_duck = False
                ducking = state in (GAMEPLAY, NO_SIGNAL) and speech

            if not ducking:
                target = base
            elif menu_duck:
                target = base * cfg.menu_idle
            else:
                target = base * cfg.idle
            if target != cmd:
                fader.set_target(target)
                cmd = target

            if state != last_state:
                logging.info("state -> %s", state)
                last_state = state

            self._tick_status(state, ducking, prob)

        self.status["running"] = False
        self._cleanup()        # free fader/telemetry even on unexpected capture end
        self._emit()


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        player=args.player, volume_backend=args.volume_backend,
        music_match=args.music_match, game_monitor=(args.game_monitor or ""),
        menu_policy=args.menu_policy, pause_scope=args.pause_scope,
        idle=args.idle, menu_idle=args.menu_idle, threshold=args.threshold,
        release_threshold=args.release_threshold, attack=args.attack,
        release=args.release, resume_fade=args.resume_fade,
        hangover=args.hangover, pause_grace=args.pause_grace,
        port=args.port, no_telemetry=args.no_telemetry)


def cmd_run(args: argparse.Namespace) -> int:
    cfg = config_from_args(args)
    eng = Engine(cfg)
    err = eng.start()
    if err:
        print(err)
        return 1
    logging.info("Backend: %s | monitor: %s | policy: %s",
                 eng.status["backend"], eng.status["monitor"], cfg.menu_policy)
    logging.info("Running. Ctrl-C to stop.")
    stop = threading.Event()
    prev = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_: stop.set())   # systemctl stop, etc.
    try:
        while eng.status["running"] and not stop.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, prev)
    logging.info("Restoring volume and stopping.")
    eng.stop()
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="underscore",
        description="Audio-side dialogue ducker for Forza Horizon on Linux.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    p.add_argument("--version", action="version",
                   version=f"underscore {__version__} — by c1hucktay4lors, "
                           "with Claude (Anthropic); MIT License")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("players", help="List MPRIS players (find your --player)")
    sub.add_parser("sources", help="List capture targets (find --game-monitor)")
    sub.add_parser("setup", help="Create a virtual sink to isolate the game")
    sub.add_parser("teardown", help="Remove the virtual sink")

    r = sub.add_parser("run", help="Run the ducker")
    r.add_argument("--player", default="spotify",
                   help="MPRIS player name to duck (see `players`)")
    r.add_argument("--volume-backend", choices=["auto", "mpris", "playerctl", "pactl"],
                   default="auto", help="How to set volume (playerctl works "
                   "without pipewire-pulse)")
    r.add_argument("--music-match", default="spotify",
                   help="Stream regex for the pactl backend only")
    r.add_argument("--game-monitor", default=None,
                   help="Capture target (see `sources`). Default after `setup` is "
                   f"{SINK_NAME}.monitor; use 'auto' for the default sink's "
                   "monitor (mixed with your music).")
    r.add_argument("--menu-policy", choices=["speech", "always", "never", "pause"],
                   default="speech",
                   help="Behaviour in menu/loading/PAUSE (all identical in FH6). "
                   "speech: duck only on detected speech, so a silent pause stays "
                   "full while loading briefings duck (recommended; needs no "
                   "telemetry). always: duck unconditionally in menus, using "
                   "--pause-grace to exempt a fresh pause. never: only ever duck "
                   "on speech during gameplay. pause: actually PAUSE playback "
                   "(MPRIS) when telemetry zeroes, and duck on speech otherwise.")
    r.add_argument("--pause-scope", choices=["from-gameplay", "all-menus"],
                   default="from-gameplay",
                   help="'pause' policy: from-gameplay pauses playback only when "
                   "zeroed telemetry follows gameplay (a real pause/quit); "
                   "all-menus also pauses on navigated menus and loading screens.")
    r.add_argument("--idle", type=float, default=0.25,
                   help="Music volume while speech is detected (fraction)")
    r.add_argument("--menu-idle", type=float, default=0.25,
                   help="'always' policy only: menu music volume (fraction)")
    r.add_argument("--threshold", type=float, default=0.5,
                   help="Silero probability to START ducking [0-1]")
    r.add_argument("--release-threshold", type=float, default=0.35,
                   help="Lower probability to KEEP ducking (hysteresis) [0-1]")
    r.add_argument("--attack", type=float, default=0.12, help="Fade-down time (s)")
    r.add_argument("--release", type=float, default=0.9,
                   help="Fade-up time after speech ends (s)")
    r.add_argument("--resume-fade", type=float, default=2.0,
                   help="'pause' policy: fade-in time when resuming from a pause (s)")
    r.add_argument("--hangover", type=float, default=1000.0,
                   help="Keep ducking this long after speech drops away (ms)")
    r.add_argument("--pause-grace", type=float, default=20.0,
                   help="'always' policy: after dropping from gameplay into zeroed "
                   "telemetry, keep music full this long before treating it as a "
                   "menu and ducking (s). Pauses longer than this will duck.")
    r.add_argument("--port", type=int, default=5335, help="Forza Data Out UDP port")
    r.add_argument("--no-telemetry", action="store_true",
                   help="Disable state machine; gameplay/VAD policy everywhere")

    d = sub.add_parser("diag", help="Print live telemetry state (find pause behaviour)")
    d.add_argument("--port", type=int, default=5335, help="Forza Data Out UDP port")
    d.add_argument("--pause-grace", type=float, default=10.0,
                   help="Grace window used for the STATE column (s)")
    return p


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    return {
        "players": cmd_players, "sources": cmd_sources,
        "setup": cmd_setup, "teardown": cmd_teardown,
        "run": cmd_run, "diag": cmd_diag,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
