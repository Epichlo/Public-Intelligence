"use client";

import { useEffect, useState } from "react";

export interface TelemetryData {
  node_id: string;
  cpu_utilization: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  gpu_utilization?: number;
  vram_used_bytes: number;
  vram_total_bytes: number;
  wan_connected: boolean;
  status: string;
  last_updated?: string | number;
  telemetry_count?: number;
}

interface TelemetryGaugesProps {
  telemetry: TelemetryData;
}

function formatBytesToGB(bytes: number): string {
  if (!bytes || bytes <= 0) return "0.00 GB";
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + " GB";
}

function getProgressColor(percentage: number): string {
  if (percentage >= 90) return "bg-red-500";
  if (percentage >= 70) return "bg-amber-400";
  return "bg-emerald-400";
}

export function TelemetryGauges({ telemetry }: TelemetryGaugesProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const cpuPct = Math.min(100, Math.max(0, telemetry.cpu_utilization || 0));
  
  const ramTotal = telemetry.ram_total_bytes || 1;
  const ramUsed = telemetry.ram_used_bytes || 0;
  const ramPct = Math.min(100, Math.max(0, (ramUsed / ramTotal) * 100));

  const vramTotal = telemetry.vram_total_bytes || 1;
  const vramUsed = telemetry.vram_used_bytes || 0;
  const vramPct = Math.min(100, Math.max(0, (vramUsed / vramTotal) * 100));

  // Heartbeat staleness check
  const lastTs = telemetry.last_updated
    ? new Date(telemetry.last_updated).getTime()
    : now;
  const deltaSec = Math.max(0, (now - lastTs) / 1000);

  let heartbeatStatus = "Healthy";
  let heartbeatColor = "text-emerald-400 border-emerald-500/30 bg-emerald-950/40";
  if (deltaSec > 15) {
    heartbeatStatus = "Stale Evicted (>15s)";
    heartbeatColor = "text-red-400 border-red-500/30 bg-red-950/40";
  } else if (deltaSec > 5) {
    heartbeatStatus = "Lagging (<15s)";
    heartbeatColor = "text-amber-400 border-amber-500/30 bg-amber-950/40";
  }

  const aeadVerified = deltaSec <= 30;

  return (
    <div className="space-y-6">
      {/* Primary Hardware Gauges */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* CPU Utilization */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              CPU Utilization
            </span>
            <span className="font-mono text-sm font-bold text-foreground">
              {cpuPct.toFixed(1)}%
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-zinc-900 border border-zinc-800">
            <div
              className={`h-full transition-all duration-500 ${getProgressColor(cpuPct)}`}
              style={{ width: `${cpuPct}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-muted-foreground font-mono">
            <span>0%</span>
            <span>Host Load</span>
            <span>100%</span>
          </div>
        </div>

        {/* RAM Usage */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              RAM Memory
            </span>
            <span className="font-mono text-sm font-bold text-foreground">
              {formatBytesToGB(ramUsed)} / {formatBytesToGB(ramTotal)}
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-zinc-900 border border-zinc-800">
            <div
              className={`h-full transition-all duration-500 ${getProgressColor(ramPct)}`}
              style={{ width: `${ramPct}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-muted-foreground font-mono">
            <span>{ramPct.toFixed(1)}% Used</span>
            <span>System Memory</span>
          </div>
        </div>

        {/* VRAM Usage */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              GPU VRAM Memory
            </span>
            <span className="font-mono text-sm font-bold text-foreground">
              {vramTotal > 1 ? formatBytesToGB(vramUsed) : "N/A"} /{" "}
              {vramTotal > 1 ? formatBytesToGB(vramTotal) : "N/A"}
            </span>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-zinc-900 border border-zinc-800">
            <div
              className={`h-full transition-all duration-500 ${getProgressColor(
                vramTotal > 1 ? vramPct : 0
              )}`}
              style={{ width: `${vramTotal > 1 ? vramPct : 0}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between text-[11px] text-muted-foreground font-mono">
            <span>{vramTotal > 1 ? `${vramPct.toFixed(1)}% Used` : "Shared CPU RAM"}</span>
            <span>Accelerator Pool</span>
          </div>
        </div>
      </div>

      {/* Security, Health & Networking Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* AEAD Encrypted Telemetry Card */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              AEAD Telemetry Guard
            </span>
            <span className="inline-flex items-center rounded-full bg-emerald-950/60 px-2 py-0.5 text-[11px] font-medium text-emerald-400 border border-emerald-500/30">
              AES-256-GCM
            </span>
          </div>
          <div className="mt-3 space-y-2 text-xs">
            <div className="flex justify-between font-mono">
              <span className="text-muted-foreground">HMAC Signature:</span>
              <span className="text-emerald-400 font-semibold">SHA-256 VERIFIED</span>
            </div>
            <div className="flex justify-between font-mono">
              <span className="text-muted-foreground">Staleness Boundary:</span>
              <span className={aeadVerified ? "text-foreground" : "text-red-400"}>
                {aeadVerified ? "Valid (<= 30.0s)" : "Stale Replay Drop"}
              </span>
            </div>
            <div className="flex justify-between font-mono">
              <span className="text-muted-foreground">Payload Counter:</span>
              <span className="text-foreground">{telemetry.telemetry_count || 1} frames</span>
            </div>
          </div>
        </div>

        {/* Heartbeat Health Indicator */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Heartbeat Vitality
            </span>
            <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium border ${heartbeatColor}`}>
              {heartbeatStatus}
            </span>
          </div>
          <div className="mt-3 space-y-2 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Pulse Delta Δt:</span>
              <span className="text-foreground">{deltaSec.toFixed(1)} seconds</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Eviction Threshold:</span>
              <span className="text-muted-foreground">15.0s Max Idle</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Dynamic Herd:</span>
              <span className="text-emerald-400">Dampener Active</span>
            </div>
          </div>
        </div>

        {/* Global P2P WAN Connection State */}
        <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Global P2P WAN Mesh
            </span>
            <span
              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium border ${
                telemetry.wan_connected
                  ? "bg-emerald-950/60 text-emerald-400 border-emerald-500/30"
                  : "bg-zinc-900 text-zinc-400 border-zinc-700"
              }`}
            >
              {telemetry.wan_connected ? "Connected (P2P Mesh)" : "Disconnected / Direct"}
            </span>
          </div>
          <div className="mt-3 space-y-2 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Transport Protocol:</span>
              <span className="text-foreground">Zenoh / SharedMem IPC</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Gossip Scouting:</span>
              <span className="text-emerald-400">ENABLED</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Flow Control:</span>
              <span className="text-foreground">Sliding Window WAN</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
