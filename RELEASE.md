# Releasing Underscore

A checklist for taking Underscore from a local working copy to a GitHub repo, and
later to the AUR. **Nothing here is done automatically** — this is the manual
runbook. The project is production-ready; you can stop after the GitHub step and
do the AUR part whenever (or never).

Current version: see `__version__` in `underscore.py` (the single source of
truth) and `pkgver` in `PKGBUILD`. Keep them in lockstep.

---

## Repo contents

These files make up the repository:

```
underscore.py          # CLI + engine (importable module)
underscore_gui.py      # PySide6 GUI front-end
silero_vad.onnx        # bundled VAD model (~2 MB) — committed so a clone just runs
underscore.svg         # app / tray icon
underscore.desktop     # KDE/desktop launcher entry
underscore.install     # pacman post-install message
install.sh             # manual venv installer
PKGBUILD               # Arch package (local-build variant active)
LICENSE                # MIT
README.md
CHANGELOG.md
RELEASE.md             # this file
.gitignore
```

Not part of the repo: any `*-backup.zip` snapshots and makepkg build output
(`pkg/`, `src/`, `*.pkg.tar.*`) — these are covered by `.gitignore`.

---

## 1. Run from source (sanity check)

```sh
pip install onnxruntime numpy jeepney PySide6-Essentials
python underscore.py --version
python underscore.py players          # confirm your player shows up
python underscore-gui                 # or: python underscore_gui.py
```

---

## 2. Publish to GitHub

```sh
git init
git add underscore.py underscore_gui.py silero_vad.onnx underscore.svg \
        underscore.desktop underscore.install install.sh PKGBUILD LICENSE \
        README.md CHANGELOG.md RELEASE.md .gitignore
git commit -m "Underscore 0.0.14"

# create the repo on GitHub first (named 'underscore'), then:
git remote add origin git@github.com:c1hucktay4lors/underscore.git
git branch -M main
git push -u origin main

# tag the release so the AUR tarball URL resolves later
git tag -a v0.0.13 -m "0.0.13"
git push origin v0.0.13
```

If you rename the repo or use a different account, update `url=` and the
`# Maintainer:` line in `PKGBUILD`, the URLs in `README.md`, and the remote above.

---

## 3. Local package test (optional, before AUR)

The active `PKGBUILD` builds from your **local** files, so you can test packaging
without publishing anything:

```sh
# in a dir containing PKGBUILD + underscore.py + underscore_gui.py +
# underscore.desktop + LICENSE
makepkg -si
namcap PKGBUILD            # lint (pacman -S namcap)
namcap underscore-*.pkg.tar.zst
```

When prompted for an `onnxruntime` provider, pick `python-onnxruntime-cpu`.

---

## 4. AUR submission (only when you decide to)

The AUR doesn't host source files — it hosts the `PKGBUILD` + `.SRCINFO`, which
fetch sources by URL. So switch the PKGBUILD from local files to the GitHub
release tarball:

1. **Edit `PKGBUILD`** per the `FOR AUR SUBMISSION` comment block at the top:
   replace the four local `source=()` entries (`underscore.py`,
   `underscore_gui.py`, `underscore.desktop`, `LICENSE`) with the release tarball,
   keep the pinned model URL, and `cd "$srcdir/$pkgname-$pkgver"` in `package()`.
2. **Checksums:** `updpkgsums` (from `pacman-contrib`) fills real `sha256sums`.
   The model's checksum is already pinned and correct.
3. **Test the URL build:** `makepkg -si` in a clean dir (it should download the
   tag tarball and build).
4. **Generate metadata:** `makepkg --printsrcinfo > .SRCINFO`.
5. **Push to the AUR:**
   ```sh
   git clone ssh://aur@aur.archlinux.org/underscore.git aur-underscore
   cd aur-underscore
   cp ../PKGBUILD ../.SRCINFO .
   git add PKGBUILD .SRCINFO
   git commit -m "underscore 0.0.13"
   git push
   ```
   (Requires an AUR account with your SSH key uploaded. Note: the name
   `underscore` is generic — check availability and consider `underscore-ducker`
   or similar if taken.)

### Updating later

Bump `__version__` and `pkgver`, add a `CHANGELOG.md` entry, push a new
`vX.Y.Z` tag, then in the AUR repo refresh checksums, regenerate `.SRCINFO`, and
push.

---

## Known limitations to mention in release notes

- **Flatpak is not provided.** Underscore drives host PipeWire tools (`pw-record`,
  `wpctl`) and, for the optional virtual sink, writes host PipeWire config and
  restarts the user service — all of which a Flatpak sandbox fights. AUR + the
  manual installer are the supported paths.
- The desktop entry uses the themed `audio-volume-high` icon as a placeholder;
  swap in a custom icon before a "1.0" if you want branding.
