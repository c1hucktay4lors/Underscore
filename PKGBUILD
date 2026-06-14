# Maintainer: c1hucktay4lors <you@example.com>   # <- put your email here
#
# underscore — audio-side dialogue ducker for Forza Horizon (+ BeamNG media-sync).
#
# ── LOCAL / OFFLINE BUILD ─────────────────────────────────────────────────────
# This PKGBUILD packages the files sitting next to it — it does NOT download
# anything, so it always builds the exact working tree you have right now. Use it
# to install/test the current version on your own machine. (The AUR-submission
# form, which fetches a pinned release tarball with verified checksums, is kept
# alongside as PKGBUILD.aur for when you publish.)
#
# Build & install from this directory (must contain underscore.py,
# underscore_gui.py, silero_vad.onnx, underscore.svg, underscore.desktop,
# underscore.install, LICENSE):
#
#     makepkg -si            # build and install (pulls deps via pacman)
#     makepkg -si --force    # rebuild after editing the source files
#
# 'SKIP' checksums are correct here: the sources are your own local files, not
# remote downloads, so there is nothing to verify against tampering.
# ──────────────────────────────────────────────────────────────────────────────

pkgname=underscore
pkgver=0.0.28
pkgrel=1
pkgdesc="Audio-side dialogue ducker for Forza Horizon on Linux (also BeamNG media-sync)"
arch=('any')
url="https://github.com/c1hucktay4lors/underscore"
license=('MIT')
install='underscore.install'

# 'python-onnxruntime' is a virtual name provided by several prebuilt packages
# (python-onnxruntime-cpu / -cuda / -rocm …). Choose the -cpu provider when
# prompted: the VAD runs on CPU with a tiny model, so GPU variants pull in
# multi-GB toolkits for zero benefit. Depending on the virtual name (rather than
# pinning -cpu) lets anyone who already has a cuda/rocm build keep it.
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

# Local files only — makepkg copies these from the build directory into $srcdir.
# No URLs, so no network access and nothing to checksum.
source=(
  'underscore.py'
  'underscore_gui.py'
  'silero_vad.onnx'
  'underscore.svg'
  'underscore.desktop'
  'LICENSE'
)
sha256sums=(
  'SKIP'   # underscore.py        (local file)
  'SKIP'   # underscore_gui.py    (local file)
  'SKIP'   # silero_vad.onnx      (local file)
  'SKIP'   # underscore.svg       (local file)
  'SKIP'   # underscore.desktop   (local file)
  'SKIP'   # LICENSE              (local file)
)

package() {
  cd "$srcdir"

  # App code. find_vad_model() looks next to underscore.py; the GUI imports
  # underscore and Python adds the script's dir to sys.path, so /usr/share works.
  install -Dm644 underscore.py     "$pkgdir/usr/share/underscore/underscore.py"
  install -Dm644 underscore_gui.py "$pkgdir/usr/share/underscore/underscore_gui.py"

  # Silero VAD model, alongside the code where find_vad_model() expects it.
  install -Dm644 silero_vad.onnx   "$pkgdir/usr/share/underscore/silero_vad.onnx"

  # Icon: app dir (the GUI's run-from-source fallback) AND the hicolor theme (so
  # the .desktop's Icon=underscore and QIcon.fromTheme resolve). pacman's icon
  # hook refreshes the cache.
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

  # Desktop entry so it shows up in the app launcher.
  install -Dm644 underscore.desktop \
    "$pkgdir/usr/share/applications/underscore.desktop"

  # License (AUR convention: /usr/share/licenses/<pkg>/).
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
