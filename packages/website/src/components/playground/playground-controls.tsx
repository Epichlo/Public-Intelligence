"use client";

interface PlaygroundControlsProps {
  temperature: number;
  setTemperature: (v: number) => void;
  topP: number;
  setTopP: (v: number) => void;
  maxTokens: number;
  setMaxTokens: (v: number) => void;
  systemPrompt: string;
  setSystemPrompt: (v: string) => void;
  jwtToken: string;
  setJwtToken: (v: string) => void;
  disabled?: boolean;
}

export function PlaygroundControls({
  temperature,
  setTemperature,
  topP,
  setTopP,
  maxTokens,
  setMaxTokens,
  systemPrompt,
  setSystemPrompt,
  jwtToken,
  setJwtToken,
  disabled,
}: PlaygroundControlsProps) {
  return (
    <div className="rounded-xl border border-border/40 bg-card p-5 shadow-sm space-y-5">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Inference Parameters & Auth
      </h3>

      {/* System Prompt */}
      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-foreground">
          System Instructions
        </label>
        <textarea
          rows={3}
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          disabled={disabled}
          placeholder="You are a helpful, respectful, and honest assistant..."
          className="w-full rounded-lg border border-border/60 bg-zinc-950 px-3 py-2 text-xs text-foreground placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none disabled:opacity-50 font-mono resize-none"
        />
      </div>

      {/* Temperature Slider */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <label className="font-medium text-foreground">Temperature</label>
          <span className="font-mono text-emerald-400 font-bold">{temperature.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min="0.0"
          max="2.0"
          step="0.05"
          value={temperature}
          onChange={(e) => setTemperature(parseFloat(e.target.value))}
          disabled={disabled}
          className="w-full accent-emerald-400 bg-zinc-900 cursor-pointer disabled:cursor-not-allowed"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
          <span>0.0 (Precise)</span>
          <span>1.0 (Balanced)</span>
          <span>2.0 (Creative)</span>
        </div>
      </div>

      {/* Top_P Slider */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <label className="font-medium text-foreground">Top-P Sampling</label>
          <span className="font-mono text-emerald-400 font-bold">{topP.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min="0.0"
          max="1.0"
          step="0.05"
          value={topP}
          onChange={(e) => setTopP(parseFloat(e.target.value))}
          disabled={disabled}
          className="w-full accent-emerald-400 bg-zinc-900 cursor-pointer disabled:cursor-not-allowed"
        />
      </div>

      {/* Max Tokens Slider */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <label className="font-medium text-foreground">Max Tokens</label>
          <span className="font-mono text-emerald-400 font-bold">{maxTokens}</span>
        </div>
        <input
          type="range"
          min="64"
          max="4096"
          step="64"
          value={maxTokens}
          onChange={(e) => setMaxTokens(parseInt(e.target.value, 10))}
          disabled={disabled}
          className="w-full accent-emerald-400 bg-zinc-900 cursor-pointer disabled:cursor-not-allowed"
        />
      </div>

      {/* JWT Authorization Token Field */}
      <div className="space-y-1.5 pt-2 border-t border-border/20">
        <label className="block text-xs font-medium text-foreground">
          RS256 JWT Auth Token
        </label>
        <input
          type="password"
          value={jwtToken}
          onChange={(e) => setJwtToken(e.target.value)}
          disabled={disabled}
          placeholder="Bearer eyJhbGciOiJSUzI1Ni..."
          className="w-full rounded-lg border border-border/60 bg-zinc-950 px-3 py-2 text-xs text-foreground placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none disabled:opacity-50 font-mono"
        />
        {/*
          This said "Optional custom RS256 Bearer JWT token header for multi-tenant
          gateway authorization" (ROADMAP 3.5). It is not optional -- the gateway has
          required a JWT since long before this, and since ROADMAP C4 an unconfigured
          Scheduler refuses everyone rather than falling back to a default key. Calling
          it optional sent a new user to a 401 with no idea where to get a credential,
          which is exactly the gap 3.5 names.
        */}
        <p className="text-[10px] text-muted-foreground">
          <strong>Required.</strong> The gateway rejects unauthenticated requests. Ask
          the operator of your Scheduler for one — they issue it with{" "}
          <code className="font-mono">POST /v1/credentials</code>, or from a shell with{" "}
          <code className="font-mono">scripts/mint_token.py</code>. It is scoped to a
          tenant and expires; 30 days by default.
        </p>
      </div>
    </div>
  );
}
