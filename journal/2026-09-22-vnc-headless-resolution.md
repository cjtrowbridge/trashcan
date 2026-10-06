# Headless VNC resolution and responsiveness

Date: 2026-09-22

## Finding

noVNC proxies x11vnc, which mirrors Xorg display `:0`; it does not create an independent virtual VNC desktop. Every Mac Pro DisplayPort connector was disconnected, so Xorg selected its no-output fallback framebuffer of 1024x768.

AMDGPU glamor/DRI3 acceleration was active, CPU and memory pressure were negligible, and the active LAN connection had approximately 0.4 ms RTT with no material loss. The slow desktop updates were therefore not caused by network or GPU saturation.

## Applied live settings

- Resized the active X session with `xrandr --fb 1920x1080`. This change is temporary and is lost at an Xorg restart.
- Disabled XFCE compositing for user `cj` (`/general/use_compositing=false`). This reduces the changed-pixel area that x11vnc must capture and encode. It is a reversible per-user XFCE setting.

## Persistent configuration

`bootstrap.sh` installs `/etc/X11/xorg.conf.d/10-headless-resolution.conf`. The file adds a `NoOutputInitialSize` value of 1920x1080 to an `OutputClass` that matches the `amdgpu` driver. This placement is required: an earlier `ServerFlags` placement was parsed but ignored by Xorg, which continued to log the 1024x768 fallback.

Xorg applies this setting only when no physical display is detected; a connected monitor retains its EDID-selected mode. The configuration takes effect after the corrected bootstrap runs and Xorg restarts. A reboot is the least disruptive remote method.

The bootstrap also disables XFCE compositing when the target user's graphical D-Bus session is available; otherwise it reports a warning and can be run again after login.
