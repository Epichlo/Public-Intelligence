import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const authHeader = request.headers.get("authorization");

    const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const upstreamUrl = `${schedulerUrl}/v1/chat/completions`;

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    if (authHeader) {
      headers["Authorization"] = authHeader;
    } else if (process.env.SCHEDULER_NETWORK_AUTH_TOKEN) {
      headers["Authorization"] = `Bearer ${process.env.SCHEDULER_NETWORK_AUTH_TOKEN}`;
    }

    const upstreamRes = await fetch(upstreamUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const contentType = upstreamRes.headers.get("content-type") ?? "";

    if (contentType.includes("text/event-stream") && upstreamRes.body) {
      return new Response(upstreamRes.body, {
        status: upstreamRes.status,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
        },
      });
    }

    if (!upstreamRes.ok) {
      const errorText = await upstreamRes.text();
      let errorData: unknown;
      try {
        errorData = JSON.parse(errorText);
      } catch {
        errorData = { detail: errorText || "Upstream request failed" };
      }
      return NextResponse.json(errorData, { status: upstreamRes.status });
    }

    const data = await upstreamRes.json();
    return NextResponse.json(data, { status: upstreamRes.status });
  } catch (error: unknown) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Chat completion proxy error" },
      { status: 502 }
    );
  }
}
