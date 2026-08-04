import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

type DiagramMarkerProps = {
  cx: number;
  cy: number;
  r?: number;
  fill?: string;
};

export function DiagramMarker({
  cx,
  cy,
  r = diagramTokens.marker.radius,
  fill = diagramTokens.color.active,
}: DiagramMarkerProps) {
  return <circle cx={cx} cy={cy} r={r} fill={fill} />;
}
