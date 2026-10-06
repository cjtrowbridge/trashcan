#!/usr/bin/env bash
# Bootstrap a Debian 13 MacPro6,1 for remote access and Ollama over Vulkan.
# Safe to run repeatedly: each step checks the current state before changing it.

set -Eeuo pipefail

# Stable setup boundary; machine repairs enter only with an explicit stage.
if [[ ${1:-} != --machine-stage ]]; then
  exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/scripts/bootstrap.py" "$@"
fi
REPAIR_STAGE=${2:?A machine repair stage is required}
shift 2
trap 'printf "bootstrap: interrupted\n" >&2; exit 130' INT

PASS_COUNT=0
CHANGE_COUNT=0
WARN_COUNT=0
REBOOT_REQUIRED=0

green='\033[0;32m'
yellow='\033[0;33m'
blue='\033[0;34m'
reset='\033[0m'

pass()   { printf "${green}[ok]${reset} %s\n" "$*"; PASS_COUNT=$((PASS_COUNT + 1)); }
change() { printf "${blue}[changed]${reset} %s\n" "$*"; CHANGE_COUNT=$((CHANGE_COUNT + 1)); }
warn()   { printf "${yellow}[warning]${reset} %s\n" "$*" >&2; WARN_COUNT=$((WARN_COUNT + 1)); }
step()   { [[ $* == "$REPAIR_STAGE" ]] || return 1; printf '\n==> %s\n' "$*"; }
die()    { printf '\n[error] %s\n' "$*" >&2; exit 1; }

if [[ ${EUID} -ne 0 ]]; then
  die "Machine repairs require explicitly running sudo python3 scripts/bootstrap.py."
fi

if [[ ! -r /etc/os-release ]]; then
  die "This bootstrap supports Debian and could not identify the operating system."
fi
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == debian ]] || die "This bootstrap supports Debian; detected ${PRETTY_NAME:-unknown}."

TARGET_USER=${TARGET_USER:-${SUDO_USER:-}}
if [[ -z ${TARGET_USER} || ${TARGET_USER} == root ]]; then
  die "Run with sudo from the normal desktop account, or set TARGET_USER to that account."
fi
id "$TARGET_USER" >/dev/null 2>&1 || die "User '$TARGET_USER' does not exist."

ARCH=$(dpkg --print-architecture)
CODENAME=${VERSION_CODENAME:-}
[[ -n ${CODENAME} ]] || die "Debian VERSION_CODENAME is unavailable."

package_installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed'; }

install_packages() {
  local missing=() package
  for package in "$@"; do
    package_installed "$package" || missing+=("$package")
  done
  if ((${#missing[@]} == 0)); then
    pass "Packages already installed: $*"
    return
  fi
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
  change "Installed packages: ${missing[*]}"
}

enable_debian_non_free() {
  local source_file changed=0
  if grep -Rqs --include='*.list' --include='*.sources' \
    -E '(^[[:space:]]*deb .*[[:space:]]non-free([[:space:]]|$)|^Components:.*[[:space:]]non-free([[:space:]]|$))' \
    /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
    pass "Debian non-free component is enabled"
    return
  fi
  for source_file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list; do
    [[ -f $source_file ]] || continue
    if grep -q 'main non-free-firmware' "$source_file"; then
      sed -i 's/main non-free-firmware/main non-free non-free-firmware/g' "$source_file"
      changed=1
    fi
  done
  for source_file in /etc/apt/sources.list.d/*.sources; do
    [[ -f $source_file ]] || continue
    if grep -q '^Components: main non-free-firmware$' "$source_file"; then
      sed -i 's/^Components: main non-free-firmware$/Components: main non-free non-free-firmware/' "$source_file"
      changed=1
    fi
  done
  ((changed)) || die "Could not enable Debian non-free; add it to an APT source containing main and non-free-firmware."
  change "Enabled the Debian non-free component for Broadcom STA"
}

enable_service() {
  local service=$1
  systemctl enable "$service" >/dev/null
  if systemctl is-active --quiet "$service"; then
    pass "$service is enabled and running"
  else
    systemctl start "$service"
    change "Enabled and started $service"
  fi
}

install_if_changed() {
  local source=$1 destination=$2 mode=$3
  if [[ -f $destination ]] && cmp -s "$source" "$destination"; then
    pass "$destination is current"
    return 1
  fi
  install -D -m "$mode" "$source" "$destination"
  change "Wrote $destination"
  return 0
}

if step "Checking host"; then
printf 'Host: %s (%s), user: %s, architecture: %s\n' "$(hostname)" "${PRETTY_NAME}" "$TARGET_USER" "$ARCH"
if [[ ${VERSION_ID:-} != 13 ]]; then
  warn "This configuration was canonized on Debian 13; continuing on ${PRETTY_NAME}."
else
  pass "Debian 13 detected"
fi
if ! grep -qi 'MacPro6,1' /sys/devices/virtual/dmi/id/product_name 2>/dev/null; then
  warn "MacPro6,1 was not detected; hardware-specific GPU settings may not apply."
else
  pass "MacPro6,1 detected"
fi

fi
if step "Installing remote-access and diagnostic packages"; then
install_packages avahi-daemon avahi-utils libnss-mdns x11vnc novnc websockify xrdp xorgxrdp \
  shellinabox pciutils iw rfkill firmware-amd-graphics mesa-vulkan-drivers vulkan-tools ca-certificates curl xfconf
enable_service avahi-daemon

fi
if step "Configuring BCM4360 Wi-Fi"; then
enable_debian_non_free
install_packages "linux-headers-$(uname -r)" broadcom-sta-dkms
modprobe -r b43 b43legacy brcmsmac bcma ssb 2>/dev/null || true
if modprobe wl; then
  if iw dev | grep -q '^Interface '; then
    pass "Broadcom wl driver created a wireless interface"
  else
    warn "Broadcom wl loaded but no wireless interface is visible; reboot and inspect: journalctl -k -b"
    REBOOT_REQUIRED=1
  fi
else
  warn "Could not load the Broadcom wl driver; reboot and inspect: dkms status"
  REBOOT_REQUIRED=1
fi

fi
if step "Configuring the headless X screen"; then
tmp_xorg=$(mktemp)
cat >"$tmp_xorg" <<'XORG_EOF'
# Xorg otherwise creates a 1024x768 framebuffer when no monitor is connected.
# x11vnc mirrors this display, so set the desired desktop size in its AMDGPU OutputClass.
Section "OutputClass"
    Identifier "Trashcan headless AMDGPU resolution"
    MatchDriver "amdgpu"
    Option "NoOutputInitialSize" "1920 1080"
EndSection
XORG_EOF
if install_if_changed "$tmp_xorg" /etc/X11/xorg.conf.d/10-headless-resolution.conf 0644; then
  warn "The headless X resolution will become 1920x1080 after the next reboot or display-manager restart."
fi
rm -f "$tmp_xorg"

fi
if step "Configuring x11vnc"; then
if [[ ! -s /etc/x11vnc.pass ]]; then
  printf 'No VNC password exists. Enter one for browser desktop access.\n'
  x11vnc -storepasswd /etc/x11vnc.pass
  chmod 600 /etc/x11vnc.pass
  change "Created /etc/x11vnc.pass"
else
  chmod 600 /etc/x11vnc.pass
  pass "VNC password file exists"
fi

tmp_x11=$(mktemp)
cat >"$tmp_x11" <<'EOF'
[Unit]
Description=x11vnc Desktop Server
After=display-manager.service
Wants=display-manager.service

[Service]
Type=simple
ExecStart=/usr/bin/x11vnc -display :0 -auth /var/run/lightdm/root/:0 -forever -shared -repeat -rfbport 5900 -rfbauth /etc/x11vnc.pass -localhost
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical.target
EOF
if install_if_changed "$tmp_x11" /etc/systemd/system/x11vnc.service 0644; then
  systemctl daemon-reload
  systemctl enable x11vnc >/dev/null
  if [[ -e /var/run/lightdm/root/:0 ]]; then
    systemctl restart x11vnc
  else
    warn "LightDM Xauthority is not present yet; x11vnc will start with the graphical session."
  fi
fi
rm -f "$tmp_x11"
systemctl enable x11vnc >/dev/null
if [[ -e /var/run/lightdm/root/:0 ]]; then
  enable_service x11vnc
else
  warn "x11vnc is enabled but cannot be started until LightDM creates its Xauthority file."
fi

fi
if step "Configuring VNC desktop responsiveness"; then
desktop_uid=$(id -u "$TARGET_USER")
desktop_bus="/run/user/$desktop_uid/bus"
if [[ -S $desktop_bus ]]; then
  compositor_state=$(sudo -u "$TARGET_USER" env DISPLAY=:0 XAUTHORITY=/var/run/lightdm/root/:0 \
    DBUS_SESSION_BUS_ADDRESS="unix:path=$desktop_bus" \
    xfconf-query -c xfwm4 -p /general/use_compositing 2>/dev/null || true)
  if [[ $compositor_state == false ]]; then
    pass "XFCE compositing is disabled for the VNC desktop"
  elif [[ $compositor_state == true ]]; then
    sudo -u "$TARGET_USER" env DISPLAY=:0 XAUTHORITY=/var/run/lightdm/root/:0 \
      DBUS_SESSION_BUS_ADDRESS="unix:path=$desktop_bus" \
      xfconf-query -c xfwm4 -p /general/use_compositing -s false
    change "Disabled XFCE compositing to reduce x11vnc frame updates"
  else
    warn "Could not read XFCE compositor state; rerun after $TARGET_USER has logged into the graphical desktop."
  fi
else
  warn "The graphical user D-Bus is not available; rerun after $TARGET_USER has logged into XFCE to disable compositing."
fi

fi
if step "Configuring noVNC"; then
tmp_novnc=$(mktemp)
cat >"$tmp_novnc" <<'EOF'
[Unit]
Description=noVNC Web Interface
After=network-online.target x11vnc.service
Requires=x11vnc.service

[Service]
Type=simple
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
if install_if_changed "$tmp_novnc" /etc/systemd/system/novnc.service 0644; then
  systemctl daemon-reload
  systemctl enable novnc >/dev/null
  systemctl restart novnc
fi
rm -f "$tmp_novnc"
enable_service novnc

fi
if step "Configuring RDP for the physical desktop"; then
tmp_xrdp=$(mktemp)
awk '
function physical_desktop() {
  print "[PhysicalDesktop]"
  print "name=Physical desktop (:0)"
  print "lib=libvnc.so"
  print "ip=127.0.0.1"
  print "port=5900"
  print "username=na"
  print "password=ask"
}
/^autorun=/ {
  print "autorun=PhysicalDesktop"
  next
}
/^\[(Xorg|PhysicalDesktop|Physical desktop)\]$/ {
  if (!physical_written) {
    physical_desktop()
    physical_written=1
  }
  skipping=1
  next
}
skipping && /^$/ {
  skipping=0
  print
  next
}
skipping { next }
{ print }
END {
  if (!physical_written) {
    print ""
    physical_desktop()
  }
}
' /etc/xrdp/xrdp.ini >"$tmp_xrdp"
if install_if_changed "$tmp_xrdp" /etc/xrdp/xrdp.ini 0644; then
  systemctl restart xrdp
fi
rm -f "$tmp_xrdp"
enable_service xrdp

fi
if step "Configuring ShellInABox with a dark default"; then
enable_service shellinabox
theme_dir=/etc/shellinabox/options-enabled
if [[ -e "$theme_dir/00+Black on White.css" || ! -e "$theme_dir/00+White On Black.css" ]]; then
  rm -f "$theme_dir/00+Black on White.css" "$theme_dir/00_White On Black.css"
  ln -sfn '../options-available/00+Black on White.css' "$theme_dir/00_Black on White.css"
  ln -sfn '../options-available/00_White On Black.css' "$theme_dir/00+White On Black.css"
  systemctl restart shellinabox
  change "Made White On Black the default ShellInABox theme"
else
  pass "ShellInABox dark theme is the default"
fi

fi
if step "Installing Docker Engine"; then
install -m 0755 -d /etc/apt/keyrings
docker_key=/etc/apt/keyrings/docker.asc
if [[ ! -s $docker_key ]]; then
  curl -fsSL https://download.docker.com/linux/debian/gpg -o "$docker_key"
  chmod a+r "$docker_key"
  change "Installed Docker repository signing key"
else
  pass "Docker repository signing key exists"
fi

docker_source=/etc/apt/sources.list.d/docker.sources
tmp_docker_source=$(mktemp)
cat >"$tmp_docker_source" <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${CODENAME}
Components: stable
Architectures: ${ARCH}
Signed-By: ${docker_key}
EOF
if install_if_changed "$tmp_docker_source" "$docker_source" 0644; then
  apt-get update
fi
rm -f "$tmp_docker_source"
install_packages docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
enable_service docker

for group in docker render video; do
  if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx "$group"; then
    pass "$TARGET_USER belongs to $group"
  else
    usermod -aG "$group" "$TARGET_USER"
    change "Added $TARGET_USER to $group (takes effect at next login)"
    REBOOT_REQUIRED=1
  fi
done

fi
if step "Selecting amdgpu for the FirePro D700 (Tahiti/Southern Islands)"; then
install_packages initramfs-tools
if [[ -r "/boot/config-$(uname -r)" ]] && ! grep -q '^CONFIG_DRM_AMDGPU_SI=y' "/boot/config-$(uname -r)"; then
  warn "The running kernel does not advertise CONFIG_DRM_AMDGPU_SI=y."
fi

grub_file=/etc/default/grub
[[ -f $grub_file ]] || die "$grub_file is missing."
grub_line=$(sed -n 's/^GRUB_CMDLINE_LINUX_DEFAULT="\([^"]*\)".*/\1/p' "$grub_file" | head -n1)
new_grub_line=$grub_line
for argument in radeon.si_support=0 amdgpu.si_support=1; do
  case " $new_grub_line " in
    *" $argument "*) ;;
    *) new_grub_line="${new_grub_line:+$new_grub_line }$argument" ;;
  esac
done
if [[ $new_grub_line != "$grub_line" ]]; then
  escaped=$(printf '%s' "$new_grub_line" | sed 's/[&|]/\\&/g')
  sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=\"[^\"]*\"|GRUB_CMDLINE_LINUX_DEFAULT=\"$escaped\"|" "$grub_file"
  update-grub
  change "Configured GRUB to use amdgpu for Southern Islands GPUs"
  REBOOT_REQUIRED=1
else
  pass "GRUB contains the Southern Islands amdgpu arguments"
fi

if [[ " $(cat /proc/cmdline) " != *' radeon.si_support=0 '* || " $(cat /proc/cmdline) " != *' amdgpu.si_support=1 '* ]]; then
  warn "The amdgpu boot arguments are not active yet. Reboot, then run bootstrap.sh again."
  REBOOT_REQUIRED=1
fi

fi
GPU_READY=0
if [[ $REPAIR_STAGE == 'Configuring Ollama' ]]; then
lspci_display=$(lspci -nnk 2>/dev/null | grep -A3 -Ei 'VGA|Display' || true)
if command -v lspci >/dev/null 2>&1 && grep -q 'Kernel driver in use: amdgpu' <<<"$lspci_display"; then
  pass "At least one display GPU is using amdgpu"
  vulkan_summary=$(vulkaninfo --summary 2>&1 || true)
  if grep -q 'RADV TAHITI' <<<"$vulkan_summary"; then
    tahiti_count=$(grep -c 'RADV TAHITI' <<<"$vulkan_summary" || true)
    if ((tahiti_count >= 2)); then
      pass "Vulkan sees both D700/Tahiti GPUs"
      GPU_READY=1
    else
      warn "Vulkan sees $tahiti_count Tahiti GPU(s), expected two."
    fi
  else
    warn "Vulkan cannot access a RADV Tahiti GPU in this session. Log out/reboot after group changes."
  fi
else
  warn "The D700s are not using amdgpu yet."
fi

fi
if step "Configuring Ollama"; then
docker volume inspect ollama >/dev/null 2>&1 || { docker volume create ollama >/dev/null; change "Created the Ollama model volume"; }
if ((GPU_READY)); then
  render_gid=$(getent group render | cut -d: -f3)
  video_gid=$(getent group video | cut -d: -f3)
  desired_config='trashcan-vulkan-v2-context-130k'
  current_config=$(docker inspect -f '{{index .Config.Labels "io.github.trashcan.bootstrap"}}' ollama 2>/dev/null || true)
  if [[ $current_config != "$desired_config" ]]; then
    if docker container inspect ollama >/dev/null 2>&1; then
      docker rm -f ollama >/dev/null
      change "Removed the superseded Ollama container (models remain in the volume)"
    fi
    docker run -d \
      --name ollama \
      --restart unless-stopped \
      --label "io.github.trashcan.bootstrap=$desired_config" \
      --device /dev/dri:/dev/dri \
      --group-add "$render_gid" \
      --group-add "$video_gid" \
      -e OLLAMA_VULKAN=1 \
      -e OLLAMA_CONTEXT_LENGTH=130000 \
      -v ollama:/root/.ollama \
      -p 11434:11434 \
      ollama/ollama:latest >/dev/null
    change "Created the Vulkan-enabled Ollama container"
  else
    docker start ollama >/dev/null 2>&1 || true
    pass "Ollama container configuration is current"
  fi

  for attempt in {1..20}; do
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    pass "Ollama API is responding"
  else
    warn "Ollama did not become ready; inspect it with: docker logs ollama"
  fi
  ollama_logs=$(docker logs ollama 2>&1 || true)
  if grep -q 'library=Vulkan' <<<"$ollama_logs"; then
    pass "Ollama detected the Vulkan backend"
  else
    warn "Ollama has not logged Vulkan compute detection yet."
  fi
else
  warn "Deferring the Ollama container until amdgpu, Vulkan, and group membership are active."
fi

fi
if step "Final status"; then
host_fqdn=$(hostname -f 2>/dev/null || hostname)
printf 'Desktop: http://%s:6080/vnc.html\n' "$host_fqdn"
printf 'RDP:     %s:3389 (physical desktop via the VNC password)\n' "$host_fqdn"
printf 'Shell:   https://%s:4200\n' "$host_fqdn"
printf 'Ollama:  http://%s:11434\n' "$host_fqdn"
printf '\nResults: %d ok, %d changed, %d warnings\n' "$PASS_COUNT" "$CHANGE_COUNT" "$WARN_COUNT"
if ((REBOOT_REQUIRED)); then
  printf "${yellow}Reboot (or fully log out after group-only changes), then run this script again.${reset}\n"
else
  pass "Bootstrap is complete; no reboot is pending"
fi
fi
