import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const nodeUrl = (process.env.NODE_URL ?? "http://localhost:8080").replace(/\/$/, "");
    const upstreamUrl = `${nodeUrl}/api/v1/node/control`;

    const response = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error: unknown) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Node control proxy error" },
      { status: 502 }
    );
  }
}
