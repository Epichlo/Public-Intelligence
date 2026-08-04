export const diagramTokens = {
  canvas: {
    width: 760,
    height: 240,
    radius: 6,
  },
  grid: {
    patternSize: 20,
    patternStrokeWidth: 0.5,
    patternStrokeOpacity: 0.03,
    borderInset: 0.5,
    borderOffset: 1,
    borderStrokeWidth: 1,
    borderStrokeOpacity: 0.08,
    cornerSize: 10,
    cornerStrokeWidth: 1,
    cornerStrokeOpacity: 0.25,
  },
  node: {
    width: 140,
    height: 60,
    compactHeight: 50,
    radius: 3,
    strokeWidth: 1,
    strokeOpacity: {
      active: 0.4,
      inactive: 0.18,
    },
    fill: "var(--background, #0f0f11)",
    textInsetX: 15,
    labelY: {
      compact: 20,
      default: 24,
    },
    detailY: {
      compact: 36,
      default: 42,
    },
  },
  connection: {
    strokeWidth: {
      active: 1.2,
      inactive: 1,
    },
    strokeOpacity: {
      active: 1,
      inactive: 0.1,
    },
    dasharray: {
      active: "none",
      inactive: "3 3",
    },
  },
  marker: {
    radius: 2.5,
  },
  arrowhead: {
    id: "arrowhead",
    markerWidth: 10,
    markerHeight: 7,
    refX: 0,
    refY: 3.5,
    points: "0 0, 10 3.5, 0 7",
  },
  text: {
    label: {
      fill: {
        active: "#D9F99D",
        inactive: "#f3f4f6",
      },
      fontSize: 11,
      fontWeight: 600,
    },
    detail: {
      fill: {
        active: "#d1d5db",
        inactive: "#9ca3af",
      },
      fontSize: 9.5,
      fontWeight: {
        active: 500,
        inactive: 400,
      },
    },
    caption: {
      fill: "#9ca3af",
      fontSize: 9.5,
      fontWeight: 400,
    },
  },
  color: {
    active: "#D9F99D",
    inherited: "currentColor",
    none: "none",
  },
} as const;
