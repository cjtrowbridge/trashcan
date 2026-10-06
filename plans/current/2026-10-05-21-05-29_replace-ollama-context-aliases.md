---
plan_id: 2026-10-05-21-05-29_replace-ollama-context-aliases
title: Replace Ollama context aliases through host bootstrap
summary: Remove legacy Flash aliases and provision canonical Qwen3.8 context presets through the versioned host bootstrap.
status: current
created_at: 2026-10-05-21-05-29
---

# Replace Ollama context aliases through host bootstrap

Key: `[ ]` pending task, `[x]` completed task, `[?]` needs validation, `[-]` closed task

## Scope and authority

Execution approved by the operator: "ok execute this plan". Promoted to
`plans/current/` before implementation. No designated governing roadmap exists.

Follow `agentic-pipelines/playbooks/how_to_create_ollama_context_aliases.md`,
its Docker alias reference, and the host-bootstrap playbook and contract.
Use the associated `agentic-pipelines/scripts/ensure_ollama_context_aliases.py`
for every new alias. Invoke its repair only through `scripts/bootstrap.py`.

Container: `ollama`. Current hostname: `trashcan0.local`, normalized by the
script to `trashcan0-local`. Preserve these installed bases and record their
full digests at execution time:

| Base model | Current short ID |
| --- | --- |
| `qwen3.8:27b-mtp-q8_0` | `8a1582877303` |
| `qwen3.8:27b-mtp-q4_K_M` | `22130167c4c2` |
| `qwen3.8-flash-next:125b-a6b-q4_K_M` | `f79436a1cc83` |

Remove only `qwen3.8-flash-next:64k` and `qwen3.8-flash-next:100k`.
Preserve all base models, shared blobs, Qwen3.5/Qwen3.6 tags, the Docker volume,
and existing user changes in `bootstrap.sh` and journal files.

For each base, declare `1k`, `4k`, `64k`, and `96k` presets, respectively
1024, 4096, 65536, and 98304 tokens. Names are
`trashcan0-local-[context]-[exact base model name and tag]`; for example,
`trashcan0-local-64k-qwen3.8:27b-mtp-q4_K_M`.
Add a verified upper preset per base where supported. Start with the inspected
and published maximum as a candidate, then lower it if bounded hardware trials
require it. Neither the current server default of 130000 nor the old 100K alias
proves an operating limit. Record unsupported presets rather than claiming they
are usable.

No active host pipeline exists, so stage mapping and measured session budgets
are not applicable yet. Provisioning presets does not authorize a pipeline or
changes to `api.yaml`. Future stages must select the smallest fitting preset
and explicitly align `num_ctx`, retaining a separate `num_predict` limit.

## Execution checklist

- [x] 1. Establish migration readiness before deleting aliases.
  - [x] 1.1 Record host/submodule revisions, dirty-worktree state, Docker endpoint, base digests and source components, model limits and their authoritative sources, and available RAM/VRAM.
  - [x] 1.2 Resolve the canonical script's current rejection of multiple `FROM` entries through a reviewed framework fix and revision adoption; verify all source components, not just the first. Require regression coverage for matching sources, changed/missing projector, context mismatch, and existing-alias conflict. Do not bypass verification or embed a host copy of the manager.
  - [x] 1.3 Confirm chosen contexts against each base's verified limit and design bounded load trials for the upper preset, with finite deadlines and recorded resource observations.
  - [x] 1.4 Resolve and record the two exact legacy alias manifest paths from the actual container volume; save their bytes and sanitized model definitions in ignored host-local rollback storage. Confirm both refer to the intended Flash base and inventory any active loads or consumers.

- [x] 2. Integrate canonical provisioning into host bootstrap.
  - [x] 2.1 Inventory every requirement represented by the existing Debian `bootstrap.sh`, including its uncommitted changes, and propose the initial selected `scripts/bootstrap-v1.py` implementation behind a standard-library-only `scripts/bootstrap.py` dispatcher. Preserve established setup behavior and explicitly supported platforms.
  - [x] 2.2 Implement read-only probes and authorized idempotent repairs for that inventory; never invoke the mutating shell setup from check mode. Report independent failures, totals, dependency-blocked checks, and controlled interruption with exit 130. Require explicit privileges for machine setup rather than silently elevating.
  - [x] 2.3 Add per-base alias requirements using the canonical manager with identical model/container/context arguments in probe and repair; only probes add `--check`. Repair only missing aliases after Docker health, base identity, and context verification; never pull or replace a base or conflicting alias.
  - [x] 2.4 Route the existing Bootstrap Trashcan task and primary launch action through the stable bootstrap, following the VS Code entrypoint playbook. Preserve benchmark behavior and document the supported commands, inventory, privilege boundary, and alias naming in `readme.md`.
  - [x] 2.5 Verify healthy and controlled unhealthy check modes are read-only; verify missing base, unavailable Docker, conflicting alias, failed repair, and Ctrl+C behavior before the live migration.

- [x] 3. Remove legacy aliases, then create replacements through bootstrap.
  - [x] 3.1 Recheck the two exact deletion targets and readiness prerequisites; directly remove only their alias manifest files as authorized by the operator. Do not delete shared blobs, use broad globs, or remove the volume. Verify both names disappear and all base digests remain unchanged.
  - [x] 3.2 Run `python3 scripts/bootstrap.py --check` and record the expected missing canonical aliases without changes.
  - [x] 3.3 Run `python3 scripts/bootstrap.py` to provision and verify canonical aliases through the associated framework manager; record per-alias source/context results and totals.
  - [x] 3.4 Run check mode and normal mode again; require all declared checks to pass and the second normal run to perform no repairs.

- [?] 4. Verify runtime behavior and close the checkpoint.
  - [?] 4.1 Use bounded non-sensitive requests to validate each declared preset; inspect loaded context and offloading with `ollama ps`, record load/decode latency and resource use, and adjust unsupported upper presets through the bootstrap inventory. Make no unmeasured performance claims.
  - [x] 4.2 Reconcile final inventory with the plan: both legacy tags absent, every supported canonical preset verified, all original base identities retained, and rollback files available. Record any pending hardware verification explicitly.
  - [?] 4.3 Validate diffs, documentation, ignored evidence, plan metadata/indexes, and bootstrap convergence; journal the outcome, archive the completed plan, and refresh indexes. Do not commit or push without separate instruction.
  - [ ] 4.4 When the separate Flash request finishes, repeat Flash 4K and verify Flash 96K/256K using the bounded verification helper; preserve the initial failed/interrupted evidence. Do not interrupt the separate request without operator direction.

## Failure and recovery

Do not delete legacy manifests until the manager and bootstrap integration are
ready. If replacement provisioning fails after deletion, preserve successful
canonical aliases and evidence; restore the exact saved legacy manifests if
needed for recovery and verify their original identities. New canonical aliases
must still be created only through the stable bootstrap. Stop affected repairs
on source conflicts, unverifiable limits, or failed runtime loads.

## Roadmap and expected files

There is no designated host roadmap governing this migration. The inference
optimization research report is not an approved bootstrap/alias roadmap; record
this absence during plan review rather than inventing one. This plan is the
proposed task scope and sequencing.

Expected host changes: `scripts/bootstrap.py`, the proposed selected
`scripts/bootstrap-v1.py`, any necessary preserving edits to `bootstrap.sh`,
`.vscode/tasks.json`, `.vscode/launch.json`, `readme.md`, this plan/indexes, and
a journal checkpoint. A framework source-verification repair is a separately
reviewed upstream prerequisite, adopted through the submodule-update playbook;
do not patch framework-owned code as an undocumented host override.
Runtime backups and evidence remain ignored and local.

## Execution notes

Framework repair is present as an explicitly documented local diff in the
canonical submodule at upstream baseline `0ffa22f`; no upstream commit or push
was performed. Eight framework tests and seven host boundary tests pass.
Publication of that framework-owned fix remains outside this checkpoint, so
a fresh clone needs the fix adopted before provisioning these multimodal bases.

Bootstrap reports 59 passing checks. It created five presets for each base;
check mode and repeated normal mode report zero failures and zero repairs.
The two old manifest files have exact recoverable backups in
`.agentic-pipelines/alias-migration/legacy/`. Original model identities are
recorded in `before.json` and checked by runtime verification.

Runtime trials use a 300-second per-request deadline and eight output tokens.
The first trial established that Ollama enforces a 2048-token allocation for
these vision-capable models even when an alias declares `num_ctx=1024`.
Preserve the canonical `1k` definitions but record exact 1K allocation as
unsupported; do not present the configured value as the actual memory budget.
