"use client";

import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { PageShell } from "@/components/page-shell";

type StatusPayload = {
  checked_at: string;
  scheduler: {
    status: string;
    environment?: string;
    network?: { connected: boolean; mode: string };
    nodes?: Array<{
      node_id: string;
      hostname: string;
      region: string;
      status: string;
      heartbeat_at?: string | null;
    }>;
    error?: string;
  };
  node: {
    status: string;
    runtime?: boolean;
    ollama?: boolean;
    scheduler_registered?: boolean;
    wan_connected?: boolean;
    inference_ready?: boolean;
    error?: string;
  };
  node_configured: boolean;
};

type ProbeResult = { node_id: string; result: { model: string; response: string } };

function State({ value }: { value: string | boolean | undefined }) {
  const label = typeof value === "boolean" ? (value ? "Connected" : "Unavailable") : value ?? "Unknown";
  const positive = value === true || ["healthy", "ready", "online"].includes(label);

  return (
    <span className={positive ? "text-[#86EFAC]" : "text-muted-foreground"}>
      <span aria-hidden="true">{positive ? "●" : "○"}</span> {label}
    </span>
  );
}

export default function StatusPage() {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("Return a one-sentence system acknowledgement.");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/status", { cache: "no-store" });
      if (!response.ok) throw new Error(`Status request failed with ${response.status}`);
      setStatus(await response.json());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Status request failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/status", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Status request failed with ${response.status}`);
        return response.json() as Promise<StatusPayload>;
      })
      .then((payload) => {
        if (!cancelled) setStatus(payload);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "Status request failed");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function runProbe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProbe(null);
    setProbeError(null);
    try {
      const response = await fetch("/api/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model, prompt, stream: false }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? body.error ?? "Inference probe failed");
      setProbe(body);
    } catch (caught) {
      setProbeError(caught instanceof Error ? caught.message : "Inference probe failed");
    }
  }

  const nodes = status?.scheduler.nodes ?? [];

  return (
    <PageShell>
      <article className="mx-auto max-w-4xl space-y-16">
        <header className="space-y-5">
          <p className="font-mono text-xs uppercase tracking-wider text-[#86EFAC]">Operational Surface</p>
          <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">System status</h1>
          <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">
            A small end-to-end check of Scheduler reachability, Node registration, WAN state, and inference execution.
          </p>
          <button
            type="button"
            onClick={() => void refresh()}
            className="border border-border/60 px-3 py-2 text-sm text-foreground transition-colors hover:border-[#86EFAC] hover:text-[#86EFAC]"
          >
            {loading ? "Checking…" : "Refresh status"}
          </button>
        </header>

        {error && <p className="border-l border-[#86EFAC] pl-4 text-sm text-muted-foreground">{error}</p>}

        <section aria-labelledby="services-heading" className="space-y-6 border-t border-border/40 pt-8">
          <div className="flex items-baseline justify-between gap-4">
            <h2 id="services-heading" className="text-2xl font-semibold tracking-tight">Services</h2>
            {status?.checked_at && <time className="font-mono text-xs text-muted-foreground">{status.checked_at}</time>}
          </div>
          <dl className="divide-y divide-border/40 border-y border-border/40">
            <div className="grid gap-2 py-4 sm:grid-cols-[1fr_auto]">
              <dt><span className="font-medium">Scheduler</span><span className="ml-3 text-sm text-muted-foreground">{status?.scheduler.environment ?? "not checked"}</span></dt>
              <dd><State value={status?.scheduler.status} /></dd>
            </div>
            <div className="grid gap-2 py-4 sm:grid-cols-[1fr_auto]">
              <dt><span className="font-medium">Scheduler transport</span><span className="ml-3 text-sm text-muted-foreground">{status?.scheduler.network?.mode ?? "not checked"}</span></dt>
              <dd><State value={status?.scheduler.network?.connected} /></dd>
            </div>
            <div className="grid gap-2 py-4 sm:grid-cols-[1fr_auto]">
              <dt><span className="font-medium">Node readiness</span><span className="ml-3 text-sm text-muted-foreground">{status?.node_configured ? "configured" : "NODE_URL not configured"}</span></dt>
              <dd><State value={status?.node.status} /></dd>
            </div>
          </dl>
        </section>

        <section aria-labelledby="nodes-heading" className="space-y-6 border-t border-border/40 pt-8">
          <h2 id="nodes-heading" className="text-2xl font-semibold tracking-tight">Registered nodes</h2>
          {nodes.length === 0 ? (
            <p className="text-sm text-muted-foreground">No nodes are currently registered with the Scheduler.</p>
          ) : (
            <ul className="divide-y divide-border/40 border-y border-border/40">
              {nodes.map((node) => (
                <li key={node.node_id} className="grid gap-2 py-4 sm:grid-cols-[1fr_auto]">
                  <div><p className="font-medium">{node.node_id}</p><p className="text-sm text-muted-foreground">{node.hostname} · {node.region}</p></div>
                  <State value={node.status} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="probe-heading" className="space-y-6 border-t border-border/40 pt-8">
          <div className="space-y-2"><h2 id="probe-heading" className="text-2xl font-semibold tracking-tight">Inference probe</h2><p className="text-sm text-muted-foreground">Send one request through the Scheduler to a registered Node.</p></div>
          <form onSubmit={runProbe} className="space-y-4">
            <label className="block space-y-2 text-sm"><span>Model</span><input required value={model} onChange={(event) => setModel(event.target.value)} className="block w-full border border-border/60 bg-transparent px-3 py-2 text-foreground outline-none focus:border-[#86EFAC]" placeholder="llama3.2" /></label>
            <label className="block space-y-2 text-sm"><span>Prompt</span><textarea required value={prompt} onChange={(event) => setPrompt(event.target.value)} className="block min-h-24 w-full border border-border/60 bg-transparent px-3 py-2 text-foreground outline-none focus:border-[#86EFAC]" /></label>
            <button type="submit" className="bg-foreground px-4 py-2 text-sm font-medium text-background transition-opacity hover:opacity-80">Run inference probe</button>
          </form>
          {probeError && <p className="border-l border-red-400 pl-4 text-sm text-muted-foreground">{probeError}</p>}
          {probe && <div className="space-y-2 border border-border/40 p-4 text-sm"><p className="font-mono text-xs text-[#86EFAC]">Node: {probe.node_id}</p><p className="whitespace-pre-wrap text-muted-foreground">{probe.result.response}</p></div>}
        </section>
      </article>
    </PageShell>
  );
}
