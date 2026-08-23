/**
 * Every /api route is a credentialed proxy.
 *
 * The dashboard's API routes attach server-side secrets — SCHEDULER_NETWORK_AUTH_TOKEN,
 * SCHEDULER_PLAYGROUND_JWT, NODE_AUTH_TOKEN — to whatever they forward, and none of
 * them authenticated the visitor: `next start` binds all interfaces, so any host on
 * the network could read fleet telemetry, relay arbitrary bodies into `/infer`, or
 * start and stop the local runtime. The routes themselves cannot tell an operator
 * from a stranger; the boundary has to sit in front of all of them, which is what
 * this middleware is.
 *
 * The gate is loopback-only because the dashboard is documented as a localhost
 * control plane (`packages/website/README.md`: "the dashboard and playground need a
 * Scheduler"; every default upstream is localhost). Both sides of the request are
 * checked:
 *
 * - **Host** catches DNS rebinding. An attacker page at `evil.example` that resolves
 *   to 127.0.0.1 can make a victim's browser send perfectly valid requests to this
 *   server; only the Host header ("evil.example:3000") gives the request away.
 * - **Origin/Referer** catch cross-site requests aimed at a real loopback Host. A
 *   page anywhere on the internet can `fetch("http://localhost:3000/api/node/control")`;
 *   the Host checks out but the Origin does not.
 *
 * X-Forwarded-* headers are deliberately ignored: on a directly reachable port they
 * are attacker-controlled, so honouring them would let a remote caller widen its own
 * access by asserting a forwarded loopback host.
 */
import { afterEach, describe, expect, it } from "vitest";

import type { NextRequest } from "next/server";

function apiRequest(headers: Record<string, string> = {}): NextRequest {
  return new Request("http://localhost:3000/api/telemetry/all", { headers }) as NextRequest;
}

async function callMiddleware(request: Request) {
  const { middleware } = await import("./middleware");
  return middleware(request as NextRequest);
}

const LOOPBACK_HOST = { host: "localhost:3000" };

afterEach(() => {
  delete process.env.DASHBOARD_ALLOW_REMOTE;
});

describe("loopback gate for /api routes", () => {
  it.each([
    ["localhost:3000"],
    ["127.0.0.1:3000"],
    ["[::1]:3000"],
    ["localhost"],
    ["127.0.0.1"],
  ])("allows a loopback Host (%s)", async (host) => {
    const response = await callMiddleware(apiRequest({ host }));
    expect(response.status).toBe(200);
  });

  it.each([
    ["dashboard.example.com:3000"],
    ["192.168.1.50:3000"],
    // The DNS-rebinding shape: a non-loopback name, however it resolves.
    ["evil.example:3000"],
  ])("denies a remote Host (%s) with 403", async (host) => {
    const response = await callMiddleware(apiRequest({ host }));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ detail: expect.stringContaining("loopback") });
  });

  it("denies a request with no Host header rather than guessing", async () => {
    const request = new Request("http://localhost:3000/api/telemetry/all") as NextRequest;
    Object.defineProperty(request, "headers", {
      value: new Headers(),
      configurable: true,
    });
    const response = await callMiddleware(request);
    expect(response.status).toBe(403);
  });

  it("denies a cross-site Origin even when the Host is loopback", async () => {
    // A hostile page's fetch to http://localhost:3000 arrives with a legitimate
    // loopback Host; only the Origin betrays it.
    const response = await callMiddleware(
      apiRequest({ ...LOOPBACK_HOST, origin: "https://evil.example" })
    );
    expect(response.status).toBe(403);
  });

  it("allows a same-origin loopback Origin alongside a loopback Host", async () => {
    const response = await callMiddleware(
      apiRequest({ ...LOOPBACK_HOST, origin: "http://localhost:3000" })
    );
    expect(response.status).toBe(200);
  });

  it("denies a remote Referer even when the Host is loopback", async () => {
    const response = await callMiddleware(
      apiRequest({ ...LOOPBACK_HOST, referer: "https://evil.example/dashboard" })
    );
    expect(response.status).toBe(403);
  });

  it("denies an unparseable Origin instead of failing open", async () => {
    const response = await callMiddleware(apiRequest({ ...LOOPBACK_HOST, origin: "::not a url::" }));
    expect(response.status).toBe(403);
  });

  describe("DASHBOARD_ALLOW_REMOTE=1 escape hatch", () => {
    it("lets a remote Host through when set", async () => {
      process.env.DASHBOARD_ALLOW_REMOTE = "1";
      const response = await callMiddleware(apiRequest({ host: "dashboard.example.com:3000" }));
      expect(response.status).toBe(200);
    });

    it("does not treat values other than '1' as consent", async () => {
      process.env.DASHBOARD_ALLOW_REMOTE = "yes";
      const response = await callMiddleware(apiRequest({ host: "dashboard.example.com:3000" }));
      expect(response.status).toBe(403);
    });
  });

  it("gates every /api route and nothing else", async () => {
    const { config } = await import("./middleware");
    expect(config.matcher).toEqual(["/api/:path*"]);
  });
});
