# Remote desktop failure after inactivity

Status: unresolved; investigate on `trashcan0` before changing bootstrap.
Recorded: 2026-10-05 (America/Los_Angeles).

## Problem and environment

The user reports the screen shuts off and remote desktop stops working until
reboot on the Debian/XFCE Mac Pro. The exact failure interval, client, transport,
physical monitor state, and whether SSH survives have not been captured.
The conversation calls the connection "RDP", while this repository bootstraps
x11vnc/noVNC against the physical LightDM display `:0`. Do not assume XRDP is
installed or that the failing connection uses it.

Sources: the user-provided "Disable Screen Blanking" transcript and the follow-up
`xset q` output in this conversation. These are observations, not a verified
root-cause analysis.

## Attempts and evidence

| Attempt or observation | Evidence and limits |
| --- | --- |
| Add `consoleblank=0` alongside `quiet radeon.si_support=0 amdgpu.si_support=1` in GRUB, then update GRUB/reboot | Suggested; user subsequently reported the problem persisted. No `/proc/cmdline` output verifies that the parameter became active. Console blanking and X11 display management are separate. |
| Set XFCE power-manager properties with `xfconf-query -s` | Four commands failed because the properties did not exist. No successful setting change was shown. |
| Disable XFCE screensaver/locking with `xfconf-query` | Suggested/attempted with errors redirected away; success is unverified. |
| Run `xset` over SSH without a display | All three commands failed with `unable to open display ""`; no graphical setting was applied. |
| Query `:0` using `/home/cj/.Xauthority` | Succeeded. Screensaver timeout was already `0`, but DPMS was enabled with standby `600`, suspend `0`, off `900` seconds. |
| Run `xset s off`, `xset s noblank`, `xset -dpms` with that authentication | Succeeded; subsequent output showed timeout `0` and `DPMS is Disabled`. No successful idle/reconnect test was recorded. |
| Inspect XFCE power-manager configuration | Only brightness-switch `0`, brightness-switch-restore-on-exit `1`, and power-button-action `3` were listed. Missing explicit timeout properties do not establish which component set DPMS; defaults may still apply. |
| Inspect graphical processes | Xorg `:0` started at 19:39, XFCE was running as `cj`, and another Xorg `:1` started at 20:03. A LightDM greeter session was listed. This does not prove the user's session was replaced or that `:1` caused the failure. |
| Delayed `disable-dpms.desktop` autostart, `.xprofile` commands, LightDM `xserver-command=X -s 0 -dpms` | Suggested as persistence measures. Installed file contents, effective LightDM configuration, restart/reboot, and current Xorg command lines have not been supplied. |
| Mask sleep/suspend/hibernate targets and change logind idle/key handling | Suggested; no execution or verification output supplied. Treat their state as unknown. |
| Latest `DISPLAY=:0 XAUTHORITY=/home/cj/.Xauthority xset q` | Succeeded with timeout `0`, prefer blanking `no`, and `Server does not have the DPMS Extension`. User suspects the fix did not work; no timed failure capture yet. |

The latest result means the queried server does not expose DPMS to the client;
it is not evidence that DPMS remains enabled. Xorg documents `-dpms` as disabling
display power management, so this result is consistent with that suggested
startup option, but the actual command line must be checked.
See the [Xorg server manual](https://cgit.freedesktop.org/xorg/xserver/tree/man/Xserver.man).
Neither this result nor timeout `0` proves that locking, suspend, a GPU failure,
or remote-server failure cannot occur.

## Investigation questions

1. Which client and endpoint fail: noVNC on port 6080, VNC, or XRDP on port 3389?
2. Does SSH survive, and is the host still reachable by IP when name lookup fails?
3. Are the same Xorg and XFCE processes/session IDs alive before and after?
4. Is only the viewer disconnected, is the framebuffer black/frozen, or is the
   physical monitor also asleep? Can local input recover it?
5. Do logs show suspend, locking, service exits, display switching, or amdgpu
   timeout/reset events at the recorded failure time?

Use the [host investigation plan](../plans/remote-desktop-idle-investigation.md).
The bootstrap has not been changed for this issue. No model-driven pipeline is
created or required for the investigation.
