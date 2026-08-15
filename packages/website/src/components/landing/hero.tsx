"use client";

import { useEffect, useState } from "react";

const NODES = [
  { id: "node-workstation", host: "127.0.0.1:8080", model: "llama3.2", state: "ONLINE" },
  { id: "node-lab-box", host: "10.0.0.7:8080", model: "qwen2.5", state: "ONLINE" },
  { id: "node-laptop", host: "10.0.0.9:8080", model: "mistral", state: "IDLE" },
];

function useClock(): string {
  const [now, setNow] = useState<string>("--:--:--");
  useEffect(() => {
    const tick = () =>
      setNow(
        new Date().toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      );
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export function Hero() {
  const clock = useClock();

  return (
    <section className="relative overflow-hidden border-b hairline bg-iron text-lead">
      {/* architectural grid */}
      <div className="pointer-events-none absolute inset-0 grid-blueprint opacity-70" aria-hidden />
      {/* amber horizon line */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-amber/50"
        aria-hidden
      />

      <div className="relative mx-auto grid max-w-6xl gap-16 px-6 py-24 md:py-32 lg:grid-cols-[1.15fr_0.85fr] lg:gap-10">
        {/* Left: manifesto headline */}
        <div className="flex flex-col justify-center">
          <p className="font-terminal text-[0.7rem] uppercase tracking-[0.32em] text-amber">
            Public Intelligence
            <span className="mx-2 text-concrete">/</span>
            <span className="text-concrete">v1.0.0</span>
          </p>

          <h1 className="mt-8 font-editorial text-5xl font-semibold uppercase leading-[0.95] tracking-[0.01em] sm:text-6xl md:text-7xl">
            The machine
            <br />
            stays in
            <br />
            <span className="text-amber">the room.</span>
          </h1>

          <p className="mt-8 max-w-md text-base leading-relaxed text-concrete">
            Self-hosted, OpenAI-compatible inference across hardware you own. One
            authenticated endpoint over your own machines &mdash; and the prompt never
            leaves your trust boundary.
          </p>

          <div className="mt-10 flex flex-wrap items-center gap-3">
            <a
              href="#tenets"
              className="group inline-flex h-11 items-center gap-3 border border-lead/80 px-6 font-terminal text-xs uppercase tracking-[0.18em] text-lead transition-colors hover:bg-lead hover:text-iron"
            >
              Read the tenets
              <span aria-hidden className="transition-transform group-hover:translate-x-1">
                &rarr;
              </span>
            </a>
            <a
              href="https://github.com/Epichlo/Public-Intelligence"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-11 items-center gap-3 border hairline px-6 font-terminal text-xs uppercase tracking-[0.18em] text-concrete transition-colors hover:border-lead/60 hover:text-lead"
            >
              Source
            </a>
          </div>
        </div>

        {/* Right: trust-boundary telemetry HUD */}
        <div className="flex items-center">
          <div className="relative w-full">
            <span className="absolute -top-2 left-4 z-10 bg-iron px-2 font-terminal text-[0.62rem] uppercase tracking-[0.24em] text-amber">
              Trust Boundary
            </span>
            <div className="border border-dashed hairline-amber bg-slate/60 p-5 backdrop-blur-sm">
              <div className="flex items-center justify-between border-b hairline pb-3 font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
                <span>Local Mesh</span>
                <span className="flex items-center gap-2">
                  <span className="telemetry-blink inline-block h-1.5 w-1.5 bg-amber" aria-hidden />
                  no cloud egress
                </span>
              </div>

              <ul className="divide-y divide-lead/5 font-terminal text-xs">
                {NODES.map((node) => (
                  <li key={node.id} className="flex items-center gap-3 py-3">
                    <span
                      className={`inline-block h-1.5 w-1.5 shrink-0 ${
                        node.state === "ONLINE" ? "bg-amber" : "bg-concrete"
                      }`}
                      aria-hidden
                    />
                    <span className="w-32 shrink-0 truncate text-lead">{node.id}</span>
                    <span className="hidden flex-1 truncate text-concrete sm:inline">
                      {node.host}
                    </span>
                    <span className="ml-auto text-concrete">{node.model}</span>
                    <span
                      className={`w-12 text-right ${
                        node.state === "ONLINE" ? "text-amber" : "text-concrete"
                      }`}
                    >
                      {node.state}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="mt-1 flex items-center justify-between border-t hairline pt-3 font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
                <span>[{clock}] mesh listening</span>
                <span className="text-concrete/70">illustrative</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
