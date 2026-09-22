# Architecture and verification

Console is a temporary exclusive Gamescope session. A fixed SDDM symlink points to a root-owned, boot-volatile request under `/run`. A transient supervisor consumes the request and restores the stock desktop path after the visit. Stock desktop and autologin files are preserved. The privileged engine uses explicit ownership records; repair and uninstall preserve unknown or modified objects rather than adopting them blindly.

## Automated checks

From this repository, run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
bash -n setup uninstall system/enter-privileged system/install.sh system/uninstall.sh
python3 system/privileged-bootstrap.py --check
```

The tests exercise ownership, repair/uninstall preservation, status, DRM admission, display preference safety and updater migration. Production setup can invoke only `/usr/lib/omarchy-gaming-console/engine-manager`, installed separately as a signed Arch package and owned by root. That package pins one exact reviewed commit; no code, URL, digest, repository, or commit from the plugin checkout crosses the privilege boundary. Its complete fetch sequence has one 180-second deadline, runs Git in a separate process group, terminates and reaps that group on timeout, and removes a partial root-owned source stage on every failure. The README's three signed helper downloads use immutable release `engine-helper-4297ecf`, bind the package to committed SHA-256 `86b3ed97f7f99841bdbd210f44e8c909285501fefc53187862d7c601dc3dc746`, and retain committed per-asset size ceilings plus one 600-second aggregate deadline before verification or installation. The disposable VM harnesses call the local bootstrap directly because they are already root and must exercise the fixture under test; they are not the production handoff. Do not run them on a daily-use installation. The exact `omarchy-vm` hostname plus QEMU boundary in production code is an intentional ARM test fixture guard, not a hardware support claim.

## Recorded acceptance

- Disposable VM: session routing, recovery, lifecycle, uninstall and earlier power-cut gates were exercised. The latest updater migration was tested with controlled process interruptions, not a new physical power-cut test.
- AMD RX 6800 / LG C5: exclusive 4K120, controller, TV audio, MangoApp, desktop/screenshare return, reboot safety and native Steam display Keep/Revert/timeout were exercised. No controlled performance benchmark is claimed. Microphone testing was not applicable.
- Steam accepts the OS updater helper's exit 7, but its unsupported Deck BIOS check can produce an update-error popup. This is an accepted limitation, not a passed error-free UI check. OS packages are updated through Omarchy; firmware remains hardware-specific.
- The user approved a continuous real-hardware launch video. Raw logs, original history and private evidence are retained outside this release history.

- Acer Swift Go 14, user-reported first use: installed the plugin and engine, including previously absent Steam; launched into Steam setup, signed in, disabled automatic resolution, selected the appropriate refresh rate, and returned to the desktop. Exact mode values, gameplay, reboot persistence, audio/controller and uninstall were not reported. Private Git authentication was a test-access prerequisite, not an engine failure.
- Independent read-only review of the sanitized base candidate found no blockers within its inspected scope; the exact snapshot passed 79 local tests. The review was not a comprehensive secret audit.

## Scope and release

The owner approved public release after the documented acceptance and privacy preparation. Marketplace submission is separate; this repository is not a marketplace approval or security certification. Hardware claims remain limited to the observations above.
