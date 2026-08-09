import { NextResponse } from "next/server";

/**
 * Proxy for the Scheduler's usage endpoints (ROADMAP 3.4).
 *
 * Server-side so the fleet credential never reaches the browser, same as
 * `api/telemetry/all` and `api/status`. `/usage` is authenticated because usage
 * records name tenants and nodes.
 *
 * `?node=<id>` asks for one host's own figures; omitting it returns the recent
 * fleet-wide tail.
 */
export async function GET(request: Request) {
  try {
    const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const nodeId = new URL(request.url).searchParams.get("node");
    const upstreamUrl = nodeId
      ? `${schedulerUrl}/nodes/${encodeURIComponent(nodeId)}/usage`
      : `${schedulerUrl}/usage`;

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

    return NextResponse.json(await response.json());
  } catch (error: unknown) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Usage fetch error" },
      { status: 502 }
    );
  }
}
