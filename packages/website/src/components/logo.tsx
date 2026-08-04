import * as React from "react";

type LogoProps = {
  className?: string;
  showText?: boolean;
};

export function Logo({ className = "w-6 h-6", showText = false }: LogoProps) {
  return (
    <div className="inline-flex items-center gap-2.5">
      <svg
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={className}
        aria-hidden="true"
      >
        {/* Coordinate orbit */}
        <circle
          cx="16"
          cy="16"
          r="10"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.2"
        />
        {/* Coordination paths radiating from center coordinator to vertices */}
        <line
          x1="16"
          y1="16"
          x2="16"
          y2="6"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.2"
        />
        <line
          x1="16"
          y1="16"
          x2="7.34"
          y2="21"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.2"
        />
        <line
          x1="16"
          y1="16"
          x2="24.66"
          y2="21"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.2"
        />
        
        {/* Center coordination hub */}
        <circle
          cx="16"
          cy="16"
          r="2"
          fill="currentColor"
        />
        {/* Connected node (Bottom-Left) */}
        <circle
          cx="7.34"
          cy="21"
          r="2"
          fill="var(--background, #0f0f11)"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.6"
        />
        {/* Connected node (Bottom-Right) */}
        <circle
          cx="24.66"
          cy="21"
          r="2"
          fill="var(--background, #0f0f11)"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeOpacity="0.6"
        />
        {/* Coordinator active execution point (Top) */}
        <circle
          cx="16"
          cy="6"
          r="2"
          fill="#D9F99D"
          stroke="#D9F99D"
          strokeWidth="1.2"
        />
      </svg>
      {showText && (
        <span className="font-sans font-medium tracking-tight text-foreground transition-colors duration-150 hover:text-foreground/90">
          Public Intelligence
        </span>
      )}
    </div>
  );
}
