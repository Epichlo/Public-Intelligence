import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

type DiagramNodeProps = {
  x: number;
  y: number;
  width?: number;
  height?: number;
  label: string;
  detail: string;
  active?: boolean;
  detailActive?: boolean;
  children?: React.ReactNode;
};

export function DiagramNode({
  x,
  y,
  width = diagramTokens.node.width,
  height = diagramTokens.node.height,
  label,
  detail,
  active = false,
  detailActive = false,
  children,
}: DiagramNodeProps) {
  return (
    <g transform={`translate(${x}, ${y})`}>
      <rect
        x="0"
        y="0"
        width={width}
        height={height}
        rx={diagramTokens.node.radius}
        stroke={active ? diagramTokens.color.active : diagramTokens.color.inherited}
        strokeWidth={diagramTokens.node.strokeWidth}
        strokeOpacity={
          active ? diagramTokens.node.strokeOpacity.active : diagramTokens.node.strokeOpacity.inactive
        }
        fill={diagramTokens.node.fill}
      />
      <text
        x={diagramTokens.node.textInsetX}
        y={
          height === diagramTokens.node.compactHeight
            ? diagramTokens.node.labelY.compact
            : diagramTokens.node.labelY.default
        }
        fill={
          active ? diagramTokens.text.label.fill.active : diagramTokens.text.label.fill.inactive
        }
        fontSize={diagramTokens.text.label.fontSize}
        fontWeight={diagramTokens.text.label.fontWeight}
      >
        {label}
      </text>
      <text
        x={diagramTokens.node.textInsetX}
        y={
          height === diagramTokens.node.compactHeight
            ? diagramTokens.node.detailY.compact
            : diagramTokens.node.detailY.default
        }
        fill={
          detailActive || active
            ? diagramTokens.text.detail.fill.active
            : diagramTokens.text.detail.fill.inactive
        }
        fontSize={diagramTokens.text.detail.fontSize}
        fontWeight={
          detailActive
            ? diagramTokens.text.detail.fontWeight.active
            : diagramTokens.text.detail.fontWeight.inactive
        }
      >
        {detail}
      </text>
      {children}
    </g>
  );
}
