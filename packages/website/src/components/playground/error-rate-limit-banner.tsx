"use client";

export interface PlaygroundError {
  statusCode: number | null;
  message: string | null;
}

interface ErrorRateLimitBannerProps {
  error: PlaygroundError | null;
  onDismiss?: () => void;
}

export function ErrorRateLimitBanner({ error, onDismiss }: ErrorRateLimitBannerProps) {
  if (!error || !error.message) return null;

  const isRateLimit = error.statusCode === 429;
  const isUnauthorized = error.statusCode === 401;
  const isUnavailable = error.statusCode === 503;

  return (
    <div
      className={`rounded-xl border p-4 shadow-sm transition-all duration-200 ${
        isRateLimit
          ? "border-amber-500/40 bg-amber-950/40 text-amber-200"
          : isUnauthorized
          ? "border-red-500/40 bg-red-950/40 text-red-200"
          : "border-red-500/30 bg-zinc-950 text-red-300"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0">
            {isRateLimit ? (
              <svg className="h-5 w-5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            ) : (
              <svg className="h-5 w-5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            )}
          </div>
          <div>
            <h4 className="text-sm font-semibold">
              {isRateLimit
                ? "HTTP 429: Multi-Tenant Rate Limit Exceeded"
                : isUnauthorized
                ? "HTTP 401: Authorization Required"
                : isUnavailable
                ? "HTTP 503: Compute Node Unavailable"
                : `Error (${error.statusCode || "Network"})`}
            </h4>
            <p className="mt-1 text-xs leading-relaxed opacity-90">
              {typeof error.message === "string" ? error.message : JSON.stringify(error.message)}
            </p>

            {/* Actionable Advice */}
            <div className="mt-2 text-[11px] font-mono opacity-80 border-t border-current/20 pt-2">
              <strong>Actionable Advice:</strong>{" "}
              {isRateLimit
                ? "The Token Bucket rate limiter enforces a burst capacity of 5 requests and a refill rate of 1 token per 2.0 seconds per tenant. Please wait a few seconds before retrying."
                : isUnauthorized
                ? "Provide a valid RS256 Bearer JWT token in the authentication panel on the right sidebar containing a valid tenant_id claim."
                : isUnavailable
                ? "Verify that a compute node serving your selected model is running and connected to the Scheduler via Zenoh."
                : "Check your local network connection, local Node API status, or Scheduler gateway endpoint."}
            </div>
          </div>
        </div>

        {onDismiss && (
          <button
            onClick={onDismiss}
            className="text-xs text-muted-foreground hover:text-foreground shrink-0 p-1"
          >
            ✕
          </button>
        )}
      </div>
    </div>
  );
}
