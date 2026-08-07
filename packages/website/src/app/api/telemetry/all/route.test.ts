/**
 * The telemetry proxy must forward the network credential and never leak it.
 *
 * `/nodes/telemetry` returns live decrypted metrics for the entire fleet and became
 * authenticated in ROADMAP 2.6. This proxy is the only caller. Until now the change
 * was verified by reading it: `packages/website` had no test runner at all, so
 * 4,270 lines were checked by nothing.
 *
 * See specs/the-gate-sees-the-website.md.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const UPSTREAM_BODY = { "node-1": { cpu_utilization: 12 } };

function mockFetch(status = 200, body: unknown = UPSTREAM_BODY) {
  const spy = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  delete process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
  delete process.env.SCHEDULER_URL;
});

describe("GET /api/telemetry/all", () => {
  it("forwards the network token upstream", async () => {
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "s3cret-token";
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET();

    expect(spy).toHaveBeenCalledOnce();
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://scheduler.test/nodes/telemetry");
    expect((init.headers as Record<string, string>)["X-Network-Auth-Token"]).toBe("s3cret-token");
  });

  it("does not leak the token to the browser", async () => {
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "s3cret-token";
    mockFetch();

    const { GET } = await import("./route");
    const response = await GET();
    const text = await response.text();

    // The whole point of proxying server-side: the credential stays on the server.
    expect(text).not.toContain("s3cret-token");
    expect(JSON.stringify([...response.headers])).not.toContain("s3cret-token");
  });

  it("sends no auth header when none is configured", async () => {
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET();

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    // An empty string would be sent as a header and read as a wrong credential.
    expect(init.headers).not.toHaveProperty("X-Network-Auth-Token");
  });

  it("passes an upstream failure through instead of masking it as success", async () => {
    mockFetch(401, { detail: "Unauthorized" });

    const { GET } = await import("./route");
    const response = await GET();

    expect(response.status).toBe(401);
  });
});
