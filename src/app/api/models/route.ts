import { NextResponse } from "next/server";

export async function GET() {
  try {
    const schedulerUrl = (process.env.SCHEDULER_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const upstreamUrl = `${schedulerUrl}/v1/models`;

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
      { detail: error instanceof Error ? error.message : "Models fetch error", data: [] },
      { status: 502 }
    );
  }
}
