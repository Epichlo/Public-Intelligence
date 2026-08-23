"use client";

import { useEffect, useState } from "react";

/**
 * What this host's machine actually served, and what it contributed (ROADMAP 3.4).
 *
 * The dashboard showed live telemetry only — CPU and VRAM gauges, a picture of a
 * moment. A host could see their GPU was busy and had no way to learn what it had
 * done.
 *
 * **"Contributed", never "earned".** `docs/decisions/D2-economics.md` found a
 * consumer-GPU host loses ~15x against commodity pricing, so credits are an
 * accounting unit with no redemption path — a decision, not an unfinished feature.
 * A dashboard saying "earned" would make a promise this project has explicitly
 * declined to make, which is why `formatCredits` is a named export with its own
 * tests rather than inline JSX.
 *
 * The window label is not decoration either. Request totals come from a bounded
 * in-memory tail on the Scheduler, so presenting them as all-time would draw a graph
 * that silently flattens once the buffer wraps.
 */

export interface NodeUsage {
  node_id: string;
  credits_contributed: number;
  credits_are_redeemable: boolean;
  totals_window: string;
  totals_window_size: number;
  totals: {
    requests: number;
    prompt_tokens: number;
    completion_tokens: number;
    failed_requests: number;
  };
}

/** Credits, rendered. Never with a currency symbol — they are not money. */
export function formatCredits(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return value.toFixed(value < 10 ? 2 : 0);
}

/** Failure ratio over the window, or null when nothing has been served yet. */
export function failureRatio(totals: NodeUsage["totals"] | undefined): number | null {
  if (!totals || !totals.requests) return null;
  return totals.failed_requests / totals.requests;
}

/**
 * The shape gate between the proxy's JSON and a render path.
 *
 * `load()` used to cast `res.json()` straight to `NodeUsage` on the strength of
 * `res.ok` alone, which trusted an HTTP status to guarantee a body shape it does
 * not: every proxy route here answers 200 with `{ detail: ... }` when it passes an
 * upstream failure through, and that error object rendered as
 * `usage.totals.requests` -- crashing this subtree at `undefined.requests` while
 * `failureRatio`, two functions up in this same file, guarded carefully against the
 * identical hazard. A panel about honest accounting crashed rather than say
 * "unavailable".
 *
 * Every field the interface names is checked, because the render reads more than
 * the obvious two (`totals_window_size` is in the footnote). Anything unshaped
 * returns null, which the caller must present as "unavailable" -- not zero.
 */
export function parseNodeUsage(value: unknown): NodeUsage | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const v = value as Record<string, unknown>;

  if (typeof v.node_id !== "string") return null;
  if (typeof v.credits_are_redeemable !== "boolean") return null;
  if (typeof v.totals_window !== "string") return null;

  const finite = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
  // Number.isFinite rejects both NaN and the infinities, so a payload carrying
  // them cannot reach formatCredits or the ratio arithmetic.
  if (!finite(v.credits_contributed) || !finite(v.totals_window_size)) return null;

  const totals = v.totals;
  if (typeof totals !== "object" || totals === null || Array.isArray(totals)) return null;
  const t = totals as Record<string, unknown>;
  if (!finite(t.requests) || !finite(t.prompt_tokens)) return null;
  if (!finite(t.completion_tokens) || !finite(t.failed_requests)) return null;

  return {
    node_id: v.node_id,
    credits_contributed: v.credits_contributed,
    credits_are_redeemable: v.credits_are_redeemable,
    totals_window: v.totals_window,
    totals_window_size: v.totals_window_size,
    totals: {
      requests: t.requests,
      prompt_tokens: t.prompt_tokens,
      completion_tokens: t.completion_tokens,
      failed_requests: t.failed_requests,
    },
  };
}

export function ContributionSummary({ nodeId }: { nodeId: string }) {
  const [usage, setUsage] = useState<NodeUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!nodeId) return;
    let mounted = true;

    const load = async () => {
      try {
        const res = await fetch(`/api/usage?node=${encodeURIComponent(nodeId)}`, {
          cache: "no-store",
        });
        if (!mounted) return;
        if (!res.ok) {
          // Distinguished from "zero contributed": a dashboard that renders an
          // unreachable Scheduler as 0 is telling the host their machine did
          // nothing, which is a different and wrong statement.
          setError(res.status === 401 ? "not authorised" : `unavailable (${res.status})`);
          return;
        }
        // The proxy can answer 200 with a body this panel cannot read (an upstream
        // error passed through under `{ detail }`). That used to be cast and set
        // as-is, crashing the subtree on first render; now it is the same
        // "unavailable, not zero" state as any other unreadable Scheduler.
        const parsed = parseNodeUsage(await res.json());
        if (!mounted) return;
        if (!parsed) {
          setError("unavailable (unreadable response)");
          return;
        }
        setUsage(parsed);
        setError(null);
      } catch {
        if (mounted) setError("unavailable");
      }
    };

    load();
    const interval = setInterval(load, 10_000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [nodeId]);

  const ratio = failureRatio(usage?.totals);

  return (
    <section
      aria-labelledby="contribution-heading"
      className="rounded-lg border border-border/60 p-4"
    >
      <h2 id="contribution-heading" className="text-sm font-semibold text-foreground">
        Contributed
      </h2>

      {error ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Usage {error}. This is not the same as zero — the Scheduler could not be read.
        </p>
      ) : !usage ? (
        <p className="mt-2 text-sm text-muted-foreground">Loading…</p>
      ) : (
        <>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Credits</dt>
              <dd className="font-mono text-lg">{formatCredits(usage.credits_contributed)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Requests</dt>
              <dd className="font-mono text-lg">{usage.totals.requests}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Tokens out</dt>
              <dd className="font-mono text-lg">{usage.totals.completion_tokens}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Failed</dt>
              <dd className="font-mono text-lg">
                {ratio === null ? "—" : `${(ratio * 100).toFixed(0)}%`}
              </dd>
            </div>
          </dl>

          <p className="mt-3 text-xs text-muted-foreground">
            Request totals cover the most recent {usage.totals_window_size} requests, not
            all time. Credits are an accounting unit and are{" "}
            <strong>not redeemable</strong>.
          </p>
        </>
      )}
    </section>
  );
}
