/**
 * The models proxy must forward the network credential like its siblings.
 *
 * `/v1/models` sits behind the same Scheduler token as everything else, but this
 * route forwarded no auth header at all -- so whenever SCHEDULER_NETWORK_AUTH_TOKEN
 * was configured, every other dashboard surface authenticated while this one 401'd,
 * and model-selector.tsx quietly papered over that with a hardcoded guess list.
 * The selector could only ever show real models on an unauthenticated Scheduler,
 * which is exactly the deployment where guessing is harmless anyway.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const UPSTREAM_BODY = { object: "list", data: [{ id: "llama3" }] };

function mockFetch(status = 200, body: unknown = UPSTREAM_BODY) {
  // Typed with the arguments fetch actually receives; see usage/route.test.ts for
  // why the inferred zero-length tuple shape is a trap.
  const spy = vi.fn(
    async (_url: string, _init?: RequestInit) =>
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
  delete process.env.SCHEDULER_URL;
  delete process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
});

describe("GET /api/models", () => {
  it("asks the gateway's /v1/models endpoint", async () => {
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET();

    expect(spy.mock.calls[0][0]).toBe("http://scheduler.test/v1/models");
  });

  it("forwards the network token upstream", async () => {
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "s3cret-token";
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET();

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-Network-Auth-Token"]).toBe("s3cret-token");
  });

  it("sends no auth header when none is configured", async () => {
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET();

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    // An empty string would be sent as a header and read as a wrong credential.
    expect(init.headers).not.toHaveProperty("X-Network-Auth-Token");
  });

  it("does not leak the credential to the browser", async () => {
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "fleet-secret";
    mockFetch();

    const { GET } = await import("./route");
    const response = await GET();

    expect(await response.text()).not.toContain("fleet-secret");
  });

  it("passes an upstream failure through instead of masking it as success", async () => {
    // This is the defect's visible symptom: with a token configured the upstream
    // answered 401 and this passthrough is what model-selector.tsx swallowed.
    mockFetch(401, { detail: "Unauthorized" });

    const { GET } = await import("./route");
    expect((await GET()).status).toBe(401);
  });
});
