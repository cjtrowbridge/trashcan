# Trashcan agent routing

Trashcan documents and automates local-AI work on the 2013 Mac Pro 6,1.
Preserve its host-owned documentation, bootstrap configuration, benchmarks, and
local runtime data.

## Agentic Pipelines

For every Agentic Pipelines task, first read and follow the canonical framework
instructions in [`agentic-pipelines/AGENTS.md`](agentic-pipelines/AGENTS.md).
Use its task-routing table to load the smallest applicable ordered set of
playbooks; do not browse framework material speculatively. Follow the framework
in dependency order: design before prompts, configure local inference before
operation, and review analysis before approving a retry.

The framework is a submodule. It owns shared runtime code, templates, schemas,
references, and default playbooks. Trashcan owns its pipeline definitions,
prompts, plans, journal entries, bootstrap and VS Code configuration, local
runtime configuration, and evidence. Keep all host-owned artifacts in this
repository and never overwrite them during framework bootstrap or update.

There is no active model-driven host pipeline yet. Do not infer one from the
benchmark runner. Design and approve a pipeline before creating or operating
one. `api.yaml`, credentials, state, artifacts, threads, failures, runs, and
reports remain local and untracked.

When a framework update changes host-relevant behavior, use the framework's
submodule-update playbook to compare revisions, preserve host customizations,
and obtain approval for behavior-changing synthesis or migration work.
