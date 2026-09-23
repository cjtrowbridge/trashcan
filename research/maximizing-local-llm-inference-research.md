# Deep research: maximizing local LLM inference on a dual-D700 Mac Pro 6,1

**Research date:** September 23, 2026
**Target:** MacPro6,1, Xeon E5-2697 v2, 128 GB RAM, dual FirePro D700 6 GB, Debian 13, amdgpu + RADV, Docker + Ollama Vulkan

**Optimization objective:** maximize steady-state Ollama/llama.cpp decode throughput (`eval_count / eval_duration`) for each of the five current models on this exact machine. Correctness, stability, thermals, and repeatability are hard constraints. TTFT, prefill, context capacity, and aggregate concurrent throughput remain separately reported diagnostics; they are not blended into the primary score.

**Evidence status:** revised against the repository's benchmark implementation and raw run bundle. Public documentation is used for mechanism and option semantics; local measurements are used for baseline claims.

---

# 1. Executive conclusion

The largest credible gains on this machine are most likely to come from **placement, residency, quantization, speculative-decoding control, and the Vulkan/RADV path**, not from generic Linux tuning.

The central architectural fact is that the two D700s are **two independent 6 GB devices**, not a unified 12 GB accelerator. Apple specifies each D700 at 6 GB GDDR5 and 264 GB/s. Current llama.cpp Vulkan can use multiple devices, but its normal mechanism is pipeline/layer splitting: different contiguous layers live on different GPUs and execution passes through them sequentially. Current tensor parallelism is explicitly experimental, requires Flash Attention and unquantized KV, and upstream warns that performance is not guaranteed outside NVIDIA CUDA. The older/current feature matrix still characterizes Vulkan multi-GPU as sequential rather than optimized parallel multi-GPU.

That leads to six high-priority conclusions.

**First: fix the benchmark before tuning anything.** The existing results are useful enough to establish that the machine is working, but not enough to distinguish a 5–15% optimization reliably. Ollama now exposes `load_duration`, `prompt_eval_count`, `prompt_eval_cached_count`, `prompt_eval_duration`, `eval_count`, and `eval_duration`. Those should be recorded separately from client-observed first-content latency.

**Second: explicitly map GPU placement.** Current Ollama intends to put a model on one GPU when it fits and spread it when it does not. It also exposes `GGML_VK_VISIBLE_DEVICES` and `OLLAMA_SCHED_SPREAD`. The D700 is an unusually strong case for experimentally comparing GPU 0 only, GPU 1 only, both GPUs with the default scheduler, and both GPUs with spread forced. Current Ollama documentation describes single-GPU placement as preferable when possible because it avoids PCIe transfers.

**Third: treat MTP as an experiment, not a feature that is already helping.** Current Ollama requires an explicit `draft_num_predict` for embedded MTP tensors; setting it to zero disables speculation. Recent field reports show everything from substantial Vulkan gains on new AMD GPUs to large regressions, CPU offloading, and concurrency-specific Vulkan performance collapses. The baseline's `n/a` acceptance evidence therefore matters: merely using an MTP-named GGUF does not demonstrate that speculative decoding was active or beneficial.

**Fourth: `RADV_PERFTEST=nogttspill` deserves a controlled early A/B test.** It is a real current Mesa option and does exactly what its name implies: prevents RADV from satisfying VRAM allocations by spilling them into GTT. On a pair of only-6-GB GPUs, silent spill is particularly relevant. It is not guaranteed to be faster—it may instead turn a slow allocation into an allocation failure—but it is unusually informative because a performance change tells us whether GTT residency is part of the problem.

**Fifth: the D700 should not be treated like a miniature modern Radeon.** RADV supports GCN1/Tahiti, but GFX6 is a Vulkan 1.3 target. AMD's GCN-era optimization documentation says packed 16-bit and 8-bit operations are not native on that architecture. The E5-2697 v2 likewise has AVX but not AVX2 and peaks at 59.7 GB/s across four DDR3-1866 memory channels. Consequently, modern recommendations involving cooperative matrices, modern packed-int dot products, HIP/ROCm kernels, AVX2/AVX-512 CPU kernels, or RDNA-specific shader paths should not be generalized to this box.

**Sixth: add a bridge model before drawing conclusions about dual-GPU scaling.** The 4B model fits one card, while the present 27B/35B/125B files are far beyond the pair's aggregate VRAM. None isolates the case where a model cannot fit one D700 but can fit entirely across two. Add a same-family model whose measured working set is above one card's usable VRAM and below the two-card aggregate—likely a roughly 7–10 GB GGUF, subject to measurement—and use it to test layer splitting without CPU/RAM capacity pressure.

The most promising **capacity/performance strategy** is therefore likely:

> one D700 for models that genuinely fit it; layer-split across two D700s for models that fit within two independently allocated 6 GB budgets; aggressive but quality-checked weight/KV quantization to cross those residency thresholds; and CPU/RAM hybrid execution primarily for sparse MoE models where the active working set is low enough to justify the much slower memory tier.

The most important unknown is what is *actually resident where* during the current benchmark. An Ollama `100% GPU` label is useful but does not prove balanced placement, absence of GTT involvement, full utilization of both cards, or optimal layer distribution.

### What not to do yet

Do **not** move to ROCm, force experimental tensor parallelism, add random RADV debug flags, disable GPU recovery, manually overclock/overvolt the cards, change IOMMU settings, enable hugepages, tune CPU affinity, replace Docker, or backport Mesa before collecting the Benchmark v2 baseline.

There is currently no evidence that any of those changes addresses the existing bottleneck.

---

# 2. Baseline audit

## Evidence actually available

The repository now contains the benchmark client and raw run bundle. The audit below covers all 15 samples per model (five rounds at each of three prompt sizes), rather than relying on summary extrema alone.

| Model | Decode mean | Median | Range | CV | Output-token range | Uncached prefill median (n=3) | Cached prefill median (n=12) | Max load |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.5:4b` | 9.151 | 9.126 | 9.060–9.371 | 0.87% | 919–4,062 | 50.01 tok/s | 998.41 tok/s | 5.973 s |
| `qwen3.6:35b-a3b-mtp-q8_0` | 6.778 | 6.656 | 6.383–7.792 | 5.59% | 204–1,321 | 22.56 tok/s | 554.38 tok/s | 38.209 s |
| `qwen3.8-flash-next:125b-a6b-q4_K_M` | 4.083 | 4.241 | 3.141–4.446 | 9.03% | 70–427 | 4.26 tok/s | 333.73 tok/s | 45.682 s |
| `qwen3.8:27b-mtp-q4_K_M` | 2.350 | 2.349 | 2.031–2.879 | 9.61% | 90–696 | 4.19 tok/s | 169.15 tok/s | 29.553 s |
| `qwen3.8:27b-mtp-q8_0` | 1.592 | 1.571 | 1.406–1.872 | 7.89% | 89–471 | 1.35 tok/s | 156.55 tok/s | 54.438 s |

These numbers establish useful starting points, but not controlled treatment effects:

* The 4B decode result is exceptionally stable and is the best canary for host/GPU-state regressions.
* Median decode for 27B Q4_K_M is about **49.5% higher** than 27B Q8_0 (`2.349 / 1.571 - 1`). This is the strongest current optimization signal, but it is not yet causal: model revision, template, MTP settings, output work, and placement must be matched before attributing the full difference to quantization.
* The sparse 35B-A3B model substantially outruns dense 27B despite more total weights. This supports active working set and architecture as important variables, while leaving expert placement, routing, and CPU/GPU traffic unresolved.
* The first prompt of each size is uncached, while subsequent repetitions reuse almost the entire prefix (approximately 30/34, 220/224, and 2,106/2,110 cached tokens). Cached and uncached prefill values therefore describe different workloads and must never be pooled.
* Generated work is uncontrolled: output counts vary by roughly 4–10× within a model. The current decode ratio is still server-reported, but short completions and model-selected stopping can change warm-up and steady-state behavior enough to invalidate fine-grained A/B conclusions.

## Benchmark implementation findings

The current request payload contains only `model`, `prompt`, and `stream`. It does not pin generation length, temperature, seed, context, batch, thinking behavior, keep-alive, or MTP draft depth. Defaults can therefore change across models and Ollama versions.

The client marks TTFT from the first non-empty `response` field. Models may stream a separate `thinking` field first, so present TTFT can include an unmeasured hidden-thinking interval. That is a strong code-level concern, not yet proof that every recorded sample contained thinking; Benchmark v2 must timestamp both fields to resolve it.

The raw bundle is sufficient to verify the numeric summaries above. It is not sufficient to reconstruct exact weight/KV/compute placement, per-device VRAM versus GTT, GPU clocks, CPU fallback, MTP acceptance, model digests, or the installed runtime stack. Those remain measurement tasks.

### Comparisons that are not yet trustworthy

Prefill is not trustworthy until `prompt_eval_cached_count` is controlled. Current Ollama separately reports cached prompt tokens and defines `prompt_eval_duration` around uncached prompt evaluation.

Cold and warm TTFT are conflated if the current TTFT starts before model loading. Ollama already supplies a separate `load_duration`; client-side timing should separately capture first streamed content.

MTP results are not MTP results until drafted/accepted work is demonstrated. Current Ollama documentation explicitly says embedded MTP requires setting `draft_num_predict`.

The 100/1,000/10,000-byte prompts are not necessarily equal-token workloads. V2 should record token counts, not only byte lengths.

Output lengths and termination reasons must be controlled. The existing bundle demonstrates this problem directly: observed outputs range from 70 to 4,062 tokens depending on model and sample.

### Important current-version ambiguity

Ollama documentation and source are evolving rapidly. For example, its FAQ currently describes a default context of 4096, while current environment configuration describes an automatic 4K/32K/256K default based on VRAM. This is exactly why the benchmark must set and record `num_ctx` explicitly rather than inheriting defaults. Every future report must also record the Ollama image digest, embedded llama.cpp revision where discoverable, model digest, kernel, Mesa/RADV, firmware, container arguments, and the canonical `launch.json`/bootstrap revision.

---

# 3. System bottleneck model

The correct model is not "the Mac Pro is memory-bandwidth limited." Different workloads can hit completely different ceilings.

| Workload                  | Leading hypothesis                                                           | Competing hypotheses                  | Evidence needed                                                  |
| ------------------------- | ---------------------------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------- |
| 4B model, one D700        | old Vulkan quant/GEMV shader efficiency, dispatch/synchronization, or clocks | VRAM BW, CPU sampling/tokenization    | single-GPU runs; GFX/compute utilization; sclk/mclk; CPU profile |
| 4B split across two D700s | inter-GPU sequencing likely adds overhead                                    | second GPU may improve prefill        | compare GPU0/GPU1/both; per-GPU utilization                      |
| ~6–12 GB working set      | layer placement / PCIe / per-GPU fit                                         | GTT spill or CPU spill                | logs, VRAM/GTT per card, `nogttspill`                            |
| >12 GB dense model        | system-RAM bandwidth + CPU/Vulkan hybrid                                     | PCIe or unsupported GPU operations    | CPU bandwidth/utilization, GPU layer count, page faults          |
| Large MoE                 | expert-weight traffic and residency                                          | routing compute, CPU expert execution | expert/CPU placement; RAM BW; compare same active-param class    |
| Long context              | KV capacity and attention implementation                                     | model weights displaced from VRAM     | KV size, FA status, VRAM growth by context                       |
| Prefill                   | shader arithmetic throughput / batch geometry                                | CPU fallback, synchronization         | pp/s vs `num_batch`, GPU util, CPU perf                          |
| Decode                    | weight movement / GEMV / dispatch                                            | sampler CPU cost                      | tg/s, CPU profile, sclk/mclk                                     |
| Cold TTFT                 | model file I/O + mmap/page faults + pipeline creation                        | model conversion/setup                | `load_duration`, major faults, disk activity                     |
| Warm TTFT                 | prompt eval + scheduler + first-token latency                                | cache                                 | cached-token count, first-content timestamp                      |
| Concurrent requests       | aggregate device occupancy may improve                                       | KV multiplication and MTP contention  | aggregate TPS + p95 latency + VRAM                               |

## Per-model optimization map

The five current models should not share one generic tuning path.

| Model | Current decode median | First mechanisms to isolate | Highest-value next tests |
| --- | ---: | --- | --- |
| 4B Q4_K_M | 9.126 tok/s | single-card Vulkan kernel efficiency, card asymmetry, clocks | GPU0 vs GPU1; best single vs dual; sustained clock trace; Q4_0/Q5 variants; direct llama.cpp |
| 35B-A3B Q8_0 | 6.656 tok/s | expert residency/traffic, CPU-MoE placement, MTP, scheduler | placement trace; MTP off/on at fixed residency; direct llama.cpp CPU-MoE controls; quant variants |
| 125B-A6B Q4_K_M | 4.241 tok/s | RAM bandwidth, expert placement, CPU fallback, unsupported/fallback operators | operator/backend trace; CPU thread/NUMA-affinity diagnostics; expert-offload controls; storage/page-fault isolation |
| 27B MTP Q4_K_M | 2.349 tok/s | hybrid layer placement, quantized bandwidth, GTT, MTP overhead | controlled quant ladder; explicit layer split; `nogttspill`; MTP off/on with acceptance evidence |
| 27B MTP Q8_0 | 1.571 tok/s | larger working set and host traffic | same-source Q4/Q5/Q6/Q8 comparison; exact CPU/GPU layer map; avoid treating Q8 as the speed target unless quality requires it |

The 125B model's relatively high decode rate does not imply that its full weight set is moving through the GPU every token. Sparse routing and hybrid placement can produce that result. Its optimization program must begin with operator- and expert-placement evidence, not with assumptions based on total parameter count.

Add a **bridge model** to the matrix: same family if possible, measured GGUF plus runtime buffers too large for one D700 but able to remain fully GPU-resident across both. This is the only clean test of whether dual-D700 layer splitting can increase capacity without introducing CPU/RAM traffic. Select it by observed allocation, not parameter-label shorthand.

## Why raw bandwidth is not enough

Each D700 has 264 GB/s of theoretical GDDR5 bandwidth. The Xeon has a theoretical maximum system-memory bandwidth of 59.7 GB/s.

Yet the observed 4.7B Q4 model produces only about 9 tok/s. A roughly few-gigabyte quantized weight set at 9 full weight sweeps/s is far below 264 GB/s. That does **not** prove unused bandwidth—the model has recurrent/attention work, dequantization, intermediate tensors, synchronization and many kernels—but it is enough to reject a simplistic "264 GB/s means the model should already be bandwidth-saturated" assumption.

Tahiti is also missing the low-precision arithmetic machinery that makes newer GPUs unusually good at quantized inference. AMD's contemporary GCN guidance explicitly says packed 16- and 8-bit operations were not native. Vulkan 1.3 conformance does not imply optional FP16, int8-dot or cooperative-matrix acceleration.

Capture these properties from the actual D700 with `vulkaninfo` before interpreting any kernel result:

```bash
vulkaninfo --summary
vulkaninfo | grep -Ei \
  'shaderFloat16|shaderInt8|integerDotProduct|cooperativeMatrix|subgroup|memoryHeap'
```

## Small model fitting one D700

This is the cleanest GPU-path diagnostic. Run the 4B model on GPU 0 alone, GPU 1 alone, and both visible.

If one-card decode equals dual-card decode, dual-GPU execution is providing no decode advantage. If dual is slower, pipeline synchronization is costing throughput. If one card is materially slower than the other, display use, thermal behavior, or card-specific health becomes a leading explanation.

Ollama itself says it normally prefers one GPU when the model fits because that reduces PCI-bus transfer.

## Model fitting only across two D700s

Current llama.cpp's default `layer` mode assigns contiguous layer groups to devices and distributes KV with those layers. This is the sensible topology for the D700 pair because it minimizes the frequency and volume of cross-device communication compared with tensor parallelism.

The key tests are not "is it 100% GPU?" but:

* how many model bytes are allocated on D700 A;
* how many on D700 B;
* how much GTT is used;
* whether either card reaches allocation pressure;
* whether one card is idle while the other works;
* whether forcing scheduler spread changes the split;
* whether `nogttspill` changes performance or turns the run into an allocation failure.

## Hybrid GPU + RAM model

Here the memory hierarchy becomes stark: 264 GB/s per local GPU versus a maximum 59.7 GB/s for the entire four-channel CPU memory controller, before accounting for CPU dequantization/compute. The E5-2697 v2 also exposes AVX but not AVX2.

Large dense models are therefore likely to become CPU/RAM-bound once a meaningful part of every layer is offloaded to the host.

Sparse MoE changes that equation. The baseline's 35B-A3B result beating dense 27B is consistent with that, although the actual per-token expert traffic must be measured rather than inferred from the advertised active parameter count.

## Long context

Long context is potentially more important than another few percent of decode speed because KV growth can push a model across a residency threshold.

Current Ollama can use Q8_0 KV at about half the memory of f16, with what it characterizes as a very small precision loss; Q4_0 uses about one quarter of f16 memory but with a larger quality penalty, especially at long contexts. Quantized KV requires Flash Attention.

Whether Flash Attention is actually beneficial on GFX6 must be measured. llama.cpp's current feature matrix says Vulkan supports FA, but that is a backend-wide claim; it does not imply that the optimal Tahiti path is a modern FP16 cooperative-matrix kernel.

## Telemetry on this exact generation

`amdgpu_top` is useful because it reads GRBM/GRBM2 counters, sensors, fdinfo and VRAM/GTT usage from amdgpu. Its newer `gpu_metrics` interface should **not** be expected on a D700: the project's own history says that interface begins at Vega12 for dGPUs.

Use:

```bash
amdgpu_top --list
amdgpu_top -d
amdgpu_top
```

and independently log each card's available sysfs nodes:

```bash
for d in /sys/class/drm/card*/device; do
  echo "=== $d ==="
  grep . "$d"/{gpu_busy_percent,mem_info_vram_total,mem_info_vram_used,mem_info_gtt_used,power_dpm_force_performance_level,pp_dpm_sclk,pp_dpm_mclk} 2>/dev/null
done
```

For CPU/hybrid runs:

```bash
vmstat 1
pidstat -rud -p <runner-pid> 1
perf stat -p <runner-pid> \
  -e cycles,instructions,cache-references,cache-misses,\
page-faults,minor-faults,major-faults,context-switches,cpu-migrations
```

There is no sufficiently well-established Tahiti `gpu_metrics` socket-power telemetry to make it the energy source of record. For energy work, a wall power meter is preferable.

---

# 4. Opportunity inventory

`Evidence` below uses **P** = primary/documented, **F** = field report, **H** = hypothesis.

| ID  | Layer           | Change                                              | Mechanism                                                                   | Applies to            | Evidence                                     | Support status/version   | Expected metric           | Expected direction/magnitude                                      | Quality impact                                                | Stability risk | Hardware risk          | Effort  | Reboot/rebuild            | Rollback                           | Confidence                                     |
| --- | --------------- | --------------------------------------------------- | --------------------------------------------------------------------------- | --------------------- | -------------------------------------------- | ------------------------ | ------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------- | -------------- | ---------------------- | ------- | ------------------------- | ---------------------------------- | ---------------------------------------------- |
| M01 | Measurement     | Benchmark v2                                        | separates load/cache/prefill/decode                                         | all                   | P: Ollama usage metrics                      | current                  | all                       | not a speedup                                                     | none                                                          | none           | none                   | medium  | no                        | old runner                         | **high**                                       |
| G01 | Placement       | GPU0-only vs GPU1-only                              | identifies display/card asymmetry                                           | small models          | P: `GGML_VK_VISIBLE_DEVICES`                 | current Ollama           | decode, pp, thermals      | unknown                                                           | none                                                          | low            | low                    | low     | server restart            | unset variable                     | **high**                                       |
| G02 | Placement       | one GPU vs both for ≤6 GB model                     | removes/introduces layer handoff                                            | small models          | P: Ollama prefers one GPU when fit           | current                  | decode/TTFT               | dual likely neutral/negative; magnitude unknown                   | none                                                          | low            | low                    | low     | restart                   | restore visibility                 | **high**                                       |
| G02b | Placement      | bridge model fully resident across both D700s       | isolates layer split from CPU/RAM spill                                     | measured ~6–12 GB working set | P/H: documented layer split + local topology | current | decode/capacity | unknown; the cleanest dual-GPU scaling test | model choice may affect comparability | low | low | medium | model acquisition/restart | remove model/restore visibility | **high** |
| G03 | Scheduling      | `OLLAMA_SCHED_SPREAD=1`                             | forces all visible GPUs into schedule                                       | models > one D700     | P: current envconfig                         | current, default false   | residency, decode         | unknown; potentially material if default placement spills         | none                                                          | medium         | low                    | low     | restart                   | unset                              | **high**                                       |
| G04 | GPU memory      | `RADV_PERFTEST=nogttspill`                          | forbids RADV GTT spill                                                      | VRAM-borderline       | P: current Mesa                              | current RADV             | decode, GTT, load success | unknown; diagnostic may become faster **or fail allocation**      | none                                                          | medium         | low                    | low     | process/container restart | unset                              | **high**                                       |
| G05 | VRAM accounting | verify accurate Vulkan free-memory reporting        | lets scheduler make correct fit decision                                    | all Vulkan            | P: Ollama docs                               | current                  | placement/load            | no direct speedup unless current accounting is wrong              | none                                                          | low            | low                    | low-med | restart                   | restore prior container capability | **medium-high**                                |
| G06 | Reservation     | `OLLAMA_GPU_OVERHEAD`                               | reserves VRAM per GPU                                                       | display/OOM workloads | P: default 0                                 | current                  | stability                 | likely slower if it causes extra CPU spill; use only if needed    | none                                                          | low            | low                    | low     | restart                   | set 0                              | **high**                                       |
| O01 | Residency       | `keep_alive=-1`                                     | avoids model reload                                                         | interactive use       | P: FAQ                                       | current                  | warm TTFT                 | removes load component; decode unchanged                          | none                                                          | low            | low                    | low     | no                        | unload / normal keepalive          | **high**                                       |
| O02 | Scheduler       | `OLLAMA_MAX_LOADED_MODELS=1`                        | avoids multi-model VRAM competition                                         | serving               | P: concurrency docs                          | current                  | stability/load            | neutral if only one model; positive under model thrash            | none                                                          | low            | low                    | low     | restart                   | unset                              | **high**                                       |
| O03 | Concurrency     | `OLLAMA_NUM_PARALLEL=1` baseline; test 2            | parallel sequence batching                                                  | serving               | P: contexts multiply with parallelism        | current default 1        | aggregate TPS/p95         | unknown; latency likely worsens                                   | none                                                          | medium         | low                    | low     | restart                   | set 1                              | **high**                                       |
| O04 | Context         | right-size `num_ctx`                                | reduces KV footprint                                                        | all                   | P: API control                               | current                  | residency/TTFT            | positive when it preserves GPU fit; otherwise neutral             | truncation if too small                                       | low            | none                   | low     | no                        | restore                            | **high**                                       |
| O05 | Prefill         | `num_batch` sweep                                   | changes prompt-evaluation work granularity                                  | long prompts          | P: current API option support                | current                  | pp tok/s, VRAM            | unknown                                                           | none                                                          | medium         | low                    | low     | no                        | restore                            | **high**                                       |
| O06 | CPU             | `num_thread` sweep                                  | avoids under/oversubscribing Ivy Bridge                                     | hybrid runs           | P/H: 12c/24t AVX CPU                         | current API              | hybrid decode/pp          | unknown                                                           | none                                                          | low            | none                   | low     | no                        | restore                            | **medium-high**                                |
| O07 | Loading         | mmap on/off                                         | changes page-cache/loading behavior                                         | very large models     | P: current runner option                     | current                  | load duration/faults      | load-time effect unknown; decode probably small                   | none                                                          | low            | none                   | low     | no                        | restore                            | **medium**                                     |
| A01 | Attention       | FA auto vs explicit off/on                          | changes attention implementation/memory                                     | long context          | P: Ollama auto-support behavior              | current                  | pp, KV memory             | D700 magnitude unknown                                            | possible backend numerical difference                         | medium         | low                    | low     | restart                   | auto/off                           | **medium**                                     |
| A02 | KV              | f16 → q8_0                                          | halves KV memory approximately                                              | long context          | P: Ollama FAQ                                | requires FA              | context/residency         | capacity positive; speed unknown                                  | very small expected precision loss                            | low-med        | none                   | low     | restart                   | f16                                | **high**                                       |
| A03 | KV              | q8_0 → q4_0                                         | quarters KV vs f16 approximately                                            | extreme contexts      | P                                            | requires FA              | capacity                  | capacity positive; speed unknown                                  | small–medium loss                                             | medium         | none                   | low     | restart                   | f16/q8                             | **high**                                       |
| S01 | Speculation     | MTP `draft_num_predict=0/1/2/4`                     | amortizes target passes only when drafts accepted cheaply                   | MTP models            | P + conflicting F                            | current, model dependent | accepted tokens, decode   | **unknown; can regress or improve substantially**                 | should preserve target distribution if implementation correct | medium-high    | none                   | medium  | no                        | 0                                  | **high that test is needed; low on direction** |
| S02 | Speculation     | keep parallel=1 during MTP characterization         | avoids interaction bug                                                      | MTP                   | F: current Vulkan issue                      | current open issue       | decode/pp                 | protects against known confound                                   | none                                                          | low            | none                   | low     | no                        | N/A                                | **high**                                       |
| Q01 | Weight quant    | Q4_K_M vs Q8_0 same model                           | smaller weight traffic/residency                                            | dense 27B             | local baseline + P backend support           | current                  | decode/capacity           | prompt baseline strongly favors Q4; exact gain needs retest       | Q4 lower fidelity                                             | low            | none                   | medium  | no                        | swap model                         | **high**                                       |
| Q02 | Weight quant    | Q4_0 vs Q4_K_M                                      | potentially simpler Vulkan dequant path                                     | 4B/27B                | F + current Vulkan support                   | current                  | decode/pp                 | unknown on Tahiti                                                 | quant-dependent                                               | low            | none                   | medium  | no                        | model swap                         | **medium**                                     |
| Q03 | Weight quant    | IQ diagnostic                                       | tests newer compact quant kernels                                           | selected small model  | P: Vulkan I-quants supported but marked slow | current                  | decode/capacity           | likely poor speed per upstream matrix; capacity positive          | model-dependent                                               | low            | none                   | medium  | no                        | model swap                         | **medium-high negative prior**                 |
| R01 | RADV            | DPM `auto` vs `high`                                | removes clock-state transitions                                             | sustained compute     | P: kernel sysfs API                          | if sysfs exposed on D700 | variance/decode           | 0 if already saturated; positive only if DPM is limiting          | none                                                          | medium         | **low-medium thermal** | low     | no                        | `echo auto`                        | **medium**                                     |
| R02 | RADV            | stable Mesa vs Trixie-backports                     | newer RADV compiler/kernel fixes                                            | Vulkan                | P: 25.0.7 stable, 26.1.2 backport            | current Debian repos     | correctness/perf          | unknown                                                           | possible numerical/correctness change                         | medium         | low                    | high    | package/reboot possible   | pin/downgrade                      | **medium**                                     |
| R03 | RADV            | preserve default shader cache                       | avoids recompilation                                                        | load/warm start       | P: Mesa warns `nocache` disables it          | current                  | load/first run            | positive only when shader compile significant                     | none                                                          | low            | none                   | low     | no                        | default                            | **medium**                                     |
| H01 | Display         | choose non-display D700                             | reduces desktop VRAM/graphics contention                                    | one-GPU models        | H supported by dual-GPU topology             | current                  | decode/VRAM               | unknown                                                           | none                                                          | low            | low                    | low     | restart                   | restore                            | **medium-high**                                |
| H02 | CPU/RAM         | verify four-channel RAM population                  | preserves 59.7 GB/s theoretical host BW                                     | hybrid                | P: Xeon has four channels                    | hardware                 | hybrid TPS                | no change if already four-channel                                 | none                                                          | none           | none                   | low     | no                        | N/A                                | **high**                                       |
| H03 | OS              | swap/page-fault elimination                         | prevents model pages leaving RAM                                            | huge models           | standard Linux mechanism                     | hybrid                   | latency/variance          | only positive if swap/major faults observed                       | none                                                          | low            | low                    | low     | maybe                     | restore                            | **high conditional**                           |
| L01 | Runtime         | direct llama.cpp Vulkan                             | exposes split/offload controls and removes Ollama scheduler from experiment | all                   | P: upstream Vulkan build                     | pin e.g. v0.4.1/b29c606  | all                       | unknown                                                           | none if same GGUF/options                                     | medium         | low                    | medium  | build                     | stop binary                        | **high as diagnostic**                         |
| L02 | Runtime         | llama.cpp layer split + explicit tensor split ratio | controls 6+6 GB placement                                                   | dual GPU              | P                                            | current                  | decode/VRAM               | unknown; useful diagnostic                                        | none                                                          | medium         | low                    | medium  | no                        | auto fit                           | **high**                                       |
| L03 | Runtime         | experimental tensor parallel                        | shards tensors, reductions across GPUs                                      | both D700s            | P: experimental/no non-CUDA guarantee        | current                  | decode                    | unknown, strong negative prior on old PCIe/Vulkan                 | none                                                          | high           | low                    | medium  | no                        | layer split                        | **low as optimization, medium as research**    |
| L04 | Runtime         | `--cpu-moe`/CPU expert placement                    | preserves VRAM for non-expert graph/KV                                      | huge MoE              | P: current llama-server flags                | current                  | capacity/TPS              | capacity positive; performance unknown/likely slower if RAM-bound | none                                                          | low            | none                   | medium  | no                        | remove flag                        | **medium**                                     |
| C01 | Container       | Docker vs native same llama.cpp build               | isolates container/library effects                                          | diagnostic            | H                                            | current                  | decode/load               | expected near-neutral unless environment differs                  | none                                                          | low            | none                   | medium  | no                        | container                          | **medium**                                     |

---

# 5. Rejected or quarantined advice

### ROCm/HIP on the D700

Reject as a current optimization path. AMD's current supported ROCm GPU lists start many generations later; Tahiti is not an officially supported modern ROCm target. Vulkan is the supported practical path here.

### Treating 2 × 6 GB as one 12 GB allocation

Reject. Layer splitting expands aggregate model capacity, but allocations remain device-local. A model or scratch allocation that individually requires more than a D700's available heap cannot simply allocate against a unified 12 GB pool.

### `GGML_CUDA_P2P`

Reject: the current llama.cpp P2P switch is explicitly a **CUDA** feature. It is not a Vulkan peer-to-peer switch.

### Assuming PCIe P2P between D700s

Quarantine as unknown. No current evidence establishes that the Vulkan backend performs useful direct D700-to-D700 peer transactions on this Mac Pro. Measure actual topology and backend behavior rather than infer it.

### `--split-mode tensor` as an obvious performance optimization

Quarantine. Upstream calls it experimental and says performance is expected to be good on multiple NVIDIA CUDA GPUs, with no guarantees elsewhere. A 2026 dual-R9700 field report found a ~70% penalty in its particular Vulkan tensor mode configuration before later work improved newer GPUs. Neither result transfers cleanly to Tahiti.

### `RADV_DEBUG=novm`

Reject as stale/non-current advice. `novm` is not in the current documented RADV debug flag list. Current Mesa does document `vm`, which *adds gaps between virtual-address allocations for fault checking*—the opposite sort of debugging behavior from a speed optimization.

### `RADV_DEBUG=syncshaders`, `fullsync`, or `zerovram` as optimizations

Reject. These are debugging/stability controls. `syncshaders` inserts synchronization, `fullsync` synchronizes and flushes broadly, and `zerovram` initializes allocations. They should be invoked only to diagnose corruption/hangs, not to improve TPS.

### Disabling GPU recovery for performance

Reject. Mesa mentions disabling recovery only as a specialized hang-debugging path. It increases operational risk and has no inference-performance mechanism.

### Modern cooperative-matrix / WMMA tuning

Reject unless `vulkaninfo` surprisingly proves the required extensions/features exist. GCN1 predates this hardware class by many generations.

### AVX2/AVX-512 CPU tuning

Reject. Intel specifies only AVX for E5-2697 v2.

### Huge pages

No change recommended. There is no evidence yet that TLB pressure is limiting this workload or that the relevant mappings would use configured huge pages.

### NUMA tuning

No change recommended. This is a one-socket MacPro6,1. Verify `numactl -H`, but do not import tuning advice from dual-socket inference servers.

### OpenCL replacement

Quarantine. Current llama.cpp's OpenCL backend is explicitly developed primarily for Qualcomm Adreno and is verified on a narrow Intel configuration; current documentation provides no Tahiti performance/support claim. Vulkan has much stronger current upstream coverage.

### Flashing firmware, overvolting or overclocking D700s

Reject for this project. The likely gain is much smaller than the risk to irreplaceable eleven-plus-year-old proprietary GPU modules.

---

# 6. Benchmark v2 specification

## 6.1 Measurement decomposition

Record four independent time domains:

**Cold model load**

* unload model first;
* measure Ollama `load_duration`;
* report host page-cache state separately;
* distinguish "runner cold but OS cache warm" from "post-reboot/full cold."

Do not silently call an Ollama-unloaded but filesystem-cached test a full cold boot.

**Warm TTFT**

Client timestamps using `CLOCK_MONOTONIC`/`perf_counter_ns()`:

```text
t0             request write begins
t_headers       response/stream established
t_first_chunk   first NDJSON/SSE chunk received
t_first_content first non-empty output or thinking content
t_done          final done chunk received
```

Then:

```text
warm_TTFT = t_first_content - t0
```

**Prompt processing**

From the final Ollama response:

```text
uncached_input_tokens =
    prompt_eval_count - prompt_eval_cached_count

uncached_prefill_tps =
    uncached_input_tokens / (prompt_eval_duration / 1e9)
```

Record cached count separately. Current Ollama explicitly defines these fields.

**Decode**

```text
decode_tps = eval_count / (eval_duration / 1e9)
```

Do not derive decode rate from total wall time.

## 6.2 Prompt cache control

Prefix caching should become an explicit experimental factor.

For **uncached** tests:

* use a bank of equal-token-length but mutually unrelated prompts;
* require `prompt_eval_cached_count == 0`, or reject the sample;
* for cold-load samples, unload the model after each trial with `keep_alive: 0`.

For **warm-cache** tests:

* intentionally repeat the exact prefix;
* require the intended cache fraction to be observed;
* report both physical uncached prefill TPS and effective user-visible prompt service time.

Do not rely on undocumented cache switches. Prompt caching behavior has changed in recent 2026 Ollama code, including an issue where caching was coupled to the `shift` control. The exposed cached-token metric is a safer acceptance criterion.

## 6.3 Request controls

Every sample should save the entire request JSON. Ollama's request controls are split between top-level fields and the `options` object; do not flatten them:

```json
{
  "model": "exact-model-tag-or-digest",
  "prompt": "fixture contents",
  "stream": true,
  "think": false,
  "keep_alive": "10m",
  "options": {
    "num_ctx": 4096,
    "num_batch": 256,
    "num_predict": 256,
    "num_gpu": -1,
    "main_gpu": 0,
    "num_thread": 12,
    "seed": 42,
    "temperature": 0,
    "draft_num_predict": 0,
    "use_mmap": true,
    "stop": []
  }
}
```

`num_ctx`, `num_batch`, `num_predict`, `num_gpu`, `main_gpu`, `num_thread`, `seed`, `use_mmap`, and `draft_num_predict` are part of Ollama's current option surface. MTP specifically requires an explicitly configured draft count.

Validate the installed Ollama version against this schema before the run. Reject a sample if the server ignores or rewrites a required control. Record effective settings from logs where available; a submitted option is not proof that the backend honored it.

## 6.4 Output work control

Target **256 generated tokens** for decode experiments.

A sample is valid as a fixed-work sample only if it reaches the requested generation length. If it terminates early on EOS/stop, mark the result as a different workload rather than silently averaging it with full-length samples.

For interactive TTFT, use a shorter 32-token output.

Thinking must be explicitly disabled where the model/API supports it, and the response should be checked to confirm that no hidden/explicit thinking stream changed generated work.

For maximum-token-rate experiments, the primary endpoint is median server-reported `decode_tps` after model warm-up. Report a paired effect size and confidence interval. Do not combine it with TTFT or prefill into a composite score. Those metrics act as regression guards and explainers.

## 6.5 Experimental ordering

Use paired, blocked trials.

For an A/B test:

```text
block 1: A B
block 2: B A
block 3: B A
block 4: A B
...
```

Randomize the pair order in advance.

Recommended minimums:

* **warm throughput:** begin with 10 valid pairs, then increase the sample count when E00 variance leaves the confidence interval too wide to decide the 5% practical threshold;
* **cold load:** 5 valid pairs;
* **thermal/sustained:** ≥20 minutes of repeated work or until clocks/temperature clearly plateau;
* **concurrency:** ≥10 request groups per concurrency level.

Report median, mean, standard deviation, coefficient of variation, p10/p90, and a bootstrap 95% confidence interval on the **paired percentage difference**.

Predeclare one primary comparison per experiment. Treat extra parameter levels as exploratory or adjust for multiple comparisons; do not mine a large sweep for the fastest noisy point and canonize it.

Do not remove statistical outliers simply because they are slow. Exclude only operationally invalid samples with a logged reason: cached prompt when uncached was required, model reload in a warm test, early generation termination, GPU reset, unrelated background load, etc.

## 6.6 Reproducibility metadata

Capture at the start of every benchmark bundle:

```bash
date --iso-8601=seconds
uname -a
cat /proc/cmdline

dpkg-query -W \
  'linux-image-*' \
  mesa-vulkan-drivers libvulkan1 \
  firmware-amd-graphics

vulkaninfo --summary

lscpu
numactl -H
free -h
swapon --show

lspci -nnk
lspci -tv

docker version
docker inspect ollama
docker image inspect <ollama-image>

docker exec ollama ollama --version
```

Store:

* Ollama version **and image digest**;
* exact model blob/digest;
* exact Modelfile;
* GGUF metadata;
* kernel;
* Mesa/RADV;
* Vulkan loader;
* AMD firmware package;
* Docker version;
* container configuration;
* repository commit plus canonical `.vscode/launch.json` and bootstrap state;
* boot arguments;
* all relevant environment variables;
* desktop/display state;
* ambient temperature if available;
* Git SHA of the benchmark runner.

## 6.7 GPU state

Per second, where exposed:

```text
timestamp
GPU PCI address
VRAM used / total
GTT used
GFX/compute busy
DMA busy
sclk state
mclk state
DPM policy
temperature
fan speed, if exposed
```

`amdgpu_top` can supply GRBM/GRBM2 activity, sensors, VRAM/GTT and fdinfo data, but do not require modern `gpu_metrics` on Tahiti.

## 6.8 CPU and host telemetry

Capture:

```text
runner CPU %
per-thread CPU %
RSS
major/minor faults
context switches
CPU migrations
system swap in/out
disk read rate
Docker/cgroup CPU and memory
```

Use `perf` profiling only in dedicated profile runs because profiling itself can perturb timing.

## 6.9 MTP acceptance

For MTP tests, `decode_tps` alone is inadequate.

Required fields:

```text
draft_num_predict
drafted token count
accepted draft token count
acceptance rate
target-model evaluations
generated output tokens
```

If the current Ollama build does not expose reliable request-scoped accepted/drafted counters, characterize MTP with direct llama.cpp as the instrumentation reference.

Never infer "MTP active" from a filename.

## 6.10 Quality controls

Changes fall into two categories.

**Nominally quality-preserving:** GPU selection, DPM mode, Mesa version, `nogttspill`, Docker/native, split placement. Require deterministic output equivalence on temperature-zero smoke tests and a task-suite regression check.

**Potentially quality-changing:** model quantization and KV quantization. Require:

* fixed deterministic task corpus;
* reasoning/code/function-call checks relevant to intended use;
* preferably `llama-perplexity` or another reproducible likelihood measure using the identical GGUF;
* long-context retrieval test for KV quantization.

A faster Q4 model is not an unconditional improvement over Q8.

---

# 7. Prioritized experiment plan

## Phase 0 — instrumentation and controls

### E00 — unchanged repeatability control

**Hypothesis:** the existing stack is stable enough to resolve later effects.

**Independent variable:** none.

**Controls:** 4B Q4_K_M, fixed 1K-token prompt, 256-token output, parallel=1, MTP=0, explicit context/batch.

**Configuration:** exactly current server/container environment.

**Warm/cold:** warm.

**Repetitions:** 20.

**Telemetry:** Ollama duration fields, cache count, both GPUs, CPU, clocks, temps.

**Success:** decode coefficient of variation ≤5%; no cache contamination.

**Regression threshold:** >10% drift between first and last quartile.

**Stop:** GPU reset/error, model reload during supposed warm sequence.

**Rollback:** none.

**Estimated duration:** ~15–30 minutes depending on output speed.

**Information gain:** establishes the smallest effect Benchmark v2 can credibly resolve.

---

### E01 — controlled five-model baseline

**Hypothesis:** fixed-work Benchmark v2 measurements reproduce the broad decode ordering of the historical run while removing its cache, output-length, and implicit-default ambiguity.

**Independent variable:** model only.

**Models:** all five current model digests.

**Controls:** fixed uncached prompt tokens, 256-token output, parallel=1, thinking off, MTP off, explicit context/batch/threads, unchanged server/container state.

**Warm/cold:** warm decode after one discarded warm-up; separately capture one runner-cold load observation without pooling it into decode.

**Repetitions:** 10 valid samples per model initially; extend according to E00 variance.

**Telemetry:** complete Benchmark v2 metadata, exact model/runtime digests, per-device placement, clocks, temperatures, CPU share, VRAM/GTT, and termination reason.

**Success:** a stable median and confidence interval for every model, with every accepted sample completing identical output work.

**Regression flag:** >10% median displacement from the historical values on 4B or a changed ordering elsewhere must be explained by controls, versions, placement, or thermals before tuning proceeds.

**Stop:** a model cannot complete fixed work reliably, GPU reset/error, or required controls are ignored.

**Rollback:** none.

**Estimated duration:** several hours at the reported large-model generation rates.

**Information gain:** produces the leaderboard against which every optimization is judged while preserving the historical bundle as a non-controlled reference.

---

### E02 — D700 identity test

**Hypothesis:** one GPU is preferable because the other drives XFCE or has different thermal behavior.

**Variable:**

```text
GGML_VK_VISIBLE_DEVICES=0
GGML_VK_VISIBLE_DEVICES=1
```

**Controls:** 4B Q4_K_M, same request, 4K context, 256 output, MTP off.

**Warm/cold:** warm after one warm-up.

**Repetitions:** 10 paired per GPU.

**Telemetry:** VRAM, GTT, sclk/mclk, temp, utilization.

**Success:** one GPU exceeds the other by >5% with non-overlapping paired CI or materially lower variance/temperature.

**Regression:** any output mismatch or GPU fault.

**Stop:** hardware errors.

**Rollback:** expose both GPUs.

**Estimated duration:** ~30–45 minutes.

**Information gain:** high; establishes card asymmetry and display contention.

---

## Phase 1 — placement and memory hierarchy

### E03 — one D700 versus two for small model

**Hypothesis:** splitting a ≤6 GB model across both D700s is not beneficial for decode.

**Variable:** best single GPU vs both GPUs.

**Model:** 4B Q4_K_M.

**Controls:** all API options identical.

**Warm/cold:** warm.

**Repetitions:** 10 paired.

**Telemetry:** both-device utilization and VRAM.

**Success:** use whichever configuration produces >5% paired improvement without pp/TTFT regression >10%.

**Stop:** none beyond normal fault criteria.

**Rollback:** prior visibility.

**Duration:** ~30 minutes.

**Information gain:** directly determines small-model scheduling policy.

---

### E04 — bridge-model dual-GPU placement

**Hypothesis:** a model that is too large for one D700 but fits wholly across both can benefit from layer splitting without host-memory traffic.

**Prerequisite:** acquire a same-family bridge GGUF whose **measured** weights plus runtime buffers exceed one card's usable VRAM but fit below the pair's usable aggregate. A roughly 7–10 GB file is only a search heuristic, not an acceptance criterion.

**Variables:** best single-card attempted placement; both cards with scheduler default; both cards with `OLLAMA_SCHED_SPREAD=1`. If single-card allocation fails cleanly, record capacity rather than throughput for that arm.

**Controls:** same digest, context, KV type, prompt, output length, MTP state, and request options.

**Warm/cold:** warm, unload/reload between configuration arms.

**Repetitions:** 10 paired valid samples for the two-card arms, increased if E00-derived power is inadequate.

**Telemetry:** exact per-GPU weight/KV/compute allocation, VRAM/GTT, layer placement, utilization, CPU share.

**Success:** >5% decode improvement between viable arms, or verified full-GPU capacity with no GTT/CPU spill.

**Regression:** >10% slower decode, spill, or allocation instability.

**Stop:** GPU OOM/reset.

**Rollback:** unset `OLLAMA_SCHED_SPREAD` and restore prior visibility.

**Duration:** ~1–2 hours after a suitable model is present.

**Information gain:** extremely high because the current large models cannot isolate dual-GPU fit from host-memory pressure.

### E04b — scheduler spread on current hybrid models

After E04 establishes clean two-card behavior, compare scheduler default versus `OLLAMA_SCHED_SPREAD=1` on 27B Q4, 35B-A3B Q8, and 125B-A6B Q4. Interpret any result as a hybrid-placement outcome, not evidence of pure dual-GPU scaling. Preserve exact residency and CPU-share telemetry for every arm.

---

### E05 — `RADV_PERFTEST=nogttspill`

**Hypothesis:** current RADV allocations are spilling into GTT and reducing performance.

**Variable:** unset vs:

```bash
RADV_PERFTEST=nogttspill
```

**Models:** 4B Q4 control; 27B Q4; 35B-A3B Q8.

**Warm/cold:** reload server/runner for each arm.

**Repetitions:** 10 pairs where model successfully loads.

**Telemetry:** GTT/VRAM, GPU allocation logs, TPS, load success.

**Success:** lower GTT plus >5% throughput or latency improvement.

**Alternative informative outcome:** allocation failure means previous successful execution depended on GTT spilling.

**Regression:** >5% slower with no memory advantage or any correctness failure.

**Stop:** repeated allocation failures.

**Rollback:** unset variable.

**Duration:** ~1–2 hours.

**Information gain:** extremely high because it directly tests hidden memory-tier use.

---

## Phase 2 — clocks and prompt engine

### E06 — DPM auto versus high

**Hypothesis:** dynamic DPM prevents sustained inference from maintaining high clocks.

Run this only if E00/E02 telemetry shows that `auto` fails to reach or sustain the highest available clock state during decode. If clocks are already stable, skip this experiment; forcing `high` cannot explain the bottleneck and adds thermal load.

**Variable:**

```bash
echo auto > .../power_dpm_force_performance_level
echo high > .../power_dpm_force_performance_level
```

for the compute card(s), only after verifying the sysfs control is exposed.

The Linux driver documents `high` as forcing the highest power state; it is reversible with `auto`.

**Models:** 4B Q4 and 27B Q4.

**Warm/cold:** thermally warmed first.

**Repetitions:** 10 paired plus ≥15 minutes sustained per state.

**Telemetry:** clocks, temperature, wall power, decode, pp.

**Success:** >5% throughput or materially reduced run-to-run variance without progressive thermal degradation. Even on success, keep this session-scoped until repeated thermal validation justifies persistence.

**Regression:** >10°C relative steady-state temperature increase with negligible performance improvement, sustained clock decline, display artifacts, kernel GPU errors, or wall-power increase disproportionate to gain.

**Stop condition:** any GPU fault, artifact, thermal warning or continuing temperature rise rather than plateau.

**Rollback:**

```bash
echo auto > .../power_dpm_force_performance_level
```

Apple specifies the computer itself for ambient temperatures of 10–35°C; I found no authoritative D700 junction limit suitable for defining a more aggressive numeric GPU-temperature ceiling, so no invented absolute limit is proposed.

**Duration:** ~45–60 minutes.

**Information gain:** medium-high.

---

### E07 — prompt batch sweep

**Hypothesis:** current prefill leaves the GPU underoccupied.

**Variable:** `num_batch` = 64, 128, 256, 512, subject to current model/backend acceptance.

**Models:** 4B Q4 and 35B-A3B Q8.

**Prompt:** fixed 10K-token uncached prompt.

**Output:** 32 tokens.

**Warm/cold:** warm.

**Repetitions:** 8 per level, randomized.

**Telemetry:** prompt TPS, transient VRAM, GTT, CPU/GPU activity.

**Success:** ≥10% prompt-TPS increase without >5% decode regression or residency change.

**Regression:** OOM, CPU spill, output mismatch.

**Rollback:** original batch.

**Duration:** ~45–90 minutes.

**Information gain:** high for prefill.

---

## Phase 3 — MTP and context

### E08 — MTP draft-depth sweep

**Hypothesis:** MTP can help only at an acceptance depth where verification is cheaper than ordinary decoding.

**Variable:**

```text
draft_num_predict = 0, 1, 2, 4
```

**Models:** the existing 27B-MTP Q4 and 35B-A3B-MTP Q8. If a smaller MTP-capable model can keep every arm in identical placement, test it first as the clean mechanism check.

**Parallel:** exactly 1.

**Prompts:** both highly predictable continuation and natural prose/code prompts.

**Output:** 256 tokens.

**Warm/cold:** warm.

**Repetitions:** 10 per condition.

**Telemetry:** drafted/accepted tokens, acceptance rate, target evaluations, decode TPS, GPU/CPU memory placement, and total memory per device.

**Success:** >10% median decode improvement with no offload or material memory-placement change and no quality regression.

**Regression:** >5% slower, loss of GPU residency, or acceptance too low to amortize draft cost.

**Stop:** CPU offload appears solely after enabling MTP, as has been reported on current Ollama.

**Rollback:** `draft_num_predict=0`.

**Duration:** ~2–3 hours.

**Information gain:** extremely high.

An arm is invalid for the causal MTP comparison if enabling MTP changes CPU/GPU layer placement or forces spill. Preserve it as a capacity observation, then repeat with a model/configuration that holds residency constant. If no such model exists, label the conclusion workload-specific rather than claiming a general MTP result.

---

### E09 — FA and KV memory matrix

Run only if `vulkaninfo` and Ollama logs demonstrate that FA is actually available on the D700 Vulkan path.

**Hypothesis:** FA and q8 KV preserve GPU residency at larger context.

**Factors:**

```text
FA: automatic / off
KV: f16 / q8_0
Context: 4K / 16K / 32K or highest practical value
```

Do **not** start with q4 KV.

**Model:** 4B and one 27B model.

**Repetitions:** 8 per healthy combination.

**Telemetry:** pp TPS, decode, peak VRAM/GTT, quality test.

**Success:** same model remains fully GPU-resident at a context where f16 does not, or ≥10% pp gain without quality/correctness loss.

**Regression:** corrupted output, CPU attention fallback, >10% performance loss.

**Rollback:** f16 + automatic FA.

**Duration:** several hours.

**Information gain:** high for maximum useful context.

---

## Phase 4 — quantization and topology

### E10 — controlled quantization frontier

**Hypothesis:** weight-size reduction is the dominant reason the baseline Q4 beats Q8.

**Variable:** quant only. Begin with identical-source 27B Q4_K_M versus Q8_0 to reproduce the observed ~49.5% median gap, then add Q5/Q6 variants where available. Run a smaller same-source ladder on 4B to isolate kernel behavior from host-memory residency.

**Model architecture:** identical 27B base/revision.

**Controls:** same template, MTP state, context, seed, prompt, runtime.

**Warm/cold:** both.

**Repetitions:** 10 paired.

**Telemetry:** model load, VRAM/GTT/RAM, decode, pp, quality suite.

**Success:** establish a per-model throughput/quality/residency frontier, not one universal "winner." The preferred operational model is the fastest quant that remains above the project's explicit quality threshold.

**Regression:** quality threshold exceeded.

**Rollback:** model selection only.

**Duration:** ~2 hours.

**Information gain:** high.

---

### E11 — Q4_0 vs Q4_K_M

**Hypothesis:** simpler Q4_0 Vulkan kernels may suit Tahiti better despite a possible quality penalty.

**Variable:** weight quant.

**Models:** preferably 4B and 27B same source weights.

**Repetitions:** 10 paired.

**Telemetry:** decode/pp, VRAM, quality/perplexity.

**Success:** meaningful speed gain with acceptable application-quality delta.

**Regression:** quality loss beyond operator threshold.

**Rollback:** Q4_K_M.

**Duration:** ~1–2 hours after models exist locally.

**Information gain:** medium-high.

---

## Phase 5 — stack isolation

### E12 — direct llama.cpp Vulkan

Pin an exact release; `v0.4.1` was released September 14, 2026 at commit `b29c606`, providing a reproducible current reference.

Build:

```bash
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j
```

Upstream documents this build path.

**Hypothesis:** direct llama.cpp reveals whether losses originate in the assembled Ollama serving stack/configuration or in the pinned ggml Vulkan path.

**Variable:** Ollama vs direct llama.cpp, same GGUF.

**Models:** 4B Q4, 27B Q4, 35B MoE.

**Controls:** match context, batch, threads, GPUs, FA, KV and generation. Record Ollama's embedded llama.cpp revision and compare it with the direct build. If revisions or compile options differ, this is an aggregate stack comparison, not a measurement of "Docker overhead" or Ollama scheduling alone.

**Repetitions:** 10.

**Success:** ≥10% reproducible difference or materially better placement/instrumentation.

**Regression:** output/configuration mismatch invalidates comparison.

**Rollback:** stop direct binary.

**Duration:** ~1–2 hours once built.

**Information gain:** extremely high diagnostically.

---

### E13 — explicit layer split

Direct llama.cpp only.

**Variable:** auto fit versus explicit `--tensor-split 1,1`, still with:

```text
--split-mode layer
```

**Hypothesis:** automatic placement is suboptimal for two equal 6 GB devices.

**Models:** those requiring both cards.

**Repetitions:** 10.

**Telemetry:** exact layer/device allocation, VRAM/GTT, TPS.

**Success:** >5% gain or elimination of spill.

**Regression:** OOM/slowdown.

**Rollback:** auto fit.

**Duration:** ~1 hour.

**Information gain:** high.

---

### E14 — experimental tensor mode diagnostic

Only after E13.

```text
--split-mode tensor
```

Do not canonize regardless of one fast sample.

**Hypothesis:** true tensor sharding might improve decode enough to offset PCIe synchronization.

**Prior:** weak/negative on Tahiti because upstream labels the mode experimental and provides no non-CUDA performance guarantee.

**Repetitions:** 10 if it runs correctly.

**Success threshold:** ≥15% improvement is required to justify the extra complexity/risk.

**Regression:** any correctness error, crash, long-context failure or ≥5% loss.

**Rollback:** `--split-mode layer`.

**Duration:** ~1 hour.

**Information gain:** medium.

---

### E15 — Mesa 25.0.7 vs 26.1.2 backport

Debian 13 currently ships Mesa Vulkan 25.0.7 in stable and 26.1.2 in Trixie-backports. Keep this late in the sequence: Mesa is shared by inference and the graphical/noVNC environment, so a regression can affect recovery access as well as benchmark speed.

**Hypothesis:** newer ACO/RADV changes improve or fix GFX6 compute behavior.

**Variable:** only Mesa userspace stack.

**Controls:** frozen kernel, Ollama/llama.cpp build, model, configuration.

**Models:** 4B control, one dual-GPU model, one long-context model.

**Repetitions:** 10 paired across reboot/package states.

**Success:** >5% stable improvement or verified correctness/stability fix.

**Regression:** any output corruption, GPU reset, ≥5% loss.

**Stop:** rendering/inference instability.

**Prerequisite:** capture the complete Mesa/Vulkan package dependency set and candidate versions; download/cache the known-good packages; verify SSH or local-console recovery independent of the desktop; and prepare an exact downgrade command before upgrading.

**Rollback:** restore the complete pinned stable Mesa/Vulkan dependency set from the recovery path, reboot, and rerun graphics plus inference smoke tests. Downgrading only `mesa-vulkan-drivers` is not an adequate rollback plan.

**Duration:** approximately half a day of operator testing because package state/reboots and full validation are required.

**Information gain:** medium-high but higher operational cost.

---

# 8. Recommended first ten experiments

Run these in exactly this order:

| Order | Experiment                          | Why now                                                                         |
| ----: | ----------------------------------- | ------------------------------------------------------------------------------- |
|     1 | **E00 Benchmark v2 repeatability**  | fixes request work, quantifies noise, and sets sample sizes for every later test |
|     2 | **E01 controlled baseline**         | records exact runtime/model digests, placement, clocks, and all five model medians |
|     3 | **E02 GPU0 vs GPU1 on 4B**          | identifies card, display, thermal, or health asymmetry                           |
|     4 | **E03 single vs dual D700 on 4B**   | establishes whether the second card hurts a model that fits one                  |
|     5 | **E04 bridge-model placement**      | cleanly measures dual-GPU layer splitting without CPU/RAM spill                  |
|     6 | **E05 `RADV_PERFTEST=nogttspill`**  | identifies hidden GTT dependence before tuning hybrid placement                  |
|     7 | **E10 controlled quant frontier**   | attacks the largest observed decode signal: the 27B Q4/Q8 gap                    |
|     8 | **E08 MTP 0/1/2/4**                | measures speculative benefit only while placement remains unchanged             |
|     9 | **E12 direct llama.cpp Vulkan**     | separates serving-stack limits from the pinned backend path                      |
|    10 | **E04b current-model placement**    | optimizes 27B/35B/125B only after clean placement mechanics are understood       |

Run E06 DPM only when baseline clock telemetry shows a failure to sustain clocks. Run the E07 batch sweep when prefill is the target, not as a substitute for decode optimization. I would deliberately **not** put a Mesa upgrade, experimental tensor parallelism, hugepages, broad CPU affinity changes, headless mode, or Docker removal in the first ten.

---

# 9. Canonization criteria

A change belongs in `bootstrap.sh` only when all of these conditions hold.

**Reproducibility:** at least two independently started benchmark sessions show the same direction, and the paired 95% CI excludes a practically insignificant effect for the metric being optimized.

**Magnitude:** a permanent performance tweak should normally deliver at least a ~5% gain in the intended metric, unless it instead provides a significant capacity, stability or latency improvement.

**Per-model decision:** record the result separately for every supported model. A setting that accelerates 4B while slowing 125B is not a global default; encode it as a model-specific profile or reject global canonization.

**No hidden trade:** decode improvements cannot conceal large prefill, TTFT or model-load regressions. Each canonized change should identify the workload it improves.

**Quality:** configuration-only changes must pass deterministic correctness smoke tests. Quantization/KV changes must pass the selected quality suite.

**Thermal stability:** improvement must survive sustained operation rather than only the first cold minutes.

**Memory stability:** no progressive GTT growth, swap growth or hidden CPU fallback.

**Hardware safety:** no GPU errors, rendering artifacts, unexplained resets or requirement to defeat protective mechanisms.

**Version specificity:** document exactly which Ollama/llama.cpp/Mesa/kernel versions were validated.

**Rollback:** one obvious inverse action must restore the prior known-good state.

**Boot safety:** a failure of the optimization should not prevent recovery to the normal graphical system.

**Interaction validation:** if a tweak depends on another tweak, test the pair. Particularly:

```text
FA × KV type × context
MTP × draft depth × batch × parallelism
quantization × layer placement
DPM state × sustained thermals
Mesa version × RADV_PERFTEST
```

A change that is merely "harmless but maybe useful" does not belong in the bootstrap. The default should remain **no change** until evidence supports intervention.

The canonical `launch.json` pipeline is the bootstrap entry point. Research findings should first become an approved experiment record, then a reversible pipeline step with verification and rollback, and only then a default. Do not edit the canonical path directly from a single benchmark session.

## Roadmap and approval gate

This report defines the research roadmap; it does not authorize the experiments automatically. Before execution, copy the first-ten sequence into the project's active plan/TODO with an owner, expected artifact path, risk class, and explicit approval state. Each completed experiment should link its immutable run bundle and decision (`adopt`, `reject`, `retest`, or `inconclusive`). Only `adopt` proceeds to bootstrap integration review.

---

# 10. Upstream/code opportunities

These are separate from configuration tuning.

## U1 — expose exact Vulkan per-device allocations in benchmark output

**Priority: high.**

The biggest missing observation is exact placement. Instrument ggml/Ollama so a benchmark artifact records:

```text
GPU/device
model buffer
KV buffer
compute buffer
scratch
GTT/host-visible allocation
layer range
```

Current multi-GPU docs make allocation/split policy central to behavior, so instrumentation here has a clear source-grounded purpose.

## U2 — profile GFX6 quantized matvec paths

**Priority: high if E02 shows high GPU activity but very low achieved throughput.**

llama.cpp's feature matrix explicitly marks Vulkan K-quants as supported but comparatively slow. Tahiti also lacks native packed 8/16-bit GCN operations. That makes the Vulkan quant/dequant matvec path a legitimate profiling target, but **not yet a demonstrated code bottleneck**.

Profile before patching.

Potential source-level question:

> Which Vulkan shader variants are actually selected for Q4_0, Q4_K and Q8_0 on a GFX6 device with no modern cooperative-matrix or integer-dot acceleration?

## U3 — quantify layer-split synchronization on dual GFX6

**Priority: high after E03/E13.**

If both GPUs show alternating activity and dual-GPU decode is slower than one-GPU decode, trace Vulkan submission/synchronization around layer boundaries.

This follows directly from llama.cpp's pipeline split model; no speculative code bottleneck is asserted yet.

## U4 — investigate GTT allocation decisions

**Priority: high if E05 changes behavior.**

If `nogttspill` produces a major difference, collect allocation traces and determine which buffers RADV otherwise chooses to spill.

That would convert a configuration finding into an actionable RADV/ggml memory-placement issue.

## U5 — MTP request-scoped instrumentation

**Priority: high.**

Ollama should expose at least:

```text
drafted_tokens
accepted_draft_tokens
draft_acceptance_rate
target_eval_steps
```

in request metrics.

Without that, a user cannot distinguish "MTP was enabled but ineffective" from "MTP never ran."

## U6 — MTP × multi-GPU Vulkan prefill profiling

**Priority: medium-high if E08 shows the regression.**

Recent upstream reports already identify current Vulkan/speculation interactions, including parallel-request regressions.

Do not extrapolate newer-GPU root causes to Tahiti; produce a D700 trace first.

## U7 — model/operator fallback audit

**Priority: medium.**

For Qwen hybrid/MoE models, use upstream backend-op tests and logs to determine whether any operator unexpectedly executes on CPU. Current llama.cpp maintains an operation/backend support matrix specifically for this purpose.

A single CPU fallback in a frequently executed layer can dominate a result even when most of the model is nominally GPU-resident.

## U8 — old-GPU Vulkan CI target

**Priority: long-term.**

Tahiti/GFX6 is officially supported by RADV yet is many generations removed from normal AI-development hardware. A reproducible CI/performance host for GFX6 would expose regressions in:

* shader compilation;
* quant kernels;
* memory allocation;
* SSM/GDN operations;
* FA fallback behavior;
* multi-GPU layer split.

This would be more useful upstream than optimizing an unmeasured shader.

---

# 11. Unknowns and operator decisions

The following cannot be resolved from public research alone.

**Exact installed stack at benchmark time.** The repository describes Debian 13 and the intended bootstrap, but the raw run bundle does not prove the actual kernel, Mesa, firmware, Ollama image digest or embedded llama.cpp revision used for those samples.

Debian's repositories currently offer kernel 6.12.107, Mesa 25.0.7 in stable and Mesa 26.1.2 in backports, but that does not establish what the Mac Pro is actually running.

**Which D700 drives XFCE.**

**PCIe topology/link widths.** The CPU supports PCIe 3.0 and 40 lanes, but the MacPro6,1 motherboard's actual negotiated D700 links should be measured with `lspci -tv` and `lspci -vv`; CPU capabilities do not establish the actual topology.

**D700 P2P.** Neither physical possibility nor current llama.cpp Vulkan use is established.

**Actual Vulkan optional features.** RADV's Vulkan 1.3 support on GFX6 does not establish `shaderFloat16`, int8 arithmetic acceleration or cooperative matrices. Capture `vulkaninfo`.

**Actual residency of the baseline models.**

**Whether `100% GPU` includes GTT-backed allocations on this exact Ollama/RADV combination.** Do not infer it.

**MTP acceptance.** The existing benchmark explicitly lacks it.

**Exact prompt-cache behavior of the installed Ollama revision.**

**Memory-channel population.** 128 GB is supported by the CPU, but the installed DIMM topology is unknown.

**Temperature/fan sensor coverage.** `gpu_metrics` is too new for Tahiti; actual hwmon exposure must be checked.

**Operator quality threshold.** Whether Q4_0, Q4_K_M, Q5, Q6, Q8, KV Q8 or KV Q4 is "better" ultimately depends on the model's intended work.

**Application quality threshold.** Maximum throughput is the primary target for this research pass, but the acceptable quality loss for Q4_0/Q4_K/Q5/Q6/Q8 and KV quantization remains an operator decision. Define task fixtures and a minimum score before selecting the fastest quant.

**Per-model operating mode.** Decide whether the final deliverable may expose separate fast profiles for 4B, dense 27B, MoE 35B, and MoE 125B. The evidence strongly suggests one global environment is unlikely to maximize all five.

---

# 12. Sources

## Primary / upstream sources

**Apple — Mac Pro (Late 2013) Technical Specifications.** Establishes dual D700 configuration, 6 GB per GPU, 264 GB/s per GPU, 3.5 TFLOPS, system operating ambient range, and original platform configuration.
[Apple Mac Pro Late 2013 technical specifications](https://support.apple.com/en-me/112025)

**Intel — Xeon E5-2697 v2 specifications.** Establishes 12C/24T, 2.7/3.5 GHz, four DDR3-1866 channels, 59.7 GB/s memory bandwidth, PCIe 3.0/40 lanes and AVX instruction support.
[Intel E5-2697 v2 specifications](https://www.intel.com/content/www/us/en/products/sku/75283/intel-xeon-processor-e52697-v2-30m-cache-2-70-ghz/specifications.html)

**Mesa RADV documentation.** Current documentation says all Linux-supported graphical GCN/RDNA GPUs from GCN1 onward are supported; GFX6/7 exposes Vulkan 1.3.
[Mesa RADV documentation](https://docs.mesa3d.org/drivers/radv.html)

**Mesa environment-variable documentation.** Defines current `RADV_DEBUG` and `RADV_PERFTEST`, including `nogttspill`, and shows that `novm` is not a current documented debug option.
[Mesa environment variables](https://docs.mesa3d.org/envvars.html)

**Linux amdgpu module parameters.** Establishes Southern Islands as first-generation GCN and confirms current `amdgpu.si_support`.
[Linux amdgpu module parameters](https://docs.kernel.org/gpu/amdgpu/module-parameters.html)

**Linux amdgpu power controls.** Documents `power_dpm_force_performance_level` and the semantics of `auto`, `high` and profiling modes.
[Linux AMDGPU power and thermal controls](https://docs.kernel.org/6.1/gpu/amdgpu/thermal.html)

**AMDGPU_TOP.** Establishes GRBM/GRBM2, sensors, fdinfo, VRAM/GTT and per-process observation capabilities.
[amdgpu_top project](https://github.com/Umio-Yasuno/amdgpu_top/blob/main/README.md)

**AMD APP SDK OpenCL Optimization Guide, 2015.** Historical primary architectural documentation stating packed 16- and 8-bit operations are not natively supported on the GCN family described there.
[AMD OpenCL Optimization Guide](https://docs.amd.com/v/u/en-US/AMD_OpenCL_Programming_Optimization_Guide2)

**Ollama GPU documentation.** Establishes current Vulkan support, GPU selection via `GGML_VK_VISIBLE_DEVICES`, free-VRAM/perfmon considerations and current ROCm supported targets.
[Ollama GPU documentation](https://github.com/ollama/ollama/blob/main/docs/gpu.mdx)

**Ollama Docker documentation.** Confirms current ordinary Docker image bundles Vulkan and can expose Vulkan through DRM devices.
[Ollama Docker documentation](https://github.com/ollama/ollama/blob/main/docs/docker.mdx)

**Ollama current environment configuration.** Establishes current variables/default definitions including `OLLAMA_SCHED_SPREAD`, `OLLAMA_GPU_OVERHEAD`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_KV_CACHE_TYPE`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_MAX_LOADED_MODELS`, `LLAMA_ARG_FIT`, and `LLAMA_ARG_FIT_TARGET`.
[Ollama envconfig source](https://github.com/ollama/ollama/blob/main/envconfig/config.go)

**Ollama FAQ.** Documents intended multi-GPU fit behavior, concurrency/context multiplication, Flash Attention and KV-cache quantization.
[Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.mdx)

**Ollama API usage metrics.** Defines model load, cached prompt, prompt evaluation and decode timing counters.
[Ollama API usage metrics](https://github.com/ollama/ollama/blob/main/docs/api/usage.mdx)

**Ollama Modelfile documentation.** Establishes `draft_num_predict` semantics and the requirement to explicitly set it for embedded MTP tensors.
[Ollama Modelfile parameters](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx)

**llama.cpp multi-GPU documentation.** Current description of pipeline/layer split, custom tensor split, single-device selection, experimental tensor parallelism, FA/KV restrictions and CUDA-specific P2P.
[llama.cpp multi-GPU documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/multi-gpu.md)

**llama.cpp feature matrix.** Establishes current Vulkan support for K/I quants, KV quants, MoE and FA, while describing Vulkan's parallel multi-GPU state and relative quant performance.
[llama.cpp feature matrix](https://github.com/ggml-org/llama.cpp/wiki/Feature-matrix)

**llama.cpp Vulkan build documentation.** Establishes supported `GGML_VULKAN` build path.
[llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)

**llama.cpp v0.4.1, September 14, 2026.** Provides a recent stable pinned upstream reference at `b29c606`; daily builds continue beyond it.
[llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases)

**Debian 13 stable Mesa.** `mesa-vulkan-drivers` 25.0.7-2+deb13u1.
[Debian Trixie Mesa Vulkan package](https://packages.debian.org/trixie/mesa-vulkan-drivers)

**Debian 13 backports Mesa.** `mesa-vulkan-drivers` 26.1.2-1~bpo13+1.
[Debian Trixie-backports Mesa Vulkan package](https://packages.debian.org/trixie-backports/amd64/mesa-vulkan-drivers)

**Debian 13 kernel.** Current stable `linux-image-amd64` metapackage resolves to 6.12.107-1 as of the research date.
[Debian Trixie linux-image-amd64](https://packages.debian.org/stable/linux-image-amd64)

## Field reports / unresolved upstream issues

These are **not established D700 facts**. They are useful for identifying experiments and failure modes.

**Ollama #17776 — Qwen3.8-27B MTP slower on Apple Silicon, August 15, 2026.** Shows that verification/draft overhead can overwhelm speculative benefit.
[Ollama MTP slowdown report](https://github.com/ollama/ollama/issues/17776)

**Ollama #18186 — MTP changing GPU/CPU placement, September 1, 2026.** Demonstrates that enabling MTP can increase memory pressure enough to alter residency.
[Ollama MTP offload report](https://github.com/ollama/ollama/issues/18186)

**llama.cpp #27544 — Vulkan + MTP + parallelism regression, August 22, 2026.** Strong reason to characterize MTP at parallel=1 first.
[llama.cpp Vulkan MTP concurrency issue](https://github.com/ggml-org/llama.cpp/issues/27544)

**llama.cpp discussion #22463 — Vulkan multi-GPU performance, April–July 2026.** Newer Radeon field evidence showing layer split was substantially more practical than early Vulkan tensor modes; not directly transferable to Tahiti.
[llama.cpp Vulkan multi-GPU discussion](https://github.com/ggml-org/llama.cpp/discussions/22463)

**Ollama #16599 — multi-GPU scheduler behavior, June 7, 2026.** Shows placement policy has changed/regressed across Ollama revisions and therefore must be verified in logs instead of assumed from documentation.
[Ollama multi-GPU scheduling issue](https://github.com/ollama/ollama/issues/16599)

---

## Overall research result

There is no evidence yet for a single magic optimization that should immediately be added to the Trashcan build. There is now direct evidence that the existing run is not controlled tightly enough for small A/B decisions: request options are implicit, output work varies widely, and most repeated prefixes are cached.

There **is** enough evidence to narrow the search dramatically.

The first-order questions are:

```text
1. Where are weights, KV, compute buffers and GTT allocations actually landing?
2. Is one D700 materially better than the other?
3. When does using the second D700 help versus hurt?
4. Is RADV silently spilling allocations to GTT?
5. Are clocks actually reaching and sustaining their intended states?
6. Is MTP really active, and what is its acceptance rate?
7. At what model/context thresholds does quantization preserve full GPU residency?
8. Does direct current llama.cpp reproduce Ollama's performance?
9. Can a bridge model remain fully resident across both D700s, and does that layer split beat every viable alternative?
10. Which quant gives each current model the highest decode rate above the agreed quality floor?
```

Those measurements can discriminate among the important mechanisms. Generic kernel tweaking cannot.

If the current baseline ultimately shows that **4B Q4 is fully resident on one D700, the GPU maintains full clocks, GTT stays near zero, CPU load is low, and Vulkan compute is continuously busy while decode remains ~9 tok/s**, then the next research target should be **the GFX6 Vulkan quantized matvec/dequantization path itself**. That would be the point at which source-level profiling becomes more promising than configuration tuning.

Conversely, if the telemetry shows GTT/CPU spill or poor placement, there is probably substantial performance still available without touching a shader.

The immediate implementation target is therefore Benchmark v2 plus the runtime/placement manifest. Once that produces stable fixed-work baselines, execute the revised first-ten sequence and maintain a per-model leaderboard. The best supported outcome may be several model-specific launch profiles rather than one universal configuration.
