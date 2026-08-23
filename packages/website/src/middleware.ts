import { NextResponse, type NextRequest } from "next/server";

/**
 * The loopback gate for every `/api` route.
 *
 * Each route under `app/api` is a proxy that attaches a server-side credential to
 * what it forwards — SCHEDULER_NETWORK_AUTH_TOKEN and SCHEDULER_PLAYGROUND_JWT to
 * the Scheduler, NODE_AUTH_TOKEN to the host Node (which can start and stop the
 * local runtime). None of them authenticated the visitor, and `next start` binds
 * all interfaces: anyone who could reach the port could read fleet telemetry,
 * relay arbitrary bodies into `/infer`, and drive host control. The routes cannot
 * tell an operator from a stranger, so the check lives here, in front of all of
 * them.
 *
 * Loopback-only, because the dashboard is a localhost control plane: every default
 * upstream (`SCHEDULER_URL`, `NODE_URL`) is localhost and nothing in it anticipates
 * being served past this machine.
 *
 * Both ends of the request are checked:
 *
 * - **Host** catches DNS rebinding — a page at an attacker's domain that resolves
 *   to 127.0.0.1 produces requests whose only tell is a non-loopback Host header.
 * - **Origin / Referer** catch cross-site requests aimed at a genuine loopback
 *   Host — any web page can `fetch("http://localhost:3000/api/node/control")`,
 *   and the Host alone checks out.
 *
 * X-Forwarded-* headers are deliberately not consulted: on a directly reachable
 * port they are attacker-controlled, and honouring them would let a remote caller
 * assert its way into loopback status.
 */

/** Hostnames that mean this machine. Compared after lower-casing and unbracketing IPv6. */
const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

/**
 * The hostname of a Host/Origin/Referer value, normalised for the loopback set.
 *
 * Handles bare hosts ("localhost"), host:port ("localhost:3000") and bracketed
 * IPv6 ("[::1]:3000"). Returns null for anything unparseable, which callers must
 * treat as "not loopback" -- failing closed here is the whole point of the gate.
 */
function loopbackHostname(value: string | null): string | null {
  if (!value) return null;
  try {
    // A bare `Host` header is not a URL, so give it a scheme; a full Origin or
    // Referer URL parses as-is.
    const url = new URL(value.includes("://") ? value : `http://${value}`);
    const hostname = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
    return LOOPBACK_HOSTNAMES.has(hostname) ? hostname : null;
  } catch {
    return null;
  }
}

/**
 * Whether the request may reach the credentialed API surface.
 *
 * Exported for the tests, which exercise it directly: invoking the middleware
 * function in vitest pins the decision logic without standing up a Next server.
 */
export function isLoopbackRequest(request: NextRequest): boolean {
  // Host is mandatory: HTTP/1.1 requires it and Next derives it from :authority on
  // HTTP/2, so a request without one is malformed and gets no benefit of the doubt.
  if (!loopbackHostname(request.headers.get("host"))) return false;

  for (const header of ["origin", "referer"]) {
    const value = request.headers.get(header);
    if (!value) continue; // Absent means non-browser or same-origin navigation; Host still applies.
    if (!loopbackHostname(value)) return false;
  }
  return true;
}

export function middleware(request: NextRequest) {
  if (isLoopbackRequest(request)) {
    return NextResponse.next();
  }

  // Checked AFTER the loopback verdict so a mis-set value ("true", "on", "yes")
  // fails closed rather than half-working.
  //
  // ESCAPE HATCH, AND IT IS A LOUD ONE. Setting DASHBOARD_ALLOW_REMOTE=1 turns
  // this gate off for every /api route: whoever can open a TCP connection to
  // this port can then read fleet telemetry, spend SCHEDULER_PLAYGROUND_JWT,
  // relay arbitrary bodies to the Scheduler, and start or stop the host runtime
  // with NODE_AUTH_TOKEN. It exists for deployments that deliberately put the
  // dashboard behind their own network boundary instead of this one. If that is
  // not you, do not set it.
  if (process.env.DASHBOARD_ALLOW_REMOTE === "1") {
    return NextResponse.next();
  }

  return NextResponse.json(
    {
      detail:
        "The dashboard's API is a credentialed proxy and answers loopback visitors " +
        "only. Reach it via localhost/127.0.0.1/[::1], or set DASHBOARD_ALLOW_REMOTE=1 " +
        "if you understand that this exposes host-control credentials to everyone who " +
        "can reach this port.",
    },
    { status: 403 }
  );
}

export const config = {
  // Every /api route carries credentials; nothing outside /api does (the pages are
  // public static content), so the matcher stays exactly this narrow.
  matcher: ["/api/:path*"],
  // Node runtime, deliberately: the default Edge runtime inlines process.env at
  // BUILD time, which would make DASHBOARD_ALLOW_REMOTE read whatever happened to
  // be set on the machine that ran `next build` instead of the operator's shell
  // running `next start`. An escape hatch that ignores its own operator is worse
  // than none.
  runtime: "nodejs",
};
