# Spec: Real heartbeat metrics (roadmap 1.3)

## What this does

Every heartbeat a node sends reports the same four made-up numbers —
`cpu_utilization 15.0`, `ram_available_gb 8.0`, `gpu_utilization 0.0`,
`vram_available_gb 0.0`, and `queue_length 0` — hardcoded in
`Node/src/node/runtime.py:300-308` behind a docstring that says "(placeholders)".

This has two live consequences, both verified by reading the Scheduler:

1. **Node selection is inert.** `algorithm.py:68` picks the *minimum* score of
   `(queue*0.4) + (gpu_util*0.3) + (cpu_util*0.1) + ((1 - vram_ratio)*0.2) + dampener`.
   With the placeholders every node scores `0.215 + dampener` — identical. Selection
   is really "first node registered", and a saturated node is as likely to be picked
   as an idle one.
2. **Every node is excluded from VRAM-gated work.** `matchmaker.py:44` prefers the
   *heartbeat's* `vram_available_gb` over the registration value whenever a heartbeat
   exists. It is always `0.0`, so any task carrying `min_vram_gb` matches nothing —
   including on a node that just registered 24 GB. Roadmap 1.2 fixed the registration
   number and could not fix this.

After this, the four values are measured from the host each heartbeat, using the same
NVIDIA → Apple Silicon → cpu-only ordering that 1.2 established for registration, so
the static advertisement and the live report cannot disagree about what the GPU is.

## Done looks like

- [x] `runtime._collect_heartbeat_metrics()` returns measured values; the literals
      `15.0`, `8.0`, and the `(placeholders)` docstring are gone.
      → `test_heartbeat_metrics.py::test_runtime_heartbeat_metrics_are_not_the_old_placeholders`
- [x] `queue_length` is the node's real pending work (`self.task_queue.qsize()`),
      not a constant `0`.
      → `test_runtime_heartbeat_reports_measured_values_and_real_queue_depth`
- [x] `cpu_utilization` and `ram_available_gb` come from psutil and change with load.
      → `test_reports_real_cpu_and_ram`; live 10.87 GB free vs psutil's 10.88.
- [x] On an NVIDIA host, `gpu_utilization` and `vram_available_gb` come from
      `nvidia-smi`. → `test_reports_real_nvidia_utilization_and_free_vram`. **Same
      caveat as 1.2: no NVIDIA GPU on this machine, so the collector result is
      synthetic.** The `nvidia-smi` invocation itself is untouched pre-existing code.
- [x] On an Apple Silicon host, `vram_available_gb` is free unified memory and
      `gpu_utilization` is the real figure from
      `ioreg -r -d 1 -c AGXAccelerator` → `"Device Utilization %"`. Confirmed readable
      without sudo on this machine. → `test_reports_apple_silicon_free_unified_memory`,
      plus `test_parses_utilization_from_real_ioreg_output` against captured ioreg text.
      The parse was verified to bite by mutating the regex and watching two tests fail.
- [x] Live VRAM and the registered VRAM come from one code path, so a node cannot
      advertise 24 GB total and heartbeat 0 GB available on the same hardware.
      → both `detect_gpu` and `detect_host_metrics` go through `_probe_gpu`.
- [x] A node with a real GPU is **no longer filtered out** of a task carrying
      `min_vram_gb`. → `test_heartbeat_driven_scheduling.py::test_honest_vram_heartbeat_keeps_a_capable_node_eligible`,
      paired with `test_placeholder_vram_excludes_a_real_gpu_node` which pins the old
      behaviour, and `test_honest_vram_still_excludes_a_node_that_is_genuinely_full`.
- [x] Two nodes with different load produce different scores, and the idle one is
      selected. → `test_idle_node_is_selected_over_a_loaded_one`, with
      `test_placeholder_metrics_hide_real_load_from_selection` pinning the old tie.
- [x] Metric collection failing degrades to conservative values and the heartbeat is
      still sent. → `test_metric_collection_degrades_instead_of_raising`.

## Out of scope

- **`Heartbeat.status` is still always `"online"`,** injected by
  `SchedulingClient.heartbeat`. A busy or draining node cannot say so. Known gap;
  it belongs with node lifecycle work, not with metrics.
- **AMD and Intel GPUs.** Same as 1.2: they fall through to the cpu-only path and
  report 0 GB. A ROCm host is therefore excluded from VRAM-gated work. Known gap.
- **The dampener** (`registry.get_dampener`) is untouched.
- **Nothing about eviction thresholds** changes. Heartbeat cadence is unchanged.

## Verification

```
Node/.venv/bin/python      -m pytest Node/tests      -q
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest tests           -q
Node/.venv/bin/python -m ruff check        ./Node ./Scheduler
Node/.venv/bin/python -m ruff format --check ./Node ./Scheduler
Node/.venv/bin/python -m bandit -r ./Node/src ./Scheduler/src -x tests -ll
```

Plus, on this machine: compare the reported `gpu_utilization` against
`ioreg -r -d 1 -w 0 -c AGXAccelerator | grep "Device Utilization %"` and
`cpu_utilization` against a second reading, and confirm CI green via `gh run list`.

## Notes / open questions

- `psutil.cpu_percent(interval=None)` returns 0.0 on its very first call in a process
  and is meaningful only from the second call onward. The heartbeat loop calls it
  repeatedly so this self-corrects after one interval, but the **first heartbeat a
  node ever sends will under-report CPU**. Accepted rather than blocking the loop on
  a sampling interval; recorded so it is not mistaken for a bug later.
- Reporting real `gpu_utilization` makes a busy node *less* likely to be chosen,
  which is the intent — but it also means a node running someone else's workload
  advertises that fact. That is inherent to load-aware scheduling, not new here.
- **The Scheduler needed no change.** Its filtering and scoring were always correct;
  they were being fed constants. The five Scheduler tests added here passed on first
  run and are regression protection, not evidence of a fix. Only the Node tests went
  red-then-green.
- **On an idle machine `_apple_gpu_utilization()` legitimately returns 0.0**, which is
  indistinguishable from a parse that matched nothing. That is why `_parse_ioreg_utilization`
  is split out and tested against captured output. Do not "verify" this by eyeballing
  the live value.
- Found while verifying, unrelated to metrics and fixed here because it is a two-line
  crash on a startup path: `runtime.start()` caught a failed Ollama discovery and then
  called `logger.warning(msg, error=...)` on a **stdlib** logger, which raises
  `TypeError`. A node whose Ollama was down died on the handler meant to keep it alive.
  Swept every other `logging.getLogger` module for the same pattern; this was the only
  one. The 36 similar-looking calls elsewhere are against `structlog.stdlib.get_logger()`,
  where kwargs are valid.
