"use client";

import { useEffect, useState } from "react";
import { PageShell } from "@/components/page-shell";
import { NodeControlToggle } from "@/components/node-control-toggle";
import { TelemetryGauges, TelemetryData } from "@/components/telemetry-gauge";
import { SandboxLogViewer } from "@/components/sandbox-log-viewer";
import { ContributionSummary } from "@/components/contribution-summary";

/**
 * There is no default telemetry object on purpose. It used to seed 16 GB RAM,
 * 8 GB VRAM, a "local-host-node" id and a module-load timestamp -- invented
 * hardware and a fresh-looking heartbeat rendered as live gauges whenever the
 * node API could not be reached. Until a real frame arrives, this dashboard
 * has nothing measured to show, so it shows exactly that.
 */

export default function DashboardPage() {
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [nodeStatus, setNodeStatus] = useState<"ready" | "running" | "stopped" | "unreachable">("stopped");

  useEffect(() => {
    let isMounted = true;

    const runFetch = async () => {
      try {
        const res = await fetch("/api/node/telemetry", { cache: "no-store" });
        if (res.ok && isMounted) {
          const data = await res.json();
          setTelemetry((prev) => ({
            ...data,
            last_updated: new Date().toISOString(),
            telemetry_count: (prev?.telemetry_count || 0) + 1,
          }));
          setFetchFailed(false);
          if (data.status === "ready" || data.status === "running") {
            setNodeStatus("running");
          } else if (data.status === "stopped") {
            setNodeStatus("stopped");
          } else {
            setNodeStatus("unreachable");
          }
        } else if (isMounted) {
          setFetchFailed(true);
          setNodeStatus("unreachable");
        }
      } catch {
        if (isMounted) {
          setFetchFailed(true);
          setNodeStatus("unreachable");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    runFetch();
    const interval = setInterval(runFetch, 2500);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleStatusChange = (newStatus: "ready" | "running" | "stopped" | "unreachable") => {
    setNodeStatus(newStatus);
  };

  return (
    <PageShell>
      <div className="py-8 space-y-8">
        {/* Header Title */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
            Host Contributor Dashboard
          </h1>
          <p className="mt-2 text-base text-muted-foreground">
            Monitor real-time host hardware telemetry, control background runtime execution, verify AEAD encryption status, and view Docker sandbox container logs.
          </p>
        </div>

        {/* Host Control Toggle */}
        <NodeControlToggle
          status={nodeStatus}
          nodeId={telemetry?.node_id}
          onStatusChange={handleStatusChange}
        />

        {/* Telemetry Gauges Section */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-foreground">Hardware & Network Telemetry</h2>
            {loading && (
              <span className="text-xs font-mono text-muted-foreground animate-pulse">
                Fetching metrics...
              </span>
            )}
          </div>
          <ContributionSummary nodeId={telemetry?.node_id ?? ""} />

        {telemetry ? (
          <TelemetryGauges telemetry={telemetry} />
        ) : (
          <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm">
            <p className="text-sm font-medium text-foreground">
              No telemetry received yet.
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {fetchFailed
                ? "The node API could not be reached, so no hardware metrics exist to show. Start the host runtime or verify the node connection."
                : "Waiting for the first telemetry frame from the local node."}
            </p>
          </div>
        )}
        </div>

        {/* Docker Sandbox Logs Section */}
        <div className="pt-2">
          <SandboxLogViewer />
        </div>
      </div>
    </PageShell>
  );
}
