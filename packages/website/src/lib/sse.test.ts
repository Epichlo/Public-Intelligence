/**
 * SSE parsing (ROADMAP 4.1). The place where being subtly wrong is invisible.
 *
 * A dropped delta does not look like a bug -- it looks like the model not saying
 * that word. These are the cases that produce a plausible-but-wrong transcript.
 */
import { describe, expect, it } from "vitest";

import { estimateTokens, extractDelta, parseSseLine, splitSseBuffer } from "./sse";

const chunk = (content: string) =>
  `data: ${JSON.stringify({ choices: [{ delta: { content } }] })}`;

describe("splitSseBuffer", () => {
  it("holds back a partial trailing line", () => {
    // The case that actually happens: a chunk boundary lands mid-line, because a
    // token is a few bytes and TCP does not respect JSON. Treating the tail as
    // complete drops it, or parses half an object and yields nothing.
    const { lines, rest } = splitSseBuffer('data: {"a":1}\ndata: {"b":');
    expect(lines).toEqual(['data: {"a":1}']);
    expect(rest).toBe('data: {"b":');
  });

  it("returns an empty rest when the buffer ends on a boundary", () => {
    const { lines, rest } = splitSseBuffer("data: one\ndata: two\n");
    expect(lines).toEqual(["data: one", "data: two"]);
    expect(rest).toBe("");
  });

  it("reassembles a delta split across two reads", () => {
    // End to end: the token must survive the boundary, not be silently lost.
    const first = splitSseBuffer('data: {"choices":[{"delta":{"cont');
    expect(first.lines).toEqual([]);

    const second = splitSseBuffer(first.rest + 'ent":"Paris"}}]}\n');
    expect(second.lines).toHaveLength(1);
    expect(parseSseLine(second.lines[0]).delta).toBe("Paris");
  });
});

describe("parseSseLine", () => {
  it("reads a content delta", () => {
    expect(parseSseLine(chunk("Paris")).delta).toBe("Paris");
  });

  it("recognises the terminator", () => {
    expect(parseSseLine("data: [DONE]")).toEqual({ delta: "", done: true });
  });

  it("accepts `data:` without a space", () => {
    // Valid per the SSE spec. Slicing a fixed 6 characters assumed the space and
    // silently ate the first character of every payload without one.
    const line = `data:${JSON.stringify({ choices: [{ delta: { content: "Paris" } }] })}`;
    expect(parseSseLine(line).delta).toBe("Paris");
  });

  it("skips malformed JSON instead of throwing", () => {
    // A stream that dies mid-object should cost that fragment, not the whole
    // conversation the user has already been shown.
    expect(parseSseLine('data: {"choices":[{"delta":')).toEqual({ delta: "", done: false });
  });

  it("ignores comments, blank lines and keep-alives", () => {
    for (const line of ["", "   ", ": keep-alive", "event: ping"]) {
      expect(parseSseLine(line)).toEqual({ delta: "", done: false });
    }
  });
});

describe("extractDelta", () => {
  it("falls back to the legacy text field", () => {
    expect(extractDelta({ choices: [{ text: "Paris" }] })).toBe("Paris");
  });

  it("returns empty for shapes it does not recognise", () => {
    for (const shape of [null, undefined, {}, { choices: [] }, { choices: "no" }, 42]) {
      expect(extractDelta(shape)).toBe("");
    }
  });

  it("preserves a whitespace-only delta", () => {
    // The gateway sends " " between words. Dropping it as falsy runs the whole
    // completion together -- "ParisistheCapital" -- which reads as a model quirk
    // rather than as a parser bug.
    expect(extractDelta({ choices: [{ delta: { content: " " } }] })).toBe(" ");
  });
});

describe("estimateTokens", () => {
  it("is zero only for empty input", () => {
    expect(estimateTokens("")).toBe(0);
    expect(estimateTokens("a")).toBe(1);
  });

  it("matches the gateway's four-characters-per-token heuristic", () => {
    expect(estimateTokens("12345678")).toBe(2);
  });
});
