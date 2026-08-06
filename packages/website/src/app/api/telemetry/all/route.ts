import { NextResponse } from "next/server";

export async function GET() {
  try {
    const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const upstreamUrl = `${schedulerUrl}/nodes/telemetry`;

    // `/nodes/telemetry` requires the network token as of ROADMAP 2.6 -- it returns
    // live decrypted metrics for every node, and answered anyone who asked. This
    // proxy is server-side, so the token never reaches the browser. `api/status`
    // already did this; this route is the one that never got it.
    // See specs/authenticate-the-read-surface.md.
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
      { detail: error instanceof Error ? error.message : "All telemetry fetch error" },
      { status: 502 }
    );
  }
}
