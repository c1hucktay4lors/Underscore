# Maintainer: c1hucktay4lors <you@example.com>   # <- put your email here
#
# underscore — audio-side dialogue ducker for Forza Horizon (+ BeamNG media-sync).
#
# ── SOURCE INTEGRITY (read this) ──────────────────────────────────────────────
# The AUR hosts only this PKGBUILD, not the code — makepkg downloads the source
# itself. To make that verifiable, the source is a *pinned release tarball* and
# `sha256sums` holds that tarball's hash; makepkg refuses to build on a mismatch,
# so a tampered / MITM'd / silently re-cut release is caught. The Silero VAD model
# is fetched from its canonical upstream and pinned to a real hash (below).
#
# Before publishing each version, regenerate the tarball hash from the REAL
# artifact — do not ship sha256sums=('SKIP') for the tarball (SKIP = "no
# verification", which is exactly what reviewers flag):
#
#     git tag v$pkgver && git push --tags        # publish the release first
#     updpkgsums                                 # fills sha256sums from the tarball
#     makepkg -si                                # test the real build
#     makepkg --printsrcinfo > .SRCINFO          # keep .SRCINFO in sync
#
# CAVEAT: GitHub's auto-generated /archive/ tarballs are not guaranteed byte-
# stable forever. For a hash that can never drift, build a tarball yourself,
# upload it as a Release *asset*, and point source= at that asset URL.
#
# OPTIONAL — GPG-signed releases (strongest; survives a hijacked account/CDN).
# Publish your key once and put its fingerprint in the README; sign each tarball
# asset and upload the .sig, then uncomment:
#     validpgpkeys=('YOUR_KEY_FINGERPRINT')
#     source+=("$pkgname-$pkgver.tar.gz.sig::$url/releases/download/v$pkgver/$pkgname-$pkgver.tar.gz.sig")
#     sha256sums+=('SKIP')   # the .sig is verified by GPG, not by a hash
# ──────────────────────────────────────────────────────────────────────────────

pkgname=underscore
pkgver=0.0.23
pkgrel=1
pkgdesc="Audio-side dialogue ducker for Forza Horizon on Linux (also BeamNG media-sync)"
arch=('any')
url="https://github.com/c1hucktay4lors/underscore"
license=('MIT')
install='underscore.install'
# 'python-onnxruntime' is a virtual name provided by several prebuilt packages
# (python-onnxruntime-cpu / -cuda / -rocm …). Choose the -cpu provider when
# prompted: the VAD runs on CPU with a tiny model, so GPU variants add multi-GB
# toolkits for zero benefit. Depending on the virtual name (not pinning -cpu)
# lets anyone who already has a cuda/rocm build keep it without a conflict.
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

# Code comes from the pinned release tarball; the model from its canonical
# upstream, pinned to the silero-vad v6.2.1 release (this exact ONNX is the
# v5-interface model the code expects, so its checksum can never drift).
_vadver=v6.2.1
source=(
  "$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz"
  "silero_vad.onnx::https://github.com/snakers4/silero-vad/raw/${_vadver}/src/silero_vad/data/silero_vad.onnx"
)
sha256sums=(
  'SKIP'   # <- tarball: replace via `updpkgsums` after tagging the release
  '1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3'  # silero_vad.onnx v6.2.1
)

package() {
  cd "$srcdir/$pkgname-$pkgver"

  # App code. find_vad_model() looks next to underscore.py; the GUI imports
  # underscore and Python adds the script's dir to sys.path, so /usr/share works.
  install -Dm644 underscore.py     "$pkgdir/usr/share/underscore/underscore.py"
  install -Dm644 underscore_gui.py "$pkgdir/usr/share/underscore/underscore_gui.py"

  # The separately-downloaded, hash-pinned model (not the tarball's copy), so the
  # installed model is verified against its canonical upstream checksum.
  install -Dm644 "$srcdir/silero_vad.onnx" "$pkgdir/usr/share/underscore/silero_vad.onnx"

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
