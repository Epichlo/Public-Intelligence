/**
 * The heartbeat card's decision logic.
 *
 * With no telemetry frame at all, this card used to render "Healthy" and
 * "SHA-256 VERIFIED": a missing `last_updated` was treated as "arrived just
 * now", so an unreachable node presented itself as a fresh, cryptographically
 * verified one. Absence of data is not freshness, and it is certainly not a
 * security verification -- these tests pin that distinction.
 */
import { describe, expect, it } from "vitest";

import { heartbeatView } from "./telemetry-gauge";

const NOW = 1_000_000;

describe("heartbeatView", () => {
  it("does not claim health or AEAD verification when no frame has arrived", () => {
    for (const absent of [undefined, "", "not a timestamp"]) {
      const view = heartbeatView(absent as string | undefined, NOW);
      expect(view.hasFrame).toBe(false);
      expect(view.label).not.toMatch(/healthy/i);
      expect(view.aeadVerified).toBe(false);
      expect(view.aeadLabel).toMatch(/no frames/i);
      expect(view.deltaLabel).toBe("—");
    }
  });

  it("keeps a fresh frame healthy and verified", () => {
    const view = heartbeatView(NOW - 2_000, NOW);
    expect(view.hasFrame).toBe(true);
    expect(view.label).toMatch(/healthy/i);
    expect(view.aeadVerified).toBe(true);
    expect(view.deltaLabel).toBe("2.0 seconds");
  });

  it("marks a frame older than the eviction boundary stale", () => {
    const view = heartbeatView(NOW - 16_000, NOW);
    expect(view.hasFrame).toBe(true);
    expect(view.label).toMatch(/stale/i);
  });

  it("keeps a stale-evicted frame inside the 30s AEAD window verified", () => {
    // Two different boundaries on purpose: the registry evicts at 15s, the
    // replay guard accepts up to 30s. A 16s frame is dead to the mesh but its
    // signature claim is still within the verified window -- the card must
    // not blur one boundary into the other.
    expect(heartbeatView(NOW - 16_000, NOW).aeadVerified).toBe(true);
  });

  it("drops the AEAD claim once the 30s replay window passes", () => {
    const view = heartbeatView(NOW - 31_000, NOW);
    expect(view.aeadVerified).toBe(false);
    expect(view.aeadLabel).toMatch(/stale/i);
  });

  it("marks a lagging frame as neither healthy nor stale", () => {
    const view = heartbeatView(NOW - 8_000, NOW);
    expect(view.hasFrame).toBe(true);
    expect(view.label).toMatch(/lagging/i);
  });
});
