"use client";

import { useEffect, useState } from "react";

interface ModelObject {
  id: string;
  created?: number;
  owned_by?: string;
}

interface ModelSelectorProps {
  value: string;
  onChange: (model: string) => void;
  disabled?: boolean;
}

export function ModelSelector({ value, onChange, disabled }: ModelSelectorProps) {
  const [models, setModels] = useState<string[]>(["llama3", "llama3.2", "mistral"]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;

    async function loadModels() {
      setLoading(true);
      try {
        const res = await fetch("/api/models");
        if (res.ok && isMounted) {
          const data = await res.json();
          if (data.data && Array.isArray(data.data) && data.data.length > 0) {
            const modelIds = data.data.map((m: ModelObject) => m.id);
            setModels(modelIds);
          }
        }
      } catch {
        // Fallback default list remains
      } finally {
        if (isMounted) setLoading(false);
      }
    }

    loadModels();
    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium uppercase tracking-wider text-muted-foreground">
        Active LLM Model
      </label>
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          className="w-full rounded-lg border border-border/60 bg-zinc-950 px-3 py-2 text-sm text-foreground focus:border-emerald-500 focus:outline-none disabled:opacity-50 font-mono"
        >
          {models.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </select>
        {loading && (
          <span className="absolute right-8 top-2.5 text-[10px] text-muted-foreground font-mono animate-pulse">
            syncing...
          </span>
        )}
      </div>
    </div>
  );
}
