/**
 * The site shipped no security headers at all: `next.config.ts` was the empty
 * scaffold, so no CSP, nothing telling a browser to refuse sniffed content types,
 * and nothing preventing the dashboard being framed elsewhere.
 *
 * These assertions pin the header set itself rather than trusting prose: a future
 * dependency that starts loading something the policy does not name fails here,
 * visibly, instead of failing silently in a browser console nobody is watching.
 */
import { describe, expect, it } from "vitest";

import nextConfig from "../next.config";

interface HeaderEntry {
  key: string;
  value: string;
}

/** Next types headers() as possibly async; this policy must stay synchronous. */
function headerSources(): { source: string; headers: HeaderEntry[] }[] {
  const sources = nextConfig.headers?.();
  if (sources instanceof Promise) throw new Error("headers() must remain synchronous");
  return sources ?? [];
}

function header(key: string): HeaderEntry {
  const entry = headerSources()
    .flatMap((source) => source.headers as HeaderEntry[])
    .find((header) => header.key === key);
  if (!entry) throw new Error(`expected a ${key} header to be configured`);
  return entry;
}

/** One directive's value out of the CSP string, for targeted assertions. */
function cspDirective(directive: string): string[] {
  const policy = header("Content-Security-Policy").value;
  const entry = policy.split("; ").find((part) => part.startsWith(`${directive} `));
  if (!entry) throw new Error(`expected CSP to contain "${directive}"`);
  return entry.split(" ").slice(1);
}

describe("security headers", () => {
  it("applies one header set to every route", () => {
    const sources = headerSources();
    expect(sources).toHaveLength(1);
    expect(sources[0].source).toBe("/:path*");
  });

  it("does not advertise Next.js via X-Powered-By", () => {
    expect(nextConfig.poweredByHeader).toBe(false);
  });

  it("refuses sniffed content types", () => {
    expect(header("X-Content-Type-Options").value).toBe("nosniff");
  });

  it("forbids framing outright", () => {
    expect(header("X-Frame-Options").value).toBe("DENY");
  });

  it("keeps referrers coarse on outbound links", () => {
    // The pages link out to github.com and x.com; full URLs would leak which page
    // sent the visitor there.
    expect(header("Referrer-Policy").value).toBe("strict-origin-when-cross-origin");
  });

  describe("content security policy", () => {
    it("defaults everything else to self", () => {
      expect(cspDirective("default-src")).toEqual(["'self'"]);
    });

    it("allows only this site and the Twitter widget to run script", () => {
      // 'unsafe-inline' is Next's hydration bootstrap, which cannot take a nonce
      // without per-request middleware; documented in next.config.ts, not hidden.
      expect(cspDirective("script-src")).toEqual([
        "'self'",
        "'unsafe-inline'",
        "https://platform.twitter.com",
      ]);
    });

    it("allows only the Twitter widget to be framed", () => {
      expect(cspDirective("frame-src")).toEqual(["https://platform.twitter.com"]);
    });

    it("loads styles, images and fonts from this site only", () => {
      // Inline styles are React's style attributes -- telemetry-gauge.tsx sizes its
      // utilisation bars that way.
      expect(cspDirective("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
      expect(cspDirective("img-src")).toEqual(["'self'", "data:"]);
      expect(cspDirective("font-src")).toEqual(["'self'"]);
    });

    it("keeps browser-initiated connections same-origin", () => {
      // Every fetch in the app targets a same-origin /api proxy route.
      expect(cspDirective("connect-src")).toEqual(["'self'"]);
    });

    it("closes the legacy embed surfaces", () => {
      expect(cspDirective("object-src")).toEqual(["'none'"]);
      expect(cspDirective("base-uri")).toEqual(["'self'"]);
      expect(cspDirective("form-action")).toEqual(["'self'"]);
      expect(cspDirective("frame-ancestors")).toEqual(["'none'"]);
    });
  });
});
