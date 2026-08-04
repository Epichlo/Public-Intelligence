import { NextResponse } from "next/server";

const schedulerUrl = () => (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
const nodeUrl = () => process.env.NODE_URL?.replace(/\/$/, "") ?? null;

async function fetchJson(url: string, headers: HeadersInit = {}) {
  const response = await fetch(url, {
    headers,
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  return response.json();
}

export async function GET() {
  const token = process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
  const headers: Record<string, string> = {};
  if (token) headers["X-Network-Auth-Token"] = token;

  const [scheduler, node] = await Promise.all([
    fetchJson(`${schedulerUrl()}/status`, headers).catch((error: unknown) => ({
      status: "unreachable",
      error: error instanceof Error ? error.message : "Scheduler unavailable",
    })),
    nodeUrl()
      ? fetchJson(`${nodeUrl()}/health/ready`).catch((error: unknown) => ({
          status: "unreachable",
          error: error instanceof Error ? error.message : "Node unavailable",
        }))
      : Promise.resolve({ status: "not_configured" }),
  ]);

  return NextResponse.json({
    checked_at: new Date().toISOString(),
    scheduler,
    node,
    node_configured: Boolean(nodeUrl()),
  });
}

export async function POST(request: Request) {
  const token = process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["X-Network-Auth-Token"] = token;

  try {
    const payload = await request.json();
    const response = await fetch(`${schedulerUrl()}/infer`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(60000),
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch (error: unknown) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Inference request failed" },
      { status: 502 },
    );
  }
}
