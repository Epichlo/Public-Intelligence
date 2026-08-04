import { NextResponse } from "next/server";

import { nodeAuthHint, nodeHeaders, nodeUrl } from "@/lib/node-api";

export async function GET() {
  try {
    const upstreamUrl = `${nodeUrl()}/api/v1/sandbox/logs/stream`;

    const upstreamRes = await fetch(upstreamUrl, {
      headers: nodeHeaders(),
      cache: "no-store",
    });

    if (!upstreamRes.ok || !upstreamRes.body) {
      const hint = nodeAuthHint(upstreamRes.status);
      const errText = hint ?? (await upstreamRes.text());
      return NextResponse.json(
        { detail: errText || "Sandbox log stream failed" },
        { status: upstreamRes.status }
      );
    }

    return new Response(upstreamRes.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error: unknown) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Sandbox log stream proxy error" },
      { status: 502 }
    );
  }
}
