import { NextResponse } from "next/server";

/**
 * Deadline for the upstream connection to answer with response headers.
 *
 * The same 5s every other proxy route here uses. It bounds the connection
 * attempt only -- see below for why it must not survive into the stream.
 */
const CONNECT_TIMEOUT_MS = 5000;

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

    // This was the only proxy fetch here with no deadline at all: a Scheduler that
    // accepted the connection and never answered held the playground request open
    // indefinitely. A plain `AbortSignal.timeout(5000)` would fix the hang but fire
    // at 5s whether or not tokens are flowing, killing any completion that outlives
    // the deadline -- so a manual controller arms a timer for the connection attempt
    // and disarms it the moment headers arrive. From then on the stream's lifetime
    // belongs to the visitor, not the clock.
    //
    // The same controller also carries the browser's disconnect: without this
    // wiring, a visitor who closed the tab left the upstream request (and the
    // inference behind it) running server-side with nobody reading the answer.
    const upstreamController = new AbortController();
    const connectTimer = setTimeout(
      () =>
        upstreamController.abort(
          new Error(`Scheduler connection timed out after ${CONNECT_TIMEOUT_MS}ms`)
        ),
      CONNECT_TIMEOUT_MS
    );
    if (request.signal.aborted) {
      upstreamController.abort();
    } else {
      request.signal.addEventListener("abort", () => upstreamController.abort(), { once: true });
    }

    let upstreamRes: Response;
    try {
      upstreamRes = await fetch(upstreamUrl, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        cache: "no-store",
        signal: upstreamController.signal,
      });
    } finally {
      // Disarm whether the fetch resolved, rejected, or timed out -- an orphaned
      // timer would abort a stream that had every right to keep flowing.
      clearTimeout(connectTimer);
    }

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
