/**
 * The chat proxy must forward the caller's credential and never invent one.
 *
 * ROADMAP 4.1. This route is the one a user actually exercises -- the playground
 * posts to it -- and it was covered by nothing.
 *
 * It also had a real defect, found by writing these. The fallback branch sent
 * `SCHEDULER_NETWORK_AUTH_TOKEN` as `Authorization: Bearer <it>`. That variable is
 * the **fleet shared secret**: the value of the `X-Network-Auth-Token` header used by
 * node registration, the read surface and credential issuance. The gateway expects an
 * **RS256 JWT** there and would reject it, so the branch could never have worked --
 * and while failing it put the fleet secret into an Authorization header on every
 * unauthenticated playground request. Two different credentials with two different
 * trust levels had been given one name.
 *
 * The fix is a separate `SCHEDULER_PLAYGROUND_JWT`, which is what the variable was
 * always describing.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const UPSTREAM_BODY = { id: "chatcmpl-1", choices: [] };

function mockFetch(status = 200, body: unknown = UPSTREAM_BODY, contentType = "application/json") {
  const spy = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": contentType },
      })
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

function post(body: unknown = { model: "llama3", messages: [] }, headers: HeadersInit = {}) {
  return new Request("http://localhost/api/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  delete process.env.SCHEDULER_URL;
  delete process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
  delete process.env.SCHEDULER_PLAYGROUND_JWT;
});

describe("POST /api/chat/completions", () => {
  it("forwards the caller's Authorization header unchanged", async () => {
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { POST } = await import("./route");
    await POST(post({ model: "llama3", messages: [] }, { authorization: "Bearer caller-jwt" }));

    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://scheduler.test/v1/chat/completions");
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer caller-jwt");
  });

  it("rejects an unauthenticated request instead of synthesising a credential", async () => {
    const spy = mockFetch();

    const { POST } = await import("./route");
    const response = await POST(post());

    expect(response.status).toBe(401);
    // The important half: nothing was sent upstream under a fallback identity.
    expect(spy).not.toHaveBeenCalled();
  });

  it("never sends the fleet shared secret as a Bearer token", async () => {
    // The defect this file was written to find. SCHEDULER_NETWORK_AUTH_TOKEN is the
    // X-Network-Auth-Token value -- a shared secret, not a JWT. The gateway would
    // reject it, and sending it here puts a fleet-wide credential in an
    // Authorization header for no benefit.
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "fleet-shared-secret";
    const spy = mockFetch();

    const { POST } = await import("./route");
    const response = await POST(post());

    expect(response.status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
    expect(JSON.stringify(spy.mock.calls)).not.toContain("fleet-shared-secret");
  });

  it("uses SCHEDULER_PLAYGROUND_JWT as the server-side fallback when configured", async () => {
    process.env.SCHEDULER_PLAYGROUND_JWT = "a-real-rs256-jwt";
    const spy = mockFetch();

    const { POST } = await import("./route");
    await POST(post());

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Authorization"]).toBe(
      "Bearer a-real-rs256-jwt"
    );
  });

  it("prefers the caller's credential over the server-side fallback", async () => {
    // Otherwise a deployment with a fallback configured would silently run every
    // request as the operator, and per-tenant metering and rate limiting would all
    // attribute to one identity.
    process.env.SCHEDULER_PLAYGROUND_JWT = "operator-jwt";
    const spy = mockFetch();

    const { POST } = await import("./route");
    await POST(post({ model: "llama3", messages: [] }, { authorization: "Bearer caller-jwt" }));

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer caller-jwt");
  });

  it("passes an upstream failure through instead of masking it as success", async () => {
    mockFetch(429, { detail: "Rate limit exceeded" });

    const { POST } = await import("./route");
    const response = await POST(post({ model: "llama3", messages: [] }, { authorization: "Bearer x" }));

    expect(response.status).toBe(429);
  });

  it("streams an SSE response through rather than buffering it", async () => {
    // The playground reads tokens as they arrive. Buffering would work in a test and
    // destroy the only user-visible property of streaming.
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("data: {}\n\n"));
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(stream, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          })
      )
    );

    const { POST } = await import("./route");
    const response = await POST(post({ model: "llama3", messages: [] }, { authorization: "Bearer x" }));

    expect(response.headers.get("content-type")).toContain("text/event-stream");
    expect(await response.text()).toContain("data:");
  });
});
