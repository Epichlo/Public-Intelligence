import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

type DiagramConnectionProps = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  active?: boolean;
  curved?: boolean;
  controlPoint?: { x: number; y: number };
  marker?: boolean;
};

export function DiagramConnection({
  x1,
  y1,
  x2,
  y2,
  active = false,
  curved = false,
  controlPoint,
  marker = false,
}: DiagramConnectionProps) {
  const stroke = active ? diagramTokens.color.active : diagramTokens.color.inherited;
  const strokeWidth = active
    ? diagramTokens.connection.strokeWidth.active
    : diagramTokens.connection.strokeWidth.inactive;
  const strokeOpacity = active
    ? diagramTokens.connection.strokeOpacity.active
    : diagramTokens.connection.strokeOpacity.inactive;
  const strokeDasharray = active
    ? diagramTokens.connection.dasharray.active
    : diagramTokens.connection.dasharray.inactive;

  if (curved && controlPoint) {
    return (
      <path
        d={`M ${x1} ${y1} Q ${controlPoint.x} ${controlPoint.y} ${x2} ${y2}`}
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeOpacity={strokeOpacity}
        strokeDasharray={strokeDasharray}
        fill={diagramTokens.color.none}
        markerEnd={marker ? `url(#${diagramTokens.arrowhead.id})` : undefined}
      />
    );
  }

  return (
    <line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeOpacity={strokeOpacity}
      strokeDasharray={strokeDasharray}
      markerEnd={marker ? `url(#${diagramTokens.arrowhead.id})` : undefined}
    />
  );
}
