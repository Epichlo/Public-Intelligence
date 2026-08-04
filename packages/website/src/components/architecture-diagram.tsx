import * as React from "react";

export function ArchitectureDiagram() {
  return (
    <div className="my-12 flex justify-center">
      <svg 
        width="600" 
        height="300" 
        viewBox="0 0 600 300" 
        className="w-full max-w-4xl"
        xmlns="http://www.w3.org/2000/svg"
      >
        {/* Website Node */}
        <rect 
          x="50" 
          y="100" 
          width="120" 
          height="80" 
          rx="8" 
          fill="white" 
          stroke="#10b981" 
          strokeWidth="2"
          className="transition-all duration-300 hover:stroke-green-500"
        />
        <text 
          x="110" 
          y="140" 
          textAnchor="middle" 
          className="fill-foreground text-sm font-medium"
        >
          Website
        </text>
        
        {/* Scheduler Node */}
        <rect 
          x="240" 
          y="100" 
          width="120" 
          height="80" 
          rx="8" 
          fill="white" 
          stroke="#10b981" 
          strokeWidth="2"
          className="transition-all duration-300 hover:stroke-green-500"
        />
        <text 
          x="300" 
          y="140" 
          textAnchor="middle" 
          className="fill-foreground text-sm font-medium"
        >
          Scheduler
        </text>
        
        {/* Global Nodes */}
        <rect 
          x="430" 
          y="60" 
          width="120" 
          height="80" 
          rx="8" 
          fill="white" 
          stroke="#10b981" 
          strokeWidth="2"
          className="transition-all duration-300 hover:stroke-green-500"
        />
        <text 
          x="490" 
          y="100" 
          textAnchor="middle" 
          className="fill-foreground text-sm font-medium"
        >
          Global Nodes
        </text>
        
        {/* Connection from Website to Scheduler */}
        <line 
          x1="170" 
          y1="140" 
          x2="240" 
          y2="140" 
          stroke="#10b981" 
          strokeWidth="2" 
          markerEnd="url(#arrowhead)"
        />
        
        {/* Connection from Scheduler to Global Nodes */}
        <line 
          x1="360" 
          y1="140" 
          x2="430" 
          y2="100" 
          stroke="#10b981" 
          strokeWidth="2" 
          markerEnd="url(#arrowhead)"
        />
        
        {/* Arrowhead definition */}
        <defs>
          <marker 
            id="arrowhead" 
            markerWidth="10" 
            markerHeight="7" 
            refX="0" 
            refY="3.5" 
            orient="auto"
          >
            <polygon 
              points="0 0, 10 3.5, 0 7" 
              fill="#10b981" 
            />
          </marker>
        </defs>
      </svg>
    </div>
  );
}