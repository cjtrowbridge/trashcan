# Trashcan

Trashcan documents and automates the work of turning a 2013 cylindrical Mac Pro
(`MacPro6,1`) into a useful local-AI machine. The reference system is a 12-core
Mac Pro with 128 GB RAM, dual 6 GB AMD FirePro D700 GPUs, and Debian 13 with
XFCE. Ollama runs in Docker and uses both old Tahiti GPUs through Mesa RADV's
Vulkan backend rather than ROCm.

## Bootstrap

[`scripts/bootstrap.py`](scripts/bootstrap.py) is the stable setup entrypoint,
selecting [`scripts/bootstrap-v1.py`](scripts/bootstrap-v1.py). It probes the
declared host inventory and repairs only failed requirements. The existing
[`bootstrap.sh`](bootstrap.sh) retains the Debian setup logic as individually
selected machine-repair stages and forwards ordinary invocations to the stable
entrypoint. The inventory includes:

- Avahi/mDNS discovery;
- x11vnc and noVNC for the physical LightDM/XFCE desktop;
- ShellInABox with a dark default theme;
- Docker Engine from Docker's Debian repository;
- Debian firmware, Mesa RADV, and Vulkan diagnostics;
- the `amdgpu` kernel driver for the D700's Southern Islands/Tahiti GPUs;
- Docker, `render`, and `video` access for the invoking user; and
- a persistent, Vulkan-enabled Ollama container; and
- canonical context aliases for the three installed Qwen3.8 base models.

Each stage reports whether it was already correct, changed, or needs attention.
The script is idempotent: run it again whenever desired, including after package
updates or configuration changes.

Run it from the normal desktop account:

```bash
python3 scripts/bootstrap.py --check
python3 scripts/bootstrap.py
```

Check mode is read-only and exits nonzero for any failed requirement. Normal
mode repairs missing aliases through the framework's canonical manager and
rechecks them. Machine repairs require explicitly running
`sudo python3 scripts/bootstrap.py`; ordinary mode never elevates. The bootstrap
and Debian machine backend are supported on this Linux host. Python dispatch
is portable, but machine setup is not claimed to work on macOS or Windows.

In VS Code connected to the Debian host, **Bootstrap Trashcan** is the primary
Run and Debug action and is also available as a task. It invokes this same
entrypoint. Existing `bash bootstrap.sh` commands also enter that boundary.

On its first run, the script asks for a VNC password if one has not been set.
Switching the GPUs from `radeon` to `amdgpu`, and newly granted group membership,
require a reboot or new login session. The script reports that condition and
defers creation of the GPU-enabled Ollama container until Vulkan is ready. After
rebooting, run the same command again to finish and verify the setup.

To configure an account other than the one invoking `sudo`:

```bash
sudo TARGET_USER=cj python3 scripts/bootstrap.py
```

When complete, the script prints the host-specific URLs for noVNC,
ShellInABox, and the Ollama API. Verify model placement while a model is loaded
with:

```bash
docker exec ollama ollama ps
```

The `PROCESSOR` column is the authoritative quick check for GPU offload.

## Desktop troubleshooting

The [remote desktop latency investigation](plans/remote-desktop-latency-investigation.md)
defines input-response and screen-update measurements, controlled mitigation
trials, and measurable acceptance criteria for the laggy remote connection.

Remote desktop failing after inactivity is tracked in the
[evidence record](research/remote-desktop-idle-failure.md) and
[host investigation plan](plans/remote-desktop-idle-investigation.md).
The plan includes a read-only diagnostic collector and before/failure captures
to run on Trashcan before promoting a remedy into bootstrap.

The [keyring encryption investigation](plans/keyring-encryption-investigation.md)
tracks the OS keyring warning, with session diagnostics, targeted remedies,
rollback, and checks for encrypted credential persistence.

Aliases use `trashcan0-local-[context]-[base model name and tag]`, preserving
the installed Qwen3.8 Q4, Q8, and Flash tags. Presets are `1k`, `4k`, `64k`,
`96k`, and `256k` (one k is 1024 tokens). Runtime verification
and its limitations are recorded in the
[migration journal](journal/2026-10-05-ollama-context-alias-migration.md). The bootstrap
creates only missing aliases; source or context conflicts fail visibly.
It never pulls models or overwrites conflicting aliases. Request-level
`num_ctx` overrides alias defaults; future pipeline stages must align both and
declare a separate `num_predict` completion budget. No host pipeline is enabled.
For these vision-capable models, Ollama enforces a minimum runtime allocation
of 2048 tokens: the `1k` aliases retain a declared `num_ctx=1024`, but do not
provide a 1024-token memory allocation. Use the recorded effective allocation
when comparing memory use.

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

The versioned report in
[`research/maximizing-local-llm-inference-research.md`](research/maximizing-local-llm-inference-research.md)
audits the baseline, investigates the hardware/software optimization space, and
defines a prioritized, falsifiable experiment program for maximizing decode
throughput before any tuning is made permanent.
