# Spec: Real hardware advertisement (roadmap 1.2)

## What this does

Today every node tells the Scheduler it has a GPU called `"unknown"` with exactly
16 GB of VRAM, 16 GB of it free, and 16 GB of system RAM — regardless of what the
machine actually is. Those numbers are literals in `Node/src/node/clients/scheduler.py:96`
and `Node/src/node/runtime.py:286`. Matchmaking filters on `min_vram_gb` and scores
nodes by VRAM ratio, so every routing decision the Scheduler makes today is made
against fiction.

After this, a node reports what it actually has: the real GPU name and VRAM from
`nvidia-smi`, Apple Silicon unified memory where that applies, and real system RAM.
A machine with no GPU says so — 0 GB VRAM — instead of claiming 16.

`GET /nodes` also stops implying a node is dialable at `127.0.0.1`.

## Done looks like

- [x] `NodeInfo` carries a `gpu: GPUInfo` field with real values; `SchedulerClient.register`
      no longer contains the literal `{"name": "unknown", "vram_total_gb": 16.0, ...}`.
      → `test_registration_hardware.py::test_register_sends_the_nodes_own_gpu`
- [ ] **UNVERIFIED on real hardware.** On a host with `nvidia-smi`, the registered
      `gpu.name` and `gpu.vram_total_gb` match `nvidia-smi --query-gpu=name,memory.total`.
      No NVIDIA GPU exists on this machine (`command -v nvidia-smi` → not found), so the
      parse is exercised only against a synthetic collector result in
      `test_hardware_profile.py::test_detect_gpu_reports_real_nvidia_values`. The
      byte→GB conversion and the clamp are covered; the actual `nvidia-smi` invocation
      is pre-existing code in `telemetry/collector.py` and is untouched by this change.
- [x] On an Apple Silicon host, `gpu.name` is the chip family and `gpu.vram_total_gb`
      is unified memory (`sysctl hw.memsize`) — because Metal genuinely uses it as VRAM.
      → checked live on this machine: `sysctl` reports `Apple M5` / `25769803776` bytes;
      detection returned `{"name": "Apple M5", "vram_total_gb": 24.0}`.
- [x] On a host with neither, registration succeeds with `gpu.vram_total_gb == 0.0`
      and `gpu.name == "cpu-only"`. It does not 422, and it does not invent a number.
      → `test_cpu_only_node_advertisement.py::test_registration_accepts_a_cpu_only_node`
- [x] `Scheduler` `GPUInfo.vram_total_gb` accepts `0.0` (`ge=0`, was `gt=0`), so the
      honest CPU-only case is representable. `algorithm.py:66` already guards `vram_total > 0`.
      → `scheduler/models/node.py:24`; negative values still rejected, per
      `test_gpu_info_still_rejects_negative_vram`.
- [x] A CPU-only node is filtered out of any task carrying `min_vram_gb > 0` —
      covered by a test in `Scheduler/tests/`.
      → `test_cpu_only_node_is_filtered_out_of_vram_tasks`, plus its converse
      `test_cpu_only_node_is_still_eligible_without_a_vram_floor`.
- [x] `runtime._get_ram_total_gb()` returns real `psutil` total RAM, not `16.0`.
      → `test_detect_ram_total_gb_matches_psutil`; live value 24.0 GB on this machine.
- [x] `GET /nodes` reports each node's `reachability` (`mesh` / `http`), derived from
      the registry's mesh observations — not asserted by the node.
      → `test_node_reachability_view.py`, including
      `test_reachability_cannot_be_asserted_by_the_node` and a check that the response
      still does not leak the per-node token.
- [x] Hardware collection failing (no `nvidia-smi`, `sysctl` error, permission denied)
      degrades to the CPU-only shape and still registers. It never blocks node startup.
      → `test_detect_gpu_degrades_when_collection_raises`,
      `test_detect_gpu_degrades_when_apple_probe_raises`,
      `test_runtime_startup_survives_hardware_detection_failure`.

## Out of scope

- **Heartbeat metrics remain placeholders.** `runtime._collect_heartbeat_metrics()` still
  returns `cpu 15.0`, `vram_available_gb 0.0`. That is roadmap **1.3** and is deliberately
  not fixed here, so `vram_available_gb` on the *heartbeat* stays fake even after this lands.
  Matchmaker prefers the heartbeat value over the registration value
  (`matchmaker.py:44`), so 1.2 alone does not make live VRAM filtering correct — it
  makes the *static* advertisement correct. Known gap, not a deliberate exclusion.
- **Model catalogue** — advertising what Ollama actually has pulled is roadmap 1.4.
- **`ip_address` stays a `str` and stays the HTTP-fallback dial target.** It is correct
  for same-host and containerised deployments, which is the only thing that path serves.
  This spec removes the *implication* that it is reachable, not the field.
- Non-NVIDIA discrete GPUs (AMD ROCm, Intel) are not detected. They land as CPU-only.

## Verification

```
Node/.venv/bin/python      -m pytest Node/tests      -q
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest tests           -q
Node/.venv/bin/python      -m ruff check Node/src
Scheduler/.venv/bin/python -m ruff check Scheduler/src
```

Plus, on this machine (Apple Silicon, no `nvidia-smi`), confirm the collected values
match `sysctl -n hw.memsize` and `sysctl -n machdep.cpu.brand_string` by hand.

## Notes / open questions

- `GPUInfo` now exists in both `Node` and `Scheduler`. That is a **fifth** duplicated
  pair, joining `quantization.py` / `local_boundary.py` / `kv_cache.py` / `transport.py`.
  Accepted here because the two are separate services with separate wire contracts and
  no shared package exists to hold it; recorded so the next person does not think it
  was an accident. If one changes, the other must.
- Relaxing `gt=0` to `ge=0` weakens a Scheduler-side invariant. The justification is
  that the invariant was previously enforced only because every node lied to satisfy it.
- Apple Silicon unified memory is reported as VRAM in full. It is shared with the OS,
  so `vram_total_gb == ram_total_gb` on those machines. That is accurate for Metal but
  will look odd next to an NVIDIA node; noted rather than papered over.
