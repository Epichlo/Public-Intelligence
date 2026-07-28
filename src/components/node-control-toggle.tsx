"use client";

import { useState } from "react";

interface NodeControlToggleProps {
  status: "ready" | "running" | "stopped" | "unreachable" | "transitioning";
  nodeId?: string;
  onStatusChange?: (newStatus: "ready" | "running" | "stopped" | "unreachable") => void;
}

export function NodeControlToggle({
  status,
  nodeId = "local-host-node",
  onStatusChange,
}: NodeControlToggleProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isRunning = status === "running" || status === "ready";

  const handleToggle = async () => {
    setLoading(true);
    setError(null);
    const targetAction = isRunning ? "stop" : "start";

    try {
      const response = await fetch("/api/node/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: targetAction }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || `Node control call failed (${response.status})`);
      }

      const result = await response.json();
      const nextStatus = result.runtime_running ? "running" : "stopped";
      if (onStatusChange) {
        onStatusChange(nextStatus);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to communicate with node API");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-border/40 bg-card p-6 shadow-sm">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-foreground">Host Node Execution Runtime</h2>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium border ${
                isRunning
                  ? "bg-emerald-950/60 border-emerald-500/30 text-emerald-400"
                  : status === "unreachable"
                  ? "bg-amber-950/60 border-amber-500/30 text-amber-400"
                  : "bg-zinc-900 border-zinc-700 text-zinc-400"
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  isRunning
                    ? "bg-emerald-400 animate-pulse"
                    : status === "unreachable"
                    ? "bg-amber-400"
                    : "bg-zinc-500"
                }`}
              />
              {isRunning
                ? "ACTIVE RUNTIME"
                : status === "unreachable"
                ? "UNREACHABLE"
                : "STOPPED"}
            </span>
          </div>
          <p className="mt-1 text-sm text-muted-foreground font-mono">
            Node ID: <span className="text-foreground">{nodeId}</span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleToggle}
            disabled={loading || status === "unreachable"}
            className={`relative inline-flex items-center justify-center rounded-lg px-5 py-2.5 text-sm font-medium transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 disabled:opacity-50 disabled:cursor-not-allowed ${
              isRunning
                ? "bg-red-500/10 text-red-400 border border-red-500/30 hover:bg-red-500/20"
                : "bg-[#D9F99D] text-zinc-950 hover:bg-[#bef264] font-semibold"
            }`}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg
                  className="h-4 w-4 animate-spin text-current"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Processing...
              </span>
            ) : isRunning ? (
              "Stop Host Node"
            ) : (
              "Start Host Node"
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-500/30 bg-red-950/40 p-3 text-xs text-red-300">
          <strong>Control Error:</strong> {error}
        </div>
      )}
    </div>
  );
}
