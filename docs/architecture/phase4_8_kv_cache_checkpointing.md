# Phase 4.8 Architectural Specification: Async KV-Cache Checkpointing & Dynamic State Rerouting

## 1. Executive Overview

Phase 4.8 introduces non-blocking, distributed key-value (KV) cache snapshotting paired with real-time pipeline topology re-stitching for Public Intelligence compute networks. In distributed pipeline-parallel model execution across heterogeneous WAN nodes, worker node dropouts (due to network drops, home ISP disconnects, or device shutdowns) historically forced complete task failure and full prompt re-evaluation ($O(N_{\text{prompt}})$ overhead). 

Phase 4.8 guarantees **Zero Token Loss** and **Zero Prompt Re-computation** upon worker eviction ($\Delta t > 15.05\text{s}$) by asynchronously streaming quantized `KVCacheSnapshot` checkpoints to neighboring nodes over Zenoh gossip channels, permitting dynamic replacement nodes to resume execution directly at sequence position $S_{\text{last}} + 1$.

---

## 2. System Architecture

```mermaid
graph TD
    subgraph Compute Node S_k (Original Worker)
        Infer[LLM Generation Loop] -->|Token Generation| KVEmitter[AsyncKVCacheEmitter]
        KVEmitter -->|Non-blocking FP8 Compression| Snap[KVCacheSnapshot Buffer]
        Snap -->|Zenoh Gossip Stream| ZMesh[Zenoh Transport Mesh]
    end

    subgraph Zenoh Network Mesh
        ZMesh -->|public-intelligence/net/tasks/task_id/kv_snapshots/stage_k| Candidate[Neighbor Candidate Node]
        ZMesh -->|Liveliness Token Drop (delta_t > 15.05s)| Scheduler[Scheduling Engine & NodeRegistry]
    end

    subgraph Scheduler Control Plane
        Scheduler -->|1. Evict Stale Node| Evict[Evict Worker S_k]
        Scheduler -->|2. Topology Re-stitching| Match[Find Replacement Worker S_k']
        Scheduler -->|3. Broadcast ConfigUpdate| Config[Updated PipelineConfig]
    end

    subgraph Replacement Worker S_k' (Restitched Node)
        Config -->|Receive Allocation| Restitch[Restitch Pipeline Stage]
        Candidate -->|Hydrate KV Cache| KVPool[Attention KV Memory Pool]
        Restitch -->|Resume Forward Pass S_last + 1| InferNew[Resume Generation]
    end
```

---

## 3. Technical Specifications

### 3.1 Non-blocking `KVCacheSnapshot` Streaming Model

#### Data Model (`KVCacheSnapshot`)
Defined in `Node` and `Scheduler` pipeline models (`src/node/models/sharding.py` / `src/scheduler/models/pipeline.py`):

```python
class KVCacheSnapshot(BaseModel):
    """Non-blocking KV-cache state snapshot streamed across pipeline nodes."""

    task_id: str = Field(description="Unique pipeline execution task ID")
    sequence_id: int = Field(ge=0, description="Token sequence position index at snapshot time")
    node_id: str = Field(description="ID of node generating the snapshot")
    layer_range: LayerRange = Field(description="Transformer layer range hosted by node")
    stage_index: int = Field(ge=0, description="Pipeline stage index")
    cache_data: bytes = Field(description="Quantized binary key-value activation tensor buffer")
    checksum: str = Field(description="SHA-256 integrity hash over (task_id, sequence_id, node_id, cache_data)")
    shape: list[int] = Field(default_factory=list, description="KV activation tensor shape [layers, 2, heads, seq_len, head_dim]")
    dtype: str = Field(default="float8_e4m3", description="Data type of cached KV tensors")
    is_quantized: bool = Field(default=True, description="Whether snapshot uses FP8/FP16 compression")
    shm_name: str | None = Field(default=None, description="Shared memory block URI for zero-copy co-located transfers")
    timestamp: float = Field(description="Epoch timestamp of snapshot creation")
```

#### Binary Frame Structure (`b"PIKV"`)
For network efficiency over Zenoh gossip transport, snapshots use a binary framing format:
```
+-------------------+--------------------+------------------------+------------------------------------+
| Magic Header      | Meta Length        | Metadata JSON          | Compressed KV Cache Data           |
| b'PIKV' (4 bytes) | uint32_be (4 bytes)| (task_id, seq_id, ...) | Raw FP8/FP16 key-value tensor bytes|
+-------------------+--------------------+------------------------+------------------------------------+
```

#### Transport Channels & Non-Blocking Emitter
- **Zenoh Snapshot Topic**: `public-intelligence/net/tasks/<task_id>/kv_snapshots/<stage_index>`
- **Async Execution**: `AsyncKVCacheEmitter` runs as an asynchronous background loop alongside the generation engine. Snapshots are dispatched at configurable sequence block boundaries (e.g. every $N=16$ tokens) without pausing GPU or CPU forward pass iterations.
- **Ring Buffer Maintenance**: Receiving neighbor candidate nodes maintain a rolling ring-buffer of the latest $K=3$ verified snapshots per task stage.

---

### 3.2 Dynamic Pipeline Re-stitching (`SchedulingEngine` & `NodeRegistry`)

#### Failure Detection & Trigger Invariant
1. **Zenoh Liveliness Eviction**: Zenoh drop event on `public-intelligence/net/liveliness/<node_id>`.
2. **Heartbeat Staleness Boundary**: Node pulse elapsed time exceeds $\Delta t > 15.05\text{s}$.

#### Re-stitching Pipeline Workflow
When a worker node dropout occurs, the `SchedulingEngine` executes `restitch_pipeline(task_id, failed_node_id)`:

1. **Topology Analysis**: Identify all active pipeline tasks where `failed_node_id` hosted stage $S_k$ with layer range $[L_{\text{start}}, L_{\text{end}}]$.
2. **Candidate Discovery**: Search `NodeRegistry` for active candidate nodes matching model layer constraints with available VRAM $\ge \text{VRAM}_{\text{required}}(L_{\text{start}} \dots L_{\text{end}})$.
3. **Fitness Scoring**: Candidate score evaluated as:
   $$\text{Score} = (\text{Reliability} \times 100.0) - (\text{QueueDepth} \times 15.0) - (\text{CPUUtilization} \times 0.5) - (\text{WANLatency}_{S_{k-1} \rightarrow S_k} \times 2.0)$$
4. **Dynamic Sub-Range Splitting (Fallback)**: If no single candidate node possesses sufficient VRAM to host $[L_{\text{start}}, L_{\text{end}}]$, the scheduler dynamically splits stage $S_k$ into sub-stages $S_{k,a}$ $[L_{\text{start}}, L_{\text{mid}}]$ and $S_{k,b}$ $[L_{\text{mid}}+1, L_{\text{end}}]$ across two distinct nodes.
5. **Config Broadcast**: Create updated `PipelineConfig` with incremented configuration version tag and publish to `public-intelligence/net/tasks/<task_id>/config_updates`.

---

### 3.3 Zero-Prompt-Recomputation Execution Resumption

#### Hydration & Verification Sequence
1. **Pipeline Re-binding**: Replacement node $N_{\text{replacement}}$ receives `PipelineConfig` update for stage $S_k$.
2. **Snapshot Fetch & Checksum Verification**: $N_{\text{replacement}}$ retrieves latest `KVCacheSnapshot` ($S_{\text{last}}$) from snapshot ring-buffer. Verifies SHA-256 hash:
   $$\text{SHA-256}(\text{task\_id} \mathbin{\Vert} \text{sequence\_id} \mathbin{\Vert} \text{node\_id} \mathbin{\Vert} \text{cache\_data}) \stackrel{?}{=} \text{checksum}$$
3. **KV Cache Injection**: Unpacks binary payload and hydrates local attention key-value cache memory (SGLang RadixCache / vLLM page tables) for layer range $[L_{\text{start}}, L_{\text{end}}]$.
4. **Execution Resumption**: Upstream stage $S_{k-1}$ forwards next token activation payload `TensorPayload(sequence_id = S_{\text{last}} + 1)` directly to $N_{\text{replacement}}$.
5. **Prompt Prefill Avoidance**: Complete prompt prefill pass ($O(N_{\text{prompt}})$ forward pass) is entirely bypassed; system proceeds directly to token generation pass at $S_{\text{last}} + 1$.

---

## 4. Verification & Testing Matrix

| Component | Test Case | Target Boundary / Assertion |
| :--- | :--- | :--- |
| **`KVCacheSnapshot`** | Serialization & Checksum Integrity | Binary frame header `b"PIKV"`, SHA-256 checksum verification, FP8 compression accuracy $<0.1\%$ loss. |
| **`AsyncKVCacheEmitter`** | Non-blocking Snapshot Stream | Verification that generation latency overhead is $<2\%$ while streaming snapshots every 16 tokens. |
| **`SchedulingEngine`** | Pipeline Re-stitching Logic | Automatic replacement candidate selection and sub-range fallback splitting upon node drop ($\Delta t > 15.05\text{s}$). |
| **State Hydration** | Checkpoint Recovery & Resumption | Direct KV cache hydration and forward pass resumption at sequence position $S_{\text{last}} + 1$ without prompt prefill. |
| **End-to-End Pipeline** | Simulated Mid-Generation Node Crash | Simulated worker kill during token 48; execution restitched and completed through token 128 with zero token loss. |

---

## 5. Implementation Roadmap Integration

- **Phase Version**: v0.50
- **Dependencies**: Phase 4.6 Asymmetric Split-Inference & Phase 4.7 FP8 Quantized Transport
- **Target Subsystems**: `Scheduler/src/scheduler/core/scheduling.py`, `Scheduler/src/scheduler/models/pipeline.py`, `Node/src/node/core/radix_cache.py`, `Node/src/node/models/sharding.py`, `Node/src/node/runtime.py`
