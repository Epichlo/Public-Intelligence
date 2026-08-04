import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

type DiagramGridProps = {
  width: number;
  height: number;
  patternId: string;
};

export function DiagramGrid({ width, height, patternId }: DiagramGridProps) {
  return (
    <>
      <defs>
        <pattern
          id={patternId}
          width={diagramTokens.grid.patternSize}
          height={diagramTokens.grid.patternSize}
          patternUnits="userSpaceOnUse"
        >
          <path
            d={`M ${diagramTokens.grid.patternSize} 0 L 0 0 0 ${diagramTokens.grid.patternSize}`}
            fill={diagramTokens.color.none}
            stroke={diagramTokens.color.inherited}
            strokeWidth={diagramTokens.grid.patternStrokeWidth}
            strokeOpacity={diagramTokens.grid.patternStrokeOpacity}
          />
        </pattern>
      </defs>
      <rect width={width} height={height} fill={`url(#${patternId})`} rx={diagramTokens.canvas.radius} />
      <rect
        x={diagramTokens.grid.borderInset}
        y={diagramTokens.grid.borderInset}
        width={width - diagramTokens.grid.borderOffset}
        height={height - diagramTokens.grid.borderOffset}
        rx={diagramTokens.canvas.radius}
        stroke={diagramTokens.color.inherited}
        strokeWidth={diagramTokens.grid.borderStrokeWidth}
        strokeOpacity={diagramTokens.grid.borderStrokeOpacity}
        fill={diagramTokens.color.none}
      />
      <path
        d={`M ${diagramTokens.grid.cornerSize} ${diagramTokens.grid.borderInset} L ${diagramTokens.grid.borderInset} ${diagramTokens.grid.borderInset} L ${diagramTokens.grid.borderInset} ${diagramTokens.grid.cornerSize}`}
        stroke={diagramTokens.color.inherited}
        strokeWidth={diagramTokens.grid.cornerStrokeWidth}
        strokeOpacity={diagramTokens.grid.cornerStrokeOpacity}
        fill={diagramTokens.color.none}
      />
      <path
        d={`M ${width - diagramTokens.grid.cornerSize} ${diagramTokens.grid.borderInset} L ${width - diagramTokens.grid.borderInset} ${diagramTokens.grid.borderInset} L ${width - diagramTokens.grid.borderInset} ${diagramTokens.grid.cornerSize}`}
        stroke={diagramTokens.color.inherited}
        strokeWidth={diagramTokens.grid.cornerStrokeWidth}
        strokeOpacity={diagramTokens.grid.cornerStrokeOpacity}
        fill={diagramTokens.color.none}
      />
      <path
        d={`M ${diagramTokens.grid.borderInset} ${height - diagramTokens.grid.cornerSize} L ${diagramTokens.grid.borderInset} ${height - diagramTokens.grid.borderInset} L ${diagramTokens.grid.cornerSize} ${height - diagramTokens.grid.borderInset}`}
        stroke={diagramTokens.color.inherited}
        strokeWidth={diagramTokens.grid.cornerStrokeWidth}
        strokeOpacity={diagramTokens.grid.cornerStrokeOpacity}
        fill={diagramTokens.color.none}
      />
      <path
        d={`M ${width - diagramTokens.grid.cornerSize} ${height - diagramTokens.grid.borderInset} L ${width - diagramTokens.grid.borderInset} ${height - diagramTokens.grid.borderInset} L ${width - diagramTokens.grid.borderInset} ${height - diagramTokens.grid.cornerSize}`}
        stroke={diagramTokens.color.inherited}
        strokeWidth={diagramTokens.grid.cornerStrokeWidth}
        strokeOpacity={diagramTokens.grid.cornerStrokeOpacity}
        fill={diagramTokens.color.none}
      />
    </>
  );
}
