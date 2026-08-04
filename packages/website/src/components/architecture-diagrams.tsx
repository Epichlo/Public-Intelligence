import * as React from "react";
import {
  DiagramCanvas,
  DiagramGrid,
  DiagramNode,
  DiagramConnection,
  DiagramMarker,
  DiagramCaption,
  ArrowheadDef,
} from "@/components/diagram";

// 1. Overall System Topology
export function OverallSystemDiagram() {
  const width = 760;
  const height = 220;
  const patternId = "grid-system-overall";
  const nodeY = 80;
  const connectionY = 110;
  const nodeWidth = 140;
  const nodeHeight = 60;
  const nodeSpacing = 230;
  const startX = 80;

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Overall System Topology"
      description="Three-node system architecture: Website Portal entry point, Scheduler Core control plane, and Node Network execution plane. Connections show data flow from website to scheduler to compute nodes."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {/* Node 1: Website */}
      <DiagramNode
        x={startX}
        y={nodeY}
        label="[WEBSITE_PORTAL]"
        detail="Entry & Onboard"
      />

      {/* Node 2: Scheduler */}
      <DiagramNode
        x={startX + nodeSpacing}
        y={nodeY}
        label="[SCHEDULER_CORE]"
        detail="Control Plane"
      >
        <DiagramMarker cx={125} cy={15} />
      </DiagramNode>

      {/* Node 3: Contributed Nodes */}
      <DiagramNode
        x={startX + nodeSpacing * 2}
        y={nodeY}
        label="[NODE_NETWORK]"
        detail="Execution Plane"
      />

      {/* Connections */}
      <DiagramConnection
        x1={startX + nodeWidth}
        y1={connectionY}
        x2={startX + nodeSpacing}
        y2={connectionY}
      />
      <DiagramConnection
        x1={startX + nodeSpacing + nodeWidth}
        y1={connectionY}
        x2={startX + nodeSpacing * 2}
        y2={connectionY}
        active
      />

      <DiagramMarker cx={startX + nodeSpacing + nodeWidth - 45} cy={connectionY} />
    </DiagramCanvas>
  );
}

// 2. Request Flow
export function RequestFlowDiagram() {
  const width = 760;
  const height = 240;
  const patternId = "grid-flow-request";
  const nodeY = 90;
  const connectionY = 120;
  const nodeWidth = 140;
  const nodeSpacing = 230;
  const startX = 80;

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Request Flow"
      description="Request lifecycle from client submission through scheduler routing to node execution. Active path highlighted showing successful routing to EU-West node with direct result return path."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {/* Node 1: Client */}
      <DiagramNode
        x={startX}
        y={nodeY}
        label="[CLIENT_INTERFACE]"
        detail="Status: SUBMITTING"
      />

      {/* Node 2: Scheduler */}
      <DiagramNode
        x={startX + nodeSpacing}
        y={nodeY}
        label="[SCHEDULER_CORE]"
        detail="Status: ROUTING"
      />

      {/* Node 3: Selected Compute Node */}
      <DiagramNode
        x={startX + nodeSpacing * 2}
        y={nodeY}
        label="[NODE_EU_WEST]"
        detail="Status: EXECUTING"
        active
        detailActive
      />

      {/* Active Connection Paths */}
      <DiagramConnection
        x1={startX + nodeWidth}
        y1={connectionY}
        x2={startX + nodeSpacing}
        y2={connectionY}
        active
      />
      <DiagramConnection
        x1={startX + nodeSpacing + nodeWidth}
        y1={connectionY}
        x2={startX + nodeSpacing * 2}
        y2={connectionY}
        active
      />

      {/* Signal indicators on the active loop */}
      <DiagramMarker cx={startX + nodeWidth + 45} cy={connectionY} />
      <DiagramMarker cx={startX + nodeSpacing * 2 - 45} cy={connectionY} />

      {/* Direct Output Return Path (Subtle feedback loop at bottom) */}
      <DiagramConnection
        x1={startX + nodeSpacing * 2 + nodeWidth - 30}
        y1={connectionY + 30}
        x2={startX + 30}
        y2={connectionY + 30}
        curved
        controlPoint={{ x: width / 2, y: connectionY + 70 }}
      />
      <DiagramCaption
        x={width / 2}
        y={connectionY + 65}
        text="DIRECT_RESULT_PAYLOAD (verification_loop)"
      />
    </DiagramCanvas>
  );
}

// 3. Geographic Scheduling
export function GeographicSchedulingDiagram() {
  const width = 760;
  const height = 280;
  const patternId = "grid-geo-scheduling";
  const schedulerX = 80;
  const schedulerY = 110;
  const nodeX = 480;
  const nodeWidth = 140;
  const nodeHeight = 50;
  const nodeSpacing = 75;
  const startY = 40;

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Geographic Scheduling"
      description="Scheduler routing decision showing three candidate nodes with latency measurements. EU-West selected as minimum latency (12ms) vs US-East (78ms) and AP-South (284ms)."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {/* Scheduler Node (Left Column) */}
      <DiagramNode
        x={schedulerX}
        y={schedulerY}
        label="[SCHEDULER_CORE]"
        detail="Latency Engine"
      />

      {/* Nodes (Right Column Stacked) */}
      {/* Node 1: US-East */}
      <DiagramNode
        x={nodeX}
        y={startY}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_US_EAST]"
        detail="Latency: 78ms"
      />

      {/* Node 2: EU-West (Selected) */}
      <DiagramNode
        x={nodeX}
        y={startY + nodeSpacing}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_EU_WEST]"
        detail="Latency: 12ms (MIN)"
        active
        detailActive
      />

      {/* Node 3: AP-South */}
      <DiagramNode
        x={nodeX}
        y={startY + nodeSpacing * 2}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_AP_SOUTH]"
        detail="Latency: 284ms"
      />

      {/* Routing branches */}
      <DiagramConnection
        x1={schedulerX + nodeWidth}
        y1={schedulerY + 30}
        x2={nodeX}
        y2={startY + nodeHeight / 2}
        curved
        controlPoint={{ x: 350, y: 65 }}
      />
      <DiagramConnection
        x1={schedulerX + nodeWidth}
        y1={schedulerY + 30}
        x2={nodeX}
        y2={startY + nodeSpacing + nodeHeight / 2}
        active
      />
      <DiagramConnection
        x1={schedulerX + nodeWidth}
        y1={schedulerY + 30}
        x2={nodeX}
        y2={startY + nodeSpacing * 2 + nodeHeight / 2}
        curved
        controlPoint={{ x: 350, y: 215 }}
      />

      <DiagramMarker cx={350} cy={schedulerY + 30} />
    </DiagramCanvas>
  );
}

// 4. Distributed Inference
export function DistributedInferenceDiagram() {
  const width = 760;
  const height = 280;
  const patternId = "grid-inf-distributed";
  const schedulerX = 80;
  const schedulerY = 110;
  const nodeWidth = 140;
  const nodeHeight = 50;

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Distributed Inference Pipeline"
      description="Model layer partitioning across three compute shards. Scheduler partitions layers 1-12 to Shard A, 13-24 to Shard B, 25-36 to Shard C. Pipeline flow shown with active connections."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {/* Scheduler (Left) */}
      <DiagramNode
        x={schedulerX}
        y={schedulerY}
        label="[SCHEDULER_CORE]"
        detail="Layer Partitioner"
      />

      {/* Pipeline Shards */}
      {/* Shard A */}
      <DiagramNode
        x={320}
        y={60}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_SHARD_A]"
        detail="Layers: 1 - 12"
        active
        detailActive
      />

      {/* Shard B */}
      <DiagramNode
        x={520}
        y={60}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_SHARD_B]"
        detail="Layers: 13 - 24"
        active
        detailActive
      />

      {/* Shard C */}
      <DiagramNode
        x={420}
        y={170}
        width={nodeWidth}
        height={nodeHeight}
        label="[NODE_SHARD_C]"
        detail="Layers: 25 - 36"
        active
        detailActive
      />

      {/* Pipeline connection paths */}
      {/* Scheduler -> Shard A */}
      <DiagramConnection
        x1={schedulerX + nodeWidth}
        y1={schedulerY + 30}
        x2={320}
        y2={85}
        active
      />

      {/* Shard A -> Shard B */}
      <DiagramConnection
        x1={460}
        y1={85}
        x2={520}
        y2={85}
        active
      />

      {/* Shard B -> Shard C */}
      <DiagramConnection
        x1={590}
        y1={110}
        x2={490}
        y2={170}
        active
      />

      {/* Flow ticks along the pipeline */}
      <DiagramMarker cx={270} cy={112.5} />
      <DiagramMarker cx={490} cy={85} />
      <DiagramMarker cx={540} cy={140} />
    </DiagramCanvas>
  );
}

// 5. Future Architecture
export function PlatformStackDiagram() {
  const width = 760;
  const height = 240;
  const patternId = "grid-stack-platform";
  const layerX = 120;
  const layerWidth = 520;
  const layerHeight = 35;
  const layerSpacing = 45;
  const startY = 30;

  const layers = [
    {
      label: "APPLICATION / API LAYER",
      detail: "Client SDKs, telemetry portals, developer API endpoints",
      y: startY,
      active: false,
    },
    {
      label: "ORCHESTRATION & COORDINATION LAYER",
      detail: "Geographic scheduling engine, node registries, queue models",
      y: startY + layerSpacing,
      active: true,
    },
    {
      label: "DECENTRALIZED TRANSPORT LAYER",
      detail: "P2P overlay routing, message heartbeats, secure gRPC tunnels",
      y: startY + layerSpacing * 2,
      active: false,
    },
    {
      label: "LOCAL HARDWARE EXECUTION RUNTIME",
      detail: "CUDA/ROCm device engines, local resource benchmarks, sandboxes",
      y: startY + layerSpacing * 3,
      active: false,
    },
  ];

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Future Platform Stack Architecture"
      description="Four-layer platform stack: Application API layer, Orchestration & Coordination layer (active), Decentralized Transport layer, and Local Hardware Execution Runtime layer. Each layer spans full width with descriptive details."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {layers.map((layer, index) => (
        <DiagramNode
          key={index}
          x={layerX}
          y={layer.y}
          width={layerWidth}
          height={layerHeight}
          label={layer.label}
          detail={layer.detail}
          active={layer.active}
          detailActive={layer.active}
        />
      ))}
    </DiagramCanvas>
  );
}
