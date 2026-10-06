# Ollama context alias migration — 2026-10-05

## Approved scope

The operator approved execution of
[`2026-10-05-21-05-29_replace-ollama-context-aliases`](../plans/current/2026-10-05-21-05-29_replace-ollama-context-aliases.md).
There is no designated governing roadmap and no active host pipeline.

## Implementation checkpoint

- Framework baseline changed from host-pinned `139f993` to upstream `0ffa22f`,
  which supplies the alias and versioned-bootstrap routes. Host overrides were
  preserved. The earlier checkout lacked these routes.
- Fixed complete source verification in the canonical framework manager:
  compare the ordered sequence of all `FROM` entries, including the projector.
  Its eight focused tests pass. This is a framework-owned, reviewable local
  change in the submodule, not a host copy or verification bypass; publication
  and committing a framework revision remain outside this checkpoint.
- Added the host stable dispatcher and selected v1 implementation. It checks
  the existing Debian inventory, pins all three base digests, and uses the
  canonical manager for alias probe/repair/re-probe. Retained the customized
  shell setup as individual privileged repair stages, with ordinary shell
  invocations entering the stable boundary. No automatic elevation.
- Updated the Bootstrap Trashcan VS Code task and primary launch action.
  Benchmark commands and setup customizations are preserved.
- Seven host bootstrap boundary tests pass: read-only failure checks, healthy
  no-op, explicit privilege requirement, failed repair, repair/re-probe,
  independent failures, and propagation of interruption to the CLI boundary.
- Host checks passed before deletion. Backed up exactly the Flash `64k` and
  `100k` manifests, confirmed their sources match the Flash base, and removed
  those two manifest files directly. Shared blobs and every original base
  remain intact. These removals can be recovered from the exact saved files.
- Created 15 canonical aliases exclusively through `scripts/bootstrap.py`:
  `trashcan0-local-{1k,4k,64k,96k,256k}-[base name and tag]` for the installed
  Qwen3.8 Q4, Q8, and Flash bases. Initial bootstrap: 59 passing requirements,
  zero failures, three alias-group repairs. Check and repeat normal runs both
  report 59 passes, zero failures, zero repairs.

## Local evidence and rollback

Ignored evidence directory: `.agentic-pipelines/alias-migration/`.
`before.json` records original names, full digests, model definitions and sources.
`check.log` and `repeat.log` record passing checks and convergence.
`runtime.json` checkpoints sanitized runtime trials and resource observations.

Saved legacy manifest hashes:

- `legacy/64k.manifest`: `b0a77d3059bae556524e11a0c3d05d3324f5f72134cedc2c57a5a2153bb0e9bb`
- `legacy/100k.manifest`: `bf6dffd74806f2d0cdfe8ebf5a5246320382fac165155bb14072c5b25c049404`

To recover a legacy tag if necessary, copy its saved manifest to the exact
original container path under
`/root/.ollama/models/manifests/registry.ollama.ai/library/qwen3.8-flash-next/`
and verify its original digest. Do not remove shared blobs or canonical aliases
as part of restoring these legacy names.

Framework rollback reference: `git submodule update --init agentic-pipelines`
restores the host-index revision, but preserve the local framework fix before
attempting rollback. Do not discard an uncommitted framework change.

## Limits and verification

Published model limits match inspected metadata at 262144 tokens for all three
bases: [Qwen3.8 tags](https://ollama.com/library/qwen3.8/tags) and
[Flash tags](https://ollama.com/library/qwen3.8-flash-next/tags).
The server's 130000 default is not a measured hardware cap.

The first runtime trial exposed Ollama's 2048-token minimum allocation for
vision-capable models. The `1k` aliases remain configured with `num_ctx=1024`,
but exact 1024-token allocation is unsupported here. This is consistent with
[Ollama's scheduler](https://github.com/ollama/ollama/blob/main/server/sched.go).
Do not claim that the `1k` aliases allocate a 1K KV cache.

Runtime trials remain in progress. Short sanitized requests verify model
loading, effective context and decode, not full-window quality, long-session
throughput, or a performance improvement. There are no stage mappings yet.

At the runtime checkpoint, both dense models passed 4K, 64K, 96K, and 256K;
Flash passed 64K. All three nominal 1K trials loaded at the 2K minimum.
Flash 4K completed its API request but the verifier could not locate its runner
afterward. A separate client began a 20420-token request during these trials,
occupying Flash at 64K and queuing further verification. The queued 96K trial
was interrupted without stopping the other client's request. Its interrupted
record was saved before an error in the verifier's final status-print path;
the verifier now records interruption explicitly and exits 130 without
attempting to unload another request's runner.

Pending: repeat Flash 4K and verify Flash 96K/256K when the local service is
available for testing. The nominal 1K allocation limitations remain explicit.
An asynchronous operator question requests direction on preserving or
interrupting the separate request. No container restart was performed.
