#!/usr/bin/env python3
"""Trashcan desired state: inspect first, repair selected requirements, recheck.

The Debian shell script remains the reviewed backend for individual privileged
machine stages. This dispatcher never elevates and never runs repairs in check
mode. Alias provisioning uses only the canonical framework manager.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import grp
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import socket
import shutil
import stat
import subprocess
import sys
from typing import Callable

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "bootstrap.sh"
MANAGER = ROOT / "agentic-pipelines/scripts/ensure_ollama_context_aliases.py"
MODELS = (
    "qwen3.8:27b-mtp-q8_0",
    "qwen3.8:27b-mtp-q4_K_M",
    "qwen3.8-flash-next:125b-a6b-q4_K_M",
)
BASE_DIGESTS = dict(zip(MODELS, (
    '8a15828773037bdbb79b103ca20344c67a05251521b918a534c135ca76f1f04d',
    '22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643',
    'f79436a1cc83fd1a9b7752cf62247a2e7ad9fd7775c67230da4254fcc1d07f01',
)))
CONTEXTS = ("1k", "4k", "64k", "96k", "256k")
PACKAGES = (
    "avahi-daemon", "avahi-utils", "libnss-mdns", "x11vnc", "novnc", "websockify",
    "xrdp", "xorgxrdp", "shellinabox", "pciutils", "iw", "rfkill", "firmware-amd-graphics",
    "mesa-vulkan-drivers", "vulkan-tools", "ca-certificates", "curl", "xfconf",
)
REMOTE_STAGE = "Installing remote-access and diagnostic packages"
WIFI_STAGE = "Configuring BCM4360 Wi-Fi"
DOCKER_STAGE = "Installing Docker Engine"
GPU_STAGE = "Selecting amdgpu for the FirePro D700 (Tahiti/Southern Islands)"


def run(command: list[str], timeout: int = 30, env: dict | None = None) -> str:
    if not shutil.which(command[0]):
        candidate = Path('/usr/sbin') / command[0]
        if candidate.is_file():
            command = [str(candidate), *command[1:]]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed ({result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def package(name: str) -> None:
    need(run(["dpkg-query", "-W", "-f=${Status}", name]) == "install ok installed", f"missing package {name}")


def service(name: str) -> None:
    need(run(["systemctl", "is-enabled", name]) == "enabled", f"{name} is not enabled")
    need(run(["systemctl", "is-active", name]) == "active", f"{name} is not active")


def content(path: str, expected: str) -> None:
    need(Path(path).read_text() == expected, f"{path} differs from declared configuration")


def shell_template(marker: str) -> str:
    # Probe exactly the host's preserved configuration text, without executing it.
    text = SHELL.read_text()
    match = re.search(r"<<'" + re.escape(marker) + r"'\n(.*?)\n" + re.escape(marker) + r"\n", text, re.S)
    need(match is not None, f"missing configuration template {marker}")
    return match.group(1) + "\n"


def config_for(variable: str) -> str:
    text = SHELL.read_text()
    match = re.search(r'cat >"\$' + variable + r'" <<\x27EOF\x27\n(.*?)\nEOF\n', text, re.S)
    need(match is not None, f"missing template {variable}")
    return match.group(1) + "\n"


def docker_config() -> None:
    details = json.loads(run(["docker", "inspect", "ollama"]))[0]
    need(details["State"]["Running"], "Ollama container is stopped")
    config = details["Config"]
    need(config.get("Labels", {}).get("io.github.trashcan.bootstrap") == "trashcan-vulkan-v2-context-130k", "Ollama configuration label differs")
    need(config["Image"] == "ollama/ollama:latest", "Ollama image differs")
    need({"OLLAMA_VULKAN=1", "OLLAMA_CONTEXT_LENGTH=130000"} <= set(config["Env"]), "Ollama environment differs")
    host = details["HostConfig"]
    need(host["RestartPolicy"]["Name"] == "unless-stopped", "Ollama restart policy differs")
    need(any(d["PathOnHost"] == "/dev/dri" and d["PathInContainer"] == "/dev/dri" for d in host["Devices"]), "GPU device mount missing")
    need({str(grp.getgrnam(g).gr_gid) for g in ("render", "video")} <= set(host["GroupAdd"]), "GPU groups missing")
    need(any(m.get("Name") == "ollama" and m["Destination"] == "/root/.ollama" for m in details["Mounts"]), "model volume differs")
    need(any(p["HostPort"] == "11434" for p in details["NetworkSettings"]["Ports"].get("11434/tcp", [])), "API port differs")


def compositor(user: str) -> None:
    uid = pwd.getpwnam(user).pw_uid
    environment = dict(os.environ, DISPLAY=":0", DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    command = ["xfconf-query", "-c", "xfwm4", "-p", "/general/use_compositing"]
    if os.getuid() != uid:
        command = ["runuser", "-u", user, "--", *command]
    need(run(command, env=environment) == "false", "XFCE compositing must be disabled")


@dataclass
class Requirement:
    name: str
    probe: Callable[[], None]
    stage: str | None = None


def inventory(user: str) -> list[Requirement]:
    checks: list[Requirement] = []
    def add(name, probe, stage=None):
        checks.append(Requirement(name, probe, stage))
    add("Debian 13 / MacPro6,1", lambda: need('ID=debian' in Path('/etc/os-release').read_text() and 'VERSION_ID="13"' in Path('/etc/os-release').read_text() and 'MacPro6,1' in Path('/sys/devices/virtual/dmi/id/product_name').read_text(), "requires Debian 13 MacPro6,1"))
    for name in PACKAGES:
        add(f"package {name}", lambda n=name: package(n), REMOTE_STAGE)
    add("Avahi enabled and running", lambda: service("avahi-daemon"), REMOTE_STAGE)
    add("non-free APT component", lambda: need(any(re.search(r'^(?:Components:|deb ).*\snon-free(?:\s|$)', p.read_text(), re.M) for p in [Path('/etc/apt/sources.list'), *Path('/etc/apt/sources.list.d').glob('*')] if p.is_file() and p.suffix in ('.sources', '.list')), "non-free APT component missing"), WIFI_STAGE)
    for name in (f"linux-headers-{os.uname().release}", "broadcom-sta-dkms"):
        add(f"package {name}", lambda n=name: package(n), WIFI_STAGE)
    add("Broadcom wl wireless interface", lambda: need('wl ' in Path('/proc/modules').read_text() and 'Interface ' in run(['iw', 'dev']), "wl wireless interface missing"), WIFI_STAGE)
    add("headless X configuration", lambda: content('/etc/X11/xorg.conf.d/10-headless-resolution.conf', shell_template('XORG_EOF')), "Configuring the headless X screen")
    def password():
        info = Path('/etc/x11vnc.pass').stat()
        need(info.st_size > 0 and stat.S_IMODE(info.st_mode) == 0o600, "VNC password missing or mode is not 0600")
    add("VNC password exists / mode 0600", password, "Configuring x11vnc")
    add("x11vnc unit", lambda: content('/etc/systemd/system/x11vnc.service', config_for('tmp_x11')), "Configuring x11vnc")
    add("x11vnc enabled and running", lambda: service('x11vnc'), "Configuring x11vnc")
    add("XFCE compositing disabled", lambda: compositor(user), "Configuring VNC desktop responsiveness")
    add("noVNC unit", lambda: content('/etc/systemd/system/novnc.service', config_for('tmp_novnc')), "Configuring noVNC")
    add("noVNC enabled and running", lambda: service('novnc'), "Configuring noVNC")
    def rdp():
        import configparser
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read('/etc/xrdp/xrdp.ini')
        need(config['Globals'].get('autorun') == 'PhysicalDesktop', 'xrdp autorun differs')
        expected = dict(name='Physical desktop (:0)', lib='libvnc.so', ip='127.0.0.1', port='5900', username='na', password='ask')
        need(all(config['PhysicalDesktop'].get(k) == v for k,v in expected.items()), 'xrdp physical desktop differs')
    add("RDP physical desktop", rdp, "Configuring RDP for the physical desktop")
    add("xrdp enabled and running", lambda: service('xrdp'), "Configuring RDP for the physical desktop")
    add("ShellInABox dark theme", lambda: need(Path('/etc/shellinabox/options-enabled/00+White On Black.css').is_file() and not Path('/etc/shellinabox/options-enabled/00+Black on White.css').exists(), 'ShellInABox theme differs'), "Configuring ShellInABox with a dark default")
    add("ShellInABox enabled and running", lambda: service('shellinabox'), "Configuring ShellInABox with a dark default")
    for name in ("docker-ce", "docker-ce-cli", "containerd.io", "docker-buildx-plugin", "docker-compose-plugin"):
        add(f"package {name}", lambda n=name: package(n), DOCKER_STAGE)
    add("Docker repository key", lambda: need(Path('/etc/apt/keyrings/docker.asc').stat().st_size > 0, 'Docker key missing'), DOCKER_STAGE)
    add("Docker repository", lambda: content('/etc/apt/sources.list.d/docker.sources', 'Types: deb\nURIs: https://download.docker.com/linux/debian\nSuites: trixie\nComponents: stable\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/docker.asc\n'), DOCKER_STAGE)
    add("Docker enabled and running", lambda: service('docker'), DOCKER_STAGE)
    for group in ('docker', 'render', 'video'):
        add(f"{user} membership in {group}", lambda g=group: need(g in run(['id', '-nG', user]).split(), f'{user} needs {g} membership'), DOCKER_STAGE)
    add("initramfs-tools", lambda: package('initramfs-tools'), GPU_STAGE)
    add("GRUB GPU arguments", lambda: need(all(a in Path('/etc/default/grub').read_text() for a in ('radeon.si_support=0', 'amdgpu.si_support=1')), 'GRUB GPU arguments missing'), GPU_STAGE)
    add("active GPU boot arguments", lambda: need(all(a in Path('/proc/cmdline').read_text().split() for a in ('radeon.si_support=0', 'amdgpu.si_support=1')), 'reboot required for GPU arguments'))
    add("amdgpu driver", lambda: need(run(['lspci', '-nnk']).count('Kernel driver in use: amdgpu') >= 2, 'both D700s need amdgpu'))
    add("both RADV Tahiti GPUs", lambda: need(run(['vulkaninfo', '--summary']).count('RADV TAHITI') >= 2, 'both Tahiti GPUs must be accessible'))
    add("Ollama container configuration", docker_config, "Configuring Ollama")
    add("Ollama API / local Docker", lambda: manager().api_json(manager().docker_endpoint('ollama', timeout=15), '/api/tags', None, timeout=15))
    def base_identity(model):
        api = manager()
        endpoint = api.docker_endpoint('ollama', timeout=15)
        tags = api.api_json(endpoint, '/api/tags', None, timeout=15)['models']
        need(any(m['name'] == model and m['digest'] == BASE_DIGESTS[model] for m in tags), f'{model} is missing or its pinned digest changed')
        need(api.model_limit(api.api_json(endpoint, '/api/show', {'model': model}, timeout=15)) == 262144, f'{model} context metadata changed')
    for model in MODELS:
        add(f'pinned base identity {model}', lambda m=model: base_identity(m))
    return checks


def manager():
    spec = importlib.util.spec_from_file_location('trashcan_alias_manager', MANAGER)
    need(spec is not None and spec.loader is not None, 'canonical alias manager missing')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe(requirement: Requirement) -> bool:
    try:
        requirement.probe()
        print(f"PASS {requirement.name}", flush=True)
        return True
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"FAIL {requirement.name}: {exc}", flush=True)
        return False


def alias_command(model: str, check: bool) -> list[str]:
    command = [sys.executable, str(MANAGER), '--container', 'ollama', '--model', model]
    for context in CONTEXTS:
        command.extend(['--context', context])
    return command + (['--check'] if check else [])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    user = os.environ.get('TARGET_USER') or os.environ.get('SUDO_USER') or getpass.getuser()
    if user == 'root':
        print('FAIL target account: specify TARGET_USER for the desktop account')
        print('TOTAL pass=0 fail=1 repaired=0')
        return 1
    checks = inventory(user)
    results = {check.name: probe(check) for check in checks}
    repaired = 0
    if not args.check:
        stages = list(dict.fromkeys(check.stage for check in checks if not results[check.name] and check.stage))
        for stage in stages:
            if os.geteuid() != 0:
                print(f'FAIL repair {stage}: run sudo python3 scripts/bootstrap.py explicitly', flush=True)
                continue
            print(f'REPAIR {stage}', flush=True)
            environment = dict(os.environ, TARGET_USER=user)
            result = subprocess.run(['bash', str(SHELL), '--machine-stage', stage], env=environment)
            repaired += 1
            print(f'repair exit={result.returncode}', flush=True)
            for check in checks:
                if check.stage == stage:
                    results[check.name] = probe(check)
    # Continue independent alias probes even when a desktop check fails, but
    # block mutation until all declared prerequisites are healthy.
    prerequisites_ready = all(results.values())
    for model in MODELS:
        status = subprocess.run(alias_command(model, True)).returncode
        if status and not args.check and prerequisites_ready:
            print(f'REPAIR context aliases for {model}', flush=True)
            status = subprocess.run(alias_command(model, False)).returncode
            repaired += 1
            if status == 0:
                status = subprocess.run(alias_command(model, True)).returncode
        if status and not args.check and not prerequisites_ready:
            print(f'FAIL alias repair {model}: prerequisite checks failed; no changes made', flush=True)
        results[f'aliases {model}'] = status == 0
    passed = sum(results.values())
    failed = len(results) - passed
    print(f'TOTAL pass={passed} fail={failed} repaired={repaired}', flush=True)
    if not args.check and not failed:
        host = socket.getfqdn()
        print(f'Desktop: http://{host}:6080/vnc.html\nRDP:     {host}:3389\nShell:   https://{host}:4200\nOllama:  http://{host}:11434', flush=True)
    return 1 if failed else 0


def cli(argv=None) -> int:
    try:
        return main(argv)
    except KeyboardInterrupt:
        print('bootstrap: interrupted; unfinished checks remain unverified', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(cli())
