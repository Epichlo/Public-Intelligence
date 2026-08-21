"use client";

import { useEffect, useRef, useState } from "react";

import { HOST_NODE_COMMAND, HOST_NODE_PREREQUISITES } from "@/lib/host-command";

type CopyState = "idle" | "copied" | "unavailable";

export function HostANode() {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const copy = async () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    // `navigator.clipboard` is undefined on an insecure origin, which is exactly how
    // this site is served when someone runs it on their own LAN. Saying so beats a
    // button that silently does nothing -- the block is selectable text either way.
    if (!navigator.clipboard) {
      setCopyState("unavailable");
      return;
    }
    try {
      await navigator.clipboard.writeText(HOST_NODE_COMMAND);
      setCopyState("copied");
      timer.current = window.setTimeout(() => setCopyState("idle"), 2000);
    } catch {
      setCopyState("unavailable");
    }
  };

  return (
    <section id="host-a-node" className="border-t hairline bg-iron text-lead">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16">
          <div className="flex flex-col justify-center">
            <p className="font-terminal text-[0.7rem] uppercase tracking-[0.3em] text-amber">
              04 &nbsp;/&nbsp; Host a Node
            </p>
            <h2 className="mt-4 font-editorial text-4xl font-medium leading-tight sm:text-5xl">
              One command. Your machine, your fleet.
            </h2>
            <p className="mt-6 max-w-md text-sm leading-relaxed text-concrete">
              It clones the repository, installs the host agent, and leaves a{" "}
              <span className="font-terminal text-lead">running</span> node. Re-running it
              updates in place. There is no network to join and nothing to sign up for
              &mdash; you point it at a Scheduler you run.
            </p>

            <ul className="mt-8 flex flex-col gap-3">
              {HOST_NODE_PREREQUISITES.map((line) => (
                <li key={line} className="flex gap-3 text-sm leading-relaxed text-concrete">
                  <span className="mt-2 inline-block h-1 w-1 shrink-0 bg-amber" aria-hidden />
                  {line}
                </li>
              ))}
            </ul>
          </div>

          {/* terminal */}
          <div className="border hairline bg-slate/70">
            <div className="flex items-center justify-between border-b hairline px-4 py-3 font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
              <span>scripts/bootstrap.sh</span>
              <span className="text-amber">your shell</span>
            </div>

            <div className="space-y-4 p-5">
              <pre className="overflow-x-auto font-terminal text-xs leading-relaxed text-lead/80">
                {HOST_NODE_COMMAND}
              </pre>

              <div className="flex flex-wrap items-center gap-4">
                <button
                  type="button"
                  onClick={copy}
                  className="inline-flex h-9 items-center gap-2 border border-amber px-4 font-terminal text-[0.7rem] uppercase tracking-[0.2em] text-amber transition-colors hover:bg-amber hover:text-iron"
                >
                  {copyState === "copied" ? "Copied" : "Copy command"}
                </button>
                <span
                  aria-live="polite"
                  className="font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete"
                >
                  {copyState === "unavailable" && "clipboard blocked — select it manually"}
                </span>
              </div>

              <p className="border-t hairline pt-4 font-terminal text-[0.62rem] leading-relaxed tracking-[0.12em] text-concrete">
                Everything after{" "}
                <span className="text-lead">bash -s --</span> is forwarded to{" "}
                <span className="text-lead">install.sh</span>. Prefer to read what runs
                first? Clone the repository and run{" "}
                <span className="text-lead">./install.sh --start</span> yourself &mdash;
                the two paths are identical.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
