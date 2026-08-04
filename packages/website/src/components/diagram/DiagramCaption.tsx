import * as React from "react";
import { diagramTokens } from "./diagram-tokens";

type DiagramCaptionProps = {
  x: number;
  y: number;
  text: string;
  fill?: string;
  fontSize?: number;
  textAnchor?: "start" | "middle" | "end";
};

export function DiagramCaption({
  x,
  y,
  text,
  fill = diagramTokens.text.caption.fill,
  fontSize = diagramTokens.text.caption.fontSize,
  textAnchor = "middle",
}: DiagramCaptionProps) {
  return (
    <text
      x={x}
      y={y}
      fill={fill}
      fontSize={fontSize}
      fontWeight={diagramTokens.text.caption.fontWeight}
      textAnchor={textAnchor}
    >
      {text}
    </text>
  );
}
