"use client";

export interface LatencyMetrics {
  ttftMs: number | null;
  tokensPerSec: number | null;
  elapsedTimeSec: number | null;
  promptTokens: number;
  completionTokens: number;
}

interface LatencyMetricsCardProps {
  metrics: LatencyMetrics;
  isStreaming?: boolean;
}

export function LatencyMetricsCard({ metrics, isStreaming }: LatencyMetricsCardProps) {
  return (
    <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Inference Latency Telemetry
        </h3>
        {isStreaming && (
          <span className="flex items-center gap-1 text-[11px] font-mono text-emerald-400">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
            STREAMING
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3">
        {/* Time to First Token (TTFT) */}
        <div className="rounded-lg border border-border/30 bg-zinc-950/60 p-3 text-center">
          <span className="block text-[10px] uppercase font-medium text-muted-foreground">
            TTFT
          </span>
          <span className="mt-1 block font-mono text-lg font-bold text-emerald-400">
            {metrics.ttftMs !== null ? `${metrics.ttftMs.toFixed(0)} ms` : "--"}
          </span>
          <span className="text-[10px] text-zinc-500 font-mono">Time To 1st Token</span>
        </div>

        {/* Tokens / Sec Generation Speed */}
        <div className="rounded-lg border border-border/30 bg-zinc-950/60 p-3 text-center">
          <span className="block text-[10px] uppercase font-medium text-muted-foreground">
            Speed
          </span>
          <span className="mt-1 block font-mono text-lg font-bold text-foreground">
            {metrics.tokensPerSec !== null ? `${metrics.tokensPerSec.toFixed(1)} t/s` : "--"}
          </span>
          <span className="text-[10px] text-zinc-500 font-mono">Generation Rate</span>
        </div>

        {/* Elapsed Time */}
        <div className="rounded-lg border border-border/30 bg-zinc-950/60 p-3 text-center">
          <span className="block text-[10px] uppercase font-medium text-muted-foreground">
            Elapsed
          </span>
          <span className="mt-1 block font-mono text-lg font-bold text-foreground">
            {metrics.elapsedTimeSec !== null ? `${metrics.elapsedTimeSec.toFixed(2)} s` : "--"}
          </span>
          <span className="text-[10px] text-zinc-500 font-mono">Total Duration</span>
        </div>
      </div>

      {/* Token Counts breakdown */}
      <div className="flex justify-between items-center text-xs font-mono pt-1 text-muted-foreground border-t border-border/20">
        <span>Prompt: <strong className="text-foreground">{metrics.promptTokens}</strong> tok</span>
        <span>Completion: <strong className="text-foreground">{metrics.completionTokens}</strong> tok</span>
        <span>Total: <strong className="text-emerald-400">{metrics.promptTokens + metrics.completionTokens}</strong> tok</span>
      </div>
    </div>
  );
}
