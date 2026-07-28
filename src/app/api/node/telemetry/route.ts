import { NextResponse } from "next/server";

export async function GET() {
  try {
    const nodeUrl = (process.env.NODE_URL ?? "http://localhost:8080").replace(/\/$/, "");
    const upstreamUrl = `${nodeUrl}/api/v1/node/telemetry`;

    const response = await fetch(upstreamUrl, {
      cache: "no-store",
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
      {
        node_id: "unknown",
        cpu_utilization: 0,
        ram_used_bytes: 0,
        ram_total_bytes: 0,
        gpu_utilization: 0,
        vram_used_bytes: 0,
        vram_total_bytes: 0,
        wan_connected: false,
        status: "unreachable",
        error: error instanceof Error ? error.message : "Node telemetry proxy error",
      },
      { status: 502 }
    );
  }
}
