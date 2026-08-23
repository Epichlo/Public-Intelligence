"use client";

import { useCallback, useEffect, useState } from "react";

interface ModelObject {
  id: string;
  created?: number;
  owned_by?: string;
}

/**
 * What the picker may show, derived only from what the Scheduler actually
 * answered. There is no "fallback list" state: a fleet the dashboard cannot
 * see is rendered as unseen, never as three models somebody once guessed.
 */
export type ModelCatalogueState =
  | { status: "loading"; models: string[] }
  | { status: "ready"; models: string[] }
  | { status: "empty"; models: [] }
  | { status: "unavailable"; models: [] };

/**
 * Shape gate between the proxy's JSON and the dropdown.
 *
 * Returns the served ids for a well-formed `{ data: [{ id }] }` catalogue,
 * `[]` for a well-formed but empty one -- an empty fleet is a fact, not a
 * failure -- and `null` for anything else, because an unreadable body must
 * never become model names.
 */
export function parseModelIds(data: unknown): string[] | null {
  if (typeof data !== "object" || data === null) return null;
  const container = (data as { data?: unknown }).data;
  if (!Array.isArray(container)) return null;

  const ids: string[] = [];
  for (const entry of container) {
    if (typeof entry !== "object" || entry === null) return null;
    const id = (entry as ModelObject).id;
    if (typeof id !== "string" || id.length === 0) return null;
    ids.push(id);
  }
  return ids;
}

/**
 * The only path from a fetch outcome to dropdown contents.
 *
 * `fetchOk` is false for a thrown request and for a non-ok response alike:
 * both mean "no catalogue was obtained", and neither may resolve to model
 * names. An unparseable 200 body is the same non-answer. This used to keep a
 * hardcoded `["llama3", "llama3.2", "mistral"]` in every one of these cases,
 * which sent hosts chasing a 503 for a model nobody serves.
 */
export function resolveModelCatalogue(
  fetchOk: boolean,
  payload: unknown
): ModelCatalogueState {
  if (!fetchOk) return { status: "unavailable", models: [] };
  const ids = parseModelIds(payload);
  if (ids === null) return { status: "unavailable", models: [] };
  if (ids.length === 0) return { status: "empty", models: [] };
  return { status: "ready", models: ids };
}

/** The empty/unavailable copy, exported so tests pin the exact words. */
export function catalogueNotice(
  state: ModelCatalogueState
): { title: string; detail: string } | null {
  if (state.status === "empty") {
    return {
      title: "No models available.",
      detail:
        "The Scheduler answered with an empty model catalogue. Start a compute node serving a model, then retry.",
    };
  }
  if (state.status === "unavailable") {
    return {
      title: "Could not load model catalogue.",
      detail:
        "The Scheduler could not be reached or returned an unreadable response. Verify the connection, then retry.",
    };
  }
  return null;
}

interface ModelSelectorProps {
  value: string;
  onChange: (model: string) => void;
  disabled?: boolean;
}

export function ModelSelector({ value, onChange, disabled }: ModelSelectorProps) {
  const [catalogue, setCatalogue] = useState<ModelCatalogueState>({
    status: "loading",
    models: [],
  });
  const [reloadTick, setReloadTick] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadModels() {
      setLoading(true);
      try {
        const res = await fetch("/api/models");
        if (!isMounted) return;
        let payload: unknown;
        const ok = res.ok;
        if (ok) {
          payload = await res.json();
        }
        if (isMounted) setCatalogue(resolveModelCatalogue(ok, payload));
      } catch {
        if (isMounted) setCatalogue({ status: "unavailable", models: [] });
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadModels();
    return () => {
      isMounted = false;
    };
  }, [reloadTick]);

  // A catalogue that arrives without the parent's current selection means the
  // parent is holding a name nobody serves (its initial state predates the
  // fetch). Re-point it at a model the fleet actually advertises rather than
  // let the dropdown display one value and the request send another.
  useEffect(() => {
    if (
      catalogue.status === "ready" &&
      catalogue.models.length > 0 &&
      !catalogue.models.includes(value)
    ) {
      onChange(catalogue.models[0]);
    }
  }, [catalogue, value, onChange]);

  const retry = useCallback(() => setReloadTick((tick) => tick + 1), []);

  const notice = catalogueNotice(catalogue);

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Active LLM Model
      </label>
      <div className="relative">
        {catalogue.status === "ready" ? (
          <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            disabled={disabled}
            className="w-full rounded-lg border border-border/60 bg-zinc-950 px-3 py-2 text-sm text-foreground focus:border-emerald-500 focus:outline-none disabled:opacity-50 font-mono"
          >
            {catalogue.models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        ) : (
          <div
            className={`w-full rounded-lg border px-3 py-2.5 text-sm font-mono ${
              catalogue.status === "empty"
                ? "border-amber-500/40 bg-amber-950/30 text-amber-200"
                : catalogue.status === "unavailable"
                ? "border-red-500/30 bg-zinc-950 text-red-300"
                : "border-border/60 bg-zinc-950 text-muted-foreground"
            }`}
          >
            {notice ? (
              <>
                <p className="text-xs font-semibold">{notice.title}</p>
                <p className="mt-1 text-[11px] leading-relaxed opacity-90">
                  {notice.detail}
                </p>
                <button
                  type="button"
                  onClick={retry}
                  disabled={loading || disabled}
                  className="mt-2 inline-flex items-center rounded-md border border-border/60 px-2.5 py-1 text-[11px] text-foreground hover:border-emerald-500/60 hover:text-emerald-400 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                >
                  {loading ? "retrying..." : "Retry"}
                </button>
              </>
            ) : (
              <span className="text-xs text-muted-foreground animate-pulse">
                loading fleet catalogue...
              </span>
            )}
          </div>
        )}
        {loading && catalogue.status === "ready" && (
          <span className="absolute right-8 top-2.5 text-[10px] text-muted-foreground font-mono animate-pulse">
            syncing...
          </span>
        )}
      </div>
    </div>
  );
}
