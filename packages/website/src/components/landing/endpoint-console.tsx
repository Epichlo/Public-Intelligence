"use client";

import { useEffect, useRef, useState } from "react";

const REQUEST_LINES = [
  "curl http://127.0.0.1:8000/v1/chat/completions \\",
  '  -H "Authorization: Bearer $PI_TOKEN" \\',
  '  -d \'{ "model": "llama3.2",',
  '        "messages": [{ "role": "user",',
  '                       "content": "Where does my prompt go?" }] }\'',
];

const RESPONSE =
  "To a node you own. This request never left your machines — no third party saw it, nothing was logged, and no token was spent. That is the whole product.";

type Status = "idle" | "running" | "done";

export function EndpointConsole() {
  const [output, setOutput] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, []);

  const run = () => {
    if (timer.current !== null) window.clearInterval(timer.current);
    setStatus("running");
    setOutput("");
    let i = 0;
    timer.current = window.setInterval(() => {
      i += 1;
      setOutput(RESPONSE.slice(0, i));
      if (i >= RESPONSE.length) {
        if (timer.current !== null) window.clearInterval(timer.current);
        timer.current = null;
        setStatus("done");
      }
    }, 18);
  };

  return (
    <section className="bg-iron text-lead">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="grid gap-12 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16">
          <div className="flex flex-col justify-center">
            <p className="font-terminal text-[0.7rem] uppercase tracking-[0.3em] text-amber">
              03 &nbsp;/&nbsp; One-Drop Endpoint
            </p>
            <h2 className="mt-4 font-editorial text-4xl font-medium leading-tight sm:text-5xl">
              The same API. None of the egress.
            </h2>
            <p className="mt-6 max-w-md text-sm leading-relaxed text-concrete">
              Anything that already speaks the OpenAI API points here with one line: a
              base URL on your own network. No rewrite, no SDK swap, no cloud in the
              path. Change <span className="font-terminal text-lead">localhost</span> and
              the request runs on a machine you control.
            </p>
            <div className="mt-8 flex items-center gap-3 font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
              <span className="telemetry-blink inline-block h-1.5 w-1.5 bg-amber" aria-hidden />
              no cloud egress &middot; illustrative simulation
            </div>
          </div>

          {/* terminal */}
          <div className="border hairline bg-slate/70">
            <div className="flex items-center justify-between border-b hairline px-4 py-3 font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
              <span>POST /v1/chat/completions</span>
              <span className="text-amber">127.0.0.1:8000</span>
            </div>

            <div className="space-y-4 p-5">
              <pre className="overflow-x-auto font-terminal text-xs leading-relaxed text-lead/80">
                {REQUEST_LINES.join("\n")}
              </pre>

              <button
                type="button"
                onClick={run}
                className="inline-flex h-9 items-center gap-2 border border-amber px-4 font-terminal text-[0.7rem] uppercase tracking-[0.2em] text-amber transition-colors hover:bg-amber hover:text-iron"
              >
                {status === "idle" ? "Run request" : status === "running" ? "Streaming…" : "Run again"}
              </button>

              <div className="min-h-[7rem] border-t hairline pt-4">
                <div className="font-terminal text-[0.62rem] uppercase tracking-[0.2em] text-concrete">
                  assistant
                </div>
                <p className="mt-2 font-terminal text-sm leading-relaxed text-lead">
                  {output}
                  {status === "running" && (
                    <span className="cursor-blink ml-0.5 inline-block h-4 w-2 translate-y-0.5 bg-amber" aria-hidden />
                  )}
                  {status === "idle" && <span className="text-concrete">awaiting run…</span>}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
