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

    // Never synthesise credentials. A request that arrives without an
    // Authorization header is unauthenticated and must be rejected here rather
    // than forwarded under a fallback identity.
    //
    // The fallback used to read SCHEDULER_NETWORK_AUTH_TOKEN, which is the FLEET
    // SHARED SECRET -- the value of the `X-Network-Auth-Token` header used by node
    // registration, the read surface and credential issuance. The gateway wants an
    // RS256 JWT here, so that branch could never have authenticated anything, and
    // while failing it put a fleet-wide credential into an Authorization header on
    // every unauthenticated request. Two credentials with two trust levels had been
    // given one name. SCHEDULER_PLAYGROUND_JWT is what it was always describing.
    //
    // The caller's own header wins, so a deployment with a fallback configured does
    // not silently run every request as the operator -- which would collapse
    // per-tenant metering and rate limiting onto one identity.
    if (authHeader) {
      headers["Authorization"] = authHeader;
    } else if (process.env.SCHEDULER_PLAYGROUND_JWT) {
      headers["Authorization"] = `Bearer ${process.env.SCHEDULER_PLAYGROUND_JWT}`;
    } else {
      return NextResponse.json(
        {
          detail:
            "Missing Authorization header. Supply a Bearer RS256 JWT in the " +
            "playground's token field, or configure SCHEDULER_PLAYGROUND_JWT with " +
            "a token from POST /v1/credentials.",
        },
        { status: 401 }
      );
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
