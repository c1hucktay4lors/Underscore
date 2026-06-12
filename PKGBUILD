# Maintainer: c1hucktay4lors <you@example.com>   # <- put your email here
#
# underscore — audio-side dialogue ducker for Forza Horizon.
#
# NOTE ON DEPENDENCIES: the system tools this app uses (playerctl, pipewire,
# wireplumber) are DECLARED below, not bundled — pacman pulls them from the
# repos. The app itself is just two Python files; the ~2 MB Silero VAD model is
# fetched (and checksum-verified) from upstream at a pinned release. Python deps
# are numpy + onnxruntime + pyside6 (no PyTorch).
#
# LOCAL TEST BUILD (no published repo needed):
#   put this PKGBUILD next to underscore.py, underscore_gui.py,
#   underscore.desktop and LICENSE, then:  makepkg -si
# makepkg downloads silero_vad.onnx itself (pinned to silero-vad v6.2.1), so you
# do NOT need the model file locally. The four local files use bare-filename
# source=() entries, so makepkg uses your local copies.
#
# FOR AUR SUBMISSION: replace the four local entries (underscore.py,
# underscore_gui.py, underscore.desktop, LICENSE) with a single release tarball:
#   source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz"
#           "silero_vad.onnx::https://github.com/snakers4/silero-vad/raw/${_vadver}/src/silero_vad/data/silero_vad.onnx")
# and cd into "$srcdir/$pkgname-$pkgver" in package(). Then fill real checksums
# (updpkgsums), test (makepkg -si), and regenerate:  makepkg --printsrcinfo > .SRCINFO
# See RELEASE.md for the full step-by-step.

pkgname=underscore
pkgver=0.0.20
pkgrel=1
pkgdesc="Audio-side dialogue ducker for Forza Horizon on Linux (ducks/pauses your music for in-game dialogue)"
arch=('any')
url="https://github.com/c1hucktay4lors/underscore"
license=('MIT')
install='underscore.install'
# 'python-onnxruntime' is a virtual name provided by several prebuilt packages
# in the official 'extra' repo (python-onnxruntime-cpu / -cuda / -opt-cuda /
# -rocm / -opt-rocm). On a system with none installed, pacman/paru/yay will ask
# which provider to use. Choose python-onnxruntime-cpu: underscore runs the VAD on
# CPUExecutionProvider with a tiny model, so the GPU (cuda/rocm) variants add
# multi-GB toolkits for zero benefit. Depending on the virtual name (not pinning
# -cpu) lets anyone who already has a cuda/rocm build keep it without a conflict.
depends=(
  'python'
  'python-numpy'
  'python-onnxruntime'   # pick the -cpu provider when prompted (see note above)
  'python-jeepney'       # direct D-Bus MPRIS control (no playerctl binary needed)
  'pyside6'              # Qt for the GUI (underscore-gui); CLI works without it
  'pipewire'             # provides pw-record / pw-loopback (capture + routing)
  'wireplumber'          # provides wpctl (sources/default-sink queries)
)
optdepends=(
  'playerctl: fallback MPRIS backend (--volume-backend playerctl)'
  'libnotify: desktop notification when the override toggle is pressed'
  'pipewire-pulse: PulseAudio-compatible capture fallback (parec)'
)
# Pinned to the silero-vad v6.2.1 release tag so the file (and its checksum)
# can never drift. This exact model is the v5-interface ONNX the code expects.
_vadver=v6.2.1
source=(
  'underscore.py'
  'underscore_gui.py'
  'underscore.desktop'
  'underscore.svg'
  'LICENSE'
  "silero_vad.onnx::https://github.com/snakers4/silero-vad/raw/${_vadver}/src/silero_vad/data/silero_vad.onnx"
)
sha256sums=(
  'SKIP'
  'SKIP'
  'SKIP'
  'SKIP'
  'SKIP'
  '1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'
)

package() {
  cd "$srcdir"

  # App code + model together: find_vad_model() looks next to underscore.py, so
  # the model in the same dir means it's found with zero configuration. The GUI
  # (underscore_gui.py) imports underscore, and Python adds the script's own dir
  # to sys.path, so importing it from /usr/share/underscore just works.
  install -Dm644 underscore.py     "$pkgdir/usr/share/underscore/underscore.py"
  install -Dm644 underscore_gui.py "$pkgdir/usr/share/underscore/underscore_gui.py"
  install -Dm644 silero_vad.onnx   "$pkgdir/usr/share/underscore/silero_vad.onnx"

  # Icon: in the app dir (the GUI's run-from-source fallback finds it next to the
  # scripts) AND in the hicolor theme (so the .desktop's `Icon=underscore` and
  # QIcon.fromTheme resolve it). pacman's icon-cache hook refreshes the theme.
  install -Dm644 underscore.svg    "$pkgdir/usr/share/underscore/underscore.svg"
  install -Dm644 underscore.svg \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/underscore.svg"

  # Launchers on PATH: `underscore` (CLI/engine) and `underscore-gui` (window).
  install -d "$pkgdir/usr/bin"
  cat > "$pkgdir/usr/bin/underscore" <<'SH'
#!/bin/sh
exec python /usr/share/underscore/underscore.py "$@"
SH
  cat > "$pkgdir/usr/bin/underscore-gui" <<'SH'
#!/bin/sh
exec python /usr/share/underscore/underscore_gui.py "$@"
SH
  chmod 755 "$pkgdir/usr/bin/underscore" "$pkgdir/usr/bin/underscore-gui"

  # Desktop entry so it shows up in the KDE app launcher.
  install -Dm644 underscore.desktop \
    "$pkgdir/usr/share/applications/underscore.desktop"

  # License (AUR convention: /usr/share/licenses/<pkg>/).
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
