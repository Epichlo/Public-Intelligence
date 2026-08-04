import * as React from "react";
import {
  DiagramCanvas,
  DiagramGrid,
  DiagramNode,
  DiagramConnection,
  DiagramMarker,
  ArrowheadDef,
} from "@/components/diagram";

export function SystemDiagram() {
  const width = 760;
  const height = 180;
  const patternId = "grid-home-system";
  const nodeY = 60;
  const connectionY = 90;
  const nodeWidth = 140;
  const nodeHeight = 60;
  const nodeSpacing = 230;
  const startX = 80;

  return (
    <DiagramCanvas
      width={width}
      height={height}
      title="Public Intelligence System Overview"
      description="Three core components: Website Portal for onboarding, Scheduler Core as coordinator, and Compute Network for execution. Active connection from scheduler to compute network indicated by lime markers."
    >
      <DiagramGrid width={width} height={height} patternId={patternId} />
      <ArrowheadDef />

      {/* Node 1: Website */}
      <DiagramNode
        x={startX}
        y={nodeY}
        label="[WEBSITE_PORTAL]"
        detail="Role: Onboarding"
      />

      {/* Node 2: Scheduler */}
      <DiagramNode
        x={startX + nodeSpacing}
        y={nodeY}
        label="[SCHEDULER_CORE]"
        detail="Role: Coordinator"
      >
        <DiagramMarker cx={125} cy={15} />
      </DiagramNode>

      {/* Node 3: Global Compute Network */}
      <DiagramNode
        x={startX + nodeSpacing * 2}
        y={nodeY}
        label="[COMPUTE_NETWORK]"
        detail="Role: Execution"
      />

      {/* CONNECTIONS (Aligned at Y=90) */}
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

      {/* Data indicator dot */}
      <DiagramMarker cx={startX + nodeSpacing * 2 - 45} cy={connectionY} />
    </DiagramCanvas>
  );
}
