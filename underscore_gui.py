#!/usr/bin/env python3
"""Underscore — a small Qt front-end for the dialogue-ducker engine.

This is a thin GUI over underscore.Engine: it builds a Config from the controls,
calls Engine.start()/stop(), and shows live state. The engine runs on its own
thread, so status updates are marshalled onto the GUI thread via a Qt Signal
(touching widgets from the engine thread directly would be a data race).

Run:  python underscore_gui.py        (needs PySide6: pip install PySide6-Essentials)

Created by c1hucktay4lors, in collaboration with Claude (Anthropic). MIT License.
"""
from __future__ import annotations

import os
import signal
import sys

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QLabel, QComboBox,
    QSlider, QGroupBox, QFormLayout, QVBoxLayout, QHBoxLayout, QGridLayout,
    QProgressBar, QPlainTextEdit, QMessageBox, QSystemTrayIcon, QMenu,
    QTabWidget, QTextBrowser,
)

from underscore import (
    Config, Engine, load_config, save_config, __version__,
    default_monitor, list_players, list_capture_targets,
    vsink_exists, create_virtual_sink, remove_virtual_sink, restart_pipewire,
    _pidfile_path,
)

MENU_POLICIES = ["speech", "always", "never", "pause"]
PAUSE_SCOPES = ["from-gameplay", "all-menus"]


# ── a float-valued slider with an inline value label ─────────────────────────-
class FloatSlider(QWidget):
    def __init__(self, lo: float, hi: float, step: float,
                 fmt: str = "{:.2f}", suffix: str = ""):
        super().__init__()
        self._lo, self._step = lo, step
        self._fmt, self._suffix = fmt, suffix
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(int(round((hi - lo) / step)))
        self.label = QLabel()
        self.label.setMinimumWidth(64)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider.valueChanged.connect(self._refresh)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self._refresh()

    def value(self) -> float:
        return self._lo + self.slider.value() * self._step

    def setValue(self, v: float) -> None:
        self.slider.setValue(int(round((v - self._lo) / self._step)))
        self._refresh()

    def _refresh(self, *_):
        self.label.setText(self._fmt.format(self.value()) + self._suffix)

    def setToolTip(self, text: str) -> None:        # propagate to children
        super().setToolTip(text)
        self.slider.setToolTip(text)
        self.label.setToolTip(text)


# ── thread bridge: engine (worker thread) → GUI thread ───────────────────────-
class EngineBridge(QObject):
    status = Signal(dict)
    error = Signal(str)


def app_icon() -> QIcon:
    """Resolve the Underscore icon: themed name first (installed via hicolor),
    then the bundled SVG next to this script (run-from-source), then a generic
    fallback so there's always *something*."""
    ic = QIcon.fromTheme("underscore")
    if ic.isNull():
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "underscore.svg")
        if os.path.exists(path):
            ic = QIcon(path)
    if ic.isNull():
        ic = QIcon.fromTheme("audio-volume-high")
    return ic


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Underscore")
        self.setWindowIcon(app_icon())
        self.engine: Engine | None = None
        self.bridge = EngineBridge()
        self.bridge.status.connect(self._on_status)   # queued onto GUI thread
        self.bridge.error.connect(self._on_error)

        self._build_ui()
        self._cfg_to_widgets(load_config())
        self._sync_policy_enabled()

        self.poll = QTimer(self)
        self.poll.setInterval(60)                      # ~16 fps meters
        self.poll.timeout.connect(self._poll)

        # let `underscore toggle` (a DE keyboard shortcut) drive the GUI too:
        # SIGUSR1 sets a flag that a steady QTimer processes on the GUI thread
        # (the timer also keeps the Python interpreter ticking under Qt so the
        # signal is actually delivered).
        self._sig_toggle = False
        try:
            signal.signal(signal.SIGUSR1, lambda *_: setattr(self, "_sig_toggle", True))
        except (ValueError, OSError):
            pass                                       # not the main thread / unsupported
        self._sigtimer = QTimer(self)
        self._sigtimer.setInterval(150)
        self._sigtimer.timeout.connect(self._check_signals)
        self._sigtimer.start()

        self._build_tray()

    # -- UI construction ------------------------------------------------------
    def _build_ui(self):
        content = QWidget()
        content.setMaximumWidth(760)      # keep a sane width when maximized
        root = QVBoxLayout(content)

        # header: start/stop + state line
        header = QHBoxLayout()
        self.btn_toggle = QPushButton("Start")
        self.btn_toggle.setMinimumWidth(110)
        self.btn_toggle.clicked.connect(self._toggle)
        self.btn_suspend = QPushButton("Suspend ducking")
        self.btn_suspend.setCheckable(True)
        self.btn_suspend.setEnabled(False)
        self.btn_suspend.setToolTip(
            "Temporarily stop ducking and hold the music at full volume.\n"
            "Also bindable to a desktop shortcut via `underscore toggle`.")
        self.btn_suspend.clicked.connect(self._toggle_override)
        self.lbl_state = QLabel("Stopped")
        self.lbl_state.setStyleSheet("font-weight: 600;")
        header.addWidget(self.btn_toggle)
        header.addWidget(self.btn_suspend)
        header.addWidget(self.lbl_state, 1)
        root.addLayout(header)

        # meters
        meters = QGridLayout()
        meters.addWidget(QLabel("Speech"), 0, 0)
        self.bar_speech = QProgressBar()
        self.bar_speech.setRange(0, 100)
        self.bar_speech.setTextVisible(False)
        meters.addWidget(self.bar_speech, 0, 1)
        meters.addWidget(QLabel("Music Level"), 1, 0)
        self.bar_volume = QProgressBar()
        self.bar_volume.setRange(0, 100)
        self.bar_volume.setTextVisible(False)
        meters.addWidget(self.bar_volume, 1, 1)
        root.addLayout(meters)

        # everything below is locked while running
        self.settings = QWidget()
        slay = QVBoxLayout(self.settings)
        slay.setContentsMargins(0, 0, 0, 0)

        # player & audio
        g_audio = QGroupBox("Player && Monitor")
        f_audio = QFormLayout(g_audio)
        self.cmb_player = QComboBox()
        self.cmb_player.setEditable(True)
        btn_player_refresh = QPushButton("Refresh")
        btn_player_refresh.clicked.connect(self._refresh_players)
        row_player = QHBoxLayout()
        row_player.addWidget(self.cmb_player, 1)
        row_player.addWidget(btn_player_refresh)
        self._w_player = _wrap(row_player)
        f_audio.addRow("Player", self._w_player)

        self.cmb_monitor = QComboBox()
        self.cmb_monitor.setEditable(True)
        self.cmb_monitor.lineEdit().setPlaceholderText(
            "blank = underscore_game.monitor   ·   'auto' = default sink")
        btn_mon_refresh = QPushButton("Refresh")
        btn_mon_refresh.clicked.connect(self._refresh_monitors)
        btn_mon_default = QPushButton("Default Sink")
        btn_mon_default.clicked.connect(self._fill_default_monitor)
        row_mon = QHBoxLayout()
        row_mon.addWidget(self.cmb_monitor, 1)
        row_mon.addWidget(btn_mon_refresh)
        row_mon.addWidget(btn_mon_default)
        self._w_monitor = _wrap(row_mon)
        f_audio.addRow("Game Monitor", self._w_monitor)
        self.btn_vsink = QPushButton()
        self.btn_vsink.clicked.connect(self._toggle_vsink)
        f_audio.addRow(self.btn_vsink)
        self._refresh_vsink_button()
        slay.addWidget(g_audio)

        # ducking
        g_duck = QGroupBox("Ducking")
        f_duck = QFormLayout(g_duck)
        self.cmb_policy = QComboBox()
        self.cmb_policy.addItems(MENU_POLICIES)
        self.cmb_policy.currentTextChanged.connect(self._sync_policy_enabled)
        f_duck.addRow("Menu Policy", self.cmb_policy)
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItems(PAUSE_SCOPES)
        f_duck.addRow("Pause Scope", self.cmb_scope)
        self.sld_idle = FloatSlider(0.0, 1.0, 0.01, "{:.0%}")
        f_duck.addRow("Duck Level", self.sld_idle)
        self.sld_resume = FloatSlider(0.0, 5.0, 0.1, "{:.1f}", " s")
        f_duck.addRow("Resume Fade", self.sld_resume)
        self.sld_attack = FloatSlider(0.02, 1.0, 0.01, "{:.2f}", " s")
        f_duck.addRow("Attack", self.sld_attack)
        self.sld_release = FloatSlider(0.1, 3.0, 0.1, "{:.1f}", " s")
        f_duck.addRow("Release", self.sld_release)
        slay.addWidget(g_duck)

        # detection
        g_det = QGroupBox("Speech Detection (Confidence)")
        f_det = QFormLayout(g_det)
        self.sld_thresh = FloatSlider(0.0, 1.0, 0.01, "{:.0%}")
        f_det.addRow("Start Threshold", self.sld_thresh)
        self.sld_rthresh = FloatSlider(0.0, 1.0, 0.01, "{:.0%}")
        f_det.addRow("Release Threshold", self.sld_rthresh)
        self.sld_hang = FloatSlider(0.0, 3000.0, 50.0, "{:.0f}", " ms")
        f_det.addRow("Hangover", self.sld_hang)
        slay.addWidget(g_det)

        root.addWidget(self.settings)

        # footer: save / reload
        footer = QHBoxLayout()
        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self._save)
        btn_reload = QPushButton("Reload")
        btn_reload.clicked.connect(lambda: self._cfg_to_widgets(load_config()))
        footer.addWidget(btn_save)
        footer.addWidget(btn_reload)
        footer.addStretch(1)
        root.addLayout(footer)

        # log
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMinimumHeight(90)
        root.addWidget(self.log, 1)        # stretch: extra height grows the log

        # center the width-capped content so maximizing looks intentional
        ducker = QWidget()
        outer = QHBoxLayout(ducker)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(content)
        outer.addStretch(1)

        self.tabs = QTabWidget()
        self.tabs.addTab(ducker, "Ducker")
        self.guide_tab = self._build_guide()
        self.tabs.addTab(self.guide_tab, "Guide")
        self.setCentralWidget(self.tabs)
        self._apply_tooltips(f_audio, f_duck, f_det)
        self._refresh_players()
        self._refresh_monitors()

    def _apply_tooltips(self, f_audio, f_duck, f_det):
        """Attach hover help to each control (and its form-row label)."""
        def tip(field, text, form=None, label_owner=None):
            field.setToolTip(text)
            if form is not None:
                lbl = form.labelForField(label_owner if label_owner is not None
                                         else field)
                if lbl:
                    lbl.setToolTip(text)

        tip(self.btn_toggle,
            "Start or stop ducking. While running, the settings below are "
            "locked — press Stop to change them.")
        tip(self.bar_speech,
            "Live speech-detection confidence from the game's audio (0–100%).")
        tip(self.bar_volume,
            "Your music's current level, relative to your normal volume.")

        tip(self.cmb_player,
            "Which media player Underscore controls (e.g. spotify). Click "
            "Refresh to list players that are currently running.",
            f_audio, self._w_player)
        tip(self.cmb_monitor,
            "Which audio output Underscore listens to for in-game speech. Leave "
            "blank for the 'underscore_game' virtual sink, type 'auto' for your "
            "default sink, or use Refresh / Default Sink to choose one.",
            f_audio, self._w_monitor)

        tip(self.cmb_policy,
            "How Underscore behaves outside of dialogue — speech: duck only when "
            "it hears a voice (recommended); always: also dim the whole time "
            "you're in a menu; never: duck only during gameplay; pause: actually "
            "pause your music when the game is paused.",
            f_duck)
        tip(self.cmb_scope,
            "Only used by the 'pause' policy. from-gameplay pauses your music "
            "only on a real pause or quit; all-menus also pauses in menus.",
            f_duck)
        tip(self.sld_idle,
            "How quiet your music gets while dialogue is playing, as a share of "
            "your normal volume. Lower = quieter (0% would silence it).",
            f_duck)
        tip(self.sld_resume,
            "How long your music takes to fade back up to full volume after a "
            "pause ends.",
            f_duck)
        tip(self.sld_attack,
            "How quickly the music dips down when speech begins. Smaller = "
            "snappier, larger = smoother.",
            f_duck)
        tip(self.sld_release,
            "How quickly the music rises back toward normal once speech ends. "
            "Larger = gentler.",
            f_duck)

        tip(self.sld_thresh,
            "How sure the speech detector must be (0–100%) that it's hearing a "
            "voice before it starts ducking. Higher = fewer false triggers, but "
            "it may miss quiet speech.",
            f_det)
        tip(self.sld_rthresh,
            "Once ducking, the detector's confidence must fall below this to "
            "stop. Keeping it lower than the start threshold prevents the volume "
            "from flickering when confidence wobbles around the line.",
            f_det)
        tip(self.sld_hang,
            "How long to keep ducking after speech stops, so short gaps between "
            "words don't pop your music back up mid-sentence.",
            f_det)

    # -- config <-> widgets ---------------------------------------------------
    def _cfg_to_widgets(self, c: Config):
        self.cmb_player.setCurrentText(c.player)
        self.cmb_monitor.setCurrentText(c.game_monitor)
        self.cmb_policy.setCurrentText(c.menu_policy)
        self.cmb_scope.setCurrentText(c.pause_scope)
        self.sld_idle.setValue(c.idle)
        self.sld_resume.setValue(c.resume_fade)
        self.sld_attack.setValue(c.attack)
        self.sld_release.setValue(c.release)
        self.sld_thresh.setValue(c.threshold)
        self.sld_rthresh.setValue(c.release_threshold)
        self.sld_hang.setValue(c.hangover)
        self._sync_policy_enabled()

    def _widgets_to_cfg(self) -> Config:
        base = load_config()                     # preserve fields we don't expose
        base.player = self.cmb_player.currentText().strip() or "spotify"
        base.game_monitor = self.cmb_monitor.currentText().strip()
        base.menu_policy = self.cmb_policy.currentText()
        base.pause_scope = self.cmb_scope.currentText()
        base.idle = round(self.sld_idle.value(), 3)
        base.resume_fade = round(self.sld_resume.value(), 2)
        base.attack = round(self.sld_attack.value(), 3)
        base.release = round(self.sld_release.value(), 2)
        base.threshold = round(self.sld_thresh.value(), 3)
        base.release_threshold = round(self.sld_rthresh.value(), 3)
        base.hangover = round(self.sld_hang.value(), 0)
        return base

    def _sync_policy_enabled(self, *_):
        self.cmb_scope.setEnabled(self.cmb_policy.currentText() == "pause")

    # -- pickers --------------------------------------------------------------
    def _refresh_players(self):
        cur = self.cmb_player.currentText()
        self.cmb_player.clear()
        items = list_players() or ["spotify"]
        self.cmb_player.addItems(items)
        self.cmb_player.setCurrentText(cur or items[0])

    def _refresh_monitors(self):
        cur = self.cmb_monitor.currentText()
        self.cmb_monitor.clear()
        self.cmb_monitor.addItems(list_capture_targets())
        self.cmb_monitor.setCurrentText(cur)

    def _fill_default_monitor(self):
        m = default_monitor()
        if m:
            self.cmb_monitor.setCurrentText(m)
        else:
            self._append("Could not resolve the default sink (is wpctl present?).")

    def _refresh_vsink_button(self):
        exists = vsink_exists()
        self.btn_vsink.setText(
            "Remove Virtual Sink" if exists else "Create Virtual Sink")
        self.btn_vsink.setToolTip(
            "Create a persistent 'Underscore_Game' audio device. Route your "
            "game's output to it so its audio is captured cleanly without your "
            "music self-triggering detection. It survives reboots; click again "
            "to remove it.")

    def _toggle_vsink(self):
        ok, msg = (remove_virtual_sink() if vsink_exists()
                   else create_virtual_sink())
        self._append(msg)
        self._refresh_vsink_button()
        if not ok:
            return
        r = QMessageBox.question(
            self, "Apply now?",
            msg + "\n\nRestart PipeWire now to apply it? Your audio will cut out "
            "for a moment. (Otherwise it applies at your next login.)")
        if r == QMessageBox.Yes:
            ok2, msg2 = restart_pipewire()
            self._append(msg2)
            if ok2:
                self._refresh_monitors()

    # -- run control ----------------------------------------------------------
    def _toggle(self):
        if self.engine is None:
            self._start()
        else:
            self._stop()

    def _start(self):
        cfg = self._widgets_to_cfg()
        eng = Engine(cfg,
                     on_status=self.bridge.status.emit,
                     on_error=self.bridge.error.emit)
        err = eng.start()
        if err:
            QMessageBox.warning(self, "Cannot start", err)
            self._append("Start failed: " + err)
            return
        self.engine = eng
        self.settings.setEnabled(False)
        self.btn_toggle.setText("Stop")
        self.btn_suspend.setEnabled(True)
        self.btn_suspend.setChecked(False)
        self.btn_suspend.setText("Suspend ducking")
        self.lbl_state.setText("Running")
        try:
            with open(_pidfile_path(), "w") as f:      # so `underscore toggle` finds us
                f.write(str(os.getpid()))
        except OSError:
            pass
        self._append("Running — backend %s, monitor %s"
                     % (eng.status["backend"], eng.status["monitor"]))
        self.poll.start()

    def _stop(self):
        self.poll.stop()
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.settings.setEnabled(True)
        self.btn_toggle.setText("Start")
        self.btn_suspend.setEnabled(False)
        self.btn_suspend.setChecked(False)
        self.btn_suspend.setText("Suspend ducking")
        self.lbl_state.setText("Stopped")
        self.bar_speech.setValue(0)
        self.bar_volume.setValue(0)
        try:
            os.remove(_pidfile_path())
        except OSError:
            pass
        self._append("Stopped — volume restored")

    # -- live updates ---------------------------------------------------------
    def _toggle_override(self):
        if not self.engine:
            return
        on = self.engine.toggle_override()
        self.btn_suspend.setChecked(on)
        self.btn_suspend.setText("Resume ducking" if on else "Suspend ducking")
        self._append("Ducking " + ("suspended (override on)" if on else "resumed"))

    def _check_signals(self):
        if self._sig_toggle:
            self._sig_toggle = False
            self._toggle_override()

    def _on_status(self, s: dict):
        ov = s.get("override", False)
        if self.btn_suspend.isChecked() != ov:         # keep button in sync with
            self.btn_suspend.setChecked(ov)            # signal/tray toggles
            self.btn_suspend.setText("Resume ducking" if ov else "Suspend ducking")
        bits = [s.get("state", "—")]
        if ov:
            bits.append("OVERRIDE — ducking off")
        elif s.get("paused"):
            bits.append("PAUSED")
        elif s.get("ducking"):
            bits.append("ducking")
        self.lbl_state.setText("  ·  ".join(bits))

    def _on_error(self, msg: str):
        self._append("Error: " + msg)
        self._stop()

    def _poll(self):
        if not self.engine:
            return
        st = self.engine.status
        self.bar_speech.setValue(int(st.get("prob", 0.0) * 100))
        self.bar_volume.setValue(int(st.get("volume", 0.0) * 100))

    # -- misc -----------------------------------------------------------------
    def _save(self):
        save_config(self._widgets_to_cfg())
        self._append("Settings saved to ~/.config/underscore/config.toml")

    def _append(self, line: str):
        self.log.appendPlainText(line)

    def _build_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(app_icon())
        self.tray.setToolTip(f"Underscore {__version__}")
        menu = QMenu()
        act_show = QAction("Show / Hide", self)
        act_show.triggered.connect(self._toggle_window)
        act_suspend = QAction("Suspend / resume ducking", self)
        act_suspend.triggered.connect(self._toggle_override)
        act_about = QAction("About Underscore", self)
        act_about.triggered.connect(self._about)
        act_quit = QAction("Quit", self)
        act_quit.triggered.connect(self.close)
        menu.addAction(act_show)
        menu.addAction(act_suspend)
        menu.addAction(act_about)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self._toggle_window()
            if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _toggle_window(self):
        self.hide() if self.isVisible() else self.showNormal()

    def _build_guide(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setHtml(self._guide_html())
        lay.addWidget(view)
        return w

    def _guide_html(self) -> str:
        return f"""
        <h2>Underscore</h2>
        <p><i>Audio-side dialogue ducker for Forza Horizon on Linux.</i></p>

        <h3>How it works</h3>
        <p>Underscore captures the game's audio from a PipeWire monitor and runs it
        through a speech-detection model. When in-game dialogue starts it fades your
        music down, then brings it back when the talking stops &mdash; it listens to
        the game's <i>audio</i>, so no mods or game telemetry are needed.</p>

        <h3>Getting game-only audio (recommended)</h3>
        <p>Capturing your default output works, but it also hears your music, which can
        false-trigger on vocals. To feed Underscore only the game:</p>
        <ol>
          <li>Run <b>Setup virtual sink</b> (or <tt>underscore setup</tt>) to create an
              <b>Underscore_Game</b> sink. It mirrors to your current output and follows
              you across device changes (speakers, Bluetooth, HDMI).</li>
          <li>Route the game into it. <b>KDE:</b> use the audio applet's per-app output.
              <b>GNOME:</b> install <tt>pavucontrol</tt> and, in its Playback tab, set the
              game's output to Underscore_Game (GNOME's own settings can't route per-app).</li>
          <li>Pick <b>underscore_game.monitor</b> as the capture source.</li>
        </ol>
        <p><b>GNOME note:</b> the Sound panel hides &ldquo;monitor&rdquo; sources, so the
        game's audio won't appear there &mdash; choose the capture source here in
        Underscore instead.</p>

        <h3>Menu behavior</h3>
        <p>Controls what happens outside of gameplay:</p>
        <ul>
          <li><b>speech</b> (default) &mdash; duck only when speech is detected.</li>
          <li><b>always</b> &mdash; keep music ducked while in menus.</li>
          <li><b>never</b> &mdash; never duck in menus.</li>
          <li><b>pause</b> &mdash; pause the music entirely in menus.</li>
        </ul>

        <h3>Suspending ducking on the fly</h3>
        <p>Use the <b>Suspend ducking</b> button (or the tray entry) to hold the music at
        full volume and ignore speech until you toggle it back. For an in-game key, bind a
        desktop keyboard shortcut to <tt>underscore toggle</tt>. (Apps can't grab global
        hotkeys on Wayland, so the desktop owns the key and signals Underscore &mdash;
        which works on both Wayland and X11.) Each toggle shows a desktop notification.</p>

        <hr>
        <h3>About</h3>
        <p><b>Underscore</b> {__version__}<br>
        Created by <b>c1hucktay4lors</b>, developed in close collaboration with
        <b>Claude</b> (Anthropic).<br>
        Speech detection uses the Silero VAD model
        (<a href="https://github.com/snakers4/silero-vad">silero-vad</a>, MIT).<br>
        Licensed under the MIT License.</p>
        """

    def _about(self):
        # About now lives in the Guide tab — bring the window up and jump there.
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentWidget(self.guide_tab)

    def closeEvent(self, e):
        if self.engine:
            self._stop()
        if getattr(self, "tray", None):
            self.tray.hide()
        e.accept()


def _wrap(layout) -> QWidget:
    w = QWidget()
    layout.setContentsMargins(0, 0, 0, 0)
    w.setLayout(layout)
    return w


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Underscore")
    app.setApplicationDisplayName("Underscore")
    # Wayland uses this as the app_id; GNOME's dock matches it to underscore.desktop
    # to pick the icon. Without it the dock falls back to a generic icon even though
    # the window/tray icon (set via QIcon) is correct.
    app.setDesktopFileName("underscore")
    app.setWindowIcon(app_icon())
    win = MainWindow()
    win.resize(440, 720)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
