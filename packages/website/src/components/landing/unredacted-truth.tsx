"use client";

import { useState } from "react";

const TRUE_ITEMS = [
  "A node registers and heartbeats over an authenticated Zenoh mesh.",
  "It advertises the models Ollama actually has — measured hardware, never a hardcoded guess.",
  "The Scheduler matchmakes and dispatches over the mesh; the OpenAI gateway sits behind RS256 JWT auth.",
  "A node on a second physical machine has served a real request over the mesh — on a LAN.",
  "Registry, credentials, credit ledger and invites persist across a restart (SQLite).",
  "Usage metering never records prompt or completion text — asserted by a test that fails if it could.",
];

const UNPROVEN_ITEMS = [
  "No request has been served across a real NAT boundary. This is the single most load-bearing unproven claim.",
  "Split / distributed inference is not implemented — the gateway answers 501, it does not fabricate a completion.",
  "Credits are an accounting unit, not a currency. There is no payout path, by decision.",
  "No independent human review has happened yet — the one question that cannot be closed from inside (D7).",
  "There is no content filtering, no meaningful rate limiting, and no backups.",
];

type Mode = "true" | "unproven";

export function UnredactedTruth() {
  const [mode, setMode] = useState<Mode>("true");
  const isTrue = mode === "true";
  const items = isTrue ? TRUE_ITEMS : UNPROVEN_ITEMS;

  return (
    <section className="border-b hairline bg-slate text-lead">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <div className="flex flex-col gap-4 border-b hairline pb-8 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="font-terminal text-[0.7rem] uppercase tracking-[0.3em] text-amber">
              02 &nbsp;/&nbsp; The Unredacted Truth
            </p>
            <h2 className="mt-4 max-w-xl font-editorial text-4xl font-medium leading-tight sm:text-5xl">
              What is true. And what is not true yet.
            </h2>
          </div>
          <p className="max-w-xs font-terminal text-xs leading-relaxed text-concrete">
            Landing-page copy is a claim. This project audits itself for the failure of
            describing intentions as achievements — so both columns are on the record.
          </p>
        </div>

        {/* toggle */}
        <div className="mt-10 inline-flex border hairline font-terminal text-xs uppercase tracking-[0.18em]">
          <button
            type="button"
            onClick={() => setMode("true")}
            aria-pressed={isTrue}
            className={`px-5 py-3 transition-colors ${
              isTrue ? "bg-lead text-iron" : "text-concrete hover:text-lead"
            }`}
          >
            What is true
          </button>
          <button
            type="button"
            onClick={() => setMode("unproven")}
            aria-pressed={!isTrue}
            className={`border-l hairline px-5 py-3 transition-colors ${
              !isTrue ? "bg-amber text-iron" : "text-concrete hover:text-lead"
            }`}
          >
            Not true yet
          </button>
        </div>

        <div className="relative mt-8 grid gap-8 lg:grid-cols-[1fr_auto]">
          <ul className="divide-y divide-lead/10 border-y hairline">
            {items.map((item, index) => (
              <li key={item} className="flex gap-5 py-5">
                <span
                  className={`mt-0.5 font-terminal text-xs tabular-nums ${
                    isTrue ? "text-lead" : "text-amber"
                  }`}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span
                  className={`mt-2 h-px w-6 shrink-0 ${isTrue ? "bg-lead/40" : "bg-amber/60"}`}
                  aria-hidden
                />
                <p className="text-sm leading-relaxed text-lead/90">{item}</p>
              </li>
            ))}
          </ul>

          {/* stamped indicator */}
          <div className="flex items-start justify-center lg:w-56">
            <div
              className={`mt-2 -rotate-6 select-none border-2 px-5 py-3 text-center font-terminal ${
                isTrue ? "border-lead/70 text-lead" : "border-amber text-amber"
              }`}
            >
              <div className="text-lg font-bold uppercase tracking-[0.2em]">
                {isTrue ? "Verified" : "Not Yet"}
              </div>
              <div className="mt-1 text-[0.6rem] uppercase tracking-[0.24em] opacity-80">
                {isTrue ? "gate · passing" : "unproven · on record"}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
