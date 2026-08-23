import type { NextConfig } from "next";

/**
 * Security headers, and why each allowance is exactly as wide as it is.
 *
 * This file was the empty Next scaffold: the site shipped no CSP, no
 * X-Content-Type-Options, nothing preventing it being framed by another origin,
 * and an `X-Powered-By` header advertising the framework. The dashboard is a
 * localhost control plane whose /api surface proxies host credentials (see
 * src/middleware.ts), so browser-level hardening here is defence in depth behind
 * that gate, not decoration.
 *
 * The CSP inventory below was taken from what the site actually loads:
 *
 * - Scripts: Next's own chunks and hydration bootstrap from this origin, plus
 *   platform.twitter.com/widgets.js for the timeline embed
 *   (src/components/twitter-timeline.tsx). Nothing else runs script.
 * - Frames: the timeline embed renders inside a platform.twitter.com iframe once
 *   widgets.js converts the anchor. That is the only frame.
 * - Styles: the compiled Tailwind sheet from this origin, plus inline style
 *   attributes -- telemetry-gauge.tsx sizes its utilisation bars with React's
 *   style prop, which CSP governs under style-src.
 * - Fonts: next/font/google self-hosts Geist/Cormorant/JetBrains Mono at build
 *   time, so they load from this origin with no third-party font host at all.
 * - Connections: every fetch in the app targets a same-origin /api proxy route.
 *
 * **'unsafe-inline' in script-src is the one deliberate looseness.** Next's app
 * router injects its bootstrap `<script>` inline, and honouring a strict policy
 * would require per-request nonces through middleware -- real machinery this site
 * does not have. The minimal reversible option is to allow inline scripts while
 * keeping everything else tight; if a nonce pipeline ever lands, delete the token
 * first. It is asserted verbatim in src/security-headers.test.ts so widening it
 * further cannot happen quietly.
 */
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' https://platform.twitter.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-src https://platform.twitter.com",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'", // The header twin of X-Frame-Options: DENY, enforced where modern browsers honour CSP.
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Synchronous on purpose: the header set is static, and a promise-returning
  // shape would make the policy awkward to assert directly in tests.
  headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
