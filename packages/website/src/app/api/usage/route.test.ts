/**
 * The usage proxy must scope to the requested node and never leak the credential.
 *
 * ROADMAP 3.4/4.1. `node` arrives from the query string, so it reaches a URL path
 * segment -- the encoding test below is the one that matters.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

function mockFetch(status = 200, body: unknown = { records: [] }) {
  const spy = vi.fn(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      })
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

const get = (query = "") => new Request(`http://localhost/api/usage${query}`);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  delete process.env.SCHEDULER_URL;
  delete process.env.SCHEDULER_NETWORK_AUTH_TOKEN;
});

describe("GET /api/usage", () => {
  it("asks for the fleet tail when no node is named", async () => {
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET(get());

    expect(spy.mock.calls[0][0]).toBe("http://scheduler.test/usage");
  });

  it("asks for one node's usage when named", async () => {
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET(get("?node=node-1"));

    expect(spy.mock.calls[0][0]).toBe("http://scheduler.test/nodes/node-1/usage");
  });

  it("encodes the node id so it cannot escape its path segment", async () => {
    // `node=../../v1/models` would otherwise traverse to a different endpoint, with
    // the fleet credential attached.
    process.env.SCHEDULER_URL = "http://scheduler.test";
    const spy = mockFetch();

    const { GET } = await import("./route");
    await GET(get("?node=" + encodeURIComponent("../../v1/models")));

    const url = spy.mock.calls[0][0] as string;
    expect(url).toBe("http://scheduler.test/nodes/..%2F..%2Fv1%2Fmodels/usage");
    expect(url).not.toContain("/v1/models");
  });

  it("does not leak the credential to the browser", async () => {
    process.env.SCHEDULER_NETWORK_AUTH_TOKEN = "fleet-secret";
    mockFetch();

    const { GET } = await import("./route");
    const response = await GET(get());

    expect(await response.text()).not.toContain("fleet-secret");
    expect(JSON.stringify([...response.headers])).not.toContain("fleet-secret");
  });

  it("passes an upstream 401 through rather than reporting empty usage", async () => {
    mockFetch(401, { detail: "Unauthorized" });

    const { GET } = await import("./route");
    expect((await GET(get())).status).toBe(401);
  });
});
