# Architecture and verification

Console is a temporary exclusive Gamescope session. A fixed SDDM symlink points to a root-owned, boot-volatile request under `/run`. A transient supervisor consumes the request and restores the stock desktop path after the visit. Stock desktop and autologin files are preserved. The privileged engine uses explicit ownership records; repair and uninstall preserve unknown or modified objects rather than adopting them blindly.

## Automated checks

From this repository, run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
bash -n setup uninstall system/enter-privileged system/install.sh system/uninstall.sh
python3 system/privileged-bootstrap.py --check
```

The tests exercise ownership, repair/uninstall preservation, status, DRM admission, display preference safety, compatibility archive validation and updater migration. Root VM harnesses under `tests/guest-verification` are destructive test utilities for a disposable fixture only, not normal setup instructions. Do not run them on a daily-use installation. The exact `omarchy-vm` hostname plus QEMU boundary in production code is an intentional ARM test fixture guard, not a hardware support claim.

## Recorded acceptance

- Disposable VM: session routing, recovery, lifecycle, uninstall and earlier power-cut gates were exercised. The latest updater migration was tested with controlled process interruptions, not a new physical power-cut test.
- AMD RX 6800 / LG C5: exclusive 4K120, controller, TV audio, MangoApp, desktop/screenshare return, reboot safety and native Steam display Keep/Revert/timeout were exercised. No controlled performance benchmark is claimed. Microphone testing was not applicable.
- Both pinned compatibility tools were discovered in Steam. Proton-CachyOS gameplay was user-confirmed; GE-Proton gameplay is not claimed. Existing game mappings were preserved.
- Steam accepts the OS updater helper's exit 7, but its unsupported Deck BIOS check can produce an update-error popup. This is an accepted limitation, not a passed error-free UI check. OS packages are updated through Omarchy; firmware remains hardware-specific.
- The user approved a continuous real-hardware launch video. Raw logs, original history and private evidence are retained outside this release history.

- Acer Swift Go 14, user-reported first use: installed the plugin and engine, including previously absent Steam; launched into Steam setup, signed in, disabled automatic resolution, selected the appropriate refresh rate, and returned to the desktop. Exact mode values, gameplay, reboot persistence, audio/controller and uninstall were not reported. Private Git authentication was a test-access prerequisite, not an engine failure.
- Independent read-only review of the sanitized base candidate found no blockers within its inspected scope; the exact snapshot passed 79 local tests. The review was not a comprehensive secret audit.

## Scope and release

The owner approved public release after the documented acceptance and privacy preparation. Marketplace submission is separate; this repository is not a marketplace approval or security certification. Hardware claims remain limited to the observations above.
