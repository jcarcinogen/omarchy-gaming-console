# Rescue — return to stock Omarchy

These commands match the current volatile session-routing design. The Desk personality never changes packaged `omarchy.desktop` or `/etc/sddm.conf.d/autologin.conf`; it only arms a file under `/run` behind a fixed symlink.

## First-line recovery

If Console, the greeter, or a transition is stuck:

1. Press **Ctrl+Alt+F3**.
2. Sign in with your normal Omarchy account.
3. Run:

   ```bash
   sudo rm -f /run/omarchy-gaming-console/sddm-oneshot.conf
   sudo systemctl reset-failed sddm
   sudo systemctl restart sddm
   sudo rmdir -- /run/omarchy-gaming-console
   ```

The missing volatile target makes the fixed route inert, so SDDM reads the unchanged stock autologin configuration and starts `omarchy.desktop`. The final `rmdir` removes only the empty runtime directory so status can return to `ready`. If it is already absent, no cleanup is needed. If it is non-empty, preserve the unknown content and investigate; do not delete it recursively.

## Disable Console routing completely

If the first-line recovery does not restore Omarchy, disable the fixed indirection too:

```bash
sudo rm -f /run/omarchy-gaming-console/sddm-oneshot.conf \
  /etc/sddm.conf.d/zz-omarchy-console-oneshot.conf
sudo systemctl reset-failed sddm
sudo systemctl restart sddm
sudo rmdir -- /run/omarchy-gaming-console
```

This leaves the Console engine incomplete until setup/repair reinstalls the fixed symlink. It does not alter either packaged stock file.

## Verify the safe state

```bash
readlink /etc/sddm.conf.d/zz-omarchy-console-oneshot.conf || true
test ! -e /run/omarchy-gaming-console/sddm-oneshot.conf
awk -F= '/^[[:space:]]*Session[[:space:]]*=/{print $2}' \
  /etc/sddm.conf.d/autologin.conf
systemctl is-active sddm
```

Expected results:

- the volatile payload is absent;
- `Session` is `omarchy.desktop`;
- SDDM is active;
- if the fixed symlink remains, it points to `/run/omarchy-gaming-console/sddm-oneshot.conf` and is harmless while that target is absent.

## Reboot safety

A reboot or abrupt power loss removes `/run/omarchy-gaming-console` automatically. The fixed symlink survives but has no target, so stock Omarchy remains the boot destination. This was exercised on the disposable VM with host-side `SIGKILL`, not inferred from a normal shutdown.
