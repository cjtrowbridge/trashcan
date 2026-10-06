# Investigate idle remote desktop failures on Trashcan

Status: ready for manual execution on the Debian host; diagnosis is pending.
Context and attempted fixes: [evidence record](../research/remote-desktop-idle-failure.md).

Goal: reproduce the failure, identify the failing layer, and validate one remedy
before integrating it into `bootstrap.sh`. Preserve current configuration and
collect failure evidence before rebooting or restarting services.

## 1. Record the connection and capture a working baseline

Work from the repository checkout on `trashcan0`. Record client application,
client OS, hostname/IP, port, and protocol. Distinguish "cannot connect" from
"connects but shows black/frozen screen". Record the physical monitor's state.
Keep an independent SSH connection available for the failure capture.

The collector reads host state and recent logs. It does not change settings,
restart services, or install packages. Run it with sudo to read system logs and
LightDM display authentication; it never prints Xauthority cookie contents.

```bash
mkdir -p diagnostics/remote-desktop
date --iso-8601=seconds > diagnostics/remote-desktop/reproduction-notes.txt
sudo bash scripts/collect-remote-desktop-diagnostics.sh \
  > diagnostics/remote-desktop/before.txt 2>&1
```

Append observations to `reproduction-notes.txt`, including the local timezone,
whether the earlier suggestions were actually installed, and any changes since
the last failure. The collector includes boot ID and uptime to distinguish boots.
An unavailable command/service/display is recorded and collection continues.
Raw evidence is ignored by Git; preserve it locally and summarize findings in
the research record after reviewing the logs for private information.

In a terminal inside the actual XFCE session, also run:

```bash
printf 'DISPLAY=%s XAUTHORITY=%s\n' "$DISPLAY" "${XAUTHORITY:-<default>}"
xset q
xfconf-query -c xfce4-power-manager -l -v
xfconf-query -c xfce4-screensaver -l -v
```

Save those results separately. Running `xfconf-query` in an unrelated SSH D-Bus
session may not inspect the graphical session's settings. Do not create missing
properties during this baseline capture. Inspect existing autostart/`.xprofile`
files and LightDM configuration to confirm the persistence measures in use.

## 2. Reproduce without changing configuration

1. Leave the desktop idle for at least 20 minutes (beyond the previously observed
   15-minute DPMS off timer), or longer if the usual failure interval requires it.
   Record whether the viewer stays connected; avoid mouse/keyboard input that
   would reset desktop inactivity. An SSH session does not prove suspend is off.
2. Record the exact failure time and visible symptom, then retry the same client.
3. From the client, try SSH by the host's IP as well as its usual hostname. Record
   success/failure separately; ping alone cannot establish host health.
4. If SSH works, capture immediately **before** any recovery action:

   ```bash
   sudo bash scripts/collect-remote-desktop-diagnostics.sh \
     > diagnostics/remote-desktop/failed.txt 2>&1
   ```

5. Test another access path if available (direct VNC versus noVNC, or local
   keyboard/monitor), and record whether it recovers the display or connection.
   Capture again after recovery to distinguish what changed.
6. If SSH is also unavailable, record the time externally and use local console
   access if possible. If reboot is necessary, collect the new state and preserve
   previous-boot logs with `sudo journalctl -b -1 --no-pager` and
   `sudo journalctl -k -b -1 --no-pager`, redirected into the evidence directory.
   Previous-boot logs may be unavailable without persistent journaling; record
   that gap rather than assuming there were no errors.

## 3. Compare evidence and choose the next experiment

| Finding | Next focused check |
| --- | --- |
| SSH and local console both fail | Inspect previous-boot kernel logs for hangs/reset events; distinguish host power/suspend from network loss. |
| SSH works and logs show suspend/resume | Inspect current sleep target/logind/XFCE policy; test a targeted suspend prevention change and record its rollback. |
| Xorg/XFCE PID or session changes, greeter appears, or locker starts | Correlate LightDM and session logs; investigate locking/session switching. A second X server alone is insufficient evidence. |
| Xorg and XFCE survive but x11vnc exits or loses authentication | Compare x11vnc logs, display ownership, and the authentication path hardcoded in its unit. |
| Direct VNC works but noVNC fails | Inspect novnc/websockify and browser error details, listener state, and network path. |
| XRDP is the actual failing service | Inspect xrdp/xrdp-sesman logs and its separate display/session; `:0` settings may not apply to it. |
| Desktop and services survive but framebuffer freezes; amdgpu errors coincide | Investigate GPU/display stack stability using timestamped kernel and Xorg logs. |
| DPMS becomes enabled or screensaver timeout changes again | Identify the component changing settings; test startup/power-manager policy on the failing display. |

Make one configuration change per experiment. Record the exact command/file diff,
reason, rollback, start time, and result. Capture state before and after each run.
Service restarts can disconnect viewers or destroy graphical sessions; collect
evidence first and perform a restart only as an intentional recovery experiment.
Do not bulk-disable locking, power keys, and sleep merely because they were
suggested in the original conversation.

## 4. Validate and promote

- Demonstrate the original failure under the baseline, if reproducible.
- After a targeted fix, complete at least two idle/reconnect cycles beyond the
  failure interval and repeat after a reboot and desktop login.
- Verify the actual failing protocol, physical display, and independent SSH.
- Record whether the result is confirmed, inconclusive, or still failing, with
  evidence filenames and timestamps. A single `xset q` result is insufficient.
- Only after validation, integrate the remedy into host-owned bootstrap with
  idempotent configuration, correct user/session handling, rollback instructions,
  and explicit reporting of any required reboot.
