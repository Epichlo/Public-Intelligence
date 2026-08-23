/**
 * The playground's model picker, pinned to honesty.
 *
 * This selector used to initialise itself with three invented models
 * (`["llama3", "llama3.2", "mistral"]`) and keep them whenever `/api/models`
 * failed, answered non-ok, or came back empty. A host with a misconfigured or
 * empty fleet saw three models "discovered", picked one, and got a 503 for a
 * model nobody serves. Presenting invented data as discovered is the cardinal
 * sin this project archived itself over once already.
 *
 * Rendering needs jsdom, which this toolchain deliberately lacks (see
 * contribution-summary.test.ts), so what is tested here is the decision logic
 * the component defers to: given any outcome of the catalogue fetch, what may
 * appear in the dropdown -- and the invariant that the legacy guesses can
 * never appear unless the Scheduler itself served them.
 */
import { describe, expect, it } from "vitest";

import {
  catalogueNotice,
  parseModelIds,
  resolveModelCatalogue,
} from "./model-selector";

const LEGACY_GUESSES = ["llama3", "llama3.2", "mistral"];

describe("parseModelIds", () => {
  it("maps a well-formed OpenAI-style catalogue to ids", () => {
    expect(
      parseModelIds({ data: [{ id: "qwen2.5" }, { id: "phi3", owned_by: "x" }] })
    ).toEqual(["qwen2.5", "phi3"]);
  });

  it("accepts an explicitly empty catalogue", () => {
    // Empty is a fact about the fleet, not a parse failure. It matters that
    // this returns [] and not null: "no models" and "unreadable" are different
    // statements and the UI owes the host each one separately.
    expect(parseModelIds({ data: [] })).toEqual([]);
  });

  it.each([
    ["null", null],
    ["a bare array", [{ id: "qwen2.5" }]],
    ["a body without data", { object: "list" }],
    ["data that is not an array", { data: "qwen2.5" }],
    ["an entry that is not an object", { data: ["qwen2.5"] }],
    ["an entry without an id", { data: [{ owned_by: "ollama" }] }],
    ["a non-string id", { data: [{ id: 7 }] }],
    ["an empty-string id", { data: [{ id: "" }] }],
  ])("rejects %s rather than guessing", (_label, payload) => {
    expect(parseModelIds(payload)).toBeNull();
  });
});

describe("resolveModelCatalogue", () => {
  it("reports unavailable when the fetch throws", () => {
    const state = resolveModelCatalogue(false, undefined);
    expect(state.status).toBe("unavailable");
    expect(state.models).toEqual([]);
  });

  it("reports unavailable when the route answers non-ok", () => {
    // A proxied 401/502 carries an error body, not a catalogue. Resolving it
    // to any model list would mean inventing a fleet from a failure.
    const state = resolveModelCatalogue(false, { detail: "Unauthorized" });
    expect(state.status).toBe("unavailable");
    expect(state.models).toEqual([]);
  });

  it("reports unavailable when the body cannot be parsed", () => {
    const state = resolveModelCatalogue(true, { detail: "upstream exploded" });
    expect(state.status).toBe("unavailable");
    expect(state.models).toEqual([]);
  });

  it("reports an empty catalogue instead of substituting defaults", () => {
    const state = resolveModelCatalogue(true, { data: [] });
    expect(state.status).toBe("empty");
    expect(state.models).toEqual([]);
  });

  it("reports exactly the served models when the catalogue is real", () => {
    const state = resolveModelCatalogue(true, {
      data: [{ id: "qwen2.5:14b" }, { id: "granite-code" }],
    });
    expect(state).toEqual({
      status: "ready",
      models: ["qwen2.5:14b", "granite-code"],
    });
  });

  it("never emits the legacy guessed models for any failure or empty outcome", () => {
    // The one invariant this whole fix exists for: whatever goes wrong with
    // the catalogue, the picker must not answer it with llama3.
    const outcomes: Array<[boolean, unknown]> = [
      [false, undefined],
      [false, { detail: "Unauthorized" }],
      [true, null],
      [true, {}],
      [true, { data: [] }],
      [true, { data: [{ id: "" }] }],
    ];
    for (const [ok, payload] of outcomes) {
      const state = resolveModelCatalogue(ok, payload);
      for (const guess of LEGACY_GUESSES) {
        expect(state.models).not.toContain(guess);
      }
    }
  });
});

describe("catalogueNotice", () => {
  it("gives the empty catalogue an honest title and a next step", () => {
    const notice = catalogueNotice({ status: "empty", models: [] });
    expect(notice?.title).toMatch(/no models available/i);
    expect(notice?.detail).toMatch(/scheduler/i);
  });

  it("gives a failed fetch an unavailable title and a retry path", () => {
    const notice = catalogueNotice({ status: "unavailable", models: [] });
    expect(notice?.title).toMatch(/could not load/i);
    expect(notice?.detail).toMatch(/retry|reconnect/i);
  });

  it("is silent for loading and ready states", () => {
    expect(catalogueNotice({ status: "loading", models: [] })).toBeNull();
    expect(catalogueNotice({ status: "ready", models: ["qwen2.5"] })).toBeNull();
  });
});
