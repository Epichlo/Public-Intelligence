import { NextResponse } from "next/server";

export async function GET() {
  try {
    const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const upstreamUrl = `${schedulerUrl}/v1/models`;

    // `/v1/models` sits behind the same Scheduler credential as every other read
    // this dashboard proxies, but this route forwarded no auth header -- the only
    // one that didn't. With SCHEDULER_NETWORK_AUTH_TOKEN configured, telemetry,
    // usage and status all authenticated while models 401'd, and
    // model-selector.tsx swallowed the rejection and showed hardcoded guesses
    // instead of the fleet's real catalogue.
    const token = process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
    const headers: Record<string, string> = {};
    if (token) headers["X-Network-Auth-Token"] = token;

    const response = await fetch(upstreamUrl, {
      cache: "no-store",
      headers,
      signal: AbortSignal.timeout(5000),
    });

    if (!response.ok) {
      const errText = await response.text();
      return NextResponse.json({ detail: errText }, { status: response.status });
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error: unknown) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Models fetch error", data: [] },
      { status: 502 }
    );
  }
}
