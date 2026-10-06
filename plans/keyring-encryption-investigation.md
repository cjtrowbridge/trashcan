# Investigate and resolve the OS keyring encryption warning

Status: ready for manual investigation; no host changes made.
Recorded: 2026-10-05 (America/Los_Angeles).

## Evidence and goal

The supplied screenshot reports that the app detects a GNOME environment but
cannot use the OS keyring for encryption, and suggests installing/running
`gnome-keyring` or another libsecret-compatible implementation.
The screenshot resembles a VS Code notification, but the app, version, install
method, and machine running its desktop process are not yet confirmed.
Trashcan's documented desktop is XFCE; the message alone does not prove GNOME
is installed or that the desktop environment must be changed.

Goal: restore an encrypted credential store accessible to the affected app and
verify persistence across app restarts and graphical logins. Preserve existing
credentials. Do not delete keyring files, reset app credential databases, remove
keyring passwords, or switch to an unencrypted/obfuscated fallback to hide the
warning. This is separate from the
[idle remote desktop investigation](remote-desktop-idle-investigation.md);
correlate session evidence only if observations connect the two problems.

## 1. Confirm where the warning originates

Record the app's About/version details, triggering action (startup, sign-in,
Settings Sync, or an extension), timestamp, and installation type: Debian
package, Snap, Flatpak, or another distribution. Record how it was launched.

Determine whether the app's desktop process is on Trashcan's XFCE desktop,
on a local workstation connected through Remote SSH, or in a separate remote
desktop session. Investigate the machine/session that owns the credential store;
installing a keyring on the SSH server may not affect a local desktop warning.
For a non-VS Code app, use its own documented logging/backend options rather
than assuming the VS Code flags below apply.

## 2. Capture session and package evidence

Run these commands as the normal desktop user in a terminal **inside the same
graphical session as the affected app**, not with sudo or in an unrelated SSH
session. From the repo checkout, save output under the ignored
`diagnostics/keyring/` directory along with reproduction notes.

```bash
mkdir -p diagnostics/keyring
{
  date --iso-8601=seconds
  hostname
  id
  printf 'Desktop=%s Session=%s Display=%s\n' \
    "${XDG_CURRENT_DESKTOP:-}" "${DESKTOP_SESSION:-}" "${DISPLAY:-}"
  printf 'Runtime=%s SessionBus=%s\n' \
    "${XDG_RUNTIME_DIR:-}" "${DBUS_SESSION_BUS_ADDRESS:-}"
  dpkg-query -W gnome-keyring libsecret-1-0 libpam-gnome-keyring seahorse
  pgrep -a -u "$(id -u)" -f 'gnome-keyring-daemon|keepassxc|kwallet'
  busctl --user list
  gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.NameHasOwner org.freedesktop.secrets
  journalctl --user -b --since '-30 minutes' --no-pager
} > diagnostics/keyring/baseline.txt 2>&1
```

Missing packages/commands or an unavailable user bus are evidence; continue to
the next check. `NameHasOwner` checks for an existing Secret Service owner
without starting one. A false result does not rule out D-Bus activation.
To test activation and interface accessibility, run:

```bash
gdbus introspect --session --dest org.freedesktop.secrets \
  --object-path /org/freedesktop/secrets \
  > diagnostics/keyring/secret-service-interface.txt 2>&1
```

This may start the configured provider; record that result separately from the
baseline. Interface visibility does not prove the default collection is unlocked
or writable. Inspect collection/default-keyring status using a keyring manager
without exporting stored secrets. Record whether login uses a password,
autologin, or a separate XRDP session.

If inspecting Trashcan login integration, read the LightDM/XFCE startup and PAM
configuration for existing keyring integration before proposing changes. Use
`sudo journalctl -b --since '-30 minutes' --no-pager` for relevant PAM/login errors.
Do not overwrite PAM configuration with an example from another display manager.
Keep tokens, passwords, and keyring contents out of committed evidence.

## 3. Diagnose and test one remedy

| Evidence | Focused remedy and rollback |
| --- | --- |
| No Secret Service provider installed on the affected Debian desktop | Review `apt-cache policy gnome-keyring libsecret-1-0 libpam-gnome-keyring seahorse`. If GNOME Keyring is selected, install `gnome-keyring libsecret-1-0 libpam-gnome-keyring` with apt; `seahorse` is an optional manager. Record newly installed packages. Log out/in after saving work and retest before modifying startup files. Roll back only newly added packages after reviewing apt's removal preview; preserve credential data. |
| Provider installed but activation fails | Inspect provider startup, user journal, D-Bus service registration, and XFCE autostart overrides. Correct the specific disabled/broken component; back up and restore any edited file for rollback. Avoid launching a duplicate daemon as root. |
| Bus differs between app and graphical session | Compare a desktop-menu launch with the failing launch. Fix the launcher/session environment if the former works; revert that launcher change if it does not. Do not hardcode another user's bus address or create a separate bus as a permanent workaround. |
| Service reachable but default collection locked/missing | Use the keyring manager to unlock the existing Login/default collection or initialize one if none exists. Verify the login/keyring password relationship and PAM integration; do not delete an existing collection. |
| Password login unlocks it, but autologin does not | Decide whether interactive unlock or password-based login is appropriate for this host. Test that path; restore prior login configuration if needed. Do not store the unlock password in scripts. |
| Service works, but VS Code selects the wrong backend | Test `gnome-libsecret` as described below; retain it only if secure storage works. Roll back the runtime argument if it does not. |
| Only a sandboxed app fails | Inspect package-specific Secret Service access and official packaging guidance. Prefer a narrowly scoped permission change; record the previous override and restore it for rollback. |

GNOME documents PAM-based unlocking of the Login keyring using the login
password; automatic login cannot provide that password. Use that distinction
when investigating a locked collection, rather than treating daemon startup as
proof of successful unlock.
Sources: [GNOME PAM integration](https://wiki.gnome.org/Projects/GnomeKeyring/Pam)
and [GNOME secret storage](https://wiki.gnome.org/Projects%282f%29GnomeKeyring%282f%29StoringSecrets.html).

### VS Code branch (only after identifying the app)

Save work and close all VS Code desktop processes before each launch test so
an existing process does not absorb the new arguments. Run as the desktop user:

```bash
code --verbose --vmodule="*/components/os_crypt/*=1" \
  > diagnostics/keyring/code-default.txt 2>&1
```

Reproduce the warning and inspect `OSCrypt`, password-storage, and selected-backend
messages. If a working Secret Service provider exists, close VS Code again and
test:

```bash
code --password-store="gnome-libsecret" --verbose \
  --vmodule="*/components/os_crypt/*=1" \
  > diagnostics/keyring/code-libsecret.txt 2>&1
```

If confirmed, use **Preferences: Configure Runtime Arguments** to merge
`"password-store": "gnome-libsecret"` into the app's `argv.json`, preserving
existing arguments and a backup for rollback. Do not put this in workspace
settings or assume every VS Code-derived app uses the same configuration path.
Avoid `--password-store=basic`: VS Code documents it as obfuscation using a
hardcoded key, not secure encryption.
Source: [VS Code credential-store troubleshooting](https://code.visualstudio.com/docs/configure/settings-sync#_troubleshoot-credentialstore-issues).

## 4. Verify resolution and decide bootstrap scope

- Repeat the original triggering action without the warning, and confirm the
  intended encrypted backend in app logs. Warning disappearance alone is not
  sufficient if the app fell back to weaker storage.
- Confirm an ordinary app credential remains usable after a full app restart,
  desktop logout/login, and reboot, without recording its value in evidence.
- Test the actual remote desktop login path as well as local/password login if
  both are used. Record any required interactive unlock under autologin.
- Record the diagnosed cause, exact package/file changes, rollback, timestamps,
  and results in this plan or a host journal entry.
- Promote only validated Trashcan requirements into bootstrap: packages and
  login integration as needed, with idempotent checks. Keep app-specific runtime
  settings scoped to the correct account/app. If the warning originates on a
  different workstation, document that fix without changing Trashcan bootstrap.
