/**
 * The contribution panel's pure logic (ROADMAP 3.4 / 4.1).
 *
 * Only the exported helpers are tested here, not the rendered component: rendering
 * needs jsdom and React Testing Library, which is a toolchain this project does not
 * have and would be a poor trade for a four-field panel. What matters and IS
 * testable is the arithmetic, the language — a credit shown with a currency symbol,
 * or a failure ratio that divides by zero, are the two ways this misleads a host —
 * and the shape gate the untrusted proxy response must pass before it can reach a
 * render path at all.
 */
import { describe, expect, it } from "vitest";

import { failureRatio, formatCredits, parseNodeUsage } from "./contribution-summary";

describe("formatCredits", () => {
  it("never renders a currency symbol", () => {
    // D2 made credits an accounting unit with no redemption path. A "$" here would
    // promise something the project has explicitly declined to offer.
    for (const value of [0, 1, 12.5, 1500, 99999]) {
      expect(formatCredits(value)).not.toMatch(/[$£€]/);
    }
  });

  it("keeps small balances legible instead of rounding them to zero", () => {
    // A host who has served a handful of requests has a fraction of a credit.
    // Rounding that to "0" tells them their machine did nothing.
    expect(formatCredits(0.42)).toBe("0.42");
    expect(formatCredits(1.5)).toBe("1.50");
  });

  it("abbreviates large balances", () => {
    expect(formatCredits(1500)).toBe("1.5k");
  });

  it("treats nonsense as zero rather than rendering NaN", () => {
    expect(formatCredits(Number.NaN)).toBe("0");
    expect(formatCredits(-5)).toBe("0");
    expect(formatCredits(Number.POSITIVE_INFINITY)).toBe("0");
  });
});

describe("failureRatio", () => {
  it("is null when nothing has been served", () => {
    // Not 0. "No requests yet" and "no failures out of 100" are different facts,
    // and rendering both as 0% tells a new host their node is healthy before it
    // has done anything.
    expect(failureRatio({ requests: 0, failed_requests: 0, prompt_tokens: 0, completion_tokens: 0 })).toBeNull();
    expect(failureRatio(undefined)).toBeNull();
  });

  it("is a fraction of the window", () => {
    expect(
      failureRatio({ requests: 4, failed_requests: 1, prompt_tokens: 0, completion_tokens: 0 })
    ).toBe(0.25);
  });

  it("reports total failure as 1, not as an error", () => {
    expect(
      failureRatio({ requests: 3, failed_requests: 3, prompt_tokens: 0, completion_tokens: 0 })
    ).toBe(1);
  });
});

describe("parseNodeUsage", () => {
  // The component used to feed `res.json()` straight into setState with a cast, on
  // the strength of `res.ok`. A proxy that answers 200 with an error body -- which
  // every route here does for upstream failures it chooses to pass through -- then
  // crashed the whole panel's subtree at the first render of `usage.totals.requests`,
  // while `failureRatio` right next to it guarded carefully. Validation lives with
  // the type so the cast is earned rather than asserted.
  const VALID = {
    node_id: "node-1",
    credits_contributed: 1.5,
    credits_are_redeemable: false,
    totals_window: "recent tail",
    totals_window_size: 100,
    totals: {
      requests: 4,
      prompt_tokens: 12,
      completion_tokens: 340,
      failed_requests: 1,
    },
  };

  it("accepts a well-formed usage payload", () => {
    expect(parseNodeUsage(VALID)).toEqual(VALID);
  });

  it("rejects an error-shaped 200 instead of casting it", () => {
    expect(parseNodeUsage({ detail: "Unauthorized" })).toBeNull();
  });

  it.each([
    ["null", null],
    ["an array", [VALID]],
    ["missing totals", { node_id: "node-1", credits_contributed: 0 }],
    ["totals not an object", { ...VALID, totals: [] }],
    ["a string where a count belongs", { ...VALID, totals: { ...VALID.totals, requests: "4" } }],
    ["NaN in a rendered field", { ...VALID, credits_contributed: Number.NaN }],
    ["Infinity in a rendered field", { ...VALID, totals: { ...VALID.totals, completion_tokens: Number.POSITIVE_INFINITY } }],
    ["a missing window size", { ...VALID, totals_window_size: undefined }],
  ])("rejects %s", (_label, payload) => {
    expect(parseNodeUsage(payload)).toBeNull();
  });
});
