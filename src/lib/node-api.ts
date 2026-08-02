/**
 * Shared helpers for the dashboard's server-side proxies to the host Node.
 *
 * The Node's control, telemetry, and sandbox-log routes require the credential
 * in `NODE_NETWORK_AUTH_TOKEN` (generated per install by install.sh /
 * install.ps1) and fail closed without it. These helpers live in one place so a
 * new proxy route cannot forget to forward it.
 *
 * `NODE_AUTH_TOKEN` is read server-side only -- it is never sent to the browser,
 * so the credential does not leave the machine running the dashboard.
 */

/** Base URL of the local host node, without a trailing slash. */
export function nodeUrl(): string {
  return (process.env.NODE_URL ?? "http://localhost:8080").replace(/\/$/, "");
}

/**
 * Headers for a request to the Node, including the auth credential when set.
 *
 * Returns the extra headers merged over any caller-supplied ones.
 */
export function nodeHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = process.env.NODE_AUTH_TOKEN;
  if (token) {
    headers["X-Network-Auth-Token"] = token;
  }
  return headers;
}

/**
 * Explains a 401 from the Node in terms the dashboard user can act on.
 *
 * Without this a misconfigured dashboard just shows "Unauthorized" with no
 * indication that a token needs setting.
 */
export function nodeAuthHint(status: number): string | null {
  if (status !== 401) return null;
  return process.env.NODE_AUTH_TOKEN
    ? "Node rejected the dashboard's credential. Confirm NODE_AUTH_TOKEN matches NODE_NETWORK_AUTH_TOKEN in Node/.env."
    : "Node requires a credential. Set NODE_AUTH_TOKEN for the dashboard to the NODE_NETWORK_AUTH_TOKEN value in Node/.env.";
}
