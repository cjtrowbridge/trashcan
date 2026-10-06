# Trashcan TODO

- [ ] Run the [remote desktop latency investigation](plans/remote-desktop-latency-investigation.md)
      and validate mitigations against input-delay and update-stall measurements.

- [ ] Run the [keyring encryption investigation](plans/keyring-encryption-investigation.md)
      in the affected app's desktop session; verify secure credential persistence.

- [ ] Run the [remote desktop idle investigation](plans/remote-desktop-idle-investigation.md)
      on `trashcan0`; validate the cause and remedy before changing bootstrap.

- [ ] Define the first Agentic Pipelines workflow: its source material, desired
      output, promotion policy, semantic review boundary, and local model budget.
- [ ] Copy `api.sample.yaml` to ignored `api.yaml` and select a local Ollama
      model when that workflow is ready for local inference.
- [ ] Benchmark the candidate D700 performance profiles before canonizing any
      non-baseline Ollama tuning in `bootstrap.sh`.
- [ ] Limit docker ollama to all but a couple of the cpu cores (10/12) so there are a couple left for everything else.
      - ie: docker run -d --cpus="10" -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
