import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

export function ArrowheadDef() {
  return (
    <defs>
      <marker
        id={diagramTokens.arrowhead.id}
        markerWidth={diagramTokens.arrowhead.markerWidth}
        markerHeight={diagramTokens.arrowhead.markerHeight}
        refX={diagramTokens.arrowhead.refX}
        refY={diagramTokens.arrowhead.refY}
        orient="auto"
      >
        <polygon points={diagramTokens.arrowhead.points} fill={diagramTokens.color.active} />
      </marker>
    </defs>
  );
}
