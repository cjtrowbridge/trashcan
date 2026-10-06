# Measure and improve remote desktop responsiveness

Status: ready for manual execution on Trashcan and its viewing client.
Reported symptom: the remote connection is extremely laggy; no measurements yet.

Goal: identify the dominant delay, test reversible mitigations, and demonstrate
an improvement in visible responsiveness against a repeatable baseline.
Keep this separate from the [idle/disconnection investigation](remote-desktop-idle-investigation.md).
A working connection can still be slow, and a faster connection can still fail
after inactivity. No protocol switch or bootstrap tuning is selected yet.

## 1. Identify the path and freeze test conditions

Record client app/version/OS, server package versions, connection protocol,
host IP/port, VPN/tunnel, wired/Wi-Fi links, monitor count, remote resolution,
scaling, color depth, and negotiated encoding/codec when logs expose it.
Confirm whether "RDP" means XRDP or the repository's x11vnc/noVNC setup.
For XRDP, record Xorg versus Xvnc backend and the session/display involved.
Do not compare a new empty session with a busy existing desktop as if only the
transport changed.

Record client and host CPU load, memory pressure, and active model workloads.
Start with an idle host; later repeat the best candidate during a fixed,
representative Ollama workload. Do not mix load states in a baseline or create
an Agentic Pipelines workflow to run these tests.

Save raw data under ignored `diagnostics/remote-desktop-latency/`. For each run,
record a timestamp, run ID, exact configuration, workload, and observations.
Use the [existing read-only collector](../scripts/collect-remote-desktop-diagnostics.sh)
for host/session context, but it does not measure end-to-end responsiveness.

## 2. Establish measurements that capture the reported lag

### Primary: input-to-visible-response delay

Use the same simple remote test window in every run, preferably a plain text
editor with an empty document, fixed font, and no completion/extensions. Press a
single key and measure the time until its character appears **inside the remote
window on the client screen**. A locally drawn pointer or click indicator is not
proof the server processed input.

Film the physical key/button action and the client display together using a
high-frame-rate camera (120 fps or more if available). Use the same camera,
screen refresh rate, and framing for all runs. A visible key-down reference is
approximate; record the contact-marker method and uncertainty. A synchronized
input-event/photodiode rig is an optional improvement, not a prerequisite.

For each isolated keypress, count frames between the physical input marker and
the first visible remote character:

```text
response_ms = (response_frame - input_frame) * 1000 / recording_fps
```

Space inputs far enough apart to associate each response with its input. Collect
30 samples per run and three baseline runs (90 samples total). Include a short
rapid-typing trial separately to reveal buffering, lost characters, and delayed
bursts. Record dropped/reordered input rather than excluding it as an outlier.
Use the same client keyboard path and remote application throughout.

Calculate median and p95 delay, maximum delay, and failed/missing responses.
Define p95 consistently as the sorted sample at index `ceil(0.95 * N)` (one-based).
Report individual runs and pooled samples so one unusually good run cannot hide
instability. At 120 fps one frame is about 8.3 ms; changes smaller than the
measurement uncertainty are inconclusive. If only a 60 fps recording is possible,
state its roughly 16.7 ms frame interval and wider uncertainty.

Do not subtract unsynchronized client and server wall-clock timestamps, use
ping as the input-delay metric, or present server-rendering FPS as client-visible
FPS. A client-local timer can aid automation only if it measures both input and
the matching visible response with the same clock and reports detection overhead.

### Secondary: update stalls and ordinary task time

Use a fixed document and repeatable 10-second scroll/window-drag sequence, with
the same window size, scroll distance, and input cadence. From the recording,
measure gaps between actual visible content updates (ignore cursor-only changes):
median/p95 update gap, longest freeze, and count of freezes longer than 250 ms.
Treat the freeze threshold as an investigation convention. Record visible tearing,
blur, unreadable text, or delayed catch-up after motion stops.

Also time one fixed desktop task, such as opening the same menu and moving the
same window between marked positions, five times per run. Record subjective
responsiveness on a consistent 1–5 scale as supporting evidence. Human task
time and ratings are secondary; they do not replace measured response delay.

### Supporting: network and resource measurements

Measure the client-to-host path during the same runs:

```bash
# Linux/macOS client; on Windows use: ping -n 100 <host-ip>
ping -c 100 <host-ip>
```

Record RTT distribution and loss. ICMP can be filtered/deprioritized, so correlate
it with transport evidence rather than declaring a cause from ping alone.
Inspect `ss -ti` on the host for the relevant connection's RTT/retransmissions,
and interface counters for drops/errors. Record client decode/browser CPU too.
If available, run `vmstat 1 60` and `pidstat -u -r -p <server-pids> 1 60` during
a test; note that pidstat comes from `sysstat`. Include Xorg and the actual
remote server/encoder processes. Inspect kernel logs for GPU resets/timeouts.

If bandwidth is suspect, optionally use iperf3 between the same endpoints in
both directions, outside the latency trial; the throughput test itself competes
with the desktop. Keep any temporary listener on the trusted LAN, stop it after
testing, and record results. Throughput is supporting evidence, not a success
criterion for responsiveness.

## 3. Locate the bottleneck and test mitigations

Run paired A/B/A trials: baseline, candidate, restored baseline. Repeat promising
pairs three times, alternating order where practical. Warm up each connection
for the same period and repeat the same workload. Change one variable at a time;
record settings/file diffs, negotiated settings, and rollback before each change.
Capture logs before a service restart. Do not run two clients simultaneously
unless multi-client access is the explicit test condition.

| Evidence or hypothesis | Candidate experiment | Cost/rollback |
| --- | --- | --- |
| Network RTT/loss/jitter tracks response spikes | Wired client versus Wi-Fi; same LAN versus current VPN/path; reduce background transfers | Keep server/client settings fixed. Restore the original path; record that a path change may not be available for everyday use. |
| Large framebuffer/encode load | Reduce remote resolution first, then separately test one monitor or lower color depth | Restore original display settings. Record readability and screen-space loss; an improvement at smaller resolution is a qualified tradeoff. |
| Client decode/render bottleneck | Same protocol/server with another native viewer; for noVNC, another browser or browser acceleration setting | Change one client variable; restore it afterward. Monitor client CPU and keep zoom/scaling fixed. |
| noVNC path adds delay | Compare noVNC with a native VNC viewer against the same x11vnc desktop | Existing bootstrap binds VNC to loopback. Use SSH forwarding (`ssh -N -L 15900:127.0.0.1:5900 cj@<host-ip>`) and connect the viewer to `127.0.0.1:15900`; stop the tunnel afterward. This comparison also changes transport to SSH, so document the confound and do not attribute all improvement to browser decoding. |
| VNC encode CPU versus bandwidth tradeoff | Compare supported encoding/quality/compression settings, one at a time | Restore previous viewer settings. Confirm negotiated encoding; inspect both CPU and bytes transferred plus text quality. |
| x11vnc capture/update scheduling suspected | Inspect installed `x11vnc -help`/manual; test one supported wait/defer or copy-rectangle behavior | Save the original service configuration; restore it and restart intentionally afterward. Smaller delays can increase CPU without improving visible response. |
| XRDP encoder/backend suspected | Inspect installed xrdp/xorgxrdp versions, session logs and local manuals; compare supported codec settings or backend | Back up relevant config and restore for rollback. Verify negotiation; newer upstream options may not exist in Debian's installed version. Backend changes may create a different desktop session. |
| XFCE compositing adds rendering overhead | Temporarily toggle compositing in XFCE Window Manager Tweaks | Record the original state and restore it; check tearing and other display regressions. |
| Lag appears only under inference/resource pressure | Repeat identical idle versus fixed Ollama load; then test limiting competing workload concurrency | Record model, request/load parameters and throughput. Do not claim a free improvement if inference performance or concurrency is reduced. |
| GPU reset or display-session faults coincide | Follow the timestamped GPU/session evidence before performance tuning | Address the fault separately; rerun baseline measurements after repair. |

For VNC settings, consult the installed server/viewer options and the
[TigerVNC viewer manual](https://tigervnc.org/doc/vncviewer.html), which documents
encoding, quality, compression, and automatic selection. For x11vnc experiments,
use its [upstream option definitions](https://github.com/LibVNC/x11vnc/blob/master/src/options.c)
and installed help. For XRDP, compare the installed configuration with
[upstream xrdp.ini](https://github.com/neutrinolabs/xrdp/blob/devel/xrdp/xrdp.ini.in)
and [gfx.toml](https://github.com/neutrinolabs/xrdp/blob/devel/xrdp/gfx.toml);
development-branch files are references, not settings to copy blindly.

## 4. Decide whether a candidate succeeds

Proposed acceptance criteria, fixed before candidate testing:

- Primary improvement: at least 30% lower pooled p95 input-response delay than
  baseline, with improvement in all three paired runs beyond measurement
  uncertainty. Median delay must not regress by more than 10%.
- Smoothness: p95 update gap must improve or stay within 10% of baseline, with
  no increase in freezes over 250 ms, lost inputs, or disconnected sessions.
- Usability: text remains readable and the fixed task is no slower. Record any
  resolution/quality concessions explicitly; judge a candidate at the required
  everyday display settings as well as its fastest settings.
- Reliability: the improvement persists after a fresh connection, desktop
  login/reboot, and at least 20 minutes of inactivity. Repeat the idle-failure
  check; a candidate that disconnects is not accepted.
- Load: repeat baseline-versus-candidate under the same representative inference
  load. Report load-specific results and resource/throughput costs separately.

Use 250 ms p95 input delay as an initial usability target, not a proven universal
limit. If a 30% improvement still leaves the connection painfully slow, report
partial progress and continue investigating. If the baseline cannot be reproduced
or differences fall within run-to-run variability, report an inconclusive result.
Do not revise thresholds after seeing a favored candidate's scores.

## 5. Record the result and promote a validated change

Keep raw input samples with columns `run_id, trial, input_frame, response_frame,
recording_fps, response_ms, outcome`. Keep update-gap observations separately.
Use this summary table for each workload:

| Variant/run | Protocol/settings | Input median/p95 ms | Update p95/max gap ms | Freezes/lost inputs | CPU/network | Quality/task time | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| Candidate | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| Restored baseline | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

Summarize cause, measurements, uncertainty, tradeoffs, exact changes, rollback,
and idle/reboot/load validation in a host journal entry. Promote only the tested
server-side remedy into bootstrap with idempotent checks. Document client or
network changes separately. A protocol replacement requires its own review of
desktop/session behavior and remote-access configuration before adoption.
