# Trashcan

Trashcan documents and automates the work of turning a 2013 cylindrical Mac Pro
(`MacPro6,1`) into a useful local-AI machine. The reference system is a 12-core
Mac Pro with 128 GB RAM, dual 6 GB AMD FirePro D700 GPUs, and Debian 13 with
XFCE. Ollama runs in Docker and uses both old Tahiti GPUs through Mesa RADV's
Vulkan backend rather than ROCm.

## Bootstrap

[`bootstrap.sh`](bootstrap.sh) is the executable record of the setup steps that
have been validated so far. It installs, configures, and verifies:

- Avahi/mDNS discovery;
- x11vnc and noVNC for the physical LightDM/XFCE desktop;
- ShellInABox with a dark default theme;
- Docker Engine from Docker's Debian repository;
- Debian firmware, Mesa RADV, and Vulkan diagnostics;
- the `amdgpu` kernel driver for the D700's Southern Islands/Tahiti GPUs;
- Docker, `render`, and `video` access for the invoking user; and
- a persistent, Vulkan-enabled Ollama container.

Each stage reports whether it was already correct, changed, or needs attention.
The script is idempotent: run it again whenever desired, including after package
updates or configuration changes.

Run it from the normal desktop account:

```bash
chmod +x bootstrap.sh
sudo ./bootstrap.sh
```

On its first run, the script asks for a VNC password if one has not been set.
Switching the GPUs from `radeon` to `amdgpu`, and newly granted group membership,
require a reboot or new login session. The script reports that condition and
defers creation of the GPU-enabled Ollama container until Vulkan is ready. After
rebooting, run the same command again to finish and verify the setup.

To configure an account other than the one invoking `sudo`:

```bash
sudo TARGET_USER=cj ./bootstrap.sh
```

When complete, the script prints the host-specific URLs for noVNC,
ShellInABox, and the Ollama API. Verify model placement while a model is loaded
with:

```bash
docker exec ollama ollama ps
```

The `PROCESSOR` column is the authoritative quick check for GPU offload.

## Benchmarking

[`llm_benchmark`](llm_benchmark) is included as a submodule for repeatable
Ollama measurements. Run `python llm_benchmark/benchmark.py`, use the
**Benchmark Ollama** VS Code task, or select the same named Run and Debug
configuration. The runner interactively chooses the endpoint, models, prompts,
and number of rounds, then writes raw samples and a Markdown report beneath
`llm_benchmark/fqdn/`.

[`agentic-pipelines`](agentic-pipelines) is included as a submodule for future
local-inference workflows. The host scaffold is ready, but there is intentionally
no active model-driven pipeline until its purpose and review/promotion rules are
defined. Copy `api.sample.yaml` to ignored `api.yaml` only when configuring one.

## Security scope

This configuration is intended for a trusted local network. noVNC is served over
plain HTTP (the VNC session itself requires the password created during setup),
ShellInABox normally uses a self-signed TLS certificate, and the Ollama API is
published on port `11434` without application-level authentication. Do not expose
ports `6080`, `4200`, or `11434` directly to the public internet; put them behind
appropriate firewalling, a VPN, or an authenticated TLS reverse proxy first.

## Current scope

The bootstrap captures the proven baseline. Performance experiments such as
forcing high GPU clocks, `RADV_PERFTEST=nogttspill`, Flash Attention, KV-cache
quantization, smaller prompt batches, or D700 stability flags are deliberately
not made permanent yet. They should be benchmarked on this hardware before being
canonized here.
