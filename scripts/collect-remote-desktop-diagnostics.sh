#!/usr/bin/env bash
# Read-only snapshot; run on Debian and redirect output to a local evidence file.
set -uo pipefail

section() { printf '\n==> %s\n' "$*"; }
capture() {
  printf '\n$'; printf ' %q' "$@"; printf '\n'
  "$@"
  local status=$?
  if ((status != 0)); then
    printf '[command exited %d; continuing]\n' "$status"
  fi
  return 0
}

section "Host and boot"
capture date --iso-8601=seconds
capture hostname
capture uname -a
capture cat /etc/os-release /proc/sys/kernel/random/boot_id /proc/cmdline
capture uptime

section "Sessions, processes, and listeners"
capture loginctl list-sessions
while read -r session _; do
  [[ -n $session ]] || continue
  capture loginctl show-session "$session" -p Name -p Type -p Class -p State \
    -p Display -p Seat -p VTNr -p Leader -p IdleHint -p LockedHint
done < <(loginctl list-sessions --no-legend --no-pager 2>/dev/null)
capture ps -eo user,pid,ppid,lstart,args
capture ss -ltnp

section "Remote/display services and sleep policy"
capture systemctl --no-pager --full status lightdm x11vnc novnc xrdp xrdp-sesman
capture systemctl cat lightdm x11vnc novnc xrdp xrdp-sesman
capture systemctl is-enabled sleep.target suspend.target hibernate.target hybrid-sleep.target
capture systemctl is-active sleep.target suspend.target hibernate.target hybrid-sleep.target
capture systemd-analyze cat-config systemd/logind.conf
capture lightdm --show-config

section "LightDM X displays (queries only; no cookie contents)"
shopt -s nullglob
auth_files=(/var/run/lightdm/root/:*)
if ((${#auth_files[@]} == 0)); then
  printf 'No readable LightDM display authentication paths found.\n'
fi
for auth_file in "${auth_files[@]}"; do
  [[ -r $auth_file ]] || continue
  capture env DISPLAY="${auth_file##*/}" XAUTHORITY="$auth_file" xset q
done

section "GPU drivers and recent logs (last 45 minutes, current boot)"
capture lspci -nnk
capture journalctl -b --since '-45 minutes' --no-pager -o short-iso-precise \
  -u lightdm -u x11vnc -u novnc -u xrdp -u xrdp-sesman -u systemd-logind
capture journalctl -k -b --since '-45 minutes' --no-pager -o short-iso-precise
capture journalctl -b --since '-45 minutes' --no-pager -o short-iso-precise \
  _COMM=xfce4-session _COMM=xfce4-power-manager _COMM=xfce4-screensaver _COMM=light-locker
for log_file in /var/log/Xorg.*.log /var/log/lightdm/*.log; do
  capture tail -n 150 "$log_file"
done

section "Snapshot complete"
